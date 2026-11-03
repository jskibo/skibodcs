# sequences/

`<aircraft>.json` = ED's own autostart / autostop timelines, generated from each module's `Macro_sequencies.lua`:

    skibodcs sequences --devices D --commands C --macros M --aircraft F-16C_50 --out sequences\\f-16c.json

Steps: `{"delay": s, "device": d, "command": c, "value": v}` (a click), or `{"message": ..., "speak": bool, "prompt": bool}`.
`delay` = seconds since the previous step; the runner follows an absolute timeline (no drift).
* Headings ("ENGINE START", "AUTOSTART COMPLETE") are spoken; per-switch detail lines are only logged.
* `prompt` = ED's own check asks the PILOT to move a physical lever (throttle / power levers). That is spoken; the
  sim cannot be told to move your HOTAS, so do it when you hear it.
* ED's internal verification checks (engine RPM, INS ready...) are NOT replayed; the timeline simply continues.
Voice: "autostart" / "cold and dark to ready to taxi" (same sequence: ED's autostart ends ready to taxi),
"autostop", "abort the start". Durations (1x): F-16C ~4.3 min, F/A-18C ~5.4 min, AH-64D ~7 min.
