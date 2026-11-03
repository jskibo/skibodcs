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


class Command(BaseModel):
    domain: Literal["comms", "cockpit", "none"]
    intent: str = ""
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
                "domain": {"type": "string", "enum": ["comms", "cockpit", "none"]},
                "intent": {"type": "string", "enum": [""] + sorted(COMMS_INTENTS)},
                "action": {"type": "string", "enum": [""] + sorted(actions)},
                "value": {"type": "string", "enum": [""] + sorted(values)},
                "addressed_to": {"type": "string"},
                "emergency": {"type": "boolean"},
            },
            "required": ["domain", "intent", "action", "value", "addressed_to", "emergency"],
        }}},
        "required": ["commands"],
    }
