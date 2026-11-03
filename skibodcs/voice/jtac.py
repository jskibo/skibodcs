"""JTAC: check-in, 9-line, read-back, BDA. Deterministic - every number comes from World, never the LLM.
The target is the nearest hostile GROUND contact to the pilot (Export's object list). The IP is synthetic: a named point
10 nm from the target on the line back toward the pilot, so lines 2/3 are always consistent with the geometry.
UNVERIFIED in the sim: that Export reports ground objects with is_air = false and MSL altitude."""
from __future__ import annotations
import math

from . import brevity as bv
from .geo import bearing_true, distance_nm, to_magnetic
from .state import Contact, World

IP_NAMES = ["Hammer", "Anvil", "Sledge", "Forge"]
IP_DISTANCE_NM = 10.0
GROUP_NM = 1.0                      # contacts this close to the primary target are "the group"
THREAT_NM = 15.0
SAM_WORDS = ("sa-", "kub", "buk", "tor", "osa", "strela", "s-300", "s-75", "s-125", "shilka", "zsu", "tunguska", "roland", "hawk", "patriot", "rapier")
CARDINAL = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def _cardinal(deg: float) -> str:
    return CARDINAL[int(((deg % 360) + 22.5) // 45) % 8]


def _offset(lat: float, lon: float, brg_true: float, nm: float) -> tuple[float, float]:
    d = nm / 3440.065
    b, p1, l1 = math.radians(brg_true), math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def latlon_dm(lat: float, lon: float) -> str:
    def part(v, pos, neg, w):
        h = pos if v >= 0 else neg
        v = abs(v); d = int(v); m = (v - d) * 60
        return f"{h} {d:0{w}d} {m:06.3f}"
    return f"{part(lat, 'N', 'S', 2)}  {part(lon, 'E', 'W', 3)}"


def _latlon_speech(lat: float, lon: float) -> str:
    def part(v, pos, neg):
        h = "north" if v >= 0 and pos == "N" else "south" if pos == "N" else "east" if v >= 0 else "west"
        v = abs(v); d = int(v); m = (v - d) * 60
        return f"{h} {bv.digits(d)}, {bv.digits(int(m))} decimal {bv.digits(int(round((m - int(m)) * 10)) % 10)}"
    return part(lat, "N", "S") + ", " + part(lon, "E", "W")


def pick_target(w: World) -> tuple[Contact, list[Contact]] | None:
    gs = [c for c in w.hostiles(air_only=False) if not c.is_air]
    if not gs:
        return None
    o = w.own
    prim = min(gs, key=lambda c: distance_nm(o.lat, o.lon, c.lat, c.lon))
    group = [c for c in gs if distance_nm(prim.lat, prim.lon, c.lat, c.lon) <= GROUP_NM]
    return prim, group


def _describe(group: list[Contact]) -> str:
    counts: dict[str, int] = {}
    for c in group:
        counts[c.type or "vehicle"] = counts.get(c.type or "vehicle", 0) + 1
    return ", ".join(f"{n} {t}" for t, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def nine_line(w: World, mark: str = "laser", code: int = 1688, ip_index: int = 0) -> dict | None:
    """Returns {'lines': {...}, 'remarks': str, 'target_ids': [...]} or None when no ground target is known."""
    t = pick_target(w)
    if t is None:
        return None
    prim, group = t
    o = w.own
    back = bearing_true(prim.lat, prim.lon, o.lat, o.lon)
    back = round(back / 5.0) * 5.0 % 360                          # IP on a clean 5-degree radial from the target
    ip_lat, ip_lon = _offset(prim.lat, prim.lon, back, IP_DISTANCE_NM)
    hdg_ip_tgt = to_magnetic(bearing_true(ip_lat, ip_lon, prim.lat, prim.lon), w.magvar_east)
    friends = [c for c in w.contacts if c.coalition == w.own_side and not c.is_air]
    if friends:
        f = min(friends, key=lambda c: distance_nm(prim.lat, prim.lon, c.lat, c.lon))
        fb = to_magnetic(bearing_true(prim.lat, prim.lon, f.lat, f.lon), w.magvar_east)
        friendlies = f"{_cardinal(fb)}, {distance_nm(prim.lat, prim.lon, f.lat, f.lon):.0f} miles"
    else:
        friendlies = "none known"
    threats = [c for c in w.hostiles(air_only=False)
               if not c.is_air and any(k in (c.type or "").lower() for k in SAM_WORDS)
               and distance_nm(prim.lat, prim.lon, c.lat, c.lon) <= THREAT_NM]
    remarks = (f"{len(threats)} air defence contact{'s' if len(threats) != 1 else ''} within {THREAT_NM:.0f} miles of the target"
               if threats else "no air defence known")
    marks = {"laser": f"laser, code {code}", "smoke": "smoke", "none": "no mark"}
    lines = {
        1: ("IP", IP_NAMES[ip_index % len(IP_NAMES)]),
        2: ("Heading", f"{int(round(hdg_ip_tgt)) % 360 or 360:03d} magnetic"),
        3: ("Distance", f"{IP_DISTANCE_NM:.0f} miles"),
        4: ("Elevation", f"{int(round(prim.alt_ft))} feet"),
        5: ("Description", _describe(group)),
        6: ("Location", latlon_dm(prim.lat, prim.lon)),
        7: ("Mark", marks.get(mark, marks["laser"])),
        8: ("Friendlies", friendlies),
        9: ("Egress", _cardinal(hdg_ip_tgt)),
    }
    return {"lines": lines, "remarks": remarks, "target_ids": [c.id for c in group], "primary_id": prim.id,
            "lat": prim.lat, "lon": prim.lon, "ip": (ip_lat, ip_lon)}


def speech_nine_line(w: World, me: str, jtac: str, nl: dict) -> str:
    L = nl["lines"]
    code_speech = ""
    mark = L[7][1]
    if mark.startswith("laser, code "):
        code_speech = "laser, code " + bv.digits(mark.split()[-1])
    parts = [f"{bv.callsign_speech(me)}, {jtac}, nine line follows.",
             f"Line one, {L[1][1]}.",
             f"Line two, {bv.digits(L[2][1].split()[0])}.",
             f"Line three, {bv.miles(float(L[3][1].split()[0]))}.",
             f"Line four, {bv.digits(L[4][1].split()[0])} feet.",
             f"Line five, {L[5][1]}.",
             f"Line six, {_latlon_speech(nl['lat'], nl['lon'])}.",
             f"Line seven, {code_speech or mark}.",
             f"Line eight, {L[8][1]}.",
             f"Line nine, egress {L[9][1]}.",
             f"Remarks, {nl['remarks']}. Advise when ready for read back."]
    return " ".join(parts)


def checkin(w: World, me: str, jtac: str) -> str:
    t = pick_target(w)
    n = len(t[1]) if t else 0
    state = f"{n} hostile ground contact{'s' if n != 1 else ''} in the target area, ready for nine line" if t else "no hostile ground contacts known, standing by"
    return f"{bv.callsign_speech(me)}, {jtac}, loud and clear. {state}."


def readback(me: str, jtac: str, have_target: bool) -> str:
    if not have_target:
        return f"{bv.callsign_speech(me)}, {jtac}, say again, no nine line passed."
    return f"{bv.callsign_speech(me)}, {jtac}, read back correct. Cleared hot when set."


def bda(w: World, me: str, jtac: str, target_ids: list[str]) -> str:
    if not target_ids:
        return f"{bv.callsign_speech(me)}, {jtac}, no target to assess."
    alive = {c.id for c in w.contacts}
    left = [i for i in target_ids if i in alive]
    dead = len(target_ids) - len(left)
    if not left:
        return f"{bv.callsign_speech(me)}, {jtac}, good effects, all {bv.digits(len(target_ids))} destroyed."
    return (f"{bv.callsign_speech(me)}, {jtac}, {bv.digits(dead)} of {bv.digits(len(target_ids))} destroyed, "
            f"{bv.digits(len(left))} remaining. Re-attack at your discretion.")
