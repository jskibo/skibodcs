"""Scenario spec: what the LLM writes. Pure data, no DCS imports.

Everything position-like is an Anchor (named place + bearing/distance), never
raw lat/lon: local models are bad at coordinates, code is good at them.
Closed vocabularies (aircraft, tasks, templates) are checked in validate.py
against the real DCS data so the model gets precise, fixable error messages.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


class Anchor(BaseModel):
    """A place: an airbase name, optionally offset by bearing/distance."""
    near: str = Field(description="Airbase name exactly as listed in the theater catalog")
    bearing: float = Field(0, ge=0, le=360, description="Degrees true from the airbase")
    distance_nm: float = Field(0, ge=0, le=400)


class Meta(BaseModel):
    id: str
    title: str
    theater: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    campaign_id: Optional[str] = None
    sequence: int = 1


class Weather(BaseModel):
    clouds: Literal["clear", "few", "scattered", "broken", "overcast"] = "clear"
    wind_kt: float = Field(5, ge=0, le=60)
    wind_from_deg: float = Field(270, ge=0, le=360)
    vis_km: float = Field(80, ge=1, le=200)
    qnh_mmhg: float = Field(760, ge=700, le=800)


class Waypoint(BaseModel):
    name: str
    at: Anchor
    alt_ft: float = Field(20000, ge=0, le=60000)
    speed_kt: float = Field(400, ge=80, le=1500)


class PlayerFlight(BaseModel):
    callsign: str
    aircraft: str                       # DCS type id, e.g. "F-16C_50"
    count: int = Field(2, ge=1, le=4)
    task: str                           # key of TASKS in catalog
    start_airbase: str
    start_type: Literal["cold", "warm", "runway"] = "cold"
    route: list[Waypoint] = []


class Objective(BaseModel):
    id: str
    type: Literal["destroy", "survive", "escort", "recon"]
    target_group: Optional[str] = None
    priority: Literal["primary", "secondary"] = "primary"


class RedGroup(BaseModel):
    id: str
    template: str                       # key of GROUND_TEMPLATES in catalog
    position: Anchor
    heading: float = Field(0, ge=0, le=360)
    skill: Literal["Average", "Good", "High", "Excellent", "Random"] = "High"


class RedAir(BaseModel):
    task: Literal["CAP"] = "CAP"
    aircraft: str
    count: int = Field(2, ge=1, le=4)
    spawn: Anchor
    trigger: Optional[str] = None       # not compiled in v0.1 (needs runtime.lua)


class Red(BaseModel):
    groups: list[RedGroup] = []
    air: list[RedAir] = []


class SupportAsset(BaseModel):
    callsign: str
    freq_mhz: float = Field(ge=30, le=400)
    tacan: Optional[str] = None


class BlueSupport(BaseModel):
    awacs: Optional[SupportAsset] = None
    tanker: Optional[SupportAsset] = None
    jtac: Optional[SupportAsset] = None


class Comms(BaseModel):
    flight_freq_mhz: float = Field(305.0, ge=30, le=400)
    tower_freq_mhz: Optional[float] = None


class DynamicRule(BaseModel):
    when: str                           # e.g. "o1.complete"
    then: str                           # e.g. "spawn:reinforcement_wave"
    delay_min: float = 0


class Briefing(BaseModel):
    situation: str = ""
    mission: str = ""
    execution: str = ""
    threats: str = ""
    roe: str = ""


class Scenario(BaseModel):
    meta: Meta
    weather: Weather = Weather()
    player: list[PlayerFlight] = Field(min_length=1)
    objectives: list[Objective] = []
    red: Red = Red()
    blue_support: BlueSupport = BlueSupport()
    comms: Comms = Comms()
    dynamic_rules: list[DynamicRule] = []
    briefing: Briefing = Briefing()
    carry_over: list[str] = []

    @model_validator(mode="after")
    def _refs(self):
        ids = {g.id for g in self.red.groups}
        for o in self.objectives:
            if o.target_group and o.target_group != "player" and o.target_group not in ids:
                raise ValueError(f"objective {o.id}: target_group '{o.target_group}' is not a red group id")
        return self
