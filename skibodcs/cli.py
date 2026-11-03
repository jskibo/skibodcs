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
    a = ap.parse_args(argv)

    if a.cmd == "catalog":
        print(json.dumps(catalog.catalog_dump(a.theater), indent=2)); return 0
    if a.cmd == "generate":
        from .llm import OllamaClient
        from .generate import generate_scenario
        sc, log = generate_scenario(OllamaClient(a.model, a.host), a.request, a.theater, a.id)
        print(*log, sep="\n")
        for w in compile_scenario(sc, a.out):
            print("  note:", w)
        print("wrote", a.out); return 0
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
