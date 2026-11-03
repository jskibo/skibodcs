import argparse, json, sys
from pathlib import Path
from . import catalog
from .validate import validate
from .compile import compile_scenario


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skibodcs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compile", help="spec.json -> .miz")
    c.add_argument("spec"); c.add_argument("out")
    v = sub.add_parser("validate", help="check spec.json, print errors")
    v.add_argument("spec")
    e = sub.add_parser("catalog", help="dump real names for the LLM prompt")
    e.add_argument("theater")
    g = sub.add_parser("generate", help="LLM request -> validated spec -> .miz")
    g.add_argument("request"); g.add_argument("--theater", default="Caucasus")
    g.add_argument("--model", default="qwen3:14b"); g.add_argument("--host", default="http://localhost:11434")
    g.add_argument("--out", default="out/generated.miz"); g.add_argument("--id", default="scn_0001")
    for name in ("install", "uninstall"):
        x = sub.add_parser(name, help=f"{name} the DCS Lua files (Hook, mission module, Export.lua block)")
        x.add_argument("--dcs-dir")
    d = sub.add_parser("deploy", help="copy a .miz (+ kneeboards) into the DCS folders")
    d.add_argument("miz"); d.add_argument("--dcs-dir")
    d.add_argument("--kneeboard", action="append", default=[], metavar="AIRCRAFT=PNG")
    g.add_argument("--deploy", action="store_true", help="also copy the result into DCS Missions")
    for name, hlp in (("controls", "export EVERY clickable control of a module as airframes/*.controls.json"),
                      ("extract", "build airframes/*.toml from ED cockpit definition files"),
                      ("find", "search controls by name in ED cockpit definition files")):
        x = sub.add_parser(name, help=hlp)
        x.add_argument("--devices", required=True); x.add_argument("--commands", required=True)
        x.add_argument("--clickable", required=True)
        if name in ("extract", "controls"):
            x.add_argument("--macros", help="Macro_sequencies.lua: pin switch values to ED's own autostart data")
            x.add_argument("--aircraft", required=True, help="F-16C_50 or FA-18C_hornet"); x.add_argument("--out", required=True)
        else:
            x.add_argument("text")
    q = sub.add_parser("sequences", help="build sequences/<aircraft>.json (autostart/autostop) from ED's Macro_sequencies.lua")
    q.add_argument("--devices", required=True); q.add_argument("--commands", required=True)
    q.add_argument("--macros", required=True); q.add_argument("--aircraft", required=True); q.add_argument("--out", required=True)
    n = sub.add_parser("native-sequence", help="sequence that triggers the module's built-in autostart/autostop key commands")
    n.add_argument("--aircraft", required=True); n.add_argument("--start", type=int, required=True)
    n.add_argument("--stop", type=int, required=True); n.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    if a.cmd in ("install", "uninstall", "deploy") or getattr(a, "deploy", False):
        from . import deploy as dp
        dirs = [Path(a.dcs_dir)] if getattr(a, "dcs_dir", None) else dp.find_dcs_dirs()
        if not dirs:
            print("No Saved Games\\DCS folder found; pass --dcs-dir"); return 1
        if len(dirs) > 1 and a.cmd in ("install", "uninstall", "deploy"):
            print("Found", *dirs, sep="\n  "); print("Pass --dcs-dir to choose one."); return 1
        dcs = dirs[0]
    if a.cmd == "install":
        print(*dp.install(dcs), sep="\n  "); return 0
    if a.cmd == "uninstall":
        print(*dp.uninstall(dcs), sep="\n  "); return 0
    if a.cmd == "deploy":
        kb: dict = {}
        for item in a.kneeboard:
            ac, png = item.split("=", 1); kb.setdefault(ac, []).append(Path(png))
        print(*dp.deploy_mission(dcs, Path(a.miz), kb), sep="\n  "); return 0
    if a.cmd == "native-sequence":
        from . import macros as mc
        seq = {"aircraft": a.aircraft, "source": "native iCommand (LoSetCommand)",
               "note": "Triggers the module's own autostart/autostop input commands instead of replaying clicks. UNVERIFIED: "
                       "confirm the codes (Controls screen shows them with OPTIONS_ADD_COMMAND_CODES_TO_TOOLTIP = true).",
               "sequences": {"autostart": [{"delay": 0, "message": "Starting automatic engine start", "speak": True},
                                           {"delay": 0.5, "icommand": a.start}],
                             "autostop": [{"delay": 0, "message": "Starting automatic shutdown", "speak": True},
                                          {"delay": 0.5, "icommand": a.stop}]}}
        mc.save_sequences(seq, a.out); print("wrote", a.out); return 0
    if a.cmd == "sequences":
        from . import extract as ex, macros as mc
        raw = ex.run_macro_extractor(Path(a.devices), Path(a.commands), Path(a.macros))
        seq = mc.to_sequences(raw, a.aircraft)
        mc.save_sequences(seq, a.out)
        print("wrote", a.out, {k: len(v) for k, v in seq["sequences"].items()},
              "| autostart ~%.0f s" % sum(st.get("delay", 0) for st in seq["sequences"]["autostart"]))
        return 0
    if a.cmd in ("extract", "find", "controls"):
        from . import extract as ex
        els = ex.run_extractor(Path(a.devices), Path(a.commands), Path(a.clickable))
        observed = None
        if getattr(a, "macros", None):
            from . import macros as mc
            observed = mc.observed_values(ex.run_macro_extractor(Path(a.devices), Path(a.commands), Path(a.macros)))
        if a.cmd == "controls":
            from . import controls as cl
            cs = cl.build_controls(els)
            pinned = cl.apply_macros(cs, observed) if observed else 0
            cl.save(cs, a.aircraft, a.out)
            kinds = {}
            for c in cs: kinds[c.kind] = kinds.get(c.kind, 0) + 1
            print("wrote", a.out, len(cs), "controls", kinds, "| confirm-required:", sum(c.danger for c in cs),
                  "| pinned to ED's autostart values:", pinned)
            return 0
        if a.cmd == "find":
            for e in ex.find(els, a.text):
                print(f"{e['hint']}  | dev {e['device']} {e['device_name']} | "
                      f"{[(c['name'], c['id']) for c in e['commands']]} | arg {e['args']}")
            return 0
        text, problems = ex.build_table(els, a.aircraft, observed=observed)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(text)
        print("wrote", a.out); [print("  PROBLEM:", p) for p in problems]
        return 1 if problems else 0
    if a.cmd == "catalog":
        print(json.dumps(catalog.catalog_dump(a.theater), indent=2)); return 0
    if a.cmd == "generate":
        from .llm import OllamaClient
        from .generate import generate_scenario
        sc, log = generate_scenario(OllamaClient(a.model, a.host), a.request, a.theater, a.id)
        print(*log, sep="\n")
        for w in compile_scenario(sc, a.out):
            print("  note:", w)
        print("wrote", a.out)
        if a.deploy:
            print(*dp.deploy_mission(dcs, Path(a.out)), sep="\n  ")
        return 0
    sc, errs = validate(Path(a.spec).read_text())
    if errs:
        print("INVALID:", *errs, sep="\n  - "); return 1
    if a.cmd == "validate":
        print("OK"); return 0
    warns = compile_scenario(sc, a.out)
    print(f"wrote {a.out}")
    for w in warns:
        print("  note:", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
