import json, math
from pathlib import Path
from skibodcs.voice import brevity as bv, comms
from skibodcs.voice.cockpit import load_table
from skibodcs.voice.geo import angle_diff, aspect_word, bearing_true, distance_nm
from skibodcs.voice.intents import intent_schema
from skibodcs.voice.router import Router
from skibodcs.voice.state import Airfield, Contact, Ownship, World

AF = Path(__file__).parent.parent / "airframes/f-16c.toml"


class FakeLLM:
    def __init__(self, reply): self.reply, self.calls = reply, []
    def chat(self, messages, schema=None):
        self.calls.append((messages, schema)); return self.reply


def world():
    w = World(own=Ownship("F-16C_50", 41.6, 41.6, 20000, 90, 400),
              bullseye=(41.0, 42.0), wind_from=310.0)
    # hostile due north ~28nm, heading south (pointing at us)
    w.contacts = [Contact("1", 41.6 + 28 / 60, 41.6, 22000, 180, 450, "red")]
    w.airfields = [Airfield("Batumi", 41.61, 41.60, 33, [310.0], 131.0)]
    return w


def test_geo_basics():
    assert abs(distance_nm(0, 0, 1, 0) - 60) < 0.2
    assert abs(bearing_true(0, 0, 1, 0)) < 0.01 or abs(bearing_true(0, 0, 1, 0) - 360) < 0.01
    assert abs(bearing_true(0, 0, 0, 1) - 90) < 0.01
    assert angle_diff(350, 10) == 20
    assert aspect_word(180, 180) == "hot" and aspect_word(0, 180) == "cold"
    assert aspect_word(90, 180) == "beam"


def test_brevity():
    assert bv.digits(9) == "niner" and bv.heading3(0) == "three six zero"
    assert bv.heading3(45) == "zero four five"
    assert bv.thousands(22400) == "twenty-two thousand"
    assert bv.callsign_speech("Viper 1-1") == "Viper one one"


def test_bogey_dope_uses_computed_numbers():
    s = comms.bogey_dope(world(), "Viper 1-1")
    assert "braa three six zero" in s and "twenty-eight" in s and "twenty-two thousand" in s and "hot" in s


def test_clean_picture_and_dope():
    w = world(); w.contacts = []
    assert "clean" in comms.bogey_dope(w, "Viper 1-1")
    assert "clean" in comms.picture(w, "Viper 1-1")


def test_picture_groups_merge():
    w = world()
    w.contacts.append(Contact("2", w.contacts[0].lat + 0.02, 41.6, 22000, 180, 450, "red"))
    assert "one group" in comms.picture(w, "Viper 1-1") and "2 contacts" in comms.picture(w, "Viper 1-1")


def test_runway_into_wind():
    af = world().airfields[0]
    h, label = comms.active_runway(af, 310.0)
    assert h == 310.0 and label == "31"
    assert comms.active_runway(af, 130.0)[1] == "13"


def test_fast_path_skips_llm():
    llm = FakeLLM("{}"); r = Router(llm, load_table(AF), world())
    res = r.handle("Magic, bogey dope.")
    assert res.source == "fast" and not llm.calls and "braa" in res.speech[0]


def test_natural_phrase_goes_to_llm_and_dispatches():
    reply = json.dumps({"commands": [{"domain": "comms", "intent": "bogey_dope", "action": "", "value": "",
                                      "addressed_to": "Magic", "emergency": False}]})
    llm = FakeLLM(reply); r = Router(llm, load_table(AF), world())
    res = r.handle("uh Magic what's that guy bearing down on us")
    assert res.source == "llm" and "braa" in res.speech[0]
    assert llm.calls[0][1]["properties"]["commands"]["items"]["properties"]["action"]["enum"]


def test_compound_cockpit_commands_resolve_to_ids():
    reply = json.dumps({"commands": [
        {"domain": "cockpit", "intent": "", "action": "gear", "value": "down", "addressed_to": "", "emergency": False},
        {"domain": "cockpit", "intent": "", "action": "master_arm", "value": "safe", "addressed_to": "", "emergency": False}]})
    r = Router(FakeLLM(reply), load_table(AF), world())
    res = r.handle("drop the wheels and safe the master arm")
    assert res.cockpit == [(7, 3001, 1.0), (19, 3002, 0.0)]      # real ids from ED's files
    assert any("UNVERIFIED" in n for n in res.notes)


def test_invalid_action_rejected_not_executed():
    reply = json.dumps({"commands": [{"domain": "cockpit", "intent": "", "action": "eject", "value": "now",
                                      "addressed_to": "", "emergency": False}]})
    res = Router(FakeLLM(reply), load_table(AF), world()).handle("get me out")
    assert res.cockpit == [] and res.speech == []


def test_chatter_is_silent():
    reply = json.dumps({"commands": [{"domain": "none", "intent": "", "action": "", "value": "",
                                      "addressed_to": "", "emergency": False}]})
    res = Router(FakeLLM(reply), load_table(AF), world()).handle("hey Dave did you see the game")
    assert res.speech == [] and res.cockpit == [] and res.source == "none"


def test_garbage_llm_output_is_safe():
    res = Router(FakeLLM("not json"), load_table(AF), world()).handle("whatever")
    assert res.source == "none" and not res.speech


def test_momentary_sends_release():
    t = load_table(AF)
    assert t.resolve("ufc_com1", "press") == [(17, 3012, 1.0), (17, 3012, 0.0)]


def test_emergency_inbound():
    s = comms.atc_inbound(world(), "Viper 1-1", emergency=True)
    assert "cleared to land" in s and "number one" in s and "three one" in s
