from pathlib import Path
from skibodcs import deploy as dp
from skibodcs.cli import main


def test_install_is_idempotent_and_preserves_existing_export(tmp_path):
    scripts = tmp_path / "Scripts"; scripts.mkdir()
    (scripts / "Export.lua").write_text("-- my existing\ndofile('tacview.lua')\n")
    dp.install(tmp_path); dp.install(tmp_path)                       # twice
    txt = (scripts / "Export.lua").read_text()
    assert "dofile('tacview.lua')" in txt and txt.count(dp.BEGIN) == 1 and dp.EXPORT_LINE in txt
    assert (scripts / "Hooks" / "skibodcs_hook.lua").exists()
    assert (scripts / "skibodcs_mission.lua").exists() and (scripts / "skibodcs_export.lua").exists()
    assert (scripts / dp.BACKUP).read_text() == "-- my existing\ndofile('tacview.lua')\n"   # original kept


def test_uninstall_restores_original_content(tmp_path):
    scripts = tmp_path / "Scripts"; scripts.mkdir()
    (scripts / "Export.lua").write_text("-- mine\n")
    dp.install(tmp_path); dp.uninstall(tmp_path)
    assert (scripts / "Export.lua").read_text() == "-- mine\n"
    assert not (scripts / "Hooks" / "skibodcs_hook.lua").exists()


def test_uninstall_removes_export_we_created(tmp_path):
    dp.install(tmp_path); dp.uninstall(tmp_path)
    assert not (tmp_path / "Scripts" / "Export.lua").exists()


def test_deploy_mission_and_replace_stale_kneeboards(tmp_path):
    miz = tmp_path / "m1.miz"; miz.write_bytes(b"PK")
    png1, png2 = tmp_path / "comm.png", tmp_path / "route.png"
    png1.write_bytes(b"1"); png2.write_bytes(b"2")
    dcs = tmp_path / "DCS"
    dp.deploy_mission(dcs, miz, {"F-16C_50": [png1, png2]})
    kb = dcs / "Kneeboard" / "F-16C_50"
    assert (dcs / "Missions" / "skibodcs" / "m1.miz").exists()
    assert sorted(p.name for p in kb.iterdir()) == ["skibodcs_01_comm.png", "skibodcs_02_route.png"]
    (kb / "mine.png").write_bytes(b"keep")                            # user's own page survives
    dp.deploy_mission(dcs, miz, {"F-16C_50": [png2]})
    assert sorted(p.name for p in kb.iterdir()) == ["mine.png", "skibodcs_01_route.png"]


def test_cli_install_deploy(tmp_path, capsys):
    miz = tmp_path / "x.miz"; miz.write_bytes(b"PK")
    assert main(["install", "--dcs-dir", str(tmp_path / "D")]) == 0
    assert main(["deploy", str(miz), "--dcs-dir", str(tmp_path / "D")]) == 0
    assert (tmp_path / "D" / "Missions" / "skibodcs" / "x.miz").exists()
