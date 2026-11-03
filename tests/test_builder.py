import random
import pytest
from skibodcs import builder, catalog
from skibodcs.validate import validate
from skibodcs.compile import compile_scenario


def ok(form, seed=1):
    spec, notes = builder.build_spec({**form, "seed": seed})
    sc, errs = validate(spec)
    assert sc is not None, errs
    return sc, notes


def test_explicit_choices_are_respected_exactly():
    sc, notes = ok({"task": "SEAD", "sam": "SA-6", "sam_count": 3, "ground": "none", "air": "none", "time": "night", "clouds": "overcast",
                    "wind_kt": 12, "wind_from": 270, "vis_km": 15, "count": 4, "callsign": "Cobra", "start_type": "runway",
                    "fighters": "none", "sead_pkg": "none"})
    assert [g.template for g in sc.red.groups] == ["SA-6"] * 3 and sc.red.air == []
    assert sc.meta.start_time == "22:30" and sc.weather.clouds == "overcast" and sc.weather.wind_kt == 12 and sc.weather.wind_from_deg == 270
    f = sc.player[0]
    assert (f.count, f.callsign, f.start_type, f.task) == (4, "Cobra", "runway", "SEAD")
    assert sc.objectives[0].target_group == "sa6_1" and sc.objectives[0].type == "destroy"
    assert notes == []                                                   # nothing was left to chance, so nothing is reported as rolled


def test_same_seed_same_mission_different_seed_different_mission():
    a = builder.build_spec({"seed": 5})[0]; b = builder.build_spec({"seed": 5})[0]; c = builder.build_spec({"seed": 6})[0]
    assert a == b and a != c


def test_tasks_always_get_something_to_do():
    sead, n1 = ok({"task": "SEAD", "sam": "none"})
    assert any(g.template in catalog.SAM_TEMPLATES for g in sead.red.groups) and any("SEAD needs a SAM" in n for n in n1)
    cas, n2 = ok({"task": "CAS", "ground": "none"})
    assert any(g.template in ("ARMOR_PLATOON", "MECH_INF") for g in cas.red.groups) and any("needs ground targets" in n for n in n2)
    cap, n3 = ok({"task": "CAP", "air": "none"})
    assert cap.red.air and cap.objectives[0].type == "survive" and any("CAP needs" in n for n in n3)
    assert cas.blue_support.jtac is not None and sead.blue_support.jtac is None            # JTAC auto-follows CAS/STRIKE


def test_target_area_can_be_anchored_on_another_airbase():
    sc, _ = ok({"start_airbase": "Batumi", "target_near": "Kutaisi", "target_bearing": 0, "target_distance": 10, "task": "STRIKE", "ground": "armor"})
    tgt = sc.objectives[0].target_group
    g = next(x for x in sc.red.groups if x.id == tgt)
    from skibodcs.catalog import resolve_anchor
    kut, p = catalog.find_airbase("Caucasus", "Kutaisi").position, resolve_anchor("Caucasus", g.position)
    import math
    assert math.hypot(p.x - kut.x, p.y - kut.y) / 1852 < 10 + 4 + 1                      # within 10 nm north of Kutaisi plus the group scatter
    assert [w.name for w in sc.player[0].route] == ["IP", "TGT", "HOME"]


@pytest.mark.parametrize("seed", range(40))
def test_random_missions_always_validate(seed):
    rnd = random.Random(seed)
    form = {"aircraft": rnd.choice(list(builder.AIRCRAFT)), "count": rnd.randint(1, 4), "start_type": rnd.choice(["cold", "warm", "runway"])}
    sc, _ = ok(form, seed)
    assert sc.player[0].aircraft == form["aircraft"] and len(sc.red.groups) >= 1 or sc.player[0].task == "CAP"


@pytest.mark.parametrize("theater,base", [("Caucasus", "Batumi"), ("PersianGulf", "Al Dhafra AB"), ("Nevada", "Nellis AFB"), ("Syria", "Incirlik"),
                                          ("Sinai", "Cairo International Airport")])
def test_other_theaters(theater, base):
    names = catalog.airbases(theater)
    base = base if base in names else names[0]
    ok({"theater": theater, "start_airbase": base, "task": "random"}, 2)


def test_bad_input_is_a_readable_error():
    with pytest.raises(KeyError, match="no airbase"):
        builder.build_spec({"start_airbase": "Nowhere"})
    with pytest.raises(ValueError):
        builder.build_spec({"date": "June 14"})


def test_a_built_scenario_compiles(tmp_path):
    sc, _ = ok({"task": "SEAD", "sam": "SA-10", "air": "mig29_2"}, 4)
    compile_scenario(sc, tmp_path / "x.miz")
    assert (tmp_path / "x.miz").exists()


def test_options_for_the_ui():
    o = builder.options("Caucasus")
    assert "Batumi" in o["airbases"] and {a["id"] for a in o["aircraft"]} >= {"F-16C_50", "FA-18C_hornet", "A-10C_2"}
    assert {t["id"] for t in o["tasks"]} == {"SEAD", "DEAD", "CAS", "STRIKE", "CAP"} and "SA-10" in {s["id"] for s in o["sams"]}


def test_campaign_sortie_can_be_steered(tmp_path):
    from skibodcs import campaign as cg
    camp = cg.Campaign.create(tmp_path / "c.db", "S", "Caucasus", "F-16C_50", "Batumi", sites=6, seed=11)
    sc = camp.plan_deterministic(steer={"task": "CAS", "time": "night", "clouds": "overcast"})
    assert sc.player[0].task == "CAS" and sc.meta.start_time == "22:30" and sc.weather.clouds == "overcast"
    assert camp.plan_deterministic(steer={"task": "SEAD"}).player[0].task == "SEAD"
    assert camp.plan_deterministic(steer={"task": "CAP"}).player[0].task == "CAP"
    assert camp.plan_deterministic(steer={"time": "07:15"}).meta.start_time == "07:15"
    for s in camp.sites("alive"):
        if s["template"] in cg.SAM:
            camp.db.execute("UPDATE site SET status='destroyed' WHERE id=?", (s["id"],))
    camp.db.commit()
    with pytest.raises(ValueError, match="No surviving air-defence"):
        camp.plan_deterministic(steer={"task": "SEAD"})


def test_theater_names_round_trip_through_the_catalog():
    ids = [t["id"] for t in builder.options("Caucasus")["theaters"]]
    assert "Caucasus" in ids and "Persian Gulf" in ids and "The Channel" in ids
    for t in ids:
        assert catalog.terrain(t) is not None                            # the id shown in the dropdown is accepted as-is everywhere


def test_many_missions_in_one_process_do_not_run_out_of_parking(tmp_path):
    # a long-running UI builds many missions from the same airbase; pydcs consumes parking slots on the terrain object it is given
    for i in range(14):
        sc, _ = ok({"count": 4, "start_airbase": "Batumi", "task": "SEAD"}, i)
        compile_scenario(sc, tmp_path / f"m{i}.miz")
    assert len(list(tmp_path.glob("*.miz"))) == 14


def test_dcs_folder_choice_prefers_the_one_actually_flown(tmp_path, monkeypatch):
    import os, time
    from skibodcs import deploy as dp
    a, b = tmp_path / "DCS.openbeta", tmp_path / "DCS"
    for d in (a, b):
        (d / "Logs").mkdir(parents=True)
    (a / "Logs" / "dcs.log").write_text("old"); (b / "Logs" / "dcs.log").write_text("new")
    os.utime(a / "Logs" / "dcs.log", (time.time() - 9999, time.time() - 9999))
    monkeypatch.setattr(dp, "find_dcs_dirs", lambda: [a, b])
    assert dp.pick_dcs_dir() == b                                              # openbeta is listed first but DCS has the newer log
    assert dp.pick_dcs_dir({"dcs_dir": str(a)}) == a                           # an explicit setting always wins
    monkeypatch.setattr(dp, "find_dcs_dirs", lambda: [])
    assert dp.pick_dcs_dir() is None


def test_support_packages_follow_the_task_rules():
    def pkg(task, **kw):
        sc, notes = ok({"task": task, "sam": "SA-6", "sam_count": 2, "ground": "armor", "air": "none", **kw}, 7)
        return {(x.role, x.aircraft, x.count) for x in sc.support_flights}, sc, notes
    p, sc, _ = pkg("SEAD"); assert p == {("cover", "F-15C", 2)}                              # SEAD: fighters, no second SEAD
    p, sc, _ = pkg("DEAD"); assert p == {("cover", "F-15C", 2)} and sc.player[0].task == "SEAD"
    assert [o.target_group for o in sc.objectives if o.type == "destroy"] == ["sa6_1", "sa6_2"]  # DEAD: every SAM site is an objective
    p, _, n = pkg("STRIKE"); assert p == {("cover", "F-15C", 2), ("sead", "F-16C_50", 2)} and any("SEAD package added" in x for x in n)
    p, _, _ = pkg("CAS"); assert p == set()
    p, _, _ = pkg("CAP"); assert p == set()
    p, _, _ = pkg("STRIKE", sam="none"); assert p == {("cover", "F-15C", 2)}                  # nothing to suppress: no SEAD package
    p, _, _ = pkg("CAS", fighters="f16_2", sead_pkg="f18_2"); assert p == {("cover", "F-16C_50", 2), ("sead", "FA-18C_hornet", 2)}   # explicit beats auto
    p, _, _ = pkg("SEAD", fighters="none"); assert p == set()


def test_package_launch_delays_follow_the_player_start():
    from skibodcs import packages
    assert packages.delay_min("cover", "cold") == 6.0 and packages.delay_min("sead", "cold") == 9.0
    assert packages.delay_min("sead", "runway") == 0.0 and packages.delay_min("cover", "warm") == 0.0
    sc, _ = ok({"task": "STRIKE", "sam": "SA-10", "start_type": "cold"}, 3)
    d = {x.role: x.delay_min for x in sc.support_flights}
    assert d["sead"] > d["cover"] > 0                                                         # SEAD leaves after the cover, both after mission start


def test_support_flights_compile_into_the_mission(tmp_path):
    import dcs
    sc, _ = ok({"task": "STRIKE", "sam": "SA-6", "air": "none", "start_type": "cold"}, 5)
    warns = compile_scenario(sc, tmp_path / "pkg.miz")
    m = dcs.Mission(); m.load_file(str(tmp_path / "pkg.miz"))
    groups = {g.name: g for c in m.coalition["blue"].countries.values() for g in c.plane_group}
    assert {"Uzi 1", "Wolf 1"} <= set(groups)
    assert len(groups["Uzi 1"].units) == 2 and groups["Uzi 1"].units[0].type == "F-15C" and groups["Uzi 1"].start_time == 360
    assert groups["Wolf 1"].units[0].type == "F-16C_50" and groups["Wolf 1"].start_time == 540
    assert str(groups["Wolf 1"].points[-1].type) == "Land" or "Land" in str(groups["Wolf 1"].points[-1].type)
    assert not any(u.is_human() for u in groups["Uzi 1"].units)                              # AI, never a player slot


def test_kneeboard_and_summary_show_the_package(tmp_path):
    from skibodcs.kneeboard import make_kneeboards
    from skibodcs.webui import App
    sc, _ = ok({"task": "STRIKE", "sam": "SA-6"}, 5)
    pages = make_kneeboards(sc, tmp_path)
    assert len(pages["F-16C_50"]) == 9
    s = App.summary(sc)
    assert any("Uzi 1" in x and "Fighter cover" in x and "F-15C" in x for x in s["package"])
    assert any("Wolf 1" in x and "SEAD package" in x for x in s["package"])


def test_campaign_sorties_carry_packages_unless_declined(tmp_path):
    from skibodcs import campaign as cg
    camp = cg.Campaign.create(tmp_path / "c.db", "P", "Caucasus", "F-16C_50", "Batumi", sites=6, seed=3)
    with_pk = camp.plan_deterministic(steer={"task": "STRIKE"})
    assert {x.role for x in with_pk.support_flights} >= {"cover"}
    assert camp.plan_deterministic(steer={"task": "STRIKE", "packages": "none"}).support_flights == []
    assert camp.plan_deterministic(steer={"task": "CAS"}).support_flights == []
