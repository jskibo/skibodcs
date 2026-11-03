"""ED's own autostart data (Macro_sequencies.lua) -> (1) sequences/<aircraft>.json, (2) the GAME'S real values
for the switches it exercises, so we do not have to guess which number means 'down' or 'arm'."""
from __future__ import annotations
import json
import re
from pathlib import Path

PROMPT_CHECKS = ("_SET_TO_", "_DOWN_TO_")          # ED asks the pilot to move a physical lever (throttle, power levers)
SYNONYMS = {"dn": "down", "dwn": "down", "stby": "standby", "ext": "extend", "retr": "retract"}


def norm(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", s.lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(SYNONYMS.get(w, w) for w in s.split())


def _label(message: str) -> str | None:
    text = message.strip().lstrip("-").strip()
    if " - " not in text:
        return None
    lab = norm(text.rsplit(" - ", 1)[1])
    return lab if lab and len(lab) <= 24 else None


def observed_values(raw: dict) -> dict[tuple[int, int], dict[str, float]]:
    """(device, command) -> {label ED states for that click: value ED sends}."""
    obs: dict[tuple[int, int], dict[str, float]] = {}
    for key in ("start", "stop"):
        label = None
        for e in raw.get(key, []):
            if "message" in e:
                label = _label(e["message"])
            elif "device" in e and label:
                obs.setdefault((int(e["device"]), int(e["command"])), {}).setdefault(label, float(e["value"]))
    return obs


def match_token(label: str, tokens, synonyms: dict[str, str] | None = None) -> str | None:
    lab = norm(label)
    syn = {norm(v): k for k, v in (synonyms or {}).items()}          # ED label -> our token
    if lab in syn and syn[lab] in tokens:
        return syn[lab]
    ntok = {t: norm(t) for t in tokens}
    for t, n in ntok.items():
        if n == lab:
            return t
    for t, n in ntok.items():
        if n and lab and (n.startswith(lab) or lab.startswith(n)) and min(len(n), len(lab)) >= 2:
            return t
    return None


def apply_observed(positions: dict[str, float], observed: dict[str, float],
                   synonyms: dict[str, str] | None = None) -> tuple[dict[str, float], set[str], set[str]]:
    """Overwrite positions with ED's values where its autostart names them; infer the rest of a 2/3-position
    switch only when exactly one of the two possible orderings fits. Returns (positions, confirmed, inferred)."""
    pos = dict(positions)
    confirmed: set[str] = set()
    for label, value in observed.items():
        tok = match_token(label, list(pos), synonyms)
        if tok is not None:
            pos[tok] = float(value)
            confirmed.add(tok)
    inferred: set[str] = set()
    toks = list(positions)
    if len(toks) in (2, 3) and confirmed and len(confirmed) < len(toks):
        cands = [[0.0, 1.0], [1.0, 0.0]] if len(toks) == 2 else [[-1.0, 0.0, 1.0], [1.0, 0.0, -1.0]]
        fit = [c for c in cands if all(abs(c[toks.index(t)] - pos[t]) < 1e-9 for t in confirmed)]
        if len(fit) == 1:
            for t, v in zip(toks, fit[0]):
                if t not in confirmed:
                    pos[t] = v; inferred.add(t)
    return pos, confirmed, inferred


def to_sequences(raw: dict, aircraft: str, source: str = "") -> dict:
    """Timeline -> steps with `delay` = seconds since the previous EMITTED step (skipped checks fold into the next delay)."""
    out: dict[str, list] = {}
    for name, key in (("autostart", "start"), ("autostop", "stop")):
        steps, prev, last_prompt = [], 0.0, None
        for e in raw.get(key, []):
            t, delay = float(e["t"]), max(0.0, float(e["t"]) - prev)
            if "device" in e:
                steps.append({"delay": round(delay, 4), "device": int(e["device"]), "command": int(e["command"]),
                              "value": float(e["value"]), "note": e.get("command_name", "")})
                prev = t
            elif "message" in e:
                text = e["message"].strip().lstrip("-").strip()
                steps.append({"delay": round(delay, 4), "message": text, "speak": " - " not in text})
                prev = t
            elif "check" in e and any(p in e["check"] for p in PROMPT_CHECKS):
                txt = e.get("text", "")
                if txt and txt != last_prompt:
                    steps.append({"delay": round(delay, 4), "message": txt, "prompt": True, "speak": True})
                    last_prompt, prev = txt, t
        out[name] = steps
    return {"aircraft": aircraft, "source": source or "Macro_sequencies.lua (ED)",
            "note": "Timeline replayed from ED's own autostart. check_condition entries that ask the pilot to move a "
                    "physical lever become spoken prompts; ED's internal verification checks are not replayed.",
            "sequences": out}


def save_sequences(seq: dict, path: str | Path):
    Path(path).write_text(json.dumps(seq, indent=1))
