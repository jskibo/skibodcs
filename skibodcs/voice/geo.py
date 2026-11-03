"""Pure geometry. The LLM never does this. Inputs are WGS84 degrees."""
from __future__ import annotations
import math

R_NM = 3440.065          # mean earth radius, nautical miles


def distance_nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(a))


def bearing_true(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def to_magnetic(true_deg: float, magvar_east_deg: float) -> float:
    """magvar_east_deg: easterly variation positive (magnetic = true - east var)."""
    return (true_deg - magvar_east_deg) % 360


def angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two headings, 0..180."""
    return abs((a - b + 180) % 360 - 180)


# Aspect bands (degrees off the target's nose toward you). Thresholds are a
# simplification of brevity usage; tune to taste.
def aspect_word(target_heading: float, bearing_target_to_me: float) -> str:
    off = angle_diff(target_heading, bearing_target_to_me)   # 0 = pointing at me
    if off <= 30:
        return "hot"
    if off <= 70:
        return "flank"
    if off <= 110:
        return "beam"
    if off <= 150:
        return "drag"
    return "cold"
