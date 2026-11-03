"""Validated Scenario -> .miz via pydcs. Returns warnings for anything in the
spec that v0.1 does not compile yet (so nothing is silently dropped)."""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path

import dcs
from dcs import mapping

from . import catalog
from .schema import Scenario

FT = 0.3048
KT_KMH = 1.852
KT_MS = 0.514444

CLOUDS = {  # name -> (density 0-10, base m, thickness m)
    "clear": (0, 3000, 500), "few": (2, 2800, 800), "scattered": (4, 2500, 1000),
    "broken": (7, 2200, 1200), "overcast": (10, 1800, 1500),
}


def _apply_weather(m: dcs.Mission, sc: Scenario):
    w, spec = m.weather, sc.weather
    to_dir = (spec.wind_from_deg + 180) % 360         # DCS stores direction wind blows TOWARD
    w.wind_at_ground = dcs.weather.Wind(to_dir, spec.wind_kt * KT_MS)
    w.qnh = spec.qnh_mmhg
    w.visibility_distance = min(spec.vis_km * 1000, 80000)
    dens, base, thick = CLOUDS[spec.clouds]
    w.clouds_density, w.clouds_base, w.clouds_thickness = dens, base, thick


def _ring(center: mapping.Point, terrain, i: int, n: int, radius: float) -> mapping.Point:
    if i == 0:
        return center
    a = 2 * math.pi * (i - 1) / max(n - 1, 1)
    return mapping.Point(center.x + radius * math.cos(a), center.y + radius * math.sin(a), terrain)


def compile_scenario(sc: Scenario, out_path: str | Path) -> list[str]:
    warnings: list[str] = []
    th = sc.meta.theater
    terrain = catalog.terrain(th)
    m = dcs.Mission(terrain)
    blue, red = dcs.countries.USA(), dcs.countries.Russia()
    m.coalition["blue"].add_country(blue)
    m.coalition["red"].add_country(red)
    blue, red = m.country("USA"), m.country("Russia")

    y, mo, d = map(int, sc.meta.date.split("-"))
    hh, mm = map(int, sc.meta.start_time.split(":"))
    m.start_time = dt.datetime(y, mo, d, hh, mm)
    _apply_weather(m, sc)

    # --- player flights
    for f in sc.player:
        ab = catalog.find_airbase(th, f.start_airbase)
        ac = catalog.aircraft_ids()[f.aircraft]
        start = {"cold": dcs.mission.StartType.Cold, "warm": dcs.mission.StartType.Warm,
                 "runway": dcs.mission.StartType.Runway}[f.start_type]
        fg = m.flight_group_from_airport(blue, f.callsign, ac, ab, catalog.TASKS[f.task],
                                         start_type=start, group_size=f.count)
        fg.units[0].set_player()
        payload = ac.loadout(catalog.TASKS[f.task])
        if not payload:
            warnings.append(f"{f.callsign}: no default {f.task} loadout for {f.aircraft}; "
                            "flight has empty pylons (pydcs reads payloads from a DCS install, "
                            "so this is expected when DCS is not installed on this machine)")
        else:
            fg.load_task_default_loadout(catalog.TASKS[f.task])
        fg.set_frequency(sc.comms.flight_freq_mhz)
        for w in f.route:
            fg.add_waypoint(catalog.resolve_anchor(th, w.at), w.alt_ft * FT,
                            w.speed_kt * KT_KMH, w.name)

    # --- red ground groups
    for g in sc.red.groups:
        pos = catalog.resolve_anchor(th, g.position)
        parts = [(cls, n) for cls, n in catalog.GROUND_TEMPLATES[g.template]]
        total = sum(n for _, n in parts)
        first_cls = parts[0][0]
        vg = m.vehicle_group(red, g.id, first_cls, pos, g.heading, group_size=1)
        idx = 1
        for ci, (cls, n) in enumerate(parts):
            for k in range(n):
                if ci == 0 and k == 0:
                    continue
                u = m.vehicle(f"{g.id}-{idx}", cls)
                u.position = _ring(pos, terrain, idx, total, 120)
                u.heading = math.radians(g.heading)
                vg.add_unit(u)
                idx += 1
        for u in vg.units:
            u.skill = getattr(dcs.unit.Skill, g.skill)

    # --- red air (unconditional only)
    for i, a in enumerate(sc.red.air):
        if a.trigger:
            warnings.append(f"red.air[{i}] trigger '{a.trigger}' not compiled in v0.1 (needs runtime.lua); spawning at start instead")
        p1 = catalog.resolve_anchor(th, a.spawn)
        p2 = mapping.Point(p1.x + 40000, p1.y, terrain)
        m.patrol_flight(red, f"RedCAP-{i+1}", catalog.aircraft_ids()[a.aircraft], None, p1, p2,
                        start_type=dcs.mission.StartType.Cold, group_size=a.count)

    # --- blue support (AI orbits near the first player's start base)
    base = catalog.find_airbase(th, sc.player[0].start_airbase)
    sup = sc.blue_support
    if sup.awacs:
        pos = mapping.Point(base.position.x, base.position.y + 60000, terrain)
        m.awacs_flight(blue, sup.awacs.callsign, dcs.planes.E_3A, None, pos,
                       altitude=9000, speed=770, frequency=sup.awacs.freq_mhz)
    if sup.tanker:
        pos = mapping.Point(base.position.x, base.position.y - 60000, terrain)
        m.refuel_flight(blue, sup.tanker.callsign, dcs.planes.KC_135, None, pos,
                        altitude=6000, speed=700, frequency=sup.tanker.freq_mhz,
                        tacanchannel=sup.tanker.tacan or "40X")
    if sup.jtac:
        warnings.append("blue_support.jtac: no JTAC unit is spawned; the voice JTAC works from real contacts instead")

    # --- not yet compiled
    if sc.dynamic_rules:
        warnings.append(f"{len(sc.dynamic_rules)} dynamic_rules kept in sidecar JSON only (runtime.lua step)")
    if sc.objectives:
        warnings.append("objectives are briefing-only in the mission; the campaign scores them from the Hook events")

    # --- briefing
    b = sc.briefing
    m.set_sortie_text(sc.meta.title)
    m.set_description_text("\n\n".join(
        f"{h}\n{t}" for h, t in [("SITUATION", b.situation), ("MISSION", b.mission),
                                  ("EXECUTION", b.execution), ("THREATS", b.threats),
                                  ("ROE", b.roe)] if t))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    out_path.with_suffix(".scenario.json").write_text(sc.model_dump_json(indent=2))
    return warnings
