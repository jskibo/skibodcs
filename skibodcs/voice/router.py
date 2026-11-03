"""Transcript -> actions. Fast regex path for crisp brevity (no LLM, instant),
LLM path for everything natural. Code, not the LLM, produces all numbers."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field

from ..llm import LLM
from . import comms
from .cockpit import AirframeTable
from .intents import COMMS_INTENTS, Command, Parsed, intent_schema
from .state import World

FAST = [
    (re.compile(r"^(?:\w+,?\s+)?(?:bogey dope|bogie dope)\.?$"), "bogey_dope"),
    (re.compile(r"^(?:\w+,?\s+)?(?:picture|request picture)\.?$"), "picture"),
    (re.compile(r"^(?:\w+,?\s+)?radio check\.?$"), "radio_check"),
]

PROMPT = """You convert a pilot's spoken words (already transcribed, may be messy) into commands.
Return JSON only. Several commands are allowed (max 4) for compound requests.

COMMS intents (domain "comms"):
{comms}
COCKPIT actions (domain "cockpit"), with allowed values:
{cockpit}

Rules:
- Use domain "none" with empty fields if the pilot is NOT addressing a controller/AI or giving a cockpit order (chatting, talking to a human wingman, noise).
- Never invent actions or values; use only those listed.
- addressed_to: the name the pilot called (e.g. Magic, Tower), or "".
- emergency=true only for urgent distress (fuel, engine fire, etc.).
Context: {ctx}"""


@dataclass
class Result:
    speech: list[str] = field(default_factory=list)
    cockpit: list[tuple[int, int, float]] = field(default_factory=list)
    source: str = "none"                 # fast | llm | none
    notes: list[str] = field(default_factory=list)


class Router:
    def __init__(self, llm: LLM | None, table: AirframeTable, world: World,
                 callsign: str = "Viper 1-1", awacs: str = "Magic"):
        self.llm, self.table, self.world = llm, table, world
        self.callsign, self.awacs = callsign, awacs
        self.schema = intent_schema(table.action_names(), table.all_values())

    # -- parse
    def _fast(self, text: str) -> Parsed | None:
        t = re.sub(r"[^\w\s,.]", "", text.lower()).strip()
        for rx, intent in FAST:
            if rx.match(t):
                return Parsed(commands=[Command(domain="comms", intent=intent)])
        return None

    def _context(self) -> str:
        af = comms.nearest_airfield(self.world)
        return json.dumps({"callsign": self.callsign, "awacs": self.awacs,
                           "nearest_airfield": af.name if af else None,
                           "hostiles_known": len(self.world.hostiles())})

    def _llm(self, text: str) -> Parsed | None:
        if not self.llm:
            return None
        cockpit = "\n".join(f"- {n}: {sorted(a.values)}" for n, a in sorted(self.table.actions.items()))
        sys_msg = PROMPT.format(comms="\n".join(f"- {k}: {v}" for k, v in COMMS_INTENTS.items()),
                                cockpit=cockpit or "- (none)", ctx=self._context())
        out = self.llm.chat([{"role": "system", "content": sys_msg},
                             {"role": "user", "content": text}], self.schema)
        try:
            return Parsed.model_validate_json(out)
        except Exception:                                    # noqa: BLE001
            return None

    # -- execute
    def handle(self, transcript: str) -> Result:
        r = Result()
        text = transcript.strip()
        if not text:
            return r
        parsed = self._fast(text)
        r.source = "fast" if parsed else "llm"
        if parsed is None:
            parsed = self._llm(text)
            if parsed is None:
                r.source, r.notes = "none", ["could not parse model output"]
                return r
        for c in parsed.commands:
            self._exec(c, r)
        if not r.speech and not r.cockpit and r.source == "llm":
            r.source = "none"
        return r

    def _exec(self, c: Command, r: Result):
        w = self.world
        if c.domain == "none":
            return
        if c.domain == "comms":
            ctrl = c.addressed_to or self.awacs
            h = {"bogey_dope": lambda: comms.bogey_dope(w, self.callsign, ctrl),
                 "picture": lambda: comms.picture(w, self.callsign, ctrl),
                 "radio_check": lambda: comms.radio_check(self.callsign, ctrl),
                 "atc_taxi": lambda: comms.atc_taxi(w, self.callsign),
                 "atc_takeoff": lambda: comms.atc_takeoff(w, self.callsign),
                 "atc_inbound": lambda: comms.atc_inbound(w, self.callsign, c.emergency)}.get(c.intent)
            if h:
                r.speech.append(h())
            else:
                r.notes.append(f"unknown comms intent '{c.intent}'")
            return
        if c.domain == "cockpit":
            try:
                r.cockpit += self.table.resolve(c.action, c.value)
                r.speech.append(f"{c.action.replace('_', ' ')} {c.value}")
                if not self.table.actions[c.action].verified:
                    r.notes.append(f"action '{c.action}' is UNVERIFIED (placeholder ids)")
            except KeyError as e:
                r.notes.append(str(e).strip("'\""))
