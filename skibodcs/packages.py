"""Friendly support packages: fighter cover and SEAD flights that fly with the player.
Rules for "auto" (the pilot can always override each slot):
  SEAD / DEAD -> fighter cover                       (you are the SEAD, so no second SEAD package)
  STRIKE      -> fighter cover + a SEAD package      (SEAD only when the enemy actually has SAMs)
  CAS         -> nothing automatic
  CAP         -> nothing automatic
Timing: AI flights start warm, so they are delayed by the time the player needs to start, taxi and take off; SEAD leaves slightly
after the cover so it arrives a few minutes ahead of the player, cover arrives well before."""
from __future__ import annotations

# key -> (aircraft id, count, label)
FIGHTERS = {"f15c_2": ("F-15C", 2, "2x F-15C Eagle"), "f15c_4": ("F-15C", 4, "4x F-15C Eagle"), "f16_2": ("F-16C_50", 2, "2x F-16C Viper"),
            "f18_2": ("FA-18C_hornet", 2, "2x F/A-18C Hornet"), "f14_2": ("F-14B", 2, "2x F-14B Tomcat")}
SEADS = {"f16_2": ("F-16C_50", 2, "2x F-16C (HARM)"), "f16_4": ("F-16C_50", 4, "4x F-16C (HARM)"), "f18_2": ("FA-18C_hornet", 2, "2x F/A-18C (HARM)")}
CALLSIGN = {"cover": "Uzi", "sead": "Wolf"}
ROLE_LABEL = {"cover": "Fighter cover", "sead": "SEAD package"}
GROUND_MIN = {"cold": 12.0, "warm": 6.0, "runway": 1.0}          # start + taxi + takeoff, before the player is airborne


def options() -> dict:
    return {"fighters": [{"id": "none", "label": "None"}, {"id": "auto", "label": "Automatic for my task"}]
                         + [{"id": k, "label": v[2]} for k, v in FIGHTERS.items()],
            "sead": [{"id": "none", "label": "None"}, {"id": "auto", "label": "Automatic for my task"}]
                     + [{"id": k, "label": v[2]} for k, v in SEADS.items()]}


def delay_min(role: str, start_type: str) -> float:
    ground = GROUND_MIN.get(start_type, 6.0)
    return round(max(0.0, ground - (6.0 if role == "cover" else 3.0)), 1)


def resolve(fighters: str, sead: str, task: str, has_sam: bool, start_airbase: str, start_type: str) -> tuple[list[dict], list[str]]:
    """Returns (support_flights as scenario dicts, notes)."""
    notes: list[str] = []
    out: list[dict] = []
    is_sead = task in ("SEAD", "DEAD")
    if fighters == "auto":
        fighters = "f15c_2" if (is_sead or task == "STRIKE") else "none"
        if fighters != "none":
            notes.append(f"fighter cover added automatically for {task}")
    if sead == "auto":
        if task == "STRIKE" and has_sam:
            sead = "f16_2"; notes.append("SEAD package added automatically for the strike")
        else:
            sead = "none"
            if task == "STRIKE":
                notes.append("no SAMs in the target area: no SEAD package needed")
    for role, key, table in (("cover", fighters, FIGHTERS), ("sead", sead, SEADS)):
        if key in (None, "", "none"):
            continue
        if key not in table:
            raise KeyError(f"unknown {ROLE_LABEL[role].lower()} '{key}'")
        ac, n, _label = table[key]
        out.append({"role": role, "aircraft": ac, "count": n, "start_airbase": start_airbase,
                    "delay_min": delay_min(role, start_type), "callsign": f"{CALLSIGN[role]} 1"})
    return out, notes
