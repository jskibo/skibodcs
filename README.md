# skibodcs v0.3

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

## UNVERIFIED (verify in this order)
1. Hook loads: DCS log should show "skibodcs: hook registered" then "mission module loaded".
   If LuaSocket is missing the log says so and the Hook idles.
2. getPlayerName() identifies you in single player; wingmen = other units in your group.
3. Export locked-target field (LoGetLockedTargetInformation()[1].ID) and whether that id equals
   Object:getID() in the mission state (otherwise engage_my_target says "target not found").
4. Pushing tasks/options onto AI wingmen inside a player's group behaves as expected.
5. net.dostring_in return order: code tolerates either (result, ok) or (ok, result).
6. airframes\f-16c.toml ids are placeholders; no F/A-18C table yet. Extract from clickabledata.lua.
7. Ollama accepting the generated schemas; Whisper/Piper/PTT never ran.
8. Whether DCS can be started with a mission chosen by the app: NOT built. The mission lands in
   Missions\skibodcs\; you still pick it in DCS.
Mission events are appended to Saved Games\DCS\skibodcs\events.jsonl for the campaign step.
