"""Form -> scenario. The mission-builder screen fills a flat dict of choices; anything left on "random" is rolled here (seedable).
Pure code: no LLM, always validated by validate.py, so a bad combination becomes a readable message, never a broken .miz."""
from __future__ import annotations
import datetime as dt
import math
import random

from dcs import mapping

from . import catalog

NM = 1852.0
# Modules the app has cockpit data for, with the callsign they usually fly under.
AIRCRAFT = {
    "F-16C_50": ("F-16C Viper", "Viper"), "FA-18C_hornet": ("F/A-18C Hornet", "Hornet"), "A-10C_2": ("A-10C II Tank Killer", "Hawg"),
    "A-10C": ("A-10C Thunderbolt II", "Hawg"), "F-14B": ("F-14B Tomcat", "Tomcat"), "AH-64D_BLK_II": ("AH-64D Apache", "Gunslinger"),
    "F-4E-45MC": ("F-4E Phantom II", "Ghost"),
}
TASK_LABELS = {"SEAD": "SEAD (suppress air defences)", "CAS": "CAS (close air support)", "STRIKE": "Strike (ground attack)",
               "CAP": "CAP (air patrol)"}
SAM_LABELS = {"SA-2": "SA-2 (long range, old)", "SA-6": "SA-6 Kub (mobile)", "SA-8": "SA-8 Osa (short range)", "SA-10": "SA-10 / S-300 (long range)",
              "SA-11": "SA-11 Buk (capable)", "SA-13": "SA-13 (IR, short)", "SA-15": "SA-15 Tor (point defence)", "ZSU-23": "ZSU-23-4 Shilka (guns)"}
AIR = {"none": None, "mig29_2": ("MiG-29S", 2), "mig29_4": ("MiG-29S", 4), "su27_2": ("Su-27", 2), "su27_4": ("Su-27", 4)}
AIR_LABELS = {"none": "None", "mig29_2": "2x MiG-29S", "mig29_4": "4x MiG-29S", "su27_2": "2x Su-27", "su27_4": "4x Su-27", "random": "Random"}
TIMES = {"dawn": "05:45", "morning": "09:00", "midday": "12:30", "afternoon": "15:30", "dusk": "18:30", "night": "22:30"}
CLOUDS = ["clear", "few", "scattered", "broken", "overcast"]
THEATER_NAMES = {"caucasus": "Caucasus", "persiangulf": "Persian Gulf", "syria": "Syria", "nevada": "Nevada", "marianaislands": "Mariana Islands",
                 "sinai": "Sinai", "falklands": "Falklands", "kola": "Kola", "afghanistan": "Afghanistan", "germany": "Germany", "normandy": "Normandy",
                 "thechannel": "The Channel"}
GROUND_KINDS = {"armor": ["ARMOR_PLATOON"], "mech": ["MECH_INF"], "both": ["ARMOR_PLATOON", "MECH_INF"]}

DEFAULTS = {
    "theater": "Caucasus", "aircraft": "F-16C_50", "count": 2, "callsign": "", "start_airbase": "Batumi", "start_type": "cold",
    "task": "random", "target_near": "", "target_bearing": "random", "target_distance": "random",
    "sam": "random", "sam_count": 2, "ground": "random", "air": "random", "skill": "High",
    "date": "2026-06-14", "time": "random", "clouds": "random", "wind_kt": "random", "wind_from": "random", "vis_km": "random",
    "awacs": True, "tanker": True, "jtac": "auto", "title": "", "seed": None,
}


def _num(v, lo, hi, rng, default_range):
    if v in (None, "", "random"):
        return rng.uniform(*default_range)
    return max(lo, min(hi, float(v)))


def _offset(p: mapping.Point, bearing: float, nm: float, terrain) -> mapping.Point:
    b = math.radians(bearing)
    return mapping.Point(p.x + nm * NM * math.cos(b), p.y + nm * NM * math.sin(b), terrain)


def _anchor(near: str, ab_point: mapping.Point, p: mapping.Point) -> dict:
    """Anchor (airbase + bearing + distance) for an arbitrary point."""
    dx, dy = p.x - ab_point.x, p.y - ab_point.y
    return {"near": near, "bearing": round((math.degrees(math.atan2(dy, dx)) + 360) % 360, 1),
            "distance_nm": round(math.hypot(dx, dy) / NM, 1)}


def options(theater: str) -> dict:
    """Everything the UI needs to fill its dropdowns."""
    return {"airbases": catalog.airbases(theater), "theaters": [{"id": THEATER_NAMES.get(k, k), "label": THEATER_NAMES.get(k, k)} for k in sorted(catalog.THEATERS)],
            "aircraft": [{"id": k, "label": v[0], "callsign": v[1]} for k, v in AIRCRAFT.items() if k in catalog.aircraft_ids()],
            "tasks": [{"id": k, "label": v} for k, v in TASK_LABELS.items()],
            "sams": [{"id": k, "label": v} for k, v in SAM_LABELS.items()],
            "air": [{"id": k, "label": v} for k, v in AIR_LABELS.items()],
            "times": list(TIMES), "clouds": CLOUDS}


def build_spec(form: dict, scn_id: str = "mission_001", rng: random.Random | None = None) -> tuple[dict, list[str]]:
    """Returns (scenario dict, notes). Notes say what was rolled randomly or added to make the request flyable."""
    f = {**DEFAULTS, **{k: v for k, v in form.items() if v is not None}}
    rng = rng or random.Random(f["seed"] if f["seed"] not in (None, "") else None)
    notes: list[str] = []
    th = f["theater"]
    terrain = catalog.terrain(th)
    start_ab = catalog.find_airbase(th, f["start_airbase"])
    if start_ab is None:
        raise KeyError(f"no airbase '{f['start_airbase']}' on {th}")
    sp = start_ab.position
    start_name = next(k for k, v in terrain.airports.items() if v is start_ab)
    tgt_near = f["target_near"] or start_name
    tab = catalog.find_airbase(th, tgt_near)
    if tab is None:
        raise KeyError(f"no airbase '{tgt_near}' on {th}")

    task = f["task"] if f["task"] != "random" else rng.choice(["SEAD", "CAS", "STRIKE", "CAP"])
    if f["task"] == "random":
        notes.append(f"task rolled: {task}")
    tb = _num(f["target_bearing"], 0, 360, rng, (0, 360))
    td_default = (25, 70) if tgt_near == start_name else (0, 25)
    td = _num(f["target_distance"], 0, 300, rng, td_default)
    tp = _offset(tab.position, tb, td, terrain)                        # target area centre
    count = max(1, min(4, int(f["count"])))
    callsign = f["callsign"] or AIRCRAFT.get(f["aircraft"], ("", "Viper"))[1]

    # --- enemy forces
    groups, used = [], {}
    def add_group(tpl: str, near_nm: tuple[float, float]):
        used[tpl] = used.get(tpl, 0) + 1
        gid = f"{tpl.lower().replace('-', '')}_{used[tpl]}"
        pos = _offset(tp, rng.uniform(0, 360), rng.uniform(*near_nm), terrain)
        groups.append({"id": gid, "template": tpl, "position": _anchor(start_name, sp, pos),
                       "heading": round(rng.uniform(0, 360)), "skill": f["skill"]})
        return gid
    sam_tpl = f["sam"]
    n_sam = max(0, min(6, int(f["sam_count"])))
    if sam_tpl == "none":
        n_sam = 0
    elif sam_tpl == "random":
        notes.append("SAM type rolled per site")
    sam_ids = []
    for _ in range(n_sam):
        sam_ids.append(add_group(rng.choice(sorted(catalog.SAM_TEMPLATES - {"ZSU-23"})) if sam_tpl == "random" else sam_tpl, (3, 10)))
    g_kind = f["ground"] if f["ground"] != "random" else rng.choice(["none", "armor", "mech", "both"])
    if f["ground"] == "random":
        notes.append(f"ground forces rolled: {g_kind}")
    gnd_ids = [add_group(t, (1, 4)) for t in GROUND_KINDS.get(g_kind, [])]

    # --- target & objectives
    target_id = None
    if task == "SEAD":
        if not sam_ids:
            sam_ids.append(add_group(rng.choice(["SA-6", "SA-11", "SA-2"]), (0, 2))); notes.append("SEAD needs a SAM: one was added")
        target_id = sam_ids[0]
    elif task in ("CAS", "STRIKE"):
        if not gnd_ids:
            gnd_ids.append(add_group("ARMOR_PLATOON", (0, 2))); notes.append(f"{task} needs ground targets: an armor platoon was added")
        target_id = gnd_ids[0]
    objectives = ([{"id": "o1", "type": "destroy", "target_group": target_id, "priority": "primary"},
                   {"id": "o2", "type": "survive", "target_group": "player", "priority": "secondary"}] if target_id
                  else [{"id": "o1", "type": "survive", "target_group": "player", "priority": "primary"}])

    # --- route
    sdx, sdy = sp.x - tp.x, sp.y - tp.y
    dist_back = math.hypot(sdx, sdy) / NM
    ip_nm = min(25.0, max(8.0, 0.6 * dist_back))
    ip = _offset(tp, (math.degrees(math.atan2(sdy, sdx)) + 360) % 360, ip_nm, terrain)
    alt = 12000 if task == "CAS" else 18000
    if task == "CAP":
        cap2 = _offset(tp, 90, 20, terrain)
        route = [{"name": "CAP1", "at": _anchor(start_name, sp, tp), "alt_ft": 25000, "speed_kt": 400},
                 {"name": "CAP2", "at": _anchor(start_name, sp, cap2), "alt_ft": 25000, "speed_kt": 400}]
    else:
        route = [{"name": "IP", "at": _anchor(start_name, sp, ip), "alt_ft": 20000, "speed_kt": 420},
                 {"name": "TGT", "at": _anchor(start_name, sp, tp), "alt_ft": alt, "speed_kt": 450}]
    route.append({"name": "HOME", "at": {"near": start_name, "bearing": 0, "distance_nm": 0}, "alt_ft": 15000, "speed_kt": 350})

    # --- enemy air
    air_key = f["air"] if f["air"] != "random" else rng.choice(["none", "none", "mig29_2", "su27_2"])
    if f["air"] == "random":
        notes.append(f"enemy fighters rolled: {AIR_LABELS[air_key]}")
    red_air = []
    if task == "CAP" and air_key == "none":
        air_key = "mig29_2"; notes.append("CAP needs something to patrol against: 2x MiG-29S added")
    if AIR.get(air_key):
        ac, n = AIR[air_key]
        sp_air = _offset(tp, rng.uniform(0, 360), 30, terrain)
        red_air = [{"task": "CAP", "aircraft": ac, "count": n, "spawn": _anchor(start_name, sp, sp_air)}]

    # --- weather & time
    clouds = f["clouds"] if f["clouds"] != "random" else rng.choice(CLOUDS[:4])
    weather = {"clouds": clouds, "wind_kt": round(_num(f["wind_kt"], 0, 40, rng, (2, 15))),
               "wind_from_deg": round(_num(f["wind_from"], 0, 360, rng, (0, 360)) / 10) * 10 % 360,
               "vis_km": round(_num(f["vis_km"], 5, 100, rng, (20, 80))), "qnh_mmhg": 760}
    t = f["time"] if f["time"] != "random" else rng.choice(list(TIMES))
    start_time = TIMES.get(t, t if len(str(t)) == 5 and ":" in str(t) else TIMES["morning"])
    dt.date.fromisoformat(f["date"])                                  # fail loudly on a bad date

    # --- support, comms, briefing
    jtac = (task in ("CAS", "STRIKE")) if f["jtac"] == "auto" else bool(f["jtac"])
    support = {}
    if f["awacs"]: support["awacs"] = {"callsign": "Overlord", "freq_mhz": 251.0}
    if f["tanker"]: support["tanker"] = {"callsign": "Texaco", "freq_mhz": 270.0, "tacan": "40X"}
    if jtac: support["jtac"] = {"callsign": "Axeman", "freq_mhz": 138.0}
    what = {"SEAD": "air defence site", "CAS": "enemy force engaging friendly troops", "STRIKE": "enemy ground force", "CAP": "airspace"}[task]
    threats = sorted({g["template"] for g in groups}) + ([f"{red_air[0]['aircraft']} x{red_air[0]['count']}"] if red_air else [])
    title = f["title"] or (f"{task} near {tgt_near}" if task != "CAP" else f"CAP out of {start_name}")
    spec = {
        "meta": {"id": scn_id, "title": title, "theater": th, "date": f["date"], "start_time": start_time},
        "weather": weather,
        "player": [{"callsign": callsign, "aircraft": f["aircraft"], "count": count, "task": task, "start_airbase": start_name,
                    "start_type": f["start_type"], "route": route}],
        "objectives": objectives, "red": {"groups": groups, "air": red_air}, "blue_support": support,
        "comms": {"flight_freq_mhz": 305.0, "tower_freq_mhz": 131.0},
        "briefing": {
            "situation": f"Enemy forces are active near {tgt_near}." if task != "CAP" else f"Enemy fighters are probing the airspace near {start_name}.",
            "mission": f"{task}: destroy {target_id} ({what})." if target_id else "Defend the airspace and engage hostile aircraft.",
            "execution": f"{f['start_type'].capitalize()} start at {start_name}, route via the IP to the target area, egress and land at {start_name}.",
            "threats": ", ".join(threats) or "None known", "roe": "Weapons tight until positive identification."},
    }
    return spec, notes
