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
                    "wind_kt": 12, "wind_from": 270, "vis_km": 15, "count": 4, "callsign": "Cobra", "start_type": "runway"})
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
    assert {t["id"] for t in o["tasks"]} == {"SEAD", "CAS", "STRIKE", "CAP"} and "SA-10" in {s["id"] for s in o["sams"]}


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
