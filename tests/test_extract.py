import os, shutil
from pathlib import Path
import pytest
from skibodcs import extract as ex
from skibodcs.voice.cockpit import load_table

FX = Path(__file__).parent / "fixtures" / "mini"
LUA = os.environ.get("LUAJIT") or shutil.which("luajit") or shutil.which("lua5.1") or (
    "/tmp/luajit/src/luajit" if Path("/tmp/luajit/src/luajit").exists() else None)
pytestmark = pytest.mark.skipif(not LUA, reason="no Lua 5.1/LuaJIT (set LUAJIT=...)")


@pytest.fixture(scope="module")
def els(monkeypatch_module=None):
    os.environ["LUAJIT"] = LUA
    return {e["key"]: e for e in ex.run_extractor(FX / "devices.lua", FX / "command_defs.lua", FX / "clickabledata.lua")}


def test_helper_elements_resolve_ids_names_devices(els):
    sw = els["SW-1"]
    assert sw["hint"] == "Test Switch, UP/DN" and sw["device"] == 2 and sw["device_name"] == "DEV_B"
    assert sw["commands"] == [{"name": "b_commands.Beta", "id": 3002}] and sw["args"] == [77]


def test_command_tables_are_independent_per_device(els):
    assert els["BTN-1"]["commands"] == [{"name": "a_commands.One", "id": 3001}]
    assert els["KNOB-1"]["commands"] == [{"name": "b_commands.Alpha", "id": 3001}]   # same number, other table


def test_three_position_has_both_commands(els):
    assert [c["id"] for c in els["TRI-1"]["commands"]] == [3001, 3002]


def test_constants_and_arithmetic_stubs_do_not_break_or_leak(els):
    assert els["KNOB-1"]["args"] == [30, 4]            # only real cockpit arg numbers kept (no anim speeds)


def test_custom_table_element(els):
    c = els["CUSTOM-1"]
    assert c["fn"].startswith("custom:") and c["hint"] == "Custom Handle"
    assert c["commands"] == [{"name": "a_commands.Two", "id": 3002}] and c["args"] == [5, 5]


def test_find(els):
    hits = ex.find(list(els.values()), "tri switch")
    assert [h["key"] for h in hits] == ["TRI-1"]
    assert [h["key"] for h in ex.find(list(els.values()), "b_commands.alpha")] == ["KNOB-1"]


def test_build_table_roundtrips_through_loader(els, monkeypatch, tmp_path):
    monkeypatch.setitem(ex.WISHLIST, "TEST", {
        "sw": ("b_commands.Beta", {"down": 1.0, "up": 0.0}, False),
        "btn": ("a_commands.One", {"press": 1.0}, True),
        "missing": ("a_commands.Nope", {"x": 1.0}, False)})
    text, problems = ex.build_table(list(els.values()), "TEST")
    assert problems and "Nope" in problems[0]
    f = tmp_path / "t.toml"; f.write_text(text)
    t = load_table(f)
    assert t.aircraft == "TEST"
    assert t.resolve("sw", "down") == [(2, 3002, 1.0)]
    assert t.resolve("btn", "press") == [(1, 3001, 1.0), (1, 3001, 0.0)]
    assert t.actions["sw"].arg == 77 and t.actions["sw"].verified is False


def test_shipped_tables_have_real_ids():
    for name, gear in (("f-16c.toml", (7, 3001)), ("fa-18c.toml", (5, 3001))):
        t = load_table(Path(__file__).parent.parent / "airframes" / name)
        a = t.actions["gear"]
        assert (a.device, a.command) == gear and a.arg > 0
