import json
from pathlib import Path
from skibodcs import controls as C
from skibodcs.sequence import load_sequences
from skibodcs.voice import jtac as jt
from skibodcs.voice.cockpit import load_table
from skibodcs.voice.router import Router
from skibodcs.voice.state import Contact, Ownship, World

ROOT = Path(__file__).parent.parent
AF = ROOT / "airframes" / "f-16c.toml"


class FakeLLM:
    def __init__(self, reply): self.reply = reply
    def chat(self, messages, schema=None): return self.reply


def jworld():
    w = World(own=Ownship("A-10C_2", 41.5, 41.5, 12000, 90, 300), magvar_east=6.0)
    # 4 hostile vehicles bunched near (41.7, 42.0) + a Kub 5 nm away + a friendly truck + one far-off hostile
    w.contacts = [Contact("10", 41.70, 42.00, 800, 0, 0, "red", "T-72B", False),
                  Contact("11", 41.701, 42.001, 800, 0, 0, "red", "T-72B", False),
                  Contact("12", 41.699, 41.999, 800, 0, 0, "red", "BMP-2", False),
                  Contact("13", 41.78, 42.00, 790, 0, 0, "red", "Kub 2P25 ln", False),
                  Contact("14", 40.30, 40.20, 100, 0, 0, "red", "T-55", False),
                  Contact("20", 41.62, 41.90, 700, 0, 0, "blue", "M-1 Abrams", False),
                  Contact("30", 42.5, 42.5, 25000, 180, 450, "red", "MiG-29S", True)]
    return w


def test_nine_line_numbers_are_consistent():
    w = jworld()
    nl = jt.nine_line(w)
    L = nl["lines"]
    assert nl["primary_id"] in {"10", "11", "12"} and set(nl["target_ids"]) == {"10", "11", "12"}   # the group, not the far T-55 or the Kub
    assert L[5][1] == "2 T-72B, 1 BMP-2"
    assert L[4][1] == "800 feet" and L[3][1] == "10 miles"
    # the IP is 10 nm from the target; flying the briefed heading from it must land on the target
    from skibodcs.voice.geo import distance_nm, bearing_true, to_magnetic
    ip, tgt = nl["ip"], (nl["lat"], nl["lon"])
    assert abs(distance_nm(*ip, *tgt) - 10) < 0.05
    assert abs(float(L[2][1].split()[0]) - to_magnetic(bearing_true(*ip, *tgt), 6.0)) % 360 < 1.0
    assert L[6][1].startswith("N 41 ") and " E 04" in L[6][1]
    assert L[8][1].split(",")[0] in jt.CARDINAL and "miles" in L[8][1]
    assert "1 air defence contact" in nl["remarks"]


def test_nine_line_speech_and_none():
    w = jworld()
    nl = jt.nine_line(w, code=1688)
    s = jt.speech_nine_line(w, "Viper 1-1", "Axeman", nl)
    assert s.startswith("Viper one one, Axeman, nine line follows.") and "code one six eight eight" in s
    assert "Line nine, egress" in s and s.endswith("Advise when ready for read back.")
    w.contacts = [c for c in w.contacts if c.is_air]
    assert jt.nine_line(w) is None and "no hostile ground contacts" in jt.checkin(w, "Viper 1-1", "Axeman")


def test_bda_counts_survivors():
    w = jworld()
    ids = jt.nine_line(w)["target_ids"]
    assert "all three destroyed" not in jt.bda(w, "Viper 1-1", "Axeman", ids) and "good effects" not in jt.bda(w, "Viper 1-1", "Axeman", ids)
    w.contacts = [c for c in w.contacts if c.id not in ids[:2]]
    assert "two of three destroyed, one remaining" in jt.bda(w, "Viper 1-1", "Axeman", ids)
    w.contacts = [c for c in w.contacts if c.id not in ids]
    assert "good effects, all three destroyed" in jt.bda(w, "Viper 1-1", "Axeman", ids)


def test_router_jtac_flow_and_cleared_hot_uses_jtac_target():
    w = jworld()
    reply = json.dumps({"commands": [{"domain": "comms", "intent": "jtac_nine_line", "addressed_to": "Axeman"}]})
    r = Router(FakeLLM(reply), load_table(AF), w, jtac="Axeman")
    out = r.handle("Axeman, Viper one one, ready for the nine line")
    assert "nine line follows" in out.speech[0] and w.jtac_target and w.jtac_primary in {"10", "11", "12"}
    r.llm = FakeLLM(json.dumps({"commands": [{"domain": "wingman", "intent": "cleared_hot", "who": "flight"}]}))
    out = r.handle("cleared hot")
    assert out.wingman[0]["intent"] == "cleared_hot" and out.wingman[0]["params"]["target_id"] == w.jtac_primary
    w.own.lock_id = "12"                                   # a cockpit lock beats the JTAC's primary
    assert r.handle("cleared hot").wingman[0]["params"]["target_id"] == "12"
    r.llm = FakeLLM(json.dumps({"commands": [{"domain": "comms", "intent": "jtac_readback"}]}))
    assert "read back correct" in r.handle("readback").speech[0]


def test_router_new_wingman_orders_pass_through():
    w = jworld()
    for intent in ("rtb", "break_left", "break_right"):
        r = Router(FakeLLM(json.dumps({"commands": [{"domain": "wingman", "intent": intent, "who": "wingman"}]})), load_table(AF), w)
        c = r.handle(intent).wingman[0]
        assert c["intent"] == intent and c["params"] == {"who": "wingman"}


def test_shipped_f4e_artifacts():
    ac, cs = C.load(ROOT / "airframes" / "f-4e.controls.json")
    assert ac == "F-4E-45MC" and len(cs) > 450
    assert {c.crew for c in cs} == {"", "PLT", "WSO"} and sum(1 for c in cs if not c.arg) < 5
    t = load_table(ROOT / "airframes" / "f-4e.toml")
    assert (t.actions["gear"].device, t.actions["gear"].arg, t.actions["hook"].arg) == (20, 5, 974)
    assert not t.actions["gear"].verified and t.actions["master_arm"].arg == 247
    seq = load_sequences(ROOT / "sequences" / "f-4e.json")
    assert [(s.device, s.command) for s in seq["autostart"] if s.device] == [(88, 3001), (88, 3001)]
    assert [(s.device, s.command) for s in seq["autostop"] if s.device] == [(88, 3002), (88, 3002)]


def test_kneeboards_render_and_deploy(tmp_path):
    from PIL import Image
    from skibodcs.kneeboard import make_kneeboards, dm
    from skibodcs.validate import validate
    from skibodcs import deploy as dp
    sc, errs = validate((ROOT / "examples" / "iron_lantern.json").read_text())
    assert not errs
    pages = make_kneeboards(sc, tmp_path / "kb")
    assert list(pages) == ["F-16C_50"] and [p.stem for p in pages["F-16C_50"]] == ["mission", "route", "briefing", "threats", "map", "datacard"]
    for p in pages["F-16C_50"]:
        im = Image.open(p)
        assert im.size == (768, 1024) and sum(1 for h in im.convert("L").histogram() if h) > 5    # not blank
    assert dm(41.5, -71.25) == "N41 30.000  W071 15.000"
    miz = tmp_path / "a.miz"; miz.write_bytes(b"x")
    out = dp.deploy_mission(tmp_path / "sg", miz, pages)
    assert (tmp_path / "sg" / "Kneeboard" / "F-16C_50" / "skibodcs_05_map.png").exists()
    dp.deploy_mission(tmp_path / "sg", miz, {"F-16C_50": pages["F-16C_50"][:2]})       # stale pages are replaced
    assert len(list((tmp_path / "sg" / "Kneeboard" / "F-16C_50").glob("skibodcs_*"))) == 2


def _events(path, rows):
    with open(path, "a") as f:
        for kind, unit, grp in rows:
            f.write(json.dumps({"type": "event", "kind": kind, "unit": unit, "group": grp, "utype": "x", "coalition": 1, "t": 1.0}) + "\n")


def test_campaign_persists_and_adapts(tmp_path):
    from skibodcs import campaign as cg, catalog
    db, dcs = tmp_path / "c.db", tmp_path / "sg"
    (dcs / "skibodcs").mkdir(parents=True)
    _events(dcs / "skibodcs" / "events.jsonl", [("dead", "old-1", "old_group")])          # history from an earlier flight: must be ignored
    camp = cg.Campaign.create(db, "Iron", "Caucasus", "F-16C_50", "Batumi", seed=7)
    r1 = cg.build_sortie(camp, tmp_path / "out", dcs)
    assert Path(r1["miz"]).exists() and (dcs / "Missions" / "skibodcs" / Path(r1["miz"]).name).exists()
    assert (dcs / "Kneeboard" / "F-16C_50" / "skibodcs_01_mission.png").exists()
    sc1 = json.loads(camp.last_mission()["scenario"])
    target = sc1["objectives"][0]["target_group"]
    tpl = next(g["template"] for g in sc1["red"]["groups"] if g["id"] == target)
    n = sum(k for _, k in catalog.GROUND_TEMPLATES[tpl])
    rows = [("takeoff", "Viper-1", "Viper"), ("takeoff", "Viper-2", "Viper")]
    rows += [("dead", f"{target}-{i}", target) for i in range(n)] + [("land", "Viper-1", "Viper"), ("land", "Viper-2", "Viper")]
    _events(dcs / "skibodcs" / "events.jsonl", rows)
    out = cg.ingest_latest(camp, dcs)
    assert out["success"] and out["destroyed"] == [target] and out["airframes_lost"] == 0 and out["landed"]
    s = camp.summary()
    assert s["sortie"] == 1 and s["date"] == "2026-06-15" and target in s["red_destroyed"]
    assert all(target not in a for a in s["red_alive"])
    r2 = cg.build_sortie(camp, tmp_path / "out", dcs)                                   # next sortie: world has moved on
    sc2 = json.loads(camp.last_mission()["scenario"])
    assert sc2["meta"]["sequence"] == 2 and sc2["meta"]["date"] == "2026-06-15"
    assert target not in {g["id"] for g in sc2["red"]["groups"]}
    cg.ingest_latest(camp, dcs)                                                        # sortie 2 has no events yet: ingests as a no-show
    assert camp.summary()["sortie"] == 3 or camp.summary()["sortie"] == 2


def test_campaign_losses_partial_kills_and_victory(tmp_path):
    from skibodcs import campaign as cg
    db = tmp_path / "c.db"
    camp = cg.Campaign.create(db, "Loss", "Caucasus", "F-16C_50", "Batumi", sites=1, seed=3)
    camp.plan_deterministic(); mid = camp.register(camp.plan_deterministic())
    sc = json.loads(camp.last_mission()["scenario"])
    tgt = sc["objectives"][0]["target_group"]
    # one unit dead only, one jet crashes, nobody lands: objective NOT met, airframe lost, site still alive
    lines = [json.dumps({"type": "event", "kind": k, "unit": u, "group": g, "utype": "x", "coalition": 1, "t": 1})
             for k, u, g in [("takeoff", "Viper-1", "Viper"), ("dead", f"{tgt}-1", tgt), ("crash", "Viper-2", "Viper")]]
    out = camp.ingest(mid, lines + ["not json"])
    assert not out["success"] and out["airframes_lost"] == 1 and out["destroyed"] == [] and not out["landed"]
    s = camp.summary()
    assert s["airframes"] == "4/4" and tgt in " ".join(s["red_alive"])               # 4 - 1 lost + 1 replacement
    # finish it: every unit dead -> victory (only site) and no reinforcement afterwards
    mid2 = camp.register(camp.plan_deterministic())
    from skibodcs import catalog
    sc2 = json.loads(camp.last_mission()["scenario"])
    n = sum(k for _, k in catalog.GROUND_TEMPLATES[sc2["red"]["groups"][0]["template"]])
    lines = [json.dumps({"type": "event", "kind": "dead", "unit": f"{tgt}-{i}", "group": tgt, "coalition": 1, "t": 1}) for i in range(n)]
    lines += [json.dumps({"type": "event", "kind": "land", "unit": "Viper-1", "group": "Viper", "coalition": 2, "t": 2})]
    out = camp.ingest(mid2, lines)
    assert out["campaign_status"] == "victory" and camp.reinforce() is None


def test_campaign_reinforces_when_red_is_nearly_gone(tmp_path):
    from skibodcs import campaign as cg
    camp = cg.Campaign.create(tmp_path / "c.db", "R", "Caucasus", "F-16C_50", "Batumi", sites=2, seed=5)
    sid = camp.reinforce()
    assert sid and len(camp.sites("alive")) == 3 and camp.reinforce() is None


def test_campaign_rejects_bad_names(tmp_path):
    from skibodcs import campaign as cg
    import pytest as _p
    with _p.raises(KeyError, match="Batumy|Batumi"):
        cg.Campaign.create(tmp_path / "c.db", "X", "Caucasus", "F-16C_50", "Batumy")
    with _p.raises(KeyError):
        cg.Campaign.create(tmp_path / "c.db", "X", "Caucasus", "F-99", "Batumi")


def test_campaign_llm_path_drops_destroyed_sites(tmp_path):
    from skibodcs import campaign as cg
    camp = cg.Campaign.create(tmp_path / "c.db", "L", "Caucasus", "F-16C_50", "Batumi", sites=2, seed=1)
    spec = json.loads((ROOT / "examples" / "iron_lantern.json").read_text())
    spec["red"]["groups"][0]["id"] = "sam_site_1"
    camp.db.execute("INSERT INTO site(campaign_id,id,template,near,bearing,distance_nm,status) VALUES(?,?,?,?,?,?,?)",
                    (camp.cid, "sam_site_1", "SA-6", "Kutaisi", 0, 22, "destroyed")); camp.db.commit()
    sc = camp.plan_llm(FakeLLM(json.dumps(spec)))
    assert "sam_site_1" not in [g.id for g in sc.red.groups] and all(o.target_group != "sam_site_1" for o in sc.objectives)
    assert sc.meta.campaign_id == "L" and sc.meta.date == "2026-06-14"
    mid = camp.register(sc)
    assert "escort_armor" in [s["id"] for s in camp.sites("alive")] and mid


def test_speech_server_roundtrip_and_errors():
    import threading
    from skibodcs.voice.server import make_server
    from skibodcs.voice.audio import RemoteSTT, RemoteTTS

    class STT:
        def transcribe(self, wav): return "bogey dope" if wav == b"RIFFfake" else (_ for _ in ()).throw(ValueError("bad audio"))

    class TTS:
        def synthesize(self, text): return b"RIFF" + text.encode()

    srv = make_server(STT(), TTS(), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert RemoteSTT(url).transcribe(b"RIFFfake") == "bogey dope"
        assert RemoteTTS(url).synthesize("roger") == b"RIFFroger"
        import pytest as _p
        with _p.raises(RuntimeError, match="bad audio"):
            RemoteSTT(url).transcribe(b"junk")
        with _p.raises(RuntimeError, match="400"):
            RemoteTTS(url).synthesize("   ")
        with _p.raises(RuntimeError):
            RemoteSTT("http://127.0.0.1:1").transcribe(b"x")
    finally:
        srv.shutdown()
