"""Put files where DCS expects them so starting a flight never involves manual copying.
All functions take dcs_dir (Saved Games\\DCS or DCS.openbeta) so they are testable anywhere."""
from __future__ import annotations
import os
import shutil
from pathlib import Path

LUA_DIR = Path(__file__).resolve().parent.parent / "dcs_hook"
BEGIN, END = "-- >>> skibodcs (managed block; `skibodcs uninstall` removes it)", "-- <<< skibodcs"
# `lfs` is NOT a global in the Export state (stock Export.lua does `local lfs = require('lfs')`); using it bare raised an error before
# pcall ran, so the module never loaded. This line brings its own lfs and cannot break the rest of Export.lua.
EXPORT_LINE = 'pcall(function() local lfs = require("lfs"); dofile(lfs.writedir() .. "Scripts/skibodcs_export.lua") end)'
BACKUP = "Export.lua.skibodcs.bak"


def find_dcs_dirs() -> list[Path]:
    env = os.environ.get("SKIBODCS_DCS_DIR")
    if env:
        return [Path(env)]
    sg = Path.home() / "Saved Games"
    return [p for p in (sg / "DCS.openbeta", sg / "DCS") if p.is_dir()]


def _block() -> str:
    return f"{BEGIN}\n{EXPORT_LINE}\n{END}\n"


def _strip_block(text: str) -> str:
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.strip() == BEGIN:
            skipping = True
        elif skipping and line.strip() == END:
            skipping = False
        elif not skipping:
            out.append(line)
    return "".join(out)


def install(dcs_dir: Path, lua_dir: Path = LUA_DIR) -> list[str]:
    dcs_dir = Path(dcs_dir)
    scripts, hooks = dcs_dir / "Scripts", dcs_dir / "Scripts" / "Hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    done = []
    shutil.copy2(lua_dir / "skibodcs_hook.lua", hooks / "skibodcs_hook.lua"); done.append("Hooks/skibodcs_hook.lua")
    for name in ("skibodcs_mission.lua", "skibodcs_export.lua"):
        shutil.copy2(lua_dir / name, scripts / name); done.append(f"Scripts/{name}")
    exp = scripts / "Export.lua"
    old = exp.read_text(encoding="utf-8", errors="replace") if exp.exists() else ""
    if exp.exists() and not (scripts / BACKUP).exists():
        shutil.copy2(exp, scripts / BACKUP); done.append(f"backup Scripts/{BACKUP}")
    base = _strip_block(old)
    if base and not base.endswith("\n"):
        base += "\n"
    # FIRST, not last: DCS stops reading Export.lua at the first error, and other tools' lines can fail (a real install had a SimHaptic
    # line pointing at a missing file). Our module chains whatever callbacks exist when it loads; tools loaded after it chain ours.
    exp.write_text(_block() + base, encoding="utf-8"); done.append("Export.lua (managed block, at the top)")
    return done


def uninstall(dcs_dir: Path) -> list[str]:
    dcs_dir = Path(dcs_dir); scripts = dcs_dir / "Scripts"; done = []
    for p in (scripts / "Hooks" / "skibodcs_hook.lua", scripts / "skibodcs_mission.lua", scripts / "skibodcs_export.lua"):
        if p.exists():
            p.unlink(); done.append(f"removed {p.name}")
    exp = scripts / "Export.lua"
    if exp.exists():
        cleaned = _strip_block(exp.read_text(encoding="utf-8", errors="replace"))
        if cleaned.strip():
            exp.write_text(cleaned, encoding="utf-8")
        else:
            exp.unlink()
        done.append("Export.lua block removed")
    return done


def deploy_mission(dcs_dir: Path, miz: Path, kneeboards: dict[str, list[Path]] | None = None,
                   folder: str = "skibodcs") -> list[Path]:
    """Copy the .miz to Missions\\<folder>\\ and kneeboard PNGs to Kneeboard\\<aircraft>\\.
    Previous skibodcs_* kneeboards for each aircraft are replaced so stale pages never linger."""
    dcs_dir, miz = Path(dcs_dir), Path(miz)
    out = []
    dest = dcs_dir / "Missions" / folder
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(miz, dest / miz.name); out.append(dest / miz.name)
    for aircraft, pngs in (kneeboards or {}).items():
        kb = dcs_dir / "Kneeboard" / aircraft
        kb.mkdir(parents=True, exist_ok=True)
        for old in kb.glob("skibodcs_*"):
            old.unlink()
        for i, png in enumerate(pngs, 1):
            tgt = kb / f"skibodcs_{i:02d}_{Path(png).name}"
            shutil.copy2(png, tgt); out.append(tgt)
    return out
