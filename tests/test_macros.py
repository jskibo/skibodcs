import json, os, shutil
from pathlib import Path
import pytest
from skibodcs import controls as C, extract as ex, macros as M
from skibodcs.sequence import load_sequences
from skibodcs.voice.cockpit import load_table

ROOT = Path(__file__).parent.parent
FX = ROOT / "tests" / "fixtures" / "mini"
LUA = os.environ.get("LUAJIT") or shutil.which("luajit") or shutil.which("lua5.1") or (
    "/tmp/luajit/src/luajit" if Path("/tmp/luajit/src/luajit").exists() else None)
needs_lua = pytest.mark.skipif(not LUA, reason="no Lua 5.1/LuaJIT (set LUAJIT=...)")


# ---------- pure logic
def test_apply_observed_two_position_infers_the_other_side():
    pos, conf, inf = M.apply_observed({"down": 1.0, "up": 0.0}, {"dn": 0.0})        # ED: "LG HANDLE - DN" = 0.0
    assert pos == {"down": 0.0, "up": 1.0} and conf == {"down"} and inf == {"up"}


def test_apply_observed_three_position_needs_an_unambiguous_ordering():
    toks = {"flap full": 0.0, "half": 0.0, "auto": 0.0}
    pos, conf, inf = M.apply_observed({"auto": 1.0, "half": 0.0, "full": -1.0}, {"full": -1.0})
    assert pos == {"auto": 1.0, "half": 0.0, "full": -1.0} and conf == {"full"} and inf == {"auto", "half"}
    # middle position alone does not decide the direction -> nothing inferred
    pos, conf, inf = M.apply_observed({"master arm": 1.0, "off": 0.0, "simulate": -1.0}, {"off": 0.0})
    assert conf == {"off"} and not inf and pos["master arm"] == 1.0                 # still the provisional guess


def test_synonyms_and_parentheticals_match():
    assert M.match_token("DN", ["up", "down"]) == "down"
    assert M.match_token("NORM (GUARD DOWN)", ["norm", "reset"]) == "norm"
    assert M.match_token("off", ["safe", "arm"], {"safe": "off"}) == "safe"
    assert M.match_token("banana", ["up", "down"]) is None


def test_observed_values_pair_each_click_with_the_message_before_it():
    raw = {"start": [{"t": 1, "message": "- HOOK SWITCH - UP"}, {"t": 2, "device": 7, "command": 3006, "value": 1.0},
                     {"t": 3, "message": "COMM PANEL"}, {"t": 4, "device": 9, "command": 1, "value": 0.5}], "stop": []}
    assert M.observed_values(raw) == {(7, 3006): {"up": 1.0}}                          # unlabelled click is not guessed at
    # a heading like "COMM PANEL - SET" labels its clicks 'set'; that must never pin a control that has no such position
    raw["start"][2]["message"] = "COMM PANEL - SET"
    assert M.observed_values(raw)[(9, 1)] == {"set": 0.5}
    pos, conf, inf = M.apply_observed({"up": 1.0, "dn": 0.0}, {"set": 0.5})
    assert pos == {"up": 1.0, "dn": 0.0} and not conf and not inf


# ---------- real extraction under LuaJIT with a small synthetic file in ED's format
@needs_lua
def test_macro_extractor_and_sequences():
    os.environ["LUAJIT"] = LUA
    raw = ex.run_macro_extractor(FX / "devices.lua", FX / "command_defs.lua", FX / "macros.lua")
    clicks = [e for e in raw["start"] if "device" in e]
    assert [(c["device"], c["command"], c["value"]) for c in clicks[:2]] == [(1, 3001, 0.0), (2, 3002, 1.0)]
    assert clicks[0]["command_name"] == "a_commands.One"
    assert any(e.get("check") == "M_AD_THROTTLE_SET_TO_IDLE" for e in raw["start"])
    seq = M.to_sequences(raw, "TEST")["sequences"]["autostart"]
    assert seq[0]["message"] == "AUTOSTART SEQUENCE IS RUNNING" and seq[0]["speak"] is True
    assert [s for s in seq if s.get("prompt")][0]["message"] == "THROTTLE - TO IDLE"   # pilot must act: spoken prompt
    assert not any("MUST BE AT IDLE" in s.get("message", "") for s in seq)             # ED's internal check not replayed
    assert abs(sum(s["delay"] for s in seq) - raw["start"][-1]["t"]) < 1e-6            # timeline preserved
    obs = M.observed_values(raw)
    assert obs[(1, 3001)] == {"down": 0.0} and obs[(2, 3002)] == {"up": 1.0}


@needs_lua
def test_controls_pinned_by_macros_on_the_mini_fixture():
    els = ex.run_extractor(FX / "devices.lua", FX / "command_defs.lua", FX / "clickabledata.lua")
    cs = C.build_controls(els)
    raw = ex.run_macro_extractor(FX / "devices.lua", FX / "command_defs.lua", FX / "macros.lua")
    n = C.apply_macros(cs, M.observed_values(raw))
    sw = next(c for c in cs if c.id == "test_switch")        # "Test Switch, UP/DN" on DEV_B/Beta, ED says UP = 1.0
    assert n >= 1 and sw.positions["up"] == 1.0 and "up" in sw.confirmed and sw.positions["dn"] == 0.0 and sw.verified


# ---------- shipped artifacts generated from the real game files
def test_shipped_curated_tables_use_edss_values():
    f16 = load_table(ROOT / "airframes" / "f-16c.toml")
    assert f16.actions["gear"].confirmed == ["down", "up"] and f16.resolve("gear", "down") == [(7, 3001, 0.0)]
    assert f16.resolve("gear", "up") == [(7, 3001, 1.0)] and f16.actions["gear"].verified
    assert f16.actions["master_arm"].confirmed == ["safe"] and not f16.actions["master_arm"].verified
    hornet = load_table(ROOT / "airframes" / "fa-18c.toml")
    assert hornet.resolve("gear", "down") == [(5, 3001, 0.0)] and hornet.resolve("master_arm", "safe") == [(23, 3003, 0.0)]
    assert hornet.resolve("master_arm", "arm") == [(23, 3003, 1.0)] and hornet.actions["master_arm"].verified
    ah = load_table(ROOT / "airframes" / "ah-64d.toml")
    assert ah.resolve("rotor_brake", "brk") == [(5, 3001, 0.0)] and ah.resolve("parking_brake", "set") == [(7, 3001, 1.0)]


@pytest.mark.parametrize("name,first_msg,last_msg,min_s,max_s", [
    ("f-16c.json", "AUTOSTART SEQUENCE IS RUNNING", "AUTOSTART COMPLETE", 200, 320),
    ("fa-18c.json", "AUTOSTART SEQUENCE IS RUNNING", "AUTOSTART COMPLETE", 250, 400),
    ("ah-64d.json", "AUTOSTART SEQUENCE IS RUNNING", "AUTOSTART COMPLETE", 350, 480)])
def test_shipped_sequences(name, first_msg, last_msg, min_s, max_s):
    seqs = load_sequences(ROOT / "sequences" / name)
    a = seqs["autostart"]
    msgs = [s.message for s in a if s.message]
    assert msgs[0] == first_msg and msgs[-1] == last_msg
    assert min_s < sum(s.delay for s in a) < max_s and sum(1 for s in a if s.device is not None) > 100
    assert any(s.prompt for s in a)                       # pilot-action prompts exist (throttle / power levers)
    assert seqs["autostop"] and [s.message for s in seqs["autostop"] if s.message][-1] == "AUTOSTOP COMPLETE"


def test_ah64_crew_filter():
    _, cs = C.load(ROOT / "airframes" / "ah-64d.controls.json")
    plt = C.ControlIndex(cs, crew="PLT")
    assert plt.controls and all(c.crew in ("", "PLT") for c in plt.controls)
    assert any(c.id.startswith("plt_") for c in plt.controls) and not any(c.id.startswith("cpg_") for c in plt.controls)
    assert plt.search("rotor brake", 1)[0].id == "plt_rotor_brake_switch"
