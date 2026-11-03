"""Validate a scenario dict. Returns flat, LLM-readable error strings so a
retry prompt can say exactly what to fix."""
from __future__ import annotations
import json
from pydantic import ValidationError

from . import catalog
from .schema import Scenario, Anchor


def _fmt_pyd(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{loc}: {err['msg']}")
    return out


def validate(raw: dict | str) -> tuple[Scenario | None, list[str]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            return None, [f"not valid JSON: {e}"]
    try:
        sc = Scenario.model_validate(raw)
    except ValidationError as e:
        return None, _fmt_pyd(e)

    errs: list[str] = []
    try:
        catalog.terrain(sc.meta.theater)
    except KeyError:
        return None, [f"meta.theater: unknown '{sc.meta.theater}'. Use one of {sorted(catalog.THEATERS)}"]
    th = sc.meta.theater
    bases = catalog.airbases(th)

    def check_anchor(path: str, a: Anchor):
        if catalog.find_airbase(th, a.near) is None:
            errs.append(f"{path}.near: no airbase '{a.near}' on {th}. Closest: {catalog.suggest(a.near, bases)}")

    def check_aircraft(path: str, t: str):
        if t not in catalog.aircraft_ids():
            errs.append(f"{path}: unknown aircraft '{t}'. Closest: {catalog.suggest(t, catalog.aircraft_ids())}")

    for i, f in enumerate(sc.player):
        p = f"player[{i}]"
        check_aircraft(f"{p}.aircraft", f.aircraft)
        if f.task not in catalog.TASKS:
            errs.append(f"{p}.task: '{f.task}' not in {sorted(catalog.TASKS)}")
        if catalog.find_airbase(th, f.start_airbase) is None:
            errs.append(f"{p}.start_airbase: no airbase '{f.start_airbase}'. Closest: {catalog.suggest(f.start_airbase, bases)}")
        for j, w in enumerate(f.route):
            check_anchor(f"{p}.route[{j}].at", w.at)
    for i, g in enumerate(sc.red.groups):
        if g.template not in catalog.GROUND_TEMPLATES:
            errs.append(f"red.groups[{i}].template: '{g.template}' not in {sorted(catalog.GROUND_TEMPLATES)}")
        check_anchor(f"red.groups[{i}].position", g.position)
    for i, a in enumerate(sc.red.air):
        check_aircraft(f"red.air[{i}].aircraft", a.aircraft)
        check_anchor(f"red.air[{i}].spawn", a.spawn)
    for i, sf in enumerate(sc.support_flights):
        check_aircraft(f"support_flights[{i}].aircraft", sf.aircraft)
        if sf.start_airbase and catalog.find_airbase(th, sf.start_airbase) is None:
            errs.append(f"support_flights[{i}].start_airbase: no airbase '{sf.start_airbase}'. Closest: {catalog.suggest(sf.start_airbase, bases)}")
    ids = [g.id for g in sc.red.groups]
    if len(ids) != len(set(ids)):
        errs.append("red.groups: duplicate id")
    return (None, errs) if errs else (sc, [])
