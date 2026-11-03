"""Deterministic radio responses. Every number comes from World, never the LLM."""
from __future__ import annotations
from . import brevity as bv
from .geo import aspect_word, bearing_true, distance_nm, to_magnetic
from .state import Airfield, Contact, World

GROUP_MERGE_NM = 5.0


def _mag_bearing(w: World, lat1, lon1, lat2, lon2) -> float:
    return to_magnetic(bearing_true(lat1, lon1, lat2, lon2), w.magvar_east)


def bogey_dope(w: World, me: str, ctrl: str = "Magic") -> str:
    hs = w.hostiles()
    if not hs:
        return f"{bv.callsign_speech(me)}, {ctrl}, clean, no factors."
    o = w.own
    c = min(hs, key=lambda c: distance_nm(o.lat, o.lon, c.lat, c.lon))
    brg = _mag_bearing(w, o.lat, o.lon, c.lat, c.lon)
    rng = distance_nm(o.lat, o.lon, c.lat, c.lon)
    asp = aspect_word(c.heading, bearing_true(c.lat, c.lon, o.lat, o.lon))
    return (f"{bv.callsign_speech(me)}, {ctrl}, bogey dope, braa {bv.heading3(brg)}, "
            f"{bv.miles(rng)}, {bv.thousands(c.alt_ft)}, {asp}.")


def _groups(contacts: list[Contact]) -> list[list[Contact]]:
    groups: list[list[Contact]] = []
    for c in contacts:
        for g in groups:
            if distance_nm(g[0].lat, g[0].lon, c.lat, c.lon) <= GROUP_MERGE_NM:
                g.append(c); break
        else:
            groups.append([c])
    return groups


def picture(w: World, me: str, ctrl: str = "Magic") -> str:
    gs = _groups(w.hostiles())
    if not gs:
        return f"{bv.callsign_speech(me)}, {ctrl}, picture clean."
    if w.bullseye is None:
        return f"{bv.callsign_speech(me)}, {ctrl}, {len(gs)} groups, bullseye not set."
    bl, bn = w.bullseye
    parts = []
    for g in sorted(gs, key=lambda g: distance_nm(w.own.lat, w.own.lon, g[0].lat, g[0].lon))[:4]:
        c = g[0]
        brg = _mag_bearing(w, bl, bn, c.lat, c.lon)
        rng = distance_nm(bl, bn, c.lat, c.lon)
        parts.append(f"group bullseye {bv.heading3(brg)}, {bv.miles(rng)}, {bv.thousands(c.alt_ft)}, "
                     f"{len(g)} contact{'s' if len(g) > 1 else ''}")
    n = len(gs)
    return f"{bv.callsign_speech(me)}, {ctrl}, {bv.digits(n)} group{'s' if n > 1 else ''}. " + ". ".join(parts) + "."


def radio_check(me: str, ctrl: str) -> str:
    return f"{bv.callsign_speech(me)}, {ctrl}, loud and clear."


def nearest_airfield(w: World) -> Airfield | None:
    if not w.airfields:
        return None
    return min(w.airfields, key=lambda a: distance_nm(w.own.lat, w.own.lon, a.lat, a.lon))


def active_runway(af: Airfield, wind_from: float | None) -> tuple[float, str]:
    """Pick the runway end with the best headwind. Returns (heading, label)."""
    ends = []
    for h in af.runway_headings:
        ends += [h % 360, (h + 180) % 360]
    if wind_from is None:
        h = ends[0]
    else:
        from .geo import angle_diff
        h = min(ends, key=lambda e: angle_diff(e, wind_from))
    label = f"{int(round(h / 10)) % 36 or 36:02d}"
    return h, label


def atc_taxi(w: World, me: str) -> str:
    af = nearest_airfield(w)
    if not af:
        return f"{bv.callsign_speech(me)}, no airfield in range."
    _, rwy = active_runway(af, w.wind_from)
    return f"{bv.callsign_speech(me)}, {af.name} ground, runway {bv.digits(rwy)}, taxi via the shortest route, hold short."


def atc_inbound(w: World, me: str, emergency: bool = False) -> str:
    af = nearest_airfield(w)
    if not af:
        return f"{bv.callsign_speech(me)}, no airfield in range."
    _, rwy = active_runway(af, w.wind_from)
    wind = ""
    if w.wind_from is not None:
        wind = f" wind {bv.heading3(w.wind_from)}."
    pri = " Emergency traffic, you are number one." if emergency else ""
    return f"{bv.callsign_speech(me)}, {af.name} tower, runway {bv.digits(rwy)}, cleared to land.{wind}{pri}"


def atc_takeoff(w: World, me: str) -> str:
    af = nearest_airfield(w)
    if not af:
        return f"{bv.callsign_speech(me)}, no airfield in range."
    _, rwy = active_runway(af, w.wind_from)
    return f"{bv.callsign_speech(me)}, {af.name} tower, runway {bv.digits(rwy)}, cleared for takeoff."
