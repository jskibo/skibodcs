"""LLM -> Scenario. Two passes (skeleton, then briefing prose) with
schema-constrained decoding and a validate/retry loop on top: constrained
decoding guarantees shape and names; validate() catches the rest."""
from __future__ import annotations
import json

from . import catalog
from .llm import LLM
from .schema import Briefing, Scenario
from .schema_tools import briefing_schema, constrained_scenario_schema
from .validate import validate

SYSTEM = """You are a DCS World mission designer. Output ONE JSON scenario object only.
Rules:
- Use only airbase names, aircraft ids, tasks and templates that appear in the schema enums.
- Place everything with anchors: {{"near": <airbase>, "bearing": 0-360, "distance_nm": n}}. Never use raw coordinates.
- Keep it flyable: SAM/armor 15-40 nm from the player's start base, route points 20-120 nm from it.
- Leave briefing fields as empty strings; they are written in a later step.
- meta.theater must be "{theater}". meta.id must be "{scn_id}". sequence is {seq}.
{state}"""

BRIEF_SYSTEM = """You write a concise military mission briefing from the scenario facts.
Fill situation, mission, execution, threats, roe. Plain text, no markdown, 1-3 sentences each.
Use only facts present in the scenario; do not invent units, places or frequencies."""


def _extract(text: str) -> dict | str:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def generate_scenario(llm: LLM, request: str, theater: str, scn_id: str = "scn_0001",
                      sequence: int = 1, prior_state: dict | None = None,
                      max_retries: int = 3) -> tuple[Scenario, list[str]]:
    """Returns (scenario, log). Raises RuntimeError if all retries fail."""
    schema = constrained_scenario_schema(theater)
    state = ""
    if prior_state:
        state = ("Campaign state from the previous mission (respect it: destroyed sites stay destroyed, "
                 "losses reduce available aircraft):\n" + json.dumps(prior_state))
    msgs = [{"role": "system", "content": SYSTEM.format(theater=theater, scn_id=scn_id, seq=sequence, state=state)},
            {"role": "user", "content": request}]
    log: list[str] = []
    sc = None
    for attempt in range(1, max_retries + 1):
        out = llm.chat(msgs, schema)
        sc, errs = validate(_extract(out))
        if sc:
            log.append(f"skeleton ok on attempt {attempt}")
            break
        log.append(f"attempt {attempt} errors: {errs}")
        msgs += [{"role": "assistant", "content": out},
                 {"role": "user", "content": "Fix these problems and return the full corrected JSON:\n- " + "\n- ".join(errs)}]
    else:
        raise RuntimeError("scenario generation failed validation:\n" + "\n".join(log))

    facts = sc.model_dump(exclude={"briefing"})
    bmsgs = [{"role": "system", "content": BRIEF_SYSTEM},
             {"role": "user", "content": json.dumps(facts)}]
    for attempt in range(1, max_retries + 1):
        out = llm.chat(bmsgs, briefing_schema())
        try:
            sc.briefing = Briefing.model_validate(_extract(out))
            log.append(f"briefing ok on attempt {attempt}")
            return sc, log
        except Exception as e:                                  # noqa: BLE001
            log.append(f"briefing attempt {attempt}: {e}")
    log.append("briefing left empty")
    return sc, log
