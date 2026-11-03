"""Fill World with static theater data from pydcs: airfields, runways, ATC freqs, bullseye."""
from __future__ import annotations
from .. import catalog
from .state import Airfield, World


def load_theater(world: World, theater: str, wind_from: float | None = None) -> World:
    t = catalog.terrain(theater)
    world.airfields = []
    for name, ap in t.airports.items():
        ll = ap.position.latlng()
        freq = ap.atc_radio.vhf_high_hz / 1e6 if getattr(ap, "atc_radio", None) else None
        heads = [float(r.main.heading) for r in ap.runways] or [0.0]
        world.airfields.append(Airfield(name, ll.lat, ll.lng, 0.0, heads, freq))
    b = t.bullseye_blue
    from dcs import mapping
    bl = mapping.Point(b["x"], b["y"], t).latlng()
    world.bullseye = (bl.lat, bl.lng)
    world.wind_from = wind_from
    return world
