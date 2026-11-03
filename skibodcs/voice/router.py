"""Transcript -> actions. Fast regex path for crisp brevity (no LLM, instant),
LLM path for everything natural. Code, not the LLM, produces all numbers."""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field

from .. import controls as ctl
from ..llm import LLM
from . import brevity as bv
from . import comms
from .cockpit import AirframeTable
from .intents import COMMS_INTENTS, SEQUENCE_INTENTS, WINGMAN_INTENTS, Command, Parsed, intent_schema
from .state import World

FAST = [
    (re.compile(r"^(?:\w+,?\s+)?(?:bogey dope|bogie dope)\.?$"), ("comms", "bogey_dope")),
    (re.compile(r"^(?:\w+,?\s+)?(?:picture|request picture)\.?$"), ("comms", "picture")),
    (re.compile(r"^(?:\w+,?\s+)?radio check\.?$"), ("comms", "radio_check")),
    (re.compile(r"^(?:\w+,?\s+)?weapons free\.?$"), ("wingman", "weapons_free")),
    (re.compile(r"^(?:\w+,?\s+)?(?:weapons hold|hold fire)\.?$"), ("wingman", "weapons_hold")),
]
CONFIRM = re.compile(r"^(?:confirm|confirmed|affirm|affirmative|yes|do it|execute)\.?$")
CANCEL = re.compile(r"^(?:cancel|negative|no|abort|disregard|belay that)\.?$")
CONFIRM_SECONDS = 10.0
# Controls where a wrong guess about the value's meaning matters. If the value is not confirmed from ED's own data,
# ask for a spoken "confirm" first instead of trusting a guess.
CONSEQUENTIAL = re.compile(r"\b(gear|hook|master arm|flaps?|canopy|fuel|engines?|throttle|brakes?|speed ?brake|"
                           r"wing sweep|apu|jfs|generator|battery|battery|ignition)\b", re.I)

PROMPT = """You convert a pilot's spoken words (already transcribed, may be messy) into commands.
Return JSON only. Several commands are allowed (max 6) for compound requests.

COMMS intents (domain "comms"):
{comms}
WINGMAN intents (domain "wingman"). who = flight (all, default) | wingman (#2) | element (#3+#4) | 2 | 3 | 4.
Use level / shape / spacing only where the intent description says so:
{wingman}
SEQUENCE intents (domain "sequence"):
{sequence}
CURATED cockpit actions (domain "cockpit"), with allowed values:
{cockpit}
CONTROLS (domain "control"): any other cockpit control. Pick the id from THIS shortlist only, then a position
from its list; for [axis] controls give amount 0-100 (percent). If none fit, use domain "none".
{controls}

Rules:
- Use domain "none" with empty fields if the pilot is NOT addressing a controller/AI or giving a cockpit order (chatting, talking to a human wingman, noise).
- Never invent actions, controls or values; use only those listed.
- addressed_to: the name the pilot called (e.g. Magic, Tower), or "".
- emergency=true only for urgent distress (fuel, engine fire, etc.).
Context: {ctx}"""


@dataclass
class Result:
    speech: list[str] = field(default_factory=list)
    cockpit: list[tuple[int, int, float]] = field(default_factory=list)
    wingman: list[dict] = field(default_factory=list)      # JSON-ready commands for the Hook
    sequence: list[str] = field(default_factory=list)      # autostart / autostop / ready_to_taxi
    checks: list[tuple[int, str]] = field(default_factory=list)   # (cockpit arg, name) to read back after sending
    abort_sequence: bool = False
    source: str = "none"                 # fast | llm | none
    notes: list[str] = field(default_factory=list)


class Router:
    def __init__(self, llm: LLM | None, table: AirframeTable, world: World,
                 callsign: str = "Viper 1-1", awacs: str = "Magic", wingman: str = "Viper 1-2",
                 index: ctl.ControlIndex | None = None, clock=time.time):
        self.llm, self.table, self.world = llm, table, world
        self.callsign, self.awacs, self.wingman = callsign, awacs, wingman
        self.index, self.clock = index, clock
        self._seq = 0
        self.pending: tuple[list, str, float] | None = None
        self.schema = intent_schema(table.action_names(), table.all_values())
        self._covered = {(a.device, a.command) for a in table.actions.values()}

    # -- parse
    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"[^\w\s,.]", "", text.lower()).strip()

    def _fast(self, text: str) -> Parsed | None:
        t = self._norm(text)
        for rx, (domain, intent) in FAST:
            if rx.match(t):
                return Parsed(commands=[Command(domain=domain, intent=intent)])
        return None

    def _context(self) -> str:
        af = comms.nearest_airfield(self.world)
        return json.dumps({"callsign": self.callsign, "awacs": self.awacs,
                           "nearest_airfield": af.name if af else None,
                           "hostiles_known": len(self.world.hostiles())})

    def _shortlist(self, text: str) -> list[ctl.Control]:
        if not self.index:
            return []
        return [c for c in self.index.search(text, 14) if (c.device, c.commands[0]) not in self._covered][:12]

    def _llm(self, text: str) -> Parsed | None:
        if not self.llm:
            return None
        short = self._shortlist(text)
        cockpit = "\n".join(f"- {n}: {sorted(a.values)}" for n, a in sorted(self.table.actions.items()))
        lines = []
        for c in short:
            how = "[axis 0-100]" if c.kind == "axis" else f"{list(c.positions)}"
            lines.append(f"- {c.id}: {c.name} {how}")
        sys_msg = PROMPT.format(
            comms="\n".join(f"- {k}: {v}" for k, v in COMMS_INTENTS.items()),
            wingman="\n".join(f"- {k}: {v}" for k, v in WINGMAN_INTENTS.items()),
            sequence="\n".join(f"- {k}: {v}" for k, v in SEQUENCE_INTENTS.items()),
            cockpit=cockpit or "- (none)", controls="\n".join(lines) or "- (none)", ctx=self._context())
        schema = intent_schema(self.table.action_names(), self.table.all_values(),
                               [c.id for c in short], [p for c in short for p in c.positions])
        out = self.llm.chat([{"role": "system", "content": sys_msg}, {"role": "user", "content": text}], schema)
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
        now = self.clock()
        if self.pending and now > self.pending[2]:
            self.pending = None
        t = self._norm(text)
        if self.pending:
            cmds, label, _ = self.pending
            self.pending = None
            if CONFIRM.match(t):
                r.cockpit, r.source = cmds, "fast"
                r.speech.append(f"{label}, confirmed.")
                return r
            if CANCEL.match(t):
                r.source = "fast"; r.speech.append("Cancelled.")
                return r
        if re.match(r"^(?:abort|stop|cancel)(?: the)? (?:start|autostart|sequence|startup)\.?$", t):
            r.abort_sequence, r.source = True, "fast"
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
        if not (r.speech or r.cockpit or r.wingman or r.sequence) and r.source == "llm":
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
        if c.domain == "sequence":
            if c.intent in SEQUENCE_INTENTS:
                r.sequence.append(c.intent)
            else:
                r.notes.append(f"unknown sequence '{c.intent}'")
            return
        if c.domain == "wingman":
            self._wingman(c, r)
            return
        if c.domain == "control":
            self._control(c, r)
            return
        if c.domain == "cockpit":
            try:
                cmds = self.table.resolve(c.action, c.value)
                a = self.table.actions[c.action]
                label = f"{c.action.replace('_', ' ')} {c.value}"
                if c.value not in a.confirmed:
                    r.notes.append(f"action '{c.action}' value '{c.value}' is UNVERIFIED (ids come from the game files; this value is not in ED's autostart data)")
                    if CONSEQUENTIAL.search(c.action.replace("_", " ")):
                        self.pending = (cmds, label, self.clock() + CONFIRM_SECONDS)
                        r.speech.append(f"Confirm {label}? That value is unverified for this aircraft. Say confirm.")
                        return
                r.cockpit += cmds
                r.speech.append(label)
                if a.arg and not a.momentary:
                    r.checks.append((a.arg, c.action.replace("_", " ")))
            except KeyError as e:
                r.notes.append(str(e).strip("'\""))

    def _control(self, c: Command, r: Result):
        k = self.index.by_id.get(c.control) if self.index else None
        if k is None:
            r.notes.append(f"unknown control '{c.control}'")
            return
        try:
            cmds = ctl.resolve(k, c.position, c.amount)
        except KeyError as e:
            msg = str(e).strip("'\"")
            r.notes.append(msg)
            if "how much" in msg:
                r.speech.append(f"{k.name}, say how much.")
            return
        label = f"{k.name} {int(round(c.amount))} percent" if k.kind == "axis" else f"{k.name} {c.position}"
        unconfirmed = k.kind != "axis" and c.position not in k.confirmed and c.position not in k.inferred
        if k.danger or (unconfirmed and CONSEQUENTIAL.search(k.name)):
            self.pending = (cmds, label, self.clock() + CONFIRM_SECONDS)
            r.speech.append(f"Confirm {label}?" + (" That value is unverified for this aircraft." if not k.danger else "") + " Say confirm.")
            return
        r.cockpit += cmds
        r.speech.append(label)
        if not k.momentary and k.kind != "button":
            r.checks.append((k.arg, k.name))
        if c.position not in k.confirmed and c.position not in k.inferred and k.kind != "axis":
            r.notes.append(f"control '{k.id}' position '{c.position}' is UNVERIFIED")

    def _wingman(self, c: Command, r: Result):
        if c.intent not in WINGMAN_INTENTS:
            r.notes.append(f"unknown wingman intent '{c.intent}'")
            return
        params: dict = {}
        if c.who and c.who != "flight":
            params["who"] = c.who
        if c.intent == "engage_my_target":
            if not self.world.own.lock_id:
                r.speech.append(f"{bv.callsign_speech(self.callsign)}, unable, no target locked.")
                return
            params["target_id"] = self.world.own.lock_id
        if c.intent in ("roe", "radar", "ecm", "reaction"):
            if not c.level:
                r.notes.append(f"{c.intent} needs a level"); return
            params["level"] = c.level
        if c.intent == "formation":
            params["shape"] = c.shape or c.mode or "spread"
            params["spacing"] = c.spacing or "open"
        self._seq += 1
        r.wingman.append({"id": f"w{self._seq}", "type": "wingman", "intent": c.intent, "params": params})
