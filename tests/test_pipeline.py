import json, math
from pathlib import Path
import dcs
from skibodcs import catalog
from skibodcs.validate import validate
from skibodcs.compile import compile_scenario

EX = json.loads((Path(__file__).parent.parent / "examples/iron_lantern.json").read_text())


def test_example_valid():
    sc, errs = validate(EX)
    assert not errs and sc.meta.theater == "Caucasus"


def test_bad_airbase_gets_suggestion():
    bad = json.loads(json.dumps(EX)); bad["player"][0]["start_airbase"] = "Batum"
    sc, errs = validate(bad)
    assert sc is None and "Batumi" in errs[0]


def test_unknown_aircraft_and_template():
    bad = json.loads(json.dumps(EX))
    bad["player"][0]["aircraft"] = "F-16C"
    bad["red"]["groups"][0]["template"] = "SA-99"
    _, errs = validate(bad)
    assert any("unknown aircraft" in e for e in errs)
    assert any("SA-99" in e for e in errs)


def test_dangling_objective_target():
    bad = json.loads(json.dumps(EX)); bad["objectives"][0]["target_group"] = "nope"
    _, errs = validate(bad)
    assert errs and "nope" in errs[0]


def test_non_json():
    assert validate("{not json")[1][0].startswith("not valid JSON")


def test_anchor_distance_and_bearing():
    from skibodcs.schema import Anchor
    base = catalog.find_airbase("Caucasus", "Kutaisi").position
    p = catalog.resolve_anchor("Caucasus", Anchor(near="Kutaisi", bearing=0, distance_nm=22))
    assert abs(math.hypot(p.x - base.x, p.y - base.y) - 22 * 1852) < 1
    assert p.x > base.x and abs(p.y - base.y) < 1       # x is north in DCS


def test_compile_roundtrip(tmp_path):
    sc, _ = validate(EX)
    out = tmp_path / "t.miz"
    warns = compile_scenario(sc, out)
    assert out.exists() and out.with_suffix(".scenario.json").exists()
    m = dcs.Mission(); m.load_file(str(out))
    groups = {}
    for side in ("blue", "red"):
        for c in m.coalition[side].countries.values():
            for kind in ("plane_group", "vehicle_group"):
                for g in getattr(c, kind):
                    groups[g.name] = (side, g)
    assert len(groups["Viper"][1].units) == 2 and groups["Viper"][0] == "blue"
    assert groups["Viper"][1].units[0].skill == dcs.unit.Skill.Player
    assert len(groups["sam_site_1"][1].units) == 4          # SR + 3 LN
    assert len(groups["escort_armor"][1].units) == 4
    assert {"Overlord", "Texaco"} <= set(groups)
    assert any(g.startswith("RedCAP") for g in groups)
    # SAM landed ~22nm north of Kutaisi
    base = catalog.find_airbase("Caucasus", "Kutaisi").position
    u = groups["sam_site_1"][1].units[0].position
    assert abs(math.hypot(u.x - base.x, u.y - base.y) / 1852 - 22) < 0.5
    assert m.start_time.year == 2026 and m.start_time.hour == 6
    assert abs(m.weather.qnh - 761) < 1
    assert any("dynamic_rules" in w for w in warns)
