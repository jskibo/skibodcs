"""Turn the pydantic Scenario into a JSON schema whose string fields that name
real DCS things are enums, so constrained decoding cannot produce a bad name."""
from __future__ import annotations
import copy
from . import catalog
from .schema import Scenario, Briefing


def _set_enum(defs: dict, model: str, field: str, values: list[str]):
    prop = defs[model]["properties"][field]
    prop.clear()
    prop.update({"type": "string", "enum": sorted(values)})


def constrained_scenario_schema(theater: str) -> dict:
    s = copy.deepcopy(Scenario.model_json_schema())
    d = s["$defs"]
    bases = catalog.airbases(theater)
    air = sorted(catalog.aircraft_ids())
    _set_enum(d, "Anchor", "near", bases)
    _set_enum(d, "PlayerFlight", "aircraft", air)
    _set_enum(d, "PlayerFlight", "task", list(catalog.TASKS))
    _set_enum(d, "PlayerFlight", "start_airbase", bases)
    _set_enum(d, "RedGroup", "template", list(catalog.GROUND_TEMPLATES))
    _set_enum(d, "RedAir", "aircraft", air)
    _set_enum(d, "Meta", "theater", [theater])
    return s


def briefing_schema() -> dict:
    return Briefing.model_json_schema()
