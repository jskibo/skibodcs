import json, socket, threading, time
from pathlib import Path
from skibodcs import controls as C
from skibodcs.sequence import RunResult, SequenceRunner, Step, load_sequences
from skibodcs.voice.cockpit import load_table
from skibodcs.voice.link import DCSLink
from skibodcs.voice.router import Router
from skibodcs.voice.state import World

ROOT = Path(__file__).parent.parent
AF = ROOT / "airframes" / "f-16c.toml"


class FakeLLM:
    def __init__(self, reply): self.reply, self.calls = reply, []
    def chat(self, messages, schema=None): self.calls.append((messages, schema)); return self.reply


def cmd(**kw):
    base = dict(domain="control", intent="", mode="", weapon="", action="", value="", control="", position="",
                amount=-1.0, who="", level="", shape="", spacing="", addressed_to="", emergency=False)
    base.update(kw); return base


def mk(reply, clock=lambda: 0.0):
    _, cs = C.load(ROOT / "airframes" / "f-16c.controls.json")
    idx = C.ControlIndex(cs); table = load_table(AF); idx.merge_curated(table)
    return Router(FakeLLM(json.dumps({"commands": reply})), table, World(), index=idx, clock=clock)


def test_control_switch_resolves_real_ids_and_queues_readback():
    _, cs = C.load(ROOT / "airframes" / "f-16c.controls.json")
    k = next(c for c in cs if c.id == "engine_anti_ice_switch")
    assert "on" in k.positions
    r = mk([cmd(control="engine_anti_ice_switch", position="on")]).handle("turn the engine anti ice on")
    assert r.source == "llm" and r.cockpit == C.resolve(k, "on")
    assert r.checks == [(k.arg, k.name)] and r.speech == [f"{k.name} on"]
    assert any("UNVERIFIED" in n for n in r.notes)


def test_curated_actions_replace_generated_duplicates():
    rt = mk([cmd(domain="none")])
    assert "gear" in rt.index.by_id and "lg_handle" not in rt.index.by_id
    rt.handle("raise the landing gear")                       # prompt shortlist must not offer the covered control twice
    assert "lg_handle" not in rt.llm.calls[0][0][0]["content"]


def test_axis_needs_amount_then_scales():
    _, cs = C.load(ROOT / "airframes" / "f-16c.controls.json")
    vol = next(c for c in cs if c.id == "uhf_vol_knob")
    r = mk([cmd(control="uhf_vol_knob", amount=-1)]).handle("uhf volume")
    assert "say how much" in r.speech[0] and not r.cockpit
    r = mk([cmd(control="uhf_vol_knob", amount=60)]).handle("uhf volume sixty percent")
    assert r.cockpit == [(vol.device, vol.commands[0], 0.6)] and r.checks == [(vol.arg, vol.name)]
    assert "60 percent" in r.speech[0]


def test_shortlist_goes_into_prompt_and_schema_enum():
    rt = mk([cmd(domain="none")])
    rt.handle("turn the uhf volume up to sixty")
    msgs, schema = rt.llm.calls[0]
    enum = schema["properties"]["commands"]["items"]["properties"]["control"]["enum"]
    assert "uhf_vol_knob" in enum and len(enum) <= 14
    assert "uhf_vol_knob" in msgs[0]["content"] and "[axis 0-100]" in msgs[0]["content"]


def test_dangerous_control_requires_confirm():
    t = [0.0]
    rt = mk([cmd(control="canopy_jettison_t_handle", position="pull")], clock=lambda: t[0])
    r = rt.handle("jettison the canopy")
    assert r.cockpit == [] and "Confirm" in r.speech[0] and rt.pending
    r2 = rt.handle("Confirm")
    assert r2.cockpit and "confirmed" in r2.speech[0] and rt.pending is None


def test_confirm_expires_and_cancel_clears():
    t = [0.0]
    rt = mk([cmd(control="canopy_jettison_t_handle", position="pull")], clock=lambda: t[0])
    rt.handle("jettison the canopy"); t[0] = 11.0
    rt.llm.reply = json.dumps({"commands": [cmd(domain="none")]})
    assert rt.handle("confirm").cockpit == []                    # expired: not executed
    t[0] = 20.0
    rt.llm.reply = json.dumps({"commands": [cmd(control="canopy_jettison_t_handle", position="pull")]})
    rt.handle("jettison the canopy")
    r = rt.handle("negative")
    assert r.cockpit == [] and "Cancelled" in r.speech[0] and rt.pending is None


def test_unrelated_speech_drops_pending():
    rt = mk([cmd(control="canopy_jettison_t_handle", position="pull")])
    rt.handle("jettison the canopy")
    rt.llm.reply = json.dumps({"commands": [cmd(domain="none")]})
    rt.handle("nice weather today")
    assert rt.pending is None and rt.handle("confirm").cockpit == []


def test_unknown_control_from_llm_is_rejected():
    r = mk([cmd(control="eject_everything", position="now")]).handle("blah")
    assert r.cockpit == [] and any("unknown control" in n for n in r.notes)


def test_wingman_who_and_levels_pass_through():
    rt = mk([cmd(domain="wingman", intent="radar", who="element", level="off"),
             cmd(domain="wingman", intent="roe", who="wingman", level="return_fire"),
             cmd(domain="wingman", intent="formation", who="flight", shape="finger_four", spacing="close"),
             cmd(domain="wingman", intent="ecm")])                                   # missing level -> rejected
    r = rt.handle("element radar off, wingman return fire, finger four close")
    assert [w["intent"] for w in r.wingman] == ["radar", "roe", "formation"]
    assert r.wingman[0]["params"] == {"who": "element", "level": "off"}
    assert r.wingman[1]["params"] == {"who": "wingman", "level": "return_fire"}
    assert r.wingman[2]["params"] == {"shape": "finger_four", "spacing": "close"}
    assert any("needs a level" in n for n in r.notes)


def test_sequence_intent_and_abort_phrase():
    r = mk([cmd(domain="sequence", intent="autostart")]).handle("cold and dark to ready, start her up")
    assert r.sequence == ["autostart"]
    assert mk([]).handle("abort the start").abort_sequence is True


# ---------------- sequence engine
def test_runner_waits_sends_in_order_and_speaks_messages():
    slept, sent, said = [], [], []
    steps = [Step(0.5, 1, 3001, 1.0), Step(2.0, message="AUTOSTART COMPLETE"), Step(0.0, 2, 3002, 0.0)]
    res = SequenceRunner(lambda d, c, v: sent.append((d, c, v)) or True, said.append, sleep=slept.append).run(steps)
    assert sent == [(1, 3001, 1.0), (2, 3002, 0.0)] and said == ["AUTOSTART COMPLETE"]
    assert abs(sum(slept) - 2.5) < 1e-9 and res.ok and res.sent == 2


def test_runner_abort_stops_midway():
    sent = []
    runner = SequenceRunner(lambda d, c, v: sent.append(c) or True, sleep=lambda s: None)
    steps = [Step(0, 1, 1, 1.0), Step(0, 1, 2, 1.0), Step(0, 1, 3, 1.0)]
    first = steps[0]
    orig = runner.send
    runner.send = lambda d, c, v: (orig(d, c, v), runner.abort())[0]
    res = runner.run(steps)
    assert sent == [1] and res.cancelled


def test_runner_gives_up_when_link_down():
    said = []
    res = SequenceRunner(lambda d, c, v: False, said.append, sleep=lambda s: None).run([Step(0, 1, i, 1.0) for i in range(10)])
    assert res.failed == 3 and "Lost the link" in said[-1]


def test_load_sequences_roundtrip(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"aircraft": "X", "sequences": {"autostart": [
        {"delay": 0.1, "device": 3, "command": 3001, "value": 1.0}, {"delay": 5, "message": "done"}]}}))
    s = load_sequences(f)["autostart"]
    assert s[0].device == 3 and s[1].message == "done" and s[1].device is None


# ---------------- argument read-back
def test_read_arg_round_trip_and_unreachable():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    def serve():
        c, _ = srv.accept(); line = c.recv(100).decode().strip()
        assert line == "R,362"; c.sendall(b"ARG,361,0.0000\nARG,362,1.0000\n"); time.sleep(0.2); c.close()
    threading.Thread(target=serve, daemon=True).start()
    link = DCSLink(World(), command_port=srv.getsockname()[1])
    assert link.read_arg(362) == 1.0
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    assert DCSLink(World(), command_port=p).read_arg(1) is None
