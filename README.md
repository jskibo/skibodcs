# skibodcs v0.8

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
VALUES (corrected in v0.6): hint order carries NO reliable polarity, and v0.4/v0.5 shipped gear/hook tables with
up and down INVERTED (F-16C and Hornet: gear DN = 0.0, UP = 1.0). Values are now pinned to ED's own autostart data
(`Macro_sequencies.lua`, via `--macros`): positions the game itself uses are `confirmed`; 2/3-position partners are
`inferred` only when exactly one ordering fits; everything else stays PROVISIONAL and triggers an UNVERIFIED note.
Each action carries its cockpit `arg` number so the read-back step can confirm the result.

## Every control by voice, wingman/element orders, autostart (new in v0.5)
**All controls.** `skibodcs controls --devices D --commands C --clickable K --aircraft F-16C_50 --out airframes\\f-16c.controls.json`
exports every clickable (F-16C: 268, F/A-18C: 258; ~90% usable: buttons, 2/3-position switches, multi-position knobs, axes).
Set `controls_file` in skibodcs.toml. Per utterance the app shortlists ~12 candidate controls (search over names,
abbreviations like LG/UFC/VOL, synonyms) and gives only those to the LLM, which must choose from that list
(schema-constrained). The curated TOML (gear, hook, master arm...) wins over generated duplicates.
Axes take a percentage ("UHF volume to 60"). About 10% of controls are composite (landing gear handle, emergency brake,
external power...) and are not voice-enabled yet; the curated TOML covers the important ones.
**Safety.** Eject/jettison/fire-extinguisher/canopy-jettison/harness etc. are flagged `danger`: the app says
"Confirm ...?" and runs it only if you say "confirm" within 10 s ("negative"/anything else cancels).
**Truthful feedback.** After a click the app reads the cockpit argument back (Export `R,<arg>`) and says
"<switch> unchanged" if nothing moved, instead of assuming success.
**Wingman / element (F-menu equivalents).** `who` = flight (default) | wingman (#2) | element (#3+#4) | 2 | 3 | 4.
Implemented through the mission Controller API: weapons free/hold + ROE (free/hold/return_fire/open_fire), radar
(off/attack_only/search/continuous), ECM (off/lock/detected/always), reaction (none/passive/evade/escape),
formation (line_abreast, trail, wedge, echelon_right/left, finger_four, spread, vic x close/open/group),
engage my target / nearest / bandits / ground / SEAD, cover me (Escort), rejoin (Follow), status.
Option ids and formation numbers follow MOOSE's source; task names/params follow pydcs. NOT implemented (the sim says
so and the app says "unable"): RTB, cleared hot, break left/right. DCS exposes NO API to press its native F-menu
items, so these are behavioural equivalents, not the literal menu entries; compare them in the sim.
**Autostart / "cold and dark to ready to taxi".** Engine in place (`skibodcs/sequence.py`, voice intents autostart /
autostop / ready_to_taxi, "abort the start"). The sequences themselves are DATA in sequences\<aircraft>.json and are
meant to be generated from ED's own `Macro_sequencies.lua` (the game's autostart: device, command, value, delay).
That file has not been parsed yet (not supplied), so nothing ships in sequences\ and the app says "no sequence available".

## v0.6: AH-64D, ED's own autostart, value pinning
Modules shipped: F-16C (288 controls), F/A-18C (274), AH-64D (478: PLT 220 / CPG 258; `crew = "PLT"` or `"CPG"`),
F-14B (469: PLT 137 / RIO 29 / shared 303; `crew = "PLT"` or `"RIO"`; files live in Mods\\aircraft\\F14, no hyphen).
**F-14 caveats.** Heatblur defines its own helpers (the extractor wraps them) and hides cockpit argument numbers in
`draw_args.lua` (supplied in v0.8: read-back now works for 461 of 469 F-14 controls; pass `--draw-args` when regenerating). There is no ED-style autostart macro
file, so NO value is confirmed: gear/hook/parking-brake values in airframes\\f-14b.toml are guesses and the app asks you to
say "confirm" before acting on any unconfirmed value of a consequential control (gear, hook, flaps, master arm, fuel, engines,
brakes, canopy...). The F-14's command file declares Engine_Start = 311 / Engine_Stop = 312 (the standard autostart/autostop
input commands); sequences\\f-14b.json triggers those through Export's LoSetCommand instead of replaying clicks. UNVERIFIED:
that LoSetCommand honours them for this module, and what state the F-14 ends in ("ready to taxi" is not guaranteed).
    skibodcs sequences --devices D --commands C --macros M --aircraft F-16C_50 --out sequences\\f-16c.json
    skibodcs controls  --devices D --commands C --clickable K --macros M --aircraft F-16C_50 --out airframes\\f-16c.controls.json
    skibodcs extract   --devices D --commands C --clickable K --macros M --aircraft F-16C_50 --out airframes\\f-16c.toml
**Autostart / "cold and dark to ready to taxi"** = replay of ED's own timeline (device, command, value, delay) through the
same Export link as every other click. Say "autostart" or "cold and dark to ready to taxi" (same sequence: ED's autostart
ends ready to taxi), "autostop", "abort the start". Spoken: section headings, prompts, completion. Where ED asks the PILOT
to move a physical lever (throttle / power levers) it is spoken as a prompt; the sim cannot move your HOTAS.
Not replayed: ED's internal verification checks (engine RPM, INS ready...) - the timeline just continues.
Untested against a live sim: that replaying these through performClickableAction behaves like ED's internal runner.

## v0.8: A-10C and A-10C II
Files: airframes\\a-10c.* / a-10c-ii.* and sequences\\a-10c.json / a-10c-ii.json (unit types `A-10C` and `A-10C_2`; ED's two
cockpits are ~99% identical, the II adds ARC-210 radio items). 470 / 473 controls, every one with a cockpit arg number (read-back).
Autostart / autostop come from ED's own Macro_sequencies.lua (146 / 46 steps, ~6.6 min at 1x, no pilot prompts).
Pinned to ED's data: APU, battery, AC generators, APU generator, oxygen supply. NOT pinned (provisional, the app asks you to say
"confirm"): the landing gear lever (down = 1.0 / up = 0.0 is a guess; ED's autostart never touches it) and AHCP master arm.
Engine start buttons are momentary. Extractor changes that came with it: (1) the cockpit arg number is now read from the element a
module-defined helper actually returns (before, A-10 args all came out 0); (2) wishlist command names may be `DEVICE:command`,
because the A-10 reuses `device_commands.Button_N` on every device; (3) `--draw-args` for the F-14. Three controls each in the
F-16C and F/A-18C files gained their real arg numbers from (1); nothing else in those files changed.

## Safety rule (v0.7)
Unconfirmed value + consequential control => the app says "Confirm <thing>? That value is unverified for this aircraft" and acts
only on a spoken "confirm" within 10 s. Confirmed values (from ED's autostart data) run immediately.

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
