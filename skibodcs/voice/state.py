"""World state fed by the DCS link (or by tests)."""
from __future__ import annotations
from dataclasses import dataclass, field
import threading


@dataclass
class Ownship:
    model: str = ""
    lat: float = 0.0
    lon: float = 0.0
    alt_ft: float = 0.0
    heading: float = 0.0          # true degrees
    gs_kt: float = 0.0


@dataclass
class Contact:
    id: str
    lat: float
    lon: float
    alt_ft: float
    heading: float
    speed_kt: float
    coalition: str                # "red" | "blue" | "neutral"
    type: str = ""
    is_air: bool = True


@dataclass
class Airfield:
    name: str
    lat: float
    lon: float
    elev_ft: float
    runway_headings: list[float]
    freq_mhz: float | None = None


@dataclass
class World:
    own: Ownship = field(default_factory=Ownship)
    contacts: list[Contact] = field(default_factory=list)
    airfields: list[Airfield] = field(default_factory=list)
    bullseye: tuple[float, float] | None = None
    magvar_east: float = 0.0
    wind_from: float | None = None
    own_side: str = "blue"
    updated: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def hostiles(self, air_only=True) -> list[Contact]:
        return [c for c in self.contacts
                if c.coalition not in (self.own_side, "neutral") and (c.is_air or not air_only)]

    def update_from_payload(self, p: dict, now: float = 0.0):
        """Telemetry JSON as emitted by dcs_hook/skibodcs_export.lua."""
        o = p.get("own") or {}
        with self.lock:
            self.own = Ownship(o.get("model", ""), o.get("lat", 0), o.get("lon", 0),
                               o.get("alt_ft", 0), o.get("hdg", 0), o.get("gs_kt", 0))
            self.contacts = [Contact(str(c["id"]), c["lat"], c["lon"], c.get("alt_ft", 0),
                                     c.get("hdg", 0), c.get("spd_kt", 0), c.get("coal", "neutral"),
                                     c.get("type", ""), c.get("air", True))
                             for c in p.get("objs", [])]
            self.updated = now
