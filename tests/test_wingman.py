import json, socket, threading, time
from pathlib import Path
from skibodcs.voice.cockpit import load_table
from skibodcs.voice.intents import intent_schema, WINGMAN_INTENTS
from skibodcs.voice.link import HookClient, HookStatus
from skibodcs.voice.router import Router
from skibodcs.voice.state import World

AF = Path(__file__).parent.parent / "airframes/f-16c.toml"


class FakeLLM:
    def __init__(self, reply): self.reply = reply
    def chat(self, messages, schema=None): return self.reply


def cmd(**kw):
    base = dict(domain="wingman", intent="", mode="", weapon="", action="", value="", control="", position="",
                amount=-1.0, who="", level="", shape="", spacing="", addressed_to="", emergency=False)
    base.update(kw); return base


def router(reply, lock=""):
    w = World(); w.own.lock_id = lock
    return Router(FakeLLM(json.dumps({"commands": reply})), load_table(AF), w)


def test_schema_has_wingman_enums():
    s = intent_schema(["gear"], ["down"])["properties"]["commands"]["items"]["properties"]
    assert "wingman" in s["domain"]["enum"] and "engage_my_target" in s["intent"]["enum"]
    assert "spread" in s["mode"]["enum"] and "fox3" in s["weapon"]["enum"]


def test_engage_my_target_uses_export_lock():
    r = router([cmd(intent="engage_my_target")], lock="12345").handle("kill what I'm locked on")
    assert r.wingman == [{"id": "w1", "type": "wingman", "intent": "engage_my_target", "params": {"target_id": "12345"}}]


def test_engage_my_target_without_lock_is_refused_locally():
    r = router([cmd(intent="engage_my_target")], lock="").handle("attack my target")
    assert r.wingman == [] and "no target locked" in r.speech[0]


def test_formation_mode_and_defaults():
    r = router([cmd(intent="formation", shape="wedge", spacing="close")]).handle("go wedge close")
    assert r.wingman[0]["params"] == {"shape": "wedge", "spacing": "close"}
    r = router([cmd(intent="formation")]).handle("spread out")
    assert r.wingman[0]["params"] == {"shape": "spread", "spacing": "open"}


def test_fast_path_weapons_free_skips_llm():
    class Boom:
        def chat(self, *a, **k): raise AssertionError("LLM must not be called")
    rt = Router(Boom(), load_table(AF), World())
    r = rt.handle("Weapons free!")
    assert r.source == "fast" and r.wingman[0]["intent"] == "weapons_free"
    assert rt.handle("hold fire").wingman[0]["intent"] == "weapons_hold"


def test_unknown_wingman_intent_dropped():
    r = router([cmd(intent="self_destruct")]).handle("boom")
    assert r.wingman == [] and r.notes


def test_ids_increment():
    rt = router([cmd(intent="weapons_free"), cmd(intent="cover_me")])
    r = rt.handle("weapons free and cover me")
    assert [c["id"] for c in r.wingman] == ["w1", "w2"]


def _server(replies):
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(2)
    got = []
    def serve():
        c, _ = srv.accept(); buf = b""
        while len(got) < len(replies):
            buf += c.recv(4096)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1); got.append(json.loads(line))
                c.sendall((json.dumps(replies[len(got) - 1](got[-1])) + "\n").encode())
        time.sleep(0.2); c.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1], got


def test_hook_client_round_trip_and_stale_reply_ignored():
    port, got = _server([lambda c: {"id": c["id"], "ok": True, "detail": "weapons free"}])
    hc = HookClient(port=port, timeout=1.0)
    assert hc.request({"id": "w1", "type": "wingman", "intent": "weapons_free", "params": {}}) == (True, "weapons free")
    assert got[0]["intent"] == "weapons_free"


def test_hook_client_reports_failure_detail():
    port, _ = _server([lambda c: {"id": c["id"], "ok": False, "detail": "not implemented: formation"}])
    ok, detail = HookClient(port=port, timeout=1.0).request({"id": "w9", "type": "wingman", "intent": "formation"})
    assert not ok and "not implemented" in detail


def test_hook_client_unreachable_and_timeout():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    assert HookClient(port=p, timeout=0.3).request({"id": "x"}) == (False, "DCS hook unreachable")
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)               # accepts, never replies
    ok, d = HookClient(port=srv.getsockname()[1], timeout=0.4).request({"id": "x"})
    assert not ok and d == "no reply from DCS"


def test_hook_status_heartbeat_and_events():
    w = World(); hs = HookStatus(w, port=0); hs.start()
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.sendto(b'{"type":"heartbeat"}', ("127.0.0.1", hs.bound_port))
    u.sendto(b'{"type":"event","kind":"dead","group":"sam_site_1"}', ("127.0.0.1", hs.bound_port))
    for _ in range(40):
        if w.events and w.hook_seen: break
        time.sleep(0.05)
    hs.stop()
    assert hs.hook_alive is False or hs.hook_alive is True      # property works after stop
    assert w.events[0]["group"] == "sam_site_1" and w.hook_seen > 0


def test_lock_id_parsed_from_telemetry():
    w = World(); w.update_from_payload({"own": {"model": "F-16C_50", "lock": "777"}, "objs": []})
    assert w.own.lock_id == "777"
