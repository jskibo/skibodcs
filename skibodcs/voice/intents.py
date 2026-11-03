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
    "jtac_checkin":   "check in with the JTAC / JTAC how copy / on station for tasking",
    "jtac_nine_line": "request the nine line / ready for tasking / ready to copy / what are we hitting",
    "jtac_readback":  "read back the nine line / ready for readback / I have the nine line",
    "jtac_bda":       "battle damage assessment / BDA / how did we do",
    "atc_inbound": "pilot wants to land / come back / inbound / low on fuel (set emergency if urgent)",
}

# Wingman / element / flight orders. `who` selects the ship(s): flight (default), wingman (#2), element (#3+#4), 2/3/4.
WINGMAN_INTENTS = {
    "engage_my_target": "attack my target / shoot what I'm locked on / engage my lock",
    "engage_nearest":   "kill the closest bandit / engage nearest threat",
    "engage_bandits":   "engage bandits / engage air targets / clean up the air",
    "engage_ground":    "engage ground targets / attack ground units",
    "engage_sead":      "SEAD / engage air defenses / suppress SAMs",
    "weapons_free":     "weapons free / free to engage hostiles",
    "weapons_hold":     "weapons hold / hold fire / don't shoot",
    "roe":              "set rules of engagement; level: free | hold | return_fire | open_fire",
    "radar":            "wingman radar; level: off | attack_only | search | continuous",
    "ecm":              "wingman jammer; level: off | lock | detected | always",
    "reaction":         "reaction to threats; level: none | passive | evade | escape",
    "formation":        "change formation; shape: line_abreast | trail | wedge | echelon_right | echelon_left | "
                        "finger_four | spread | vic; spacing: close | open | group",
    "cover_me":         "cover me / protect me / stay with me",
    "rejoin":           "rejoin / form up / back to formation",
    "status":           "wingman status / how's your fuel / what are you doing",
    "cleared_hot":      "cleared hot / clear to drop on the ground target",
    "rtb":              "return to base / go home",
    "break_left":       "break left",
    "break_right":      "break right",
}
SEQUENCE_INTENTS = {
    "autostart":     "start the jet from cold and dark / autostart / start engines and systems",
    "autostop":      "shut everything down / autostop",
    "ready_to_taxi": "get ready to taxi / cold and dark to ready to taxi",
}
WHO = ["flight", "wingman", "element", "2", "3", "4"]
LEVELS = ["off", "attack_only", "search", "continuous", "lock", "detected", "always",
          "none", "passive", "evade", "escape", "free", "hold", "return_fire", "open_fire"]
SHAPES = ["line_abreast", "trail", "wedge", "echelon_right", "echelon_left", "finger_four", "spread", "vic"]
SPACINGS = ["close", "open", "group"]
FORMATION_MODES = SHAPES        # kept for older imports
WEAPONS = ["auto", "fox1", "fox2", "fox3", "guns"]


class Command(BaseModel):
    domain: Literal["comms", "cockpit", "control", "wingman", "sequence", "none"]
    intent: str = ""
    mode: str = ""
    weapon: str = ""
    action: str = ""
    value: str = ""
    control: str = ""
    position: str = ""
    amount: float = -1.0
    who: str = ""
    level: str = ""
    shape: str = ""
    spacing: str = ""
    addressed_to: str = ""
    emergency: bool = False


class Parsed(BaseModel):
    commands: list[Command] = Field(default_factory=list, max_length=6)


def intent_schema(actions: list[str], values: list[str], controls: list[str] | None = None,
                  positions: list[str] | None = None) -> dict:
    """JSON schema handed to Ollama's `format`; enums come from real tables (controls = per-utterance shortlist)."""
    e = lambda xs: {"type": "string", "enum": [""] + sorted(set(xs))}
    props = {
        "domain": {"type": "string", "enum": ["comms", "cockpit", "control", "wingman", "sequence", "none"]},
        "intent": e(list(COMMS_INTENTS) + list(WINGMAN_INTENTS) + list(SEQUENCE_INTENTS)),
        "mode": e(SHAPES), "weapon": e(WEAPONS),
        "action": e(actions), "value": e(values),
        "control": e(controls or []), "position": e(positions or []),
        "amount": {"type": "number"},
        "who": e(WHO), "level": e(LEVELS), "shape": e(SHAPES), "spacing": e(SPACINGS),
        "addressed_to": {"type": "string"}, "emergency": {"type": "boolean"},
    }
    return {"type": "object",
            "properties": {"commands": {"type": "array", "maxItems": 6, "items": {
                "type": "object", "properties": props, "required": list(props)}}},
            "required": ["commands"]}
