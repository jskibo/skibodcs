"""Scripted cockpit sequences (autostart, autostop, ready-to-taxi): timed performClickableAction steps.
Sequences are DATA (sequences/<aircraft>.json), ideally generated from ED's own Macro_sequencies.lua so the
device/command/value triples are the game's, not ours. The runner is abortable and reports progress."""
from __future__ import annotations
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Step:
    delay: float = 0.0                 # seconds to wait BEFORE this step (ED's macros use deltas)
    device: int | None = None
    command: int | None = None
    value: float | None = None
    message: str | None = None         # spoken/printed progress text instead of a click

    @staticmethod
    def from_dict(d: dict) -> "Step":
        return Step(float(d.get("delay", 0)), d.get("device"), d.get("command"), d.get("value"), d.get("message"))


@dataclass
class RunResult:
    sent: int = 0
    failed: int = 0
    cancelled: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.cancelled and self.failed == 0


def load_sequences(path: str | Path) -> dict[str, list[Step]]:
    d = json.loads(Path(path).read_text())
    return {name: [Step.from_dict(s) for s in steps] for name, steps in d.get("sequences", {}).items()}


class SequenceRunner:
    def __init__(self, send: Callable[[int, int, float], bool], say: Callable[[str], None] = lambda s: None,
                 sleep: Callable[[float], None] = time.sleep, speed: float = 1.0):
        self.send, self.say, self.sleep, self.speed = send, say, sleep, speed
        self.cancel = threading.Event()

    def abort(self):
        self.cancel.set()

    def run(self, steps: list[Step]) -> RunResult:
        res = RunResult()
        for st in steps:
            if st.delay > 0:
                # sleep in slices so an abort is honoured within ~0.25 s
                left = st.delay / max(self.speed, 1e-6)
                while left > 0 and not self.cancel.is_set():
                    chunk = min(0.25, left)
                    self.sleep(chunk); left -= chunk
            if self.cancel.is_set():
                res.cancelled = True
                self.say("Sequence aborted.")
                return res
            if st.message:
                res.messages.append(st.message); self.say(st.message)
            if st.device is not None and st.command is not None:
                if self.send(st.device, st.command, float(st.value if st.value is not None else 1.0)):
                    res.sent += 1
                else:
                    res.failed += 1
                    if res.failed >= 3:                         # DCS gone or link broken: stop instead of flailing
                        self.say("Lost the link to DCS, stopping the sequence.")
                        return res
        return res
