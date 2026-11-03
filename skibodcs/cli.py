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
    a = ap.parse_args(argv)

    if a.cmd == "catalog":
        print(json.dumps(catalog.catalog_dump(a.theater), indent=2)); return 0
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
