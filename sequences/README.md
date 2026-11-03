# sequences/

`<aircraft>.json` holds timed cockpit steps for `autostart`, `autostop` and `ready_to_taxi`:

    {"aircraft": "F-16C_50", "sequences": {"autostart": [
        {"delay": 0.1, "device": 3, "command": 3001, "value": 1.0},
        {"delay": 5.0, "message": "AUTOSTART COMPLETE"}]}}

`delay` = seconds to wait BEFORE the step (ED's `push_start_command(delta, ...)` uses deltas).
Generate these from ED's own `Macro_sequencies.lua` (the game's autostart data) once the files are
available; hand-written sequences are possible but unverified. Point `sequence_file` in skibodcs.toml at one.
Say "abort the start" to stop a running sequence.
