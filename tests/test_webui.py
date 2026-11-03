import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from skibodcs.webui import App, make_server

ROOT = Path(__file__).parent.parent


class FakeLLM:
    def __init__(self, reply): self.reply, self.calls = reply, []
    def chat(self, messages, schema=None): self.calls.append(messages); return self.reply


class FakeHook:
    def __init__(self, ok=True): self.ok, self.paths = ok, []
    def load_mission(self, path): self.paths.append(str(path)); return (self.ok, "loading x.miz" if self.ok else "DCS hook unreachable")


@pytest.fixture
def app(tmp_path):
    dcs = tmp_path / "sg"; (dcs / "skibodcs").mkdir(parents=True)
    hook = FakeHook()
    a = App({"ollama": {"host": "http://x", "model": "m"}}, dcs, tmp_path / "state", llm_factory=None, hook_factory=lambda: hook)
    a.hook = hook
    return a


def call(app, method, url, body=None):
    st, ctype, data = app.handle(method, url, json.dumps(body).encode() if body is not None else b"")
    return st, (json.loads(data) if ctype == "application/json" else data)


def test_page_and_options(app):
    st, ctype, data = app.handle("GET", "/")
    assert st == 200 and b"Mission Builder" in data and b"/api/preview" in data
    st, o = call(app, "GET", "/api/options?theater=Caucasus")
    assert st == 200 and "Batumi" in o["airbases"] and o["ollama"] is True and {t["id"] for t in o["tasks"]} == {"SEAD", "DEAD", "CAS", "STRIKE", "CAP"}
    assert call(app, "GET", "/nope")[0] == 404


def test_preview_install_launch_flow(app, tmp_path):
    st, r = call(app, "POST", "/api/preview", {"form": {"task": "SEAD", "sam": "SA-6", "sam_count": 2, "time": "dusk", "seed": 4}})
    assert st == 200 and r["summary"]["title"].startswith("SEAD") and len(r["kneeboards"]) == 9
    assert "18:30" in r["summary"]["when"] and any("SA-6" in e for e in r["summary"]["enemy"])
    assert not (app.dcs_dir / "Missions").exists(), "preview must not touch DCS"
    for url in r["kneeboards"][:2]:
        st, data = call(app, "GET", url)
        assert st == 200 and data[:4] == b"\x89PNG"
    assert call(app, "POST", "/api/launch", {"id": r["id"]})[0] == 400                      # not installed yet
    st, i = call(app, "POST", "/api/install", {"id": r["id"]})
    assert st == 200 and (app.dcs_dir / "Missions" / "skibodcs" / f"{r['id']}.miz").exists()
    assert (app.dcs_dir / "Kneeboard" / "F-16C_50" / "skibodcs_01_mission.png").exists()
    st, l = call(app, "POST", "/api/launch", {"id": r["id"]})
    assert st == 200 and app.hook.paths[0].endswith(f"{r['id']}.miz")
    app.hook.ok = False
    st, e = call(app, "POST", "/api/launch", {"id": r["id"]})
    assert st == 400 and "DCS did not start it" in e["error"]


def test_bad_input_is_a_message_not_a_crash(app):
    st, e = call(app, "POST", "/api/preview", {"form": {"start_airbase": "Nowhere"}})
    assert st == 400 and "no airbase" in e["error"]
    st, e = call(app, "POST", "/api/preview", {"form": {"date": "June 14"}})
    assert st == 400
    assert call(app, "POST", "/api/install", {"id": "../../etc"})[0] == 400
    assert call(app, "GET", "/files/../../etc/passwd")[0] == 404
    assert call(app, "POST", "/api/describe", {"text": "  "})[0] == 400
    assert call(app, "POST", "/api/campaign/next", {"name": "ghost"})[1]["error"] == "No campaign called 'ghost'."


def test_ai_describe_uses_the_model_and_validates_it(app):
    spec = json.loads((ROOT / "examples" / "iron_lantern.json").read_text())
    llm = FakeLLM(json.dumps(spec))
    app.llm_factory = lambda: llm
    st, r = call(app, "POST", "/api/describe", {"text": "SEAD on an SA-6 near Kutaisi", "theater": "Caucasus"})
    assert st == 200 and r["kind"] == "ai" and r["summary"]["title"] == "Operation Iron Lantern" and len(r["kneeboards"]) == 9
    assert "SEAD on an SA-6" in llm.calls[0][1]["content"]
    bad = FakeLLM("not json at all")
    app.llm_factory = lambda: bad
    st, e = call(app, "POST", "/api/describe", {"text": "x", "theater": "Caucasus"})
    assert st == 400 and "failed validation" in e["error"]
    plain = App({}, app.dcs_dir, app.state)                                              # no [ollama] section
    st, e = call(plain, "POST", "/api/describe", {"text": "x"})
    assert st == 400 and "not configured" in e["error"]


def _events(path, rows):
    with open(path, "a") as f:
        for k, u, g in rows:
            f.write(json.dumps({"type": "event", "kind": k, "unit": u, "group": g, "utype": "x", "coalition": 1, "t": 1}) + "\n")


def test_campaign_flow_through_the_ui(app):
    from skibodcs import catalog
    st, c = call(app, "POST", "/api/campaign/new", {"name": "Iron", "theater": "Caucasus", "aircraft": "F-16C_50", "home": "Batumi", "sites": 6, "seed": 7})
    assert st == 200 and c["campaign"] == "Iron" and len(c["red_alive"]) == 6
    assert call(app, "POST", "/api/campaign/new", {"name": "Iron", "home": "Batumi"})[1]["error"] == "A campaign with that name already exists."
    assert call(app, "POST", "/api/campaign/new", {"name": "Bad", "home": "Batumy"})[0] == 400
    assert [x["campaign"] for x in call(app, "GET", "/api/campaigns")[1]["campaigns"]] == ["Iron"]
    _events(app.dcs_dir / "skibodcs" / "events.jsonl", [("dead", "old-1", "old")])                    # earlier history must not count
    st, r = call(app, "POST", "/api/campaign/next", {"name": "Iron", "steer": {"task": "SEAD", "time": "night", "clouds": "random"}})
    assert st == 200 and r["kind"] == "campaign" and r["summary"]["flight"].find("SEAD") > 0 and "22:30" in r["summary"]["when"]
    assert not (app.dcs_dir / "Missions").exists()
    st, i = call(app, "POST", "/api/install", {"id": r["id"]})
    assert st == 200
    scn = json.loads(next((app.builds / r["id"]).glob("*.scenario.json")).read_text())
    target = scn["objectives"][0]["target_group"]
    tpl = next(g["template"] for g in scn["red"]["groups"] if g["id"] == target)
    n = sum(k for _, k in catalog.GROUND_TEMPLATES[tpl])
    _events(app.dcs_dir / "skibodcs" / "events.jsonl",
            [("takeoff", "Viper-1", "Viper")] + [("dead", f"{target}-{k}", target) for k in range(n)] + [("land", "Viper-1", "Viper")])
    st, o = call(app, "POST", "/api/campaign/ingest", {"name": "Iron"})
    assert st == 200 and o["outcome"]["success"] and o["outcome"]["destroyed"] == [target] and target in o["status"]["red_destroyed"]
    assert call(app, "POST", "/api/campaign/ingest", {"name": "Iron"})[0] == 400                      # nothing new to score
    st, r2 = call(app, "POST", "/api/campaign/next", {"name": "Iron", "steer": {"task": "random"}})
    assert st == 200, r2


def test_real_http_round_trip(app):
    srv = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert b"Mission Builder" in urllib.request.urlopen(base + "/").read()
        req = urllib.request.Request(base + "/api/preview", json.dumps({"form": {"task": "CAP", "seed": 2}}).encode(), {"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req).read())
        assert r["summary"]["title"].startswith("CAP")
        assert urllib.request.urlopen(base + r["kneeboards"][0]).read()[:4] == b"\x89PNG"
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(urllib.request.Request(base + "/api/preview", json.dumps({"form": {"start_airbase": "Nowhere"}}).encode()))
        assert ei.value.code == 400 and "no airbase" in json.loads(ei.value.read())["error"]
    finally:
        srv.shutdown()
