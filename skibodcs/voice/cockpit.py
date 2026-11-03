"""Cockpit action tables (airframes/*.toml). The LLM only ever sees action and
value NAMES; the numeric device/command ids live here, in git, per module."""
from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Action:
    name: str
    device: int
    command: int
    values: dict[str, float]
    momentary: bool = False         # send value then release (0.0) shortly after
    verified: bool = False


@dataclass
class AirframeTable:
    aircraft: str
    actions: dict[str, Action] = field(default_factory=dict)

    def action_names(self) -> list[str]:
        return sorted(self.actions)

    def all_values(self) -> list[str]:
        return sorted({v for a in self.actions.values() for v in a.values})

    def resolve(self, action: str, value: str) -> list[tuple[int, int, float]]:
        a = self.actions.get(action)
        if a is None:
            raise KeyError(f"unknown action '{action}'")
        if value not in a.values:
            raise KeyError(f"'{value}' not valid for {action}; use {sorted(a.values)}")
        v = a.values[value]
        cmds = [(a.device, a.command, v)]
        if a.momentary:
            cmds.append((a.device, a.command, 0.0))
        return cmds


def load_table(path: str | Path) -> AirframeTable:
    d = tomllib.loads(Path(path).read_text())
    t = AirframeTable(d["aircraft"]["id"])
    for name, a in d.get("actions", {}).items():
        t.actions[name] = Action(name, int(a["device"]), int(a["command"]),
                                 {k: float(v) for k, v in a["values"].items()},
                                 bool(a.get("momentary", False)), bool(a.get("verified", False)))
    return t
