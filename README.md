# skibodcs v0.2

Two tracks, one codebase. Everything below marked UNVERIFIED could not be run in the build
sandbox (no DCS, no Ollama, no Whisper/Piper there). All logic with fakes is covered by `pytest`.

## Setup (sim PC, Windows)
    py -m venv .venv && .venv\Scripts\activate
    pip install pydcs pyproj "pydantic>=2" pytest
    pip install -e .[voice]
    pytest

## A. Mission generator (Ollama, schema-constrained)
    skibodcs catalog Caucasus
    skibodcs generate "SEAD strike on a SA-6 near Kutaisi, dawn" --theater Caucasus ^
        --model qwen3:14b --host http://MAC_STUDIO_IP:11434 --out out\m1.miz
Flow: schema (enums = real airbases/aircraft/tasks) -> Ollama `format` -> validate() ->
on errors the exact messages go back to the model (max 3 tries) -> briefing pass -> pydcs .miz.
UNVERIFIED: that Ollama accepts the generated schema ($defs/$ref) as-is on your version. If it
rejects it, tell me the error and I will inline the refs.

## B. Voice (natural speech, no exact phrases)
    copy skibodcs.example.toml skibodcs.toml   (edit host, model, piper path, joystick button)
    skibodcs-voice --text          # type instead of speak: safe way to test everything
    skibodcs-voice                 # PTT -> Whisper -> intent -> action -> Piper -> headset
Install the DCS side by appending ONE line to Saved Games\DCS\Scripts\Export.lua:
    pcall(dofile, lfs.writedir() .. [[Scripts\skibodcs_export.lua]])
and copying dcs_hook\skibodcs_export.lua to Saved Games\DCS\Scripts\.

Design rules: the LLM only picks an intent and action/value NAMES (enums). Code computes every
number (BRAA, bullseye, runway) and owns device/command ids (airframes\*.toml, in git).
Crisp calls like "bogey dope" skip the LLM entirely.

## UNVERIFIED / TODO
- airframes\f-16c.toml ids are PLACEHOLDERS. Extract real ones from clickabledata.lua; the
  app flags unverified actions.
- skibodcs_export.lua field names (Coalition, Type.level1, LoGetWorldObjects) are from the Export
  API as I know it; confirm in a live cockpit.
- FasterWhisperSTT/PiperTTS/PTTRecorder never ran. Piper is called via its CLI on purpose.
- Magnetic variation defaults to 0 (set magvar_east per theater). Aspect bands are simple.
- Not yet: JTAC 9-line, AI wingman orders, campaign DB (SQLite), mission-side Hook, kneeboards.
