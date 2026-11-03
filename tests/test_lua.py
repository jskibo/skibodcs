import os, shutil, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).parent.parent
LUA = os.environ.get("LUAJIT") or shutil.which("luajit") or shutil.which("lua5.1") or (
    "/tmp/luajit/src/luajit" if Path("/tmp/luajit/src/luajit").exists() else None)

pytestmark = pytest.mark.skipif(not LUA, reason="no Lua 5.1/LuaJIT interpreter (set LUAJIT=...)")


@pytest.mark.parametrize("script,marker", [("test_mission.lua", "MISSION LUA OK"), ("test_hook.lua", "HOOK LUA OK")])
def test_lua(script, marker):
    r = subprocess.run([LUA, f"tests/lua/{script}"], cwd=ROOT, capture_output=True, text=True)
    assert marker in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("f", ["skibodcs_hook.lua", "skibodcs_mission.lua", "skibodcs_export.lua"])
def test_lua_syntax(f):
    r = subprocess.run([LUA, "-e", f"assert(loadfile('dcs_hook/{f}'))"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
