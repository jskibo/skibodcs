"""Every clickable control of a module, classified for voice use.
Built from the extractor's output. Value semantics (which number means which position) are
PROVISIONAL unless an entry says verified; the closed-loop read-back/calibration step fixes that."""
from __future__ import annotations
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DANGER = re.compile(r"\bejec|jett|extingu|fire (?:disch|pull)|discharge|emerg|dump|zeroize|harness|"
                    r"spin rec|wing fold|canopy jett|fuel shut|cutoff|bleed.*off", re.I)
STOP = {"the", "a", "an", "to", "of", "and", "or", "on", "off", "in", "my", "please", "set", "switch", "knob",
        "button", "control", "handle", "lever", "turn", "put", "push", "press", "toggle"}


@dataclass
class Control:
    """aliases/verified come from the hand-verified TOML table when present."""
    id: str
    name: str
    kind: str                     # button | switch | multi | axis | other
    device: int
    device_name: str
    commands: list[int]
    command_names: list[str]
    arg: int
    positions: dict[str, float] = field(default_factory=dict)   # name -> command value
    momentary: bool = False
    danger: bool = False
    verified: bool = False
    fn: str = ""
    note: str = ""
    aliases: list[str] = field(default_factory=list)
    crew: str = ""                 # AH-64D: PLT or CPG ('' = single-seat / shared)
    confirmed: list[str] = field(default_factory=list)   # positions with a value taken from ED's autostart data
    inferred: list[str] = field(default_factory=list)    # positions deduced from a confirmed one (2/3-position switches)

    def to_json(self) -> dict:
        return asdict(self)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:48]


def _split_hint(hint: str) -> tuple[str, list[str]]:
    """'MASTER ARM Switch, MASTER ARM/OFF/SIMULATE' -> ('MASTER ARM Switch', [...])"""
    h = re.sub(r"\((?:RMB|LMB|MW)\)", "", hint)
    name, _, tail = h.partition(",")
    toks = [t.strip() for t in re.split(r"/", tail) if t.strip()] if tail else []
    return name.strip(), [re.sub(r"\s+", " ", t).lower() for t in toks]


def _names(tokens: list[str], n: int) -> list[str]:
    if len(tokens) == n:
        return tokens
    return [str(i + 1) for i in range(n)]


def classify(e: dict) -> Control | None:
    fn, hint = e["fn"], e["hint"]
    if e.get("device") is None or not e.get("commands"):
        return None
    name, toks = _split_hint(hint)
    cmds = e["commands"]
    p = e.get("params") or []
    arg = int(p[0]) if p else (e["args"][0] if e.get("args") else 0)
    c = Control(id="", name=name or hint, kind="other", device=int(e["device"]), device_name=e.get("device_name", ""),
                commands=[int(x["id"]) for x in cmds], command_names=[x["name"] for x in cmds], arg=arg, fn=fn,
                crew=(e.get("crew") or ""))
    l = fn.lower()
    if "rocker_switch" in l or l.endswith("_switch_negative") or l.endswith("_switch_positive") \
            or "push_button" in l or "pushbutton" in l:
        c.kind, c.positions, c.momentary = "button", {"press": 1.0}, True
        if l.endswith("negative"):
            c.note = "negative (down/decrease) side of a rocker"
        elif l.endswith("positive"):
            c.note = "positive (up/increase) side of a rocker"
        return _finish(c)
    if fn.startswith("custom:") or any(k in l for k in ("double_tumb", "tumb_button", "button_knob", "button_axis",
                                                          "button_tumb", "pull", "gear_control")):
        c.note = "composite control; not exposed to voice yet"
        return _finish(c)
    if "multiposition" in l:
        count = int(p[1]) if len(p) > 1 else len(toks) or 2
        delta = float(p[2]) if len(p) > 2 else 0.1
        mn = float(p[3]) if len(p) > 3 else 0.0
        names = _names(toks, count)
        c.kind, c.positions = "multi", {n: round(mn + i * delta, 4) for i, n in enumerate(names)}
    elif "axis" in l or "rheostat" in l or l == "default_lever":
        c.kind, c.positions = "axis", {}
        c.note = "continuous 0..1; say a percentage"
    elif "button" in l:
        c.kind, c.positions, c.momentary = "button", {"press": 1.0}, True
    elif "red_cover" in l:
        c.kind, c.positions = "switch", {"open": 1.0, "close": 0.0}
    elif "3_pos" in l and len(c.commands) == 2:                       # springloaded, one command per direction
        c.kind, c.momentary = "switch", True
        names = toks if len(toks) == 3 else ["a", "b"]
        sides = [t for t in names if t not in ("off", "center", "norm", "mid")][:2] or ["a", "b"]
        c.positions = {}
        for t in sides:                                               # match token to command name when possible
            idx = next((i for i, cn in enumerate(c.command_names) if _slug(t).replace("_", "") in _slug(cn).replace("_", "")), None)
            if idx is not None:
                c.positions[t] = 1.0 + idx * 0.0
        if len(c.positions) < 2:
            c.positions = {"first": 1.0, "second": 1.0}
            c.note = "two-command spring switch; direction naming unverified"
    elif "3_pos" in l:
        names = _names(toks, 3)
        c.kind, c.positions = "switch", dict(zip(names, (-1.0, 0.0, 1.0)))
        c.momentary = "springloaded" in l
    elif "2_pos" in l:
        names = _names(toks, 2)
        c.kind, c.positions = "switch", dict(zip(names, (0.0, 1.0)))
        c.momentary = "springloaded" in l
    else:
        c.note = f"unclassified helper {fn}"
        return _finish(c)
    return _finish(c)


def _finish(c: Control) -> Control:
    c.danger = bool(DANGER.search(c.name + " " + " ".join(c.positions)))
    c.id = _slug((c.crew + " " if c.crew else "") + c.name) or f"ctl_{c.device}_{c.commands[0]}"
    return c


def build_controls(elements: list[dict]) -> list[Control]:
    out, seen = [], {}
    for e in elements:
        c = classify(e)
        if c is None:
            continue
        base = c.id
        if base in seen:                      # disambiguate repeated names with the cockpit arg number
            c.id = f"{base}_{c.arg}"
            while c.id in seen:
                c.id += "_"
        seen[base] = seen.get(base, 0) + 1
        seen[c.id] = 1
        out.append(c)
    return out


def apply_macros(controls: list[Control], observed: dict) -> int:
    """Pin position values to what ED's autostart uses. Returns how many controls got at least one confirmed position."""
    from .macros import apply_observed
    n = 0
    for c in controls:
        if c.kind not in ("switch", "multi") or len(c.commands) != 1 or not c.positions:
            continue
        obs = observed.get((c.device, c.commands[0]))
        if not obs:
            continue
        pos, conf, inf = apply_observed(c.positions, obs)
        if conf:
            c.positions, c.confirmed, c.inferred = pos, sorted(conf), sorted(inf)
            c.verified = set(pos) <= (conf | inf)
            n += 1
    return n


def save(controls: list[Control], aircraft: str, path: str | Path, source: str = ""):
    Path(path).write_text(json.dumps({"aircraft": aircraft, "source": source, "generated_by": "skibodcs",
                                      "values": "PROVISIONAL unless verified=true",
                                      "controls": [c.to_json() for c in controls]}, indent=1))


def load(path: str | Path) -> tuple[str, list[Control]]:
    d = json.loads(Path(path).read_text())
    return d["aircraft"], [Control(**c) for c in d["controls"]]


def resolve(c: Control, position: str = "", amount: float = -1.0) -> list[tuple[int, int, float]]:
    """-> [(device, command, value), ...] ready for performClickableAction."""
    cmd = c.commands[0]
    if c.kind == "axis":
        if amount < 0:
            raise KeyError("say how much (a percentage)")
        return [(c.device, cmd, round(max(0.0, min(100.0, amount)) / 100.0, 4))]
    if c.kind in ("button", "switch", "multi"):
        if position not in c.positions:
            raise KeyError(f"'{position}' not valid for {c.name}; use {sorted(c.positions)}")
        v = c.positions[position]
        if len(c.commands) == 2 and c.kind == "switch":                # one command per direction
            i = list(c.positions).index(position)
            cmd = c.commands[min(i, 1)]
        out = [(c.device, cmd, v)]
        if c.momentary:
            out.append((c.device, cmd, 0.0))
        return out
    raise KeyError(f"{c.name} is not voice-controllable yet ({c.note})")


# ---------------------------------------------------------------- retrieval
SYNONYMS = {
    "gear": ["landing", "wheels", "undercarriage"], "landing": ["gear"], "hook": ["tailhook", "arresting"],
    "tailhook": ["hook"], "canopy": ["bubble"], "lights": ["light", "lighting"], "nav": ["navigation", "position"],
    "radar": ["fcr", "radar"], "refuel": ["refueling", "aar", "probe"], "uhf": ["comm", "radio"], "vhf": ["comm", "radio"],
    "radio": ["comm", "uhf", "vhf"], "master": ["master"], "flaps": ["flap"], "speedbrake": ["airbrake", "speed", "brake"],
    "battery": ["batt"], "generator": ["gen"], "apu": ["apu"], "jfs": ["jfs"], "wing": ["wingspan"],
}


ABBR = {"lg": "landing gear", "ldg": "landing", "vol": "volume", "brt": "brightness", "alt": "altitude altimeter",
        "mfd": "display", "mdi": "display", "ddi": "display", "ampcd": "display map", "ufc": "up front control",
        "icp": "up front control", "cmds": "countermeasures chaff flare", "rwr": "radar warning",
        "ecm": "jammer", "tgp": "targeting pod", "fcr": "radar", "hud": "head up display", "ins": "inertial",
        "epu": "emergency power", "jfs": "jet fuel starter", "apu": "auxiliary power unit", "ext": "exterior",
        "extlights": "exterior lights", "cptlights": "cockpit lights", "anticoll": "anti collision",
        "wng": "wing", "fus": "fuselage", "pos": "position", "nws": "nose wheel steering", "ky": "crypto",
        "ldg": "landing", "aar": "refuel", "dn": "down", "ils": "landing system", "tcn": "tacan"}


def tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP:
            continue
        w = w[:-1] if len(w) > 3 and w.endswith("s") else w
        out.append(w)
    return out


def doc_tokens(text: str) -> list[str]:
    out = []
    for t in tokens(text):
        out.append(t)
        if t in ABBR:
            out += tokens(ABBR[t])
    return out


class ControlIndex:
    def __init__(self, controls: list[Control], crew: str = ""):
        self.crew = crew
        self.controls = [c for c in controls if c.kind != "other" and (not crew or not c.crew or c.crew == crew)]
        self.by_id = {c.id: c for c in self.controls}
        self._docs = [doc_tokens(c.name + " " + " ".join(c.positions) + " " + c.device_name.replace("_", " ")
                                 + " " + " ".join(getattr(c, "aliases", []) or []))
                      for c in self.controls]
        n = len(self._docs)
        df: dict[str, int] = {}
        for d in self._docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log(1 + n / v) for t, v in df.items()}

    def merge_curated(self, table, aliases: dict[str, list[str]] | None = None):
        """Curated TOML actions (cockpit.AirframeTable) replace generated controls on the same device+command."""
        aliases = aliases or {}
        for name, a in table.actions.items():
            key = (a.device, a.command)
            self.controls = [c for c in self.controls if (c.device, c.commands[0]) != key]
            self.controls.append(Control(id=name, name=name.replace("_", " "), kind="button" if a.momentary else "switch",
                                         device=a.device, device_name="", commands=[a.command], command_names=[],
                                         arg=a.arg, positions=dict(a.values), momentary=a.momentary, verified=a.verified,
                                         aliases=aliases.get(name, [])))
        self.__init__(self.controls, self.crew)

    def search(self, text: str, k: int = 12) -> list[Control]:
        q = tokens(text)
        qx = set(q)
        for t in q:
            qx.update(tokens(" ".join(SYNONYMS.get(t, []))))
        scored = []
        for c, d in zip(self.controls, self._docs):
            ds = set(d)
            s = sum(self._idf.get(t, 0.0) for t in qx if t in ds)
            for t in qx:                                   # prefix match: vol ~ volume, brt ~ brightness
                if t not in ds and len(t) >= 3 and any((u.startswith(t) or t.startswith(u)) and len(u) >= 3 for u in ds):
                    s += 0.6 * self._idf.get(t, 1.0)
            if s > 0:                                   # prefer shorter, more specific names
                scored.append((s - 0.02 * len(d), c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:k]]
