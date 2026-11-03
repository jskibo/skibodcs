# skibodcs v0.4

Three tracks in one codebase: mission generator, natural-language voice (comms, cockpit, wingman),
and a DCS bridge. Anything marked UNVERIFIED could not be run against a live DCS/Ollama/Whisper/
Piper in the build sandbox. Python is tested with fakes; the Lua is tested under LuaJIT (Lua 5.1
semantics, like DCS) against mocked DCS APIs (tests/lua).

## Setup (sim PC, Windows)
    py -m venv .venv && .venv\Scripts\activate
    pip install pydcs pyproj "pydantic>=2" pytest
    pip install -e .[voice]
    pytest                         (Lua tests are skipped unless LUAJIT=path\to\luajit.exe is set)
    skibodcs install               (add --dcs-dir "C:\Users\you\Saved Games\DCS.openbeta" if both exist)
`install` copies the Hook, mission module and Export module into Saved Games\DCS\Scripts and adds
ONE managed block to your existing Export.lua (original backed up once; `skibodcs uninstall`
removes everything cleanly).

## Three Lua states, one bridge (this is why there are three files)
| file | runs in | job |
|---|---|---|
| skibodcs_export.lua | Export (cockpit) | telemetry, locked target, cockpit clicks (UDP 14501 / TCP 14500) |
| Hooks/skibodcs_hook.lua | Hook (GUI) | sockets + files; reaches the mission via net.dostring_in (TCP 14510 / UDP 14511) |
| skibodcs_mission.lua | Mission | wingman tasking, event buffer; no sockets/io (sanitized) |
The PC app is the bridge: it takes your locked target id from Export and puts it in the wingman
command it sends to the Hook.

## Use
    skibodcs generate "SEAD on an SA-6 near Kutaisi" --host http://MAC:11434 --deploy
    skibodcs deploy out\m1.miz --kneeboard F-16C_50=route.png      (kneeboard PNG generation not built yet)
    copy skibodcs.example.toml skibodcs.toml ; skibodcs-voice --text      # type instead of speak
Wingman examples: "weapons free", "attack my target", "go wedge", "how's your fuel".

## Honest status of wingman intents
IMPLEMENTED in the mission module: weapons_free, weapons_hold, engage_my_target, engage_nearest, status.
NOT implemented (the sim answers "not implemented" and the app says "unable", never a fake "roger"):
formation, cover_me, rejoin, rtb, cleared_hot, break_left/right. Formation needs the real AI
option values; the rest need route/task injection. Add them one at a time against a live sim.

## Cockpit tables: generated from your own DCS files (new in v0.4)
    skibodcs find --devices D --commands C --clickable K "master arm"      # look up any control
    skibodcs extract --devices D --commands C --clickable K --aircraft F-16C_50 --out airframes\f-16c.toml
where D/C/K are the module's devices.lua, command_defs.lua, clickabledata.lua (see
Mods\aircraft\<module>\Cockpit\Scripts on your install). The extractor runs ED's own definition files
under stubs, so device ids, command ids (3000+position) and cockpit arg numbers are READ, not guessed.
Needs LuaJIT/Lua 5.1 on PATH (or LUAJIT=path) or `pip install lupa`. Add controls by extending WISHLIST in
skibodcs\extract.py. After a DCS update: re-run, `git diff airframes/` shows exactly which ids moved.
Do not commit ED's .lua files; commit only the generated TOMLs. Shipped: airframes\f-16c.toml, fa-18c.toml
(gear, hook, master arm, plus F-16 ICP COM1/COM2 and Hornet master-mode buttons).
What is still a guess: the VALUE meaning (is gear "down" 1.0 or 0.0? arm = 1.0?). The files do not say.
Each action carries its cockpit `arg` number so a future read-back step can confirm the result.

## UNVERIFIED (verify in this order)
1. Hook loads: DCS log should show "skibodcs: hook registered" then "mission module loaded".
   If LuaSocket is missing the log says so and the Hook idles.
2. getPlayerName() identifies you in single player; wingmen = other units in your group.
3. Export locked-target field (LoGetLockedTargetInformation()[1].ID) and whether that id equals
   Object:getID() in the mission state (otherwise engage_my_target says "target not found").
4. Pushing tasks/options onto AI wingmen inside a player's group behaves as expected.
5. net.dostring_in return order: code tolerates either (result, ok) or (ok, result).
6. Action VALUE polarity in airframes\*.toml (ids are real; test each action once in the sim, then set verified = true). The lupa fallback in extract.py never ran (LuaJIT path is tested).
7. Ollama accepting the generated schemas; Whisper/Piper/PTT never ran.
8. Whether DCS can be started with a mission chosen by the app: NOT built. The mission lands in
   Missions\skibodcs\; you still pick it in DCS.
Mission events are appended to Saved Games\DCS\skibodcs\events.jsonl for the campaign step.
