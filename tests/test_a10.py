import os, shutil
from pathlib import Path
import pytest
from skibodcs import controls as C, extract as ex
from skibodcs.sequence import load_sequences
from skibodcs.voice.cockpit import load_table

ROOT = Path(__file__).parent.parent
FX = ROOT / "tests" / "fixtures"
LUA = os.environ.get("LUAJIT") or shutil.which("luajit") or shutil.which("lua5.1") or (
    "/tmp/luajit/src/luajit" if Path("/tmp/luajit/src/luajit").exists() else None)
needs_lua = pytest.mark.skipif(not LUA, reason="no Lua 5.1/LuaJIT")


@needs_lua
def test_arg_comes_from_the_element_a_module_helper_returns():
    os.environ["LUAJIT"] = LUA
    d = FX / "mini_a10"
    els = {e["key"]: e for e in ex.run_extractor(d / "devices.lua", d / "command_defs.lua", d / "clickabledata.lua")}
    assert (els["G"]["arg"], els["B"]["arg"], els["ES"]["arg"]) == (716, 246, 676)   # was 0 -> read-back could never verify


@needs_lua
def test_device_qualified_wishlist_names_disambiguate_reused_command_names(monkeypatch):
    os.environ["LUAJIT"] = LUA
    d = FX / "mini_a10"
    els = ex.run_extractor(d / "devices.lua", d / "command_defs.lua", d / "clickabledata.lua")
    monkeypatch.setitem(ex.WISHLIST, "T", {
        "gear": ("CPT_MECH:device_commands.Button_1", {"down": 1.0, "up": 0.0}, False, {}),
        "battery": ("ELEC_INTERFACE:device_commands.Button_1", {"on": 1.0, "off": 0.0}, False, {})})
    text, problems = ex.build_table(els, "T")
    assert not problems
    import tomllib
    t = tomllib.loads(text)["actions"]
    assert (t["gear"]["device"], t["gear"]["arg"]) == (2, 716) and (t["battery"]["device"], t["battery"]["arg"]) == (1, 246)


@needs_lua
def test_draw_args_file_supplies_cockpit_arg_numbers():
    os.environ["LUAJIT"] = LUA
    d = FX / "mini_f14_draw"            # same elements as mini_f14, but its clickabledata dofile()s draw_args.lua like the real one
    base = ex.run_extractor(d / "devices.lua", d / "command_defs.lua", d / "clickabledata.lua")
    withd = ex.run_extractor(d / "devices.lua", d / "command_defs.lua", d / "clickabledata.lua", d / "draw_args.lua")
    assert {e["key"]: e["arg"] for e in base}["X1"] is None
    got = {e["key"]: e["arg"] for e in withd}
    assert got["X1"] == 326 and got["X2"] == 7 and got["X3"] is None


@pytest.mark.parametrize("name,ac", [("a-10c", "A-10C"), ("a-10c-ii", "A-10C_2")])
def test_shipped_a10_artifacts(name, ac):
    got_ac, cs = C.load(ROOT / "airframes" / f"{name}.controls.json")
    assert got_ac == ac and len(cs) > 400
    assert all(c.arg for c in cs)                                           # every control can be read back
    byid = {c.id: c for c in cs}
    assert byid["apu_on_off"].positions == {"off": 0.0, "on": 1.0} and set(byid["apu_on_off"].confirmed) == {"on", "off"}
    assert byid["canopy_jettison_lever"].danger and byid["emergency_jettison_external_stores"].danger
    t = load_table(ROOT / "airframes" / f"{name}.toml")
    assert t.aircraft == ac
    assert (t.actions["gear"].device, t.actions["gear"].command, t.actions["gear"].arg) == (39, 3001, 716)
    assert not t.actions["gear"].verified                                   # ED's autostart never moves the gear lever
    assert t.actions["apu"].verified and t.actions["battery"].verified
    seq = load_sequences(ROOT / "sequences" / f"{name}.json")
    assert 120 < len(seq["autostart"]) < 200 and len(seq["autostop"]) > 30
    assert any("READY TO FLY" in (s.message or "") for s in seq["autostart"])


def test_f14_arg_numbers_now_known():
    ac, cs = C.load(ROOT / "airframes" / "f-14b.controls.json")
    by = {c.id: c for c in cs}
    assert (by["landing_gear_lever"].arg, by["hook_extension_handle"].arg) == (326, 238)
    assert sum(1 for c in cs if not c.arg) < 15
    t = load_table(ROOT / "airframes" / "f-14b.toml")
    assert t.actions["gear"].arg == 326 and t.actions["hook"].arg == 238
