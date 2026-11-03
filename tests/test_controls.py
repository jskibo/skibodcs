import json, os, shutil
from pathlib import Path
import pytest
from skibodcs import controls as C, extract as ex
from skibodcs.voice.cockpit import load_table

ROOT = Path(__file__).parent.parent
FX = ROOT / "tests" / "fixtures" / "mini"
LUA = os.environ.get("LUAJIT") or shutil.which("luajit") or shutil.which("lua5.1") or (
    "/tmp/luajit/src/luajit" if Path("/tmp/luajit/src/luajit").exists() else None)


def E(fn, hint, cmds, params, dev=1, dn="DEV"):
    return {"key": hint, "fn": fn, "hint": hint, "device": dev, "device_name": dn,
            "commands": [{"name": f"x.{c}", "id": i} for c, i in cmds], "args": [int(params[0])], "params": params}


def test_classification_of_each_kind():
    cs = {c.id: c for c in C.build_controls([
        E("default_2_position_tumb", "LG Handle, UP/DN", [("LG", 3001)], [362]),
        E("default_3_position_tumb", "MASTER ARM Switch, MASTER ARM/OFF/SIMULATE", [("MA", 3002)], [105]),
        E("default_button", "Test Button", [("B", 3003)], [12]),
        E("multiposition_switch", "AIR SOURCE Knob, OFF/NORM/DUMP/RAM", [("AS", 3004)], [693, 4, 0.1, 0]),
        E("multiposition_switch_tumb", "UHF 100 MHz", [("U", 3005)], [411, 3, 0.1, 0.1]),
        E("default_axis_limited", "UHF VOL Knob", [("V", 3006)], [420]),
        E("springloaded_2_pos_tumb", "Spring Switch, A/B", [("S", 3007)], [9]),
        E("custom:", "Weird", [("W", 3008)], [5]),
    ])}
    assert cs["lg_handle"].kind == "switch" and cs["lg_handle"].positions == {"up": 0.0, "dn": 1.0}
    assert cs["master_arm_switch"].positions == {"master arm": -1.0, "off": 0.0, "simulate": 1.0}
    b = cs["test_button"]; assert b.kind == "button" and b.momentary and b.positions == {"press": 1.0}
    assert cs["air_source_knob"].positions == {"off": 0.0, "norm": 0.1, "dump": 0.2, "ram": 0.3} and cs["air_source_knob"].danger
    assert cs["uhf_100_mhz"].positions == {"1": 0.1, "2": 0.2, "3": 0.30000000000000004} or \
        [round(v, 3) for v in cs["uhf_100_mhz"].positions.values()] == [0.1, 0.2, 0.3]
    assert cs["uhf_vol_knob"].kind == "axis" and cs["spring_switch"].momentary
    assert cs["weird"].kind == "other"


def test_resolve_values_and_errors():
    cs = {c.id: c for c in C.build_controls([
        E("default_2_position_tumb", "LG Handle, UP/DN", [("LG", 3001)], [362]),
        E("default_button", "Test Button", [("B", 3003)], [12]),
        E("default_axis_limited", "UHF VOL Knob", [("V", 3006)], [420])])}
    assert C.resolve(cs["lg_handle"], "dn") == [(1, 3001, 1.0)]
    assert C.resolve(cs["test_button"], "press") == [(1, 3003, 1.0), (1, 3003, 0.0)]
    assert C.resolve(cs["uhf_vol_knob"], amount=60) == [(1, 3006, 0.6)]
    assert C.resolve(cs["uhf_vol_knob"], amount=250) == [(1, 3006, 1.0)]       # clamped
    with pytest.raises(KeyError): C.resolve(cs["lg_handle"], "sideways")
    with pytest.raises(KeyError): C.resolve(cs["uhf_vol_knob"])


def test_danger_regex_catches_eject_not_reject():
    cs = {c.id: c for c in C.build_controls([
        E("default_2_position_tumb", "Ejection Seat SAFE/ARMED Handle, SAFE/ARMED", [("E", 3001)], [1]),
        E("default_2_position_tumb", "HUD Symbology Reject Switch, NORM/REJ", [("R", 3002)], [2]),
        E("default_button", "Emergency Jettison Button", [("J", 3003)], [3])])}
    assert cs["ejection_seat_safe_armed_handle"].danger and cs["emergency_jettison_button"].danger
    assert not cs["hud_symbology_reject_switch"].danger


def test_duplicate_names_get_unique_ids():
    cs = C.build_controls([E("default_button", "Station Button", [("A", 3001)], [155]),
                           E("default_button", "Station Button", [("B", 3002)], [157]),
                           E("default_button", "Station Button", [("C", 3003)], [159])])
    assert len({c.id for c in cs}) == 3


def test_search_finds_by_abbreviation_and_prefix():
    cs = C.build_controls([
        E("default_2_position_tumb", "LG Handle, UP/DN", [("LG", 3001)], [362]),
        E("default_axis_limited", "UHF VOL Knob", [("V", 3006)], [420]),
        E("default_2_position_tumb", "HOOK Switch, UP/DN", [("H", 3007)], [354]),
        E("default_2_position_tumb", "Left Generator Control Switch, NORM/OFF", [("G", 3008)], [402])])
    idx = C.ControlIndex(cs)
    assert idx.search("raise the landing gear")[0].id == "lg_handle"
    assert idx.search("set the uhf volume to 60")[0].id == "uhf_vol_knob"
    assert idx.search("drop the tailhook")[0].id == "hook_switch"
    assert idx.search("left generator off")[0].id == "left_generator_control_switch"
    assert idx.search("zzzz nothing") == []


def test_merge_curated_overrides_generated_same_command():
    cs = C.build_controls([E("default_2_position_tumb", "LG Handle, UP/DN", [("LG", 3001)], [362], dev=7)])
    idx = C.ControlIndex(cs)
    idx.merge_curated(load_table(ROOT / "airframes" / "f-16c.toml"), {"gear": ["landing gear"]})
    assert "lg_handle" not in idx.by_id and "gear" in idx.by_id and idx.search("landing gear")[0].id == "gear"


@pytest.mark.parametrize("name,aircraft,gear_query,expect", [
    ("f-16c.controls.json", "F-16C_50", "landing gear handle", "lg_handle"),
    ("fa-18c.controls.json", "FA-18C_hornet", "arresting hook", "arresting_hook_handle")])
def test_shipped_controls_files(name, aircraft, gear_query, expect):
    ac, cs = C.load(ROOT / "airframes" / name)
    assert ac == aircraft and len(cs) > 200 and len({c.id for c in cs}) == len(cs)
    idx = C.ControlIndex(cs)
    assert idx.search(gear_query, 3)[0].id == expect
    assert any(c.danger for c in cs) and all(c.verified is False for c in cs)
    assert sum(c.kind in ("switch", "button", "multi", "axis") for c in cs) / len(cs) > 0.9
