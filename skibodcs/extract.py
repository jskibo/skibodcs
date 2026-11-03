"""Turn ED's cockpit definition files into airframe action tables.
Run the Lua extractor (tools/extract_clickables.lua) under LuaJIT/Lua 5.1, or lupa if installed,
then build airframes/<module>.toml from a curated wishlist. Re-run after a DCS update; git shows
exactly which ids moved."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
from pathlib import Path

EXTRACTOR = Path(__file__).resolve().parent.parent / "tools" / "extract_clickables.lua"
MACRO_EXTRACTOR = Path(__file__).resolve().parent.parent / "tools" / "extract_macros.lua"

# action -> (command name in command_defs, {position: PROVISIONAL value}, momentary, {position: label ED uses in its autostart text})
# Provisional values are only a starting point: positions that ED's own Macro_sequencies.lua exercises are overwritten
# with the game's real values (and recorded as `confirmed`). Hint order carries NO reliable polarity (checked).
WISHLIST: dict[str, dict[str, tuple]] = {
    "F-16C_50": {
        "gear":        ("gear_commands.LGHandle",   {"down": 0.0, "up": 1.0}, False, {}),
        "hook":        ("gear_commands.HookSw",     {"down": 0.0, "up": 1.0}, False, {}),
        "master_arm":  ("mmc_commands.MasterArmSw", {"arm": 1.0, "safe": 0.0, "simulate": -1.0}, False, {"safe": "off", "arm": "master arm"}),
        "ufc_com1":    ("ufc_commands.COM1",        {"press": 1.0}, True, {}),
        "ufc_com2":    ("ufc_commands.COM2",        {"press": 1.0}, True, {}),
    },
    "FA-18C_hornet": {
        "gear":           ("gear_commands.GearHandle",     {"down": 0.0, "up": 1.0}, False, {}),
        "hook":           ("gear_commands.HookHandle",     {"down": 0.0, "up": 1.0}, False, {}),
        "master_arm":     ("SMS_commands.MasterArmSw",     {"arm": 1.0, "safe": 0.0}, False, {}),
        "master_mode_aa": ("SMS_commands.AA_MasterModeSw", {"press": 1.0}, True, {}),
        "master_mode_ag": ("SMS_commands.AG_MasterModeSw", {"press": 1.0}, True, {}),
    },
    "F-14B": {      # Heatblur: no autostart-macro data, so every value here is a PROVISIONAL guess (the app asks to confirm)
        "gear":          ("device_commands.GEAR_Handle",          {"down": 1.0, "up": 0.0}, False, {}),
        "hook":          ("device_commands.HOOK_Handle",          {"down": 1.0, "up": 0.0}, False, {}),
        "parking_brake": ("device_commands.BRAKE_ParkingBrake",   {"set": 1.0, "release": 0.0}, False, {}),
    },
    "F-4E-45MC": {   # Heatblur: no Macro_sequencies supplied => every value is PROVISIONAL (consequential ones need a spoken "confirm")
        "gear":         ("device_commands.LANDING_GEAR_PilotHandle", {"down": 1.0, "up": 0.0}, False, {}),
        "hook":         ("device_commands.PILOT_HOOK_HANDLE",        {"down": 1.0, "up": 0.0}, False, {}),
        "master_arm":   ("device_commands.WEAPONS_Master_Arm",       {"arm": 1.0, "safe": 0.0}, False, {}),
        "left_engine_master":  ("device_commands.ENGINES_LeftMasterSwitch",  {"on": 1.0, "off": 0.0}, False, {}),
        "right_engine_master": ("device_commands.ENGINES_RightMasterSwitch", {"on": 1.0, "off": 0.0}, False, {}),
        "left_ignition":  ("device_commands.ENGINES_LeftIgnition",  {"press": 1.0}, True, {}),
        "right_ignition": ("device_commands.ENGINES_RightIgnition", {"press": 1.0}, True, {}),
    },
    "A-10C": {      # ED autostart pins the electrical/engine items; the gear lever is NOT touched by it => provisional
        "gear":          ("CPT_MECH:device_commands.Button_1",   {"down": 1.0, "up": 0.0}, False, {}),
        "apu":           ("ENGINE_SYSTEM:device_commands.Button_5", {"on": 1.0, "off": 0.0}, False, {"on": "apu"}),
        "battery":       ("ELEC_INTERFACE:device_commands.Button_6", {"on": 1.0, "off": 0.0}, False, {"on": "battery"}),
        "master_arm":    ("AHCP:device_commands.Button_1",       {"arm": 1.0, "safe": 0.0, "train": -1.0}, False, {}),
        "engine_start_left":  ("ELEC_INTERFACE:device_commands.Button_17", {"press": 1.0}, True, {}),
        "engine_start_right": ("ELEC_INTERFACE:device_commands.Button_18", {"press": 1.0}, True, {}),
    },
    "AH-64D_BLK_II": {
        "parking_brake":   ("gear_commands.AH64_ParkingBrake",     {"set": 1.0, "release": 0.0}, False, {}),
        "rotor_brake":     ("hydraulic_commands.Rotor_Brake",      {"off": 1.0, "brk": 0.0, "lock": -1.0}, False, {}),
        "master_ignition": ("electric_commands.MIK",               {"off": 0.0, "batt": 0.5, "ext pwr": 1.0}, False, {}),
        "apu_start":       ("engine_commands.APU_StartBtn",        {"press": 1.0}, True, {}),
        "engine1_start":   ("engine_commands.Eng1StartSw",         {"press": 1.0}, True, {}),
        "engine2_start":   ("engine_commands.Eng2StartSw",         {"press": 1.0}, True, {}),
    },
}

WISHLIST["A-10C_2"] = WISHLIST["A-10C"]


def _find_lua() -> str | None:
    for cand in (os.environ.get("LUAJIT"), shutil.which("luajit"), shutil.which("lua5.1"), shutil.which("lua")):
        if cand and Path(cand).exists() or (cand and shutil.which(cand)):
            return cand
    return None


def run_lua_script(script: Path, files: tuple) -> str:
    """Run one of tools/*.lua over (devices, commands, third) files; returns its stdout."""
    lua = _find_lua()
    args = [str(Path(p).resolve()) for p in files]
    if lua:
        r = subprocess.run([lua, str(script), *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{script.name} failed: {r.stderr.strip()[:500]}")
        return r.stdout
    try:                                                    # fallback: pip install lupa
        import lupa
    except ImportError as e:
        raise RuntimeError("need a Lua 5.1/LuaJIT executable (set LUAJIT=path) or `pip install lupa`") from e
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute("__out = {}; io.write = function(...) for _, v in ipairs({...}) do __out[#__out+1] = tostring(v) end end")
    rt.globals().arg = rt.table_from(args)
    rt.execute(script.read_text(encoding="utf-8"))
    return rt.eval("table.concat(__out)")


def run_extractor(devices: Path, commands: Path, clickable: Path, draw_args: Path | None = None) -> list[dict]:
    files = (devices, commands, clickable) + ((draw_args,) if draw_args else ())
    return json.loads(run_lua_script(EXTRACTOR, files))


def run_macro_extractor(devices: Path, commands: Path, macros: Path) -> dict:
    return json.loads(run_lua_script(MACRO_EXTRACTOR, (devices, commands, macros)))


def find(elements: list[dict], text: str) -> list[dict]:
    t = text.lower()
    return [e for e in elements if t in e["hint"].lower() or any(t in c["name"].lower() for c in e["commands"])]


def _key(k: str) -> str:
    import re
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else '"' + k.replace('"', '') + '"'


def build_table(elements: list[dict], aircraft: str, source: str = "", observed: dict | None = None) -> tuple[str, list[str]]:
    """Returns (toml text, problems). `observed` = macros.observed_values(...) pins values to ED's own."""
    from .macros import apply_observed
    # A-10 style modules reuse device_commands.Button_N on every device, so a name alone is ambiguous:
    # a wishlist entry may say "DEVICE_NAME:command" (e.g. "CPT_MECH:device_commands.Button_1").
    by_cmd = {c["name"]: e for e in elements for c in e["commands"]}
    ids = {c["name"]: c["id"] for e in elements for c in e["commands"]}
    for e in elements:
        for c in e["commands"]:
            by_cmd[f"{e['device_name']}:{c['name']}"] = e
            ids[f"{e['device_name']}:{c['name']}"] = c["id"]
    lines = [f"# GENERATED by `skibodcs extract` from ED's cockpit definition files{' (' + source + ')' if source else ''}.",
             "# device/command/arg are read from the game files. `confirmed` positions carry the value ED's own autostart uses",
             "# (or that follows from it); anything not listed there is a PROVISIONAL guess - test it in the sim.",
             "[aircraft]", f'id = "{aircraft}"', ""]
    problems: list[str] = []
    for action, spec in WISHLIST[aircraft].items():
        cmd_name, values, momentary = spec[0], dict(spec[1]), spec[2]
        synonyms = spec[3] if len(spec) > 3 else {}
        e = by_cmd.get(cmd_name)
        if e is None or e["device"] is None:
            problems.append(f"{action}: {cmd_name} not found in clickabledata"); continue
        obs = (observed or {}).get((e["device"], ids[cmd_name]), {})
        values, confirmed, inferred = apply_observed(values, obs, synonyms)
        vals = ", ".join(f"{_key(k)} = {v}" for k, v in values.items())
        conf = ", ".join(f'"{k}"' for k in sorted(confirmed | inferred))
        lines += [f"# {e['hint']}  [{e['fn']}, device {e['device_name']}]",
                  f"[actions.{action}]", f"device = {e['device']}", f"command = {ids[cmd_name]}",
                  f"arg = {e['args'][0] if e['args'] else 0}"]
        if momentary:
            lines.append("momentary = true")
        all_ok = bool(values) and set(values) <= (confirmed | inferred) and not momentary
        lines += [f"verified = {'true' if all_ok else 'false'}", f"confirmed = [{conf}]",
                  f"values = {{ {vals} }}", ""]
    return "\n".join(lines), problems
