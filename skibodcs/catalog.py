"""Closed vocabularies, resolved against the installed pydcs (and so the DCS
version it targets). validate.py reports misses with suggestions."""
from __future__ import annotations
import difflib
import math
from functools import lru_cache

import dcs
from dcs import mapping
from dcs.vehicles import AirDefence as AD, Armor

THEATERS = {
    "caucasus": dcs.terrain.Caucasus, "persiangulf": dcs.terrain.PersianGulf,
    "syria": dcs.terrain.Syria, "nevada": dcs.terrain.Nevada,
    "marianaislands": dcs.terrain.MarianaIslands, "sinai": dcs.terrain.Sinai,
    "falklands": dcs.terrain.Falklands, "kola": dcs.terrain.Kola,
    "afghanistan": dcs.terrain.Afghanistan, "germany": dcs.terrain.Germany,
    "normandy": dcs.terrain.Normandy, "thechannel": dcs.terrain.TheChannel,
}

TASKS = {
    "CAP": dcs.task.CAP, "SEAD": dcs.task.SEAD, "CAS": dcs.task.CAS,
    "STRIKE": dcs.task.GroundAttack, "ESCORT": dcs.task.Escort,
}

# Ground-group templates: name -> [(pydcs vehicle class, count)]
GROUND_TEMPLATES = {
    "SA-2":  [(AD.SNR_75V, 1), (AD.S_75M_Volhov, 3)],
    "SA-6":  [(AD.Kub_1S91_str, 1), (AD.Kub_2P25_ln, 3)],
    "SA-8":  [(AD.Osa_9A33_ln, 2)],
    "SA-10": [(AD.S_300PS_40B6MD_sr, 1), (AD.S_300PS_64H6E_sr, 1), (AD.S_300PS_54K6_cp, 1),
              (AD.S_300PS_40B6M_tr, 1), (AD.S_300PS_5P85C_ln, 4)],
    "SA-11": [(AD.SA_11_Buk_SR_9S18M1, 1), (AD.SA_11_Buk_CC_9S470M1, 1), (AD.SA_11_Buk_LN_9A310M1, 3)],
    "SA-13": [(AD.Strela_10M3, 2)],
    "SA-15": [(AD.Tor_9A331, 2)],
    "ZSU-23": [(AD.ZSU_23_4_Shilka, 2)],
    "ARMOR_PLATOON": [(Armor.T_72B, 4)],
    "MECH_INF":      [(Armor.BMP_2, 4)],
}
SAM_TEMPLATES = {"SA-2", "SA-6", "SA-8", "SA-10", "SA-11", "SA-13", "SA-15", "ZSU-23"}


@lru_cache
def aircraft_ids() -> dict:
    out = {k: v for k, v in dcs.planes.plane_map.items()}
    out.update(dcs.helicopters.helicopter_map)
    return out


@lru_cache
def terrain(theater: str):
    key = theater.lower().replace(" ", "")
    if key not in THEATERS:
        raise KeyError(theater)
    return THEATERS[key]()


def airbases(theater: str) -> list[str]:
    return sorted(terrain(theater).airports)


def suggest(word: str, options, n=3) -> list[str]:
    return difflib.get_close_matches(word, list(options), n=n, cutoff=0.5)


def find_airbase(theater: str, name: str):
    t = terrain(theater)
    for k, v in t.airports.items():
        if k.lower() == name.lower():
            return v
    return None


def resolve_anchor(theater: str, anchor):
    """Anchor -> dcs Point (x=north, y=east, metres)."""
    ab = find_airbase(theater, anchor.near)
    if ab is None:
        raise KeyError(anchor.near)
    d = anchor.distance_nm * 1852.0
    b = math.radians(anchor.bearing)
    return mapping.Point(ab.position.x + d * math.cos(b),
                         ab.position.y + d * math.sin(b),
                         terrain(theater))


def catalog_dump(theater: str) -> dict:
    """What to paste into the generator prompt so the LLM only picks real names."""
    return {
        "theater": theater,
        "airbases": airbases(theater),
        "aircraft": sorted(aircraft_ids()),
        "tasks": sorted(TASKS),
        "ground_templates": sorted(GROUND_TEMPLATES),
    }
