"""Semantic intent schema. The LLM maps free speech to these; code executes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

COMMS_INTENTS = {
    "bogey_dope":  "pilot asks where the nearest threat is / what's out there / bogey dope",
    "picture":     "pilot wants the overall air picture / who's up / what do we have",
    "radio_check": "pilot checks that the controller hears them",
    "atc_taxi":    "pilot asks to taxi",
    "atc_takeoff": "pilot asks for takeoff clearance",
    "atc_inbound": "pilot wants to land / come back / inbound / low on fuel (set emergency if urgent)",
}


WINGMAN_INTENTS = {
    "engage_my_target": "attack my target / shoot what I'm locked on / engage my lock",
    "engage_nearest":   "kill the closest bandit / engage nearest threat",
    "weapons_free":     "weapons free / free to engage hostiles (air-to-air ROE)",
    "weapons_hold":     "weapons hold / hold fire / don't shoot",
    "cleared_hot":      "cleared hot / clear to drop on the ground target (ground attack release)",
    "formation":        "change formation: spread, line, wedge, echelon, trail, close (set mode)",
    "cover_me":         "cover me / protect me / stay with me",
    "rejoin":           "rejoin / form up / back to formation",
    "rtb":              "return to base / go home",
    "break_left":       "break left",
    "break_right":      "break right",
    "status":           "wingman status / how's your fuel / what are you doing",
}
FORMATION_MODES = ["spread", "line", "wedge", "echelon", "trail", "close"]
WEAPONS = ["auto", "fox1", "fox2", "fox3", "guns"]


class Command(BaseModel):
    domain: Literal["comms", "cockpit", "wingman", "none"]
    intent: str = ""
    mode: str = ""
    weapon: str = ""
    action: str = ""
    value: str = ""
    addressed_to: str = ""
    emergency: bool = False


class Parsed(BaseModel):
    commands: list[Command] = Field(default_factory=list, max_length=4)


def intent_schema(actions: list[str], values: list[str]) -> dict:
    """JSON schema handed to Ollama's `format`; enums come from real tables."""
    return {
        "type": "object",
        "properties": {"commands": {"type": "array", "maxItems": 4, "items": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "enum": ["comms", "cockpit", "wingman", "none"]},
                "intent": {"type": "string", "enum": [""] + sorted(COMMS_INTENTS) + sorted(WINGMAN_INTENTS)},
                "mode": {"type": "string", "enum": [""] + FORMATION_MODES},
                "weapon": {"type": "string", "enum": [""] + WEAPONS},
                "action": {"type": "string", "enum": [""] + sorted(actions)},
                "value": {"type": "string", "enum": [""] + sorted(values)},
                "addressed_to": {"type": "string"},
                "emergency": {"type": "boolean"},
            },
            "required": ["domain", "intent", "mode", "weapon", "action", "value", "addressed_to", "emergency"],
        }}},
        "required": ["commands"],
    }
