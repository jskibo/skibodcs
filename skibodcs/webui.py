"""`skibodcs ui`: the mission builder as a local web page (stdlib only, no extra installs, one process).
Nothing touches your DCS folders until you press Install. Preview builds into <state>/builds/<id>/ and shows the kneeboard pages."""
from __future__ import annotations
import datetime as dt
import json
import mimetypes
import re
import shutil
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import builder, catalog, deploy as dp, packages
from .campaign import Campaign, events_path
from .compile import compile_scenario
from .doctor import _tcp_open
from .kneeboard import loadout_rows, make_kneeboards
from .schema import Scenario
from .validate import validate

WEB = Path(__file__).parent / "web"


class UserError(Exception):
    """Something the user can fix; shown verbatim in the page."""


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40] or "mission"


class App:
    def __init__(self, config: dict | None = None, dcs_dir: str | Path | None = None, state_dir: str | Path | None = None,
                 llm_factory=None, hook_factory=None):
        self.cfg = config or {}
        self.dcs_dir = Path(dcs_dir) if dcs_dir else None
        self.state = Path(state_dir) if state_dir else ((self.dcs_dir / "skibodcs" / "ui") if self.dcs_dir else Path("skibodcs_ui"))
        self.builds = self.state / "builds"
        self.builds.mkdir(parents=True, exist_ok=True)
        self.db = self.state / "campaign.db"
        self.llm_factory = llm_factory or self._default_llm
        self.hook_factory = hook_factory or self._default_hook
        self._lock = threading.Lock()

    # ---------- dependencies
    def _default_llm(self):
        o = self.cfg.get("ollama")
        if not o:
            raise UserError("The AI is not configured: add an [ollama] section (host, model) to skibodcs.toml.")
        from .llm import OllamaClient
        return OllamaClient(o["model"], o["host"])

    def _default_hook(self):
        from .voice.link import HookClient
        return HookClient(port=self.cfg.get("hook_command_port", 14510))

    # ---------- shared: spec -> files
    def _make_build(self, spec_or_sc, kind: str, extra: dict | None = None, camp_mission: int | None = None) -> dict:
        sc = spec_or_sc if isinstance(spec_or_sc, Scenario) else None
        if sc is None:
            sc, errs = validate(spec_or_sc)
            if sc is None:
                raise UserError("That combination does not work: " + "; ".join(errs))
        bid = f"{_slug(sc.meta.title)}_{dt.datetime.now():%H%M%S}"
        d = self.builds / bid
        d.mkdir(parents=True, exist_ok=True)
        sc.meta.id = bid
        miz = d / f"{bid}.miz"
        warnings = compile_scenario(sc, miz)
        pages = make_kneeboards(sc, d / "kneeboard")
        meta = {"id": bid, "kind": kind, "miz": miz.name, "aircraft": [f.aircraft for f in sc.player], "camp_mission": camp_mission, **(extra or {})}
        (d / "meta.json").write_text(json.dumps(meta))
        return {"id": bid, "summary": self.summary(sc), "warnings": warnings, "kind": kind,
                "kneeboards": [f"/files/{bid}/kneeboard/{ac}/{p.name}" for ac, ps in pages.items() for p in ps], **(extra or {})}

    @staticmethod
    def summary(sc: Scenario) -> dict:
        f = sc.player[0]
        def place(a): return f"{a.near} {int(round(a.bearing)) % 360:03d}/{a.distance_nm:.0f} nm" if a.distance_nm else a.near
        return {
            "title": sc.meta.title, "when": f"{sc.meta.date} {sc.meta.start_time}", "theater": sc.meta.theater,
            "flight": f"{f.callsign} x{f.count} {f.aircraft}, {f.task}, {f.start_type} start at {f.start_airbase}",
            "route": [f"{w.name}: {place(w.at)} @ {int(w.alt_ft):,} ft" for w in f.route],
            "enemy": [f"{g.id}: {g.template} at {place(g.position)}" for g in sc.red.groups]
                     + [f"CAP: {a.aircraft} x{a.count}" for a in sc.red.air],
            "objectives": [f"[{o.priority}] {o.type} {o.target_group or ''}".strip() for o in sc.objectives],
            "weather": f"{sc.weather.clouds}, wind {int(sc.weather.wind_from_deg):03d}/{int(sc.weather.wind_kt)} kt, vis {int(sc.weather.vis_km)} km",
            "support": [k for k, v in sc.blue_support.model_dump().items() if v],
            "package": [f"{sf.callsign or sf.role}: {packages.ROLE_LABEL[sf.role]}, {sf.count}x {sf.aircraft}, launches "
                        + (f"{sf.delay_min:g} min after start" if sf.delay_min else "at start") for sf in sc.support_flights],
            "loadout": [f"Station {n}: {name}" for n, name in loadout_rows(f)],
            "briefing": sc.briefing.model_dump()}

    # ---------- API
    def api_options(self, q):
        th = (q.get("theater") or ["Caucasus"])[0]
        return {**builder.options(th), "defaults": builder.DEFAULTS, "ollama": bool(self.cfg.get("ollama")),
                "dcs_dir": str(self.dcs_dir) if self.dcs_dir else None}

    def api_status(self, q):
        return {"export": _tcp_open(14500), "hook": _tcp_open(14510), "dcs_dir": str(self.dcs_dir) if self.dcs_dir else None}

    def api_preview(self, body):
        form = body.get("form") or {}
        try:
            spec, notes = builder.build_spec(form, "preview")
        except (KeyError, ValueError) as e:
            raise UserError(str(e).strip("'\"")) from e
        out = self._make_build(spec, "quick", {"notes": notes})
        if body.get("ai_briefing"):
            out["notes"].append("AI briefing requested: use the 'Describe it' tab for a fully AI-written mission.")
        return out

    def api_describe(self, body):
        from .generate import generate_scenario
        text = (body.get("text") or "").strip()
        if not text:
            raise UserError("Describe the mission you want first.")
        llm = self.llm_factory()
        th = body.get("theater") or "Caucasus"
        try:
            sc, log = generate_scenario(llm, text, th, "ai_preview")
        except RuntimeError as e:
            raise UserError(str(e)) from e
        except Exception as e:                                   # noqa: BLE001 - network/model errors become readable messages
            raise UserError(f"Could not reach the AI: {e}") from e
        out = self._make_build(sc, "ai", {"notes": log})
        return out

    def _build_dir(self, bid: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_]+", bid or ""):
            raise UserError("Unknown build.")
        d = self.builds / bid
        if not (d / "meta.json").exists():
            raise UserError("Unknown build: preview it again.")
        return d

    def api_install(self, body):
        if not self.dcs_dir:
            raise UserError("No Saved Games\\DCS folder found: start the UI with --dcs-dir.")
        d = self._build_dir(body.get("id"))
        meta = json.loads((d / "meta.json").read_text())
        pages: dict[str, list[Path]] = {}
        for ac in meta["aircraft"]:
            pages[ac] = sorted((d / "kneeboard" / ac).glob("*.png"), key=lambda p: ["mission", "flight", "loadout", "route", "briefing",
                       "threats", "threattable", "map", "datacard"].index(p.stem) if p.stem in
                       ["mission", "flight", "loadout", "route", "briefing", "threats", "threattable", "map", "datacard"] else 99)
        out = dp.deploy_mission(self.dcs_dir, d / meta["miz"], pages)
        deployed = str(self.dcs_dir / "Missions" / "skibodcs" / meta["miz"])
        if meta.get("camp_mission") and meta.get("campaign"):             # the sortie's events start counting NOW
            ep = events_path(self.dcs_dir)
            Campaign.open(self.db, meta["campaign"]).set_offset(meta["camp_mission"], ep.stat().st_size if ep.exists() else 0)
        return {"installed": [str(p) for p in out], "mission_path": deployed,
                "message": f"Installed. In DCS pick '{Path(meta['miz']).stem}' from the skibodcs mission folder."}

    def api_launch(self, body):
        if not self.dcs_dir:
            raise UserError("No Saved Games\\DCS folder found.")
        d = self._build_dir(body.get("id"))
        meta = json.loads((d / "meta.json").read_text())
        path = self.dcs_dir / "Missions" / "skibodcs" / meta["miz"]
        if not path.exists():
            raise UserError("Install it first.")
        ok, detail = self.hook_factory().load_mission(path)
        if not ok:
            raise UserError(f"DCS did not start it: {detail}. (DCS must already be running a mission; otherwise pick it in the DCS mission list.)")
        return {"message": detail}

    # --- campaigns
    def _camp(self, name: str) -> Campaign:
        try:
            return Campaign.open(self.db, name)
        except KeyError as e:
            raise UserError(f"No campaign called '{name}'.") from e

    def api_campaigns(self, q):
        import sqlite3
        if not self.db.exists():
            return {"campaigns": []}
        con = sqlite3.connect(str(self.db))
        names = [r[0] for r in con.execute("SELECT name FROM campaign ORDER BY id")] if con.execute(
            "SELECT name FROM sqlite_master WHERE name='campaign'").fetchone() else []
        con.close()
        return {"campaigns": [self._camp(n).summary() | {"aircraft": self._camp(n).row()["aircraft"], "theater": self._camp(n).row()["theater"]} for n in names]}

    def api_campaign_new(self, body):
        try:
            Campaign.create(self.db, (body.get("name") or "").strip() or "Campaign", body.get("theater", "Caucasus"), body.get("aircraft", "F-16C_50"),
                            body.get("home", "Batumi"), body.get("callsign") or builder.AIRCRAFT.get(body.get("aircraft", "F-16C_50"), ("", "Viper"))[1],
                            body.get("start_date") or "2026-06-14", int(body.get("flight_size", 2)), int(body.get("sites", 6)),
                            int(body["seed"]) if body.get("seed") not in (None, "") else None)
        except KeyError as e:
            raise UserError(str(e).strip("'\"")) from e
        except Exception as e:                                   # noqa: BLE001
            if "UNIQUE" in str(e):
                raise UserError("A campaign with that name already exists.") from e
            raise
        return self._camp((body.get("name") or "Campaign").strip()).summary()

    def api_campaign_status(self, q):
        return self._camp((q.get("name") or [""])[0]).summary()

    def api_campaign_next(self, body):
        camp = self._camp(body.get("name", ""))
        steer = {k: v for k, v in (body.get("steer") or {}).items() if v and v != "random"}
        try:
            if body.get("use_ai"):
                from .campaign import Campaign as C
                sc = camp.plan_llm(self.llm_factory(), body.get("request", ""))
            else:
                sc = camp.plan_deterministic(steer=steer)
        except ValueError as e:
            raise UserError(str(e)) from e
        except UserError:
            raise
        except Exception as e:                                   # noqa: BLE001
            raise UserError(f"Could not plan the sortie: {e}") from e
        mid = camp.register(sc)
        out = self._make_build(sc, "campaign", {"campaign": camp.row()["name"], "notes": []}, camp_mission=mid)
        out["campaign_status"] = camp.summary()
        return out

    def api_campaign_ingest(self, body):
        if not self.dcs_dir:
            raise UserError("No Saved Games\\DCS folder found.")
        from .campaign import ingest_latest
        camp = self._camp(body.get("name", ""))
        try:
            outcome = ingest_latest(camp, self.dcs_dir)
        except RuntimeError as e:
            raise UserError(str(e)) from e
        return {"outcome": outcome, "status": camp.summary()}

    # ---------- HTTP plumbing
    ROUTES_GET = {"/api/options": "api_options", "/api/status": "api_status", "/api/campaigns": "api_campaigns",
                  "/api/campaign/status": "api_campaign_status"}
    ROUTES_POST = {"/api/preview": "api_preview", "/api/describe": "api_describe", "/api/install": "api_install",
                   "/api/launch": "api_launch", "/api/campaign/new": "api_campaign_new", "/api/campaign/next": "api_campaign_next",
                   "/api/campaign/ingest": "api_campaign_ingest"}

    def handle(self, method: str, url: str, body: bytes = b"") -> tuple[int, str, bytes]:
        u = urlparse(url)
        try:
            if method == "GET" and u.path in ("/", "/index.html"):
                return 200, "text/html; charset=utf-8", (WEB / "index.html").read_bytes()
            if method == "GET" and u.path.startswith("/files/"):
                return self._file(u.path[len("/files/"):])
            routes = self.ROUTES_GET if method == "GET" else self.ROUTES_POST
            name = routes.get(u.path)
            if name is None:
                return 404, "application/json", b'{"error":"not found"}'
            fn = getattr(self, name)
            with self._lock:                                      # one build at a time: pydcs and the DB are not made for parallel use
                res = fn(parse_qs(u.query)) if method == "GET" else fn(json.loads(body or b"{}"))
            return 200, "application/json", json.dumps(res).encode()
        except UserError as e:
            return 400, "application/json", json.dumps({"error": str(e)}).encode()
        except Exception as e:                                    # noqa: BLE001 - never a stack trace in the page
            return 500, "application/json", json.dumps({"error": f"{type(e).__name__}: {e}"}).encode()

    def _file(self, rel: str):
        p = (self.builds / rel).resolve()
        if self.builds.resolve() not in p.parents or not p.is_file() or p.suffix not in (".png", ".miz", ".json"):
            return 404, "application/json", b'{"error":"not found"}'
        return 200, mimetypes.guess_type(p.name)[0] or "application/octet-stream", p.read_bytes()


def make_server(app: App, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def _go(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            status, ctype, data = app.handle(method, self.path, self.rfile.read(n) if n else b"")
            self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)
        def do_GET(self): self._go("GET")
        def do_POST(self): self._go("POST")
        def log_message(self, *a): pass
    return ThreadingHTTPServer((host, port), H)


def run(config_path: str = "skibodcs.toml", dcs_dir: str | None = None, port: int = 8765, lan: bool = False, open_browser: bool = True):
    cfg = tomllib.loads(Path(config_path).read_text()) if Path(config_path).exists() else {}
    if dcs_dir is None:
        picked = dp.pick_dcs_dir(cfg)
        dcs_dir = str(picked) if picked else None
    app = App(cfg, dcs_dir)
    host = "0.0.0.0" if lan else "127.0.0.1"
    srv = make_server(app, host, port)
    url = f"http://localhost:{port}/"
    print(f"Mission builder running at {url}   (Ctrl+C to stop)" + ("  [LAN: anyone on your network can open it]" if lan else ""))
    if dcs_dir is None:
        print("No Saved Games\\\\DCS folder found: you can preview missions but not install them.")
    if open_browser:
        import webbrowser; threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
