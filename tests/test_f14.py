import json, os, shutil
from pathlib import Path
import pytest
from skibodcs import controls as C, extract as ex
from skibodcs.sequence import SequenceRunner, Step, load_sequences
from skibodcs.voice.cockpit import load_table
import socket, threading, time
from skibodcs.voice.link import DCSLink
from skibodcs.voice.state import World

ROOT = Path(__file__).parent.parent
FX = ROOT / "tests" / "fixtures" / "mini_f14"
LUA = os.environ.get("LUAJIT") or shutil.which("luajit") or shutil.which("lua5.1") or (
    "/tmp/luajit/src/luajit" if Path("/tmp/luajit/src/luajit").exists() else None)


@pytest.mark.skipif(not LUA, reason="no Lua 5.1/LuaJIT")
def test_modules_with_their_own_helpers_and_missing_support_files():
    os.environ["LUAJIT"] = LUA
    els = {e["key"]: e for e in ex.run_extractor(FX / "devices.lua", FX / "command_defs.lua", FX / "clickabledata.lua")}
    x1, x2, x3 = els["X1"], els["X2"], els["X3"]
    assert x1["fn"] == "default_2_position_tumb" and x1["hint"] == "Gear Lever" and x1["device_name"] == "GEARHOOK"
    assert [c["id"] for c in x1["commands"]] == [3001] and x1["crew"] == "PLT" and x1["arg"] is None
    assert x2["crew"] == "RIO" and x2["fn"] == "default_button" and x2["commands"][0]["id"] == 3003
    assert x3["crew"] is None                                              # defaults to both seats
    cs = {c.id: c for c in C.build_controls(list(els.values()))}
    assert cs["plt_gear_lever"].kind == "switch" and cs["plt_gear_lever"].arg == 0
    assert cs["plt_gear_lever"].positions == {"off": 0.0, "on": 1.0} and "generic" in cs["plt_gear_lever"].note
    assert cs["rio_radar_reset"].kind == "button" and cs["shared_button"].crew == ""


def test_shipped_f14_artifacts():
    ac, cs = C.load(ROOT / "airframes" / "f-14b.controls.json")
    assert ac == "F-14B" and len(cs) > 400
    assert {c.crew for c in cs} == {"", "PLT", "RIO"}
    pilot = C.ControlIndex(cs, crew="PLT")
    assert all(c.crew in ("", "PLT") for c in pilot.controls)
    t = load_table(ROOT / "airframes" / "f-14b.toml")
    assert (t.actions["gear"].device, t.actions["gear"].command) == (18, 3016) and t.actions["gear"].confirmed == []
    assert not t.actions["gear"].verified                                        # no autostart data for this module
    seq = load_sequences(ROOT / "sequences" / "f-14b.json")
    assert [s.icommand for s in seq["autostart"] if s.icommand] == [311] and [s.icommand for s in seq["autostop"] if s.icommand] == [312]


def test_runner_sends_native_icommands():
    t = [0.0]
    sent = []
    run = SequenceRunner(lambda d, c, v: True, sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0],
                         send_icommand=lambda code: sent.append(code) or True)
    res = run.run([Step(0, message="go", speak=True), Step(0.5, icommand=311)])
    assert sent == [311] and res.ok and res.sent == 1
    bad = SequenceRunner(lambda d, c, v: True, sleep=lambda s: None, clock=lambda: 0.0, send_icommand=lambda c: False)
    said = []; bad.say = said.append
    assert bad.run([Step(0, icommand=311)]).failed == 1 and "Could not send" in said[-1]


def test_link_sends_icommand_line():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    got = []
    threading.Thread(target=lambda: (lambda c: (got.append(c.recv(100).decode()), c.close()))(srv.accept()[0]), daemon=True).start()
    link = DCSLink(World(), command_port=srv.getsockname()[1])
    assert link.send_icommand(311) and link.send_icommand(2004, -1.0) is True
    time.sleep(0.2)
    assert got and got[0].startswith("C,311\n")
