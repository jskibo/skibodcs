# skibodcs v0.1 — step 1: scenario spec -> validate -> .miz

## Setup (sim PC, Windows)
    py -m venv .venv && .venv\Scripts\activate
    pip install pydcs pyproj "pydantic>=2" pytest
    pip install -e .

## Use
    skibodcs catalog Caucasus                      # real names to paste into the LLM prompt
    skibodcs validate examples\iron_lantern.json   # LLM-readable errors, with suggestions
    skibodcs compile  examples\iron_lantern.json out\iron_lantern.miz
    pytest

Copy the .miz into  Saved Games\DCS\Missions  and open it in the Mission Editor.

## First things to check on the real machine
1. Player F-16 pylons: default loadouts come from your DCS install via pydcs.
   (My sandbox had no DCS, so loadouts were empty there and the compiler warns.)
2. Mission opens in the editor without errors; SA-6 site + armor sit ~22 nm north of Kutaisi.
3. AWACS/tanker orbits, frequencies, TACAN 40X.

## Not compiled yet (kept in out\*.scenario.json, listed as notes)
dynamic_rules, objectives scoring, conditional red air, JTAC -> need runtime.lua (step 2).

## Spec change vs. my earlier sketch
Anchors are {near: <airbase>, bearing, distance_nm}. Player flights are a list.
