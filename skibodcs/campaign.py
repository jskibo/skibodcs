"""Campaign engine: persistent state in SQLite, deterministic mission generation (no LLM needed), optional LLM path,
and results ingestion from the Hook's events.jsonl so the next sortie reflects what happened in the last one.

State carried between missions: red sites (alive / destroyed), the airframe pool, sortie count and date. The LLM (when used)
only gets a summary of that state; code owns the truth. Everything is seedable so a campaign is reproducible."""
from __future__ import annotations
import datetime as dt
import json
import random
import sqlite3
from pathlib import Path

from . import catalog
from .schema import Scenario
from .validate import validate

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign(id INTEGER PRIMARY KEY, name TEXT UNIQUE, theater TEXT, aircraft TEXT, callsign TEXT,
  home TEXT, flight_size INTEGER, pool INTEGER, pool_max INTEGER, seq INTEGER DEFAULT 0, current_date TEXT, status TEXT DEFAULT 'active',
  seed INTEGER);
CREATE TABLE IF NOT EXISTS site(campaign_id INTEGER, id TEXT, template TEXT, near TEXT, bearing REAL, distance_nm REAL,
  heading REAL DEFAULT 0, status TEXT DEFAULT 'alive', destroyed_seq INTEGER, units_dead INTEGER DEFAULT 0,
  PRIMARY KEY(campaign_id, id));
CREATE TABLE IF NOT EXISTS mission(id INTEGER PRIMARY KEY, campaign_id INTEGER, seq INTEGER, title TEXT, scenario TEXT, miz TEXT,
  status TEXT DEFAULT 'planned', events_offset INTEGER DEFAULT 0, outcome TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS event(mission_id INTEGER, kind TEXT, unit TEXT, grp TEXT, utype TEXT, coalition INTEGER, t REAL);
"""
SAM = ["SA-2", "SA-6", "SA-8", "SA-10", "SA-11", "SA-13", "SA-15", "ZSU-23"]
GROUND = ["ARMOR_PLATOON", "MECH_INF"]
TIMES = ["06:30", "09:00", "13:00", "16:30", "19:00"]
CLOUDS = ["clear", "few", "scattered", "broken"]


def _units(template: str) -> int:
    return sum(n for _, n in catalog.GROUND_TEMPLATES[template])


class Campaign:
    def __init__(self, db: str | Path, cid: int):
        self.db = sqlite3.connect(str(db))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.cid = cid

    # ---------- lifecycle
    @classmethod
    def open(cls, db: str | Path, name: str) -> "Campaign":
        con = sqlite3.connect(str(db)); con.executescript(SCHEMA)
        row = con.execute("SELECT id FROM campaign WHERE name=?", (name,)).fetchone()
        con.close()
        if row is None:
            raise KeyError(f"no campaign '{name}'")
        return cls(db, row[0])

    @classmethod
    def create(cls, db: str | Path, name: str, theater: str, aircraft: str, home: str, callsign: str = "Viper",
               start_date: str = "2026-06-14", flight_size: int = 2, sites: int = 6, seed: int | None = None) -> "Campaign":
        if aircraft not in catalog.aircraft_ids():
            raise KeyError(f"unknown aircraft '{aircraft}'")
        if catalog.find_airbase(theater, home) is None:
            raise KeyError(f"no airbase '{home}' on {theater}; try {catalog.suggest(home, catalog.airbases(theater))}")
        seed = random.Random().randrange(1 << 30) if seed is None else seed
        con = sqlite3.connect(str(db)); con.executescript(SCHEMA)
        cur = con.execute("INSERT INTO campaign(name,theater,aircraft,callsign,home,flight_size,pool,pool_max,current_date,seed) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?)", (name, theater, aircraft, callsign, home, flight_size,
                                                          flight_size * 2, flight_size * 2, start_date, seed))
        cid = cur.lastrowid
        rng = random.Random(seed)
        for i in range(sites):
            tpl = rng.choice(SAM) if i % 2 == 0 else rng.choice(GROUND)
            con.execute("INSERT INTO site(campaign_id,id,template,near,bearing,distance_nm,heading) VALUES(?,?,?,?,?,?,?)",
                        (cid, f"{tpl.lower().replace('-', '')}_{i + 1}", tpl, home, round(rng.uniform(0, 360)),
                         round(rng.uniform(25, 85)), round(rng.uniform(0, 360))))
        con.commit(); con.close()
        return cls(db, cid)

    def row(self) -> sqlite3.Row:
        return self.db.execute("SELECT * FROM campaign WHERE id=?", (self.cid,)).fetchone()

    def sites(self, status: str | None = None) -> list[sqlite3.Row]:
        q, a = "SELECT * FROM site WHERE campaign_id=?", [self.cid]
        if status:
            q += " AND status=?"; a.append(status)
        return self.db.execute(q + " ORDER BY id", a).fetchall()

    def summary(self) -> dict:
        c = self.row()
        return {"campaign": c["name"], "sortie": c["seq"], "date": c["current_date"], "status": c["status"],
                "airframes": f"{c['pool']}/{c['pool_max']}",
                "red_alive": [f"{s['id']} ({s['template']})" for s in self.sites("alive")],
                "red_destroyed": [s["id"] for s in self.sites("destroyed")]}

    # ---------- generation
    def _anchor(self, s) -> dict:
        return {"near": s["near"], "bearing": s["bearing"], "distance_nm": s["distance_nm"]}

    def _pick_target(self, rng: random.Random):
        alive = self.sites("alive")
        sams = [s for s in alive if s["template"] in SAM]
        # SEAD first while SAMs live and the dice agree; otherwise hit ground forces; CAP when nothing is left to hit
        if sams and (rng.random() < 0.6 or len(sams) == len(alive)):
            return "SEAD", rng.choice(sams)
        grd = [s for s in alive if s["template"] not in SAM]
        if grd:
            return rng.choice(["CAS", "STRIKE"]), rng.choice(grd)
        return "CAP", None

    def plan_deterministic(self, rng: random.Random | None = None) -> Scenario:
        c = self.row()
        rng = rng or random.Random(c["seed"] * 1000 + c["seq"] + 1)
        seq = c["seq"] + 1
        task, tgt = self._pick_target(rng)
        near = c["home"]
        size = max(1, min(c["flight_size"], c["pool"]))
        weather = {"clouds": rng.choice(CLOUDS), "wind_kt": rng.randint(2, 18), "wind_from_deg": rng.randrange(0, 360, 10),
                   "vis_km": rng.choice([15, 30, 60, 80]), "qnh_mmhg": rng.randint(752, 768)}
        route, groups, objectives = [], [], []
        if tgt is not None:
            tb, td = tgt["bearing"], tgt["distance_nm"]
            ip_d = max(td - 25, 15) if td > 40 else td + 20
            route = [{"name": "IP", "at": {"near": near, "bearing": tb, "distance_nm": ip_d}, "alt_ft": 20000, "speed_kt": 420},
                     {"name": "TGT", "at": self._anchor(tgt), "alt_ft": 18000 if task != "CAS" else 12000, "speed_kt": 450}]
            for s in self.sites("alive"):                 # persistent world: every living site near the target is on the map
                near_tgt = abs(s["distance_nm"] - td) < 30 and min(abs(s["bearing"] - tb), 360 - abs(s["bearing"] - tb)) < 25
                if s["id"] == tgt["id"] or near_tgt:
                    groups.append({"id": s["id"], "template": s["template"], "position": self._anchor(s),
                                   "heading": s["heading"], "skill": "High"})
            objectives = [{"id": "o1", "type": "destroy", "target_group": tgt["id"], "priority": "primary"},
                          {"id": "o2", "type": "survive", "target_group": "player", "priority": "secondary"}]
        else:
            route = [{"name": "CAP1", "at": {"near": near, "bearing": rng.randrange(360), "distance_nm": 40}, "alt_ft": 25000, "speed_kt": 400}]
            objectives = [{"id": "o1", "type": "survive", "target_group": "player", "priority": "primary"}]
        red_air = []
        if len(self.sites("alive")) >= 3 and rng.random() < 0.35 or task == "CAP":
            base = tgt if tgt is not None else {"bearing": rng.randrange(360), "distance_nm": 70}
            red_air = [{"task": "CAP", "aircraft": "MiG-29S", "count": 2,
                        "spawn": {"near": near, "bearing": base["bearing"], "distance_nm": min(base["distance_nm"] + 30, 150)}}]
        what = {"SEAD": "air defence site", "CAS": "armour concentration", "STRIKE": "ground force", "CAP": "airspace"}[task]
        tdesc = f"{tgt['id']} ({tgt['template']})" if tgt is not None else "the assigned CAP area"
        d = dt.date.fromisoformat(c["current_date"])
        spec = {
            "meta": {"id": f"{c['name']}_{seq:03d}".replace(" ", "_"), "title": f"{c['name']} - Sortie {seq}", "theater": c["theater"],
                     "date": d.isoformat(), "start_time": rng.choice(TIMES), "campaign_id": c["name"], "sequence": seq},
            "weather": weather,
            "player": [{"callsign": c["callsign"], "aircraft": c["aircraft"], "count": size, "task": task if task != "CAP" else "CAP",
                        "start_airbase": near, "start_type": "cold", "route": route}],
            "objectives": objectives, "red": {"groups": groups, "air": red_air},
            "blue_support": {"awacs": {"callsign": "Overlord", "freq_mhz": 251.0},
                             "tanker": {"callsign": "Texaco", "freq_mhz": 270.0, "tacan": "40X"},
                             **({"jtac": {"callsign": "Axeman", "freq_mhz": 138.0}} if task in ("CAS", "STRIKE") else {})},
            "comms": {"flight_freq_mhz": 305.0, "tower_freq_mhz": 131.0},
            "briefing": {
                "situation": f"Day {seq} of the campaign. {len(self.sites('alive'))} enemy sites remain active, {len(self.sites('destroyed'))} destroyed.",
                "mission": f"{task}: neutralise {tdesc}." if tgt is not None else "Defensive counter-air over the home area.",
                "execution": f"Cold start {near}, route via the IP, attack the {what}, egress and land at {near}.",
                "threats": ", ".join(sorted({g["template"] for g in groups})) + (", MiG-29 CAP likely" if red_air else "") if groups or red_air else "None known",
                "roe": "Weapons tight until positive identification."},
        }
        sc, errs = validate(spec)
        if sc is None:
            raise RuntimeError("deterministic planner produced an invalid scenario: " + "; ".join(errs))
        return sc

    def plan_llm(self, llm, request: str = "Plan the next campaign sortie.") -> Scenario:
        from .generate import generate_scenario
        c = self.row()
        sc, _log = generate_scenario(llm, request, c["theater"], f"{c['name']}_{c['seq'] + 1:03d}".replace(" ", "_"),
                                     c["seq"] + 1, prior_state=self.summary())
        dead = {s["id"] for s in self.sites("destroyed")}
        sc.red.groups = [g for g in sc.red.groups if g.id not in dead]               # destroyed stays destroyed
        sc.objectives = [o for o in sc.objectives if o.target_group not in dead]
        sc.meta.campaign_id = c["name"]
        sc.meta.date = c["current_date"]
        return sc

    # ---------- bookkeeping
    def register(self, sc: Scenario, miz: str = "", events_offset: int = 0) -> int:
        """Persist the mission and any new red groups the planner introduced (an LLM may invent sites)."""
        c = self.row()
        known = {s["id"] for s in self.sites()}
        for g in sc.red.groups:
            if g.id not in known:
                self.db.execute("INSERT INTO site(campaign_id,id,template,near,bearing,distance_nm,heading) VALUES(?,?,?,?,?,?,?)",
                                (self.cid, g.id, g.template, g.position.near, g.position.bearing, g.position.distance_nm, g.heading))
        cur = self.db.execute("INSERT INTO mission(campaign_id,seq,title,scenario,miz,events_offset,created) VALUES(?,?,?,?,?,?,?)",
                              (self.cid, c["seq"] + 1, sc.meta.title, sc.model_dump_json(), miz, events_offset,
                               dt.datetime.now().isoformat(timespec="seconds")))
        self.db.commit()
        return cur.lastrowid

    def ingest(self, mission_id: int, lines: list[str]) -> dict:
        """Apply the Hook's events (one JSON object per line) from one sortie. Returns the outcome dict."""
        m = self.db.execute("SELECT * FROM mission WHERE id=? AND campaign_id=?", (mission_id, self.cid)).fetchone()
        if m is None:
            raise KeyError(f"no mission {mission_id}")
        sc = Scenario.model_validate_json(m["scenario"])
        evs = []
        for ln in lines:
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if e.get("type") == "event":
                evs.append(e)
                self.db.execute("INSERT INTO event VALUES(?,?,?,?,?,?,?)", (mission_id, e.get("kind"), e.get("unit"), e.get("group"),
                                                                           e.get("utype"), e.get("coalition"), e.get("t")))
        dead: dict[str, set] = {}
        for e in evs:
            if e["kind"] == "dead" and e.get("group"):
                dead.setdefault(e["group"], set()).add(e.get("unit"))
        destroyed = []
        c = self.row()
        for g in sc.red.groups:
            n = len(dead.get(g.id, ()))
            if n:
                s = self.db.execute("SELECT * FROM site WHERE campaign_id=? AND id=?", (self.cid, g.id)).fetchone()
                total = min(s["units_dead"] + n, _units(g.template))
                gone = total >= _units(g.template)
                self.db.execute("UPDATE site SET units_dead=?, status=?, destroyed_seq=? WHERE campaign_id=? AND id=?",
                                (total, "destroyed" if gone else "alive", c["seq"] + 1 if gone else None, self.cid, g.id))
                if gone and s["status"] != "destroyed":
                    destroyed.append(g.id)
        pgroup = sc.player[0].callsign
        mine = [e for e in evs if e.get("group") == pgroup]
        took_off = any(e["kind"] == "takeoff" for e in mine)
        landed = any(e["kind"] == "land" for e in mine)
        lost = len({e.get("unit") for e in mine if e["kind"] in ("crash", "eject", "dead")})
        lost = min(lost, sc.player[0].count)
        results = {}
        for o in sc.objectives:
            if o.type == "destroy":
                results[o.id] = o.target_group in destroyed or (self.db.execute(
                    "SELECT status FROM site WHERE campaign_id=? AND id=?", (self.cid, o.target_group)).fetchone() or ["alive"])[0] == "destroyed"
            elif o.type == "survive":
                results[o.id] = landed and lost < sc.player[0].count
            else:
                results[o.id] = False
        primary_ok = all(results[o.id] for o in sc.objectives if o.priority == "primary") if sc.objectives else landed
        outcome = {"success": bool(primary_ok), "objectives": results, "destroyed": destroyed, "took_off": took_off,
                   "landed": landed, "airframes_lost": lost, "events": len(evs)}
        pool = max(0, c["pool"] - lost)
        pool = min(c["pool_max"], pool + 1)                                   # one replacement airframe per sortie
        alive = self.db.execute("SELECT COUNT(*) FROM site WHERE campaign_id=? AND status='alive'", (self.cid,)).fetchone()[0]
        status = "victory" if alive == 0 else "active"
        nxt = (dt.date.fromisoformat(c["current_date"]) + dt.timedelta(days=1)).isoformat()
        self.db.execute("UPDATE campaign SET seq=?, pool=?, current_date=?, status=? WHERE id=?", (c["seq"] + 1, pool, nxt, status, self.cid))
        self.db.execute("UPDATE mission SET status='ingested', outcome=? WHERE id=?", (json.dumps(outcome), mission_id))
        self.db.commit()
        outcome["campaign_status"] = status
        return outcome

    def reinforce(self, rng: random.Random | None = None) -> str | None:
        """Red rebuilds: when fewer than 3 sites live, a new one appears (never when the campaign is won)."""
        c = self.row()
        if c["status"] != "active" or len(self.sites("alive")) >= 3:
            return None
        rng = rng or random.Random(c["seed"] * 7 + c["seq"])
        tpl = rng.choice(SAM + GROUND)
        sid = f"{tpl.lower().replace('-', '')}_r{c['seq']}"
        self.db.execute("INSERT OR IGNORE INTO site(campaign_id,id,template,near,bearing,distance_nm,heading) VALUES(?,?,?,?,?,?,?)",
                        (self.cid, sid, tpl, c["home"], round(rng.uniform(0, 360)), round(rng.uniform(30, 90)), 0))
        self.db.commit()
        return sid

    def last_mission(self):
        return self.db.execute("SELECT * FROM mission WHERE campaign_id=? ORDER BY id DESC LIMIT 1", (self.cid,)).fetchone()


def events_path(dcs_dir: str | Path) -> Path:
    return Path(dcs_dir) / "skibodcs" / "events.jsonl"


def build_sortie(camp: Campaign, out_dir: str | Path, dcs_dir: str | Path | None = None, llm=None) -> dict:
    """Plan -> compile .miz -> kneeboards -> (deploy) -> register. Returns paths + the mission id.
    The events file offset is stored so `ingest` reads only this sortie's events."""
    from .compile import compile_scenario
    from .kneeboard import make_kneeboards
    c = camp.row()
    if c["status"] != "active":
        raise RuntimeError(f"campaign is {c['status']}")
    camp.reinforce()
    sc = camp.plan_llm(llm) if llm else camp.plan_deterministic()
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    miz = out / f"{sc.meta.id}.miz"
    warnings = compile_scenario(sc, miz)
    pages = make_kneeboards(sc, out / "kneeboard" / sc.meta.id)
    res: dict = {"title": sc.meta.title, "miz": str(miz), "kneeboards": {k: [str(p) for p in v] for k, v in pages.items()},
                 "warnings": warnings, "task": sc.player[0].task}
    offset = 0
    if dcs_dir:
        from . import deploy as dp
        res["deployed"] = [str(p) for p in dp.deploy_mission(Path(dcs_dir), miz, pages)]
        ep = events_path(dcs_dir)
        offset = ep.stat().st_size if ep.exists() else 0
        res["deployed_miz"] = str(Path(dcs_dir) / "Missions" / "skibodcs" / miz.name)
    res["mission_id"] = camp.register(sc, str(miz), offset)
    return res


def ingest_latest(camp: Campaign, dcs_dir: str | Path) -> dict:
    m = camp.last_mission()
    if m is None or m["status"] == "ingested":
        raise RuntimeError("no un-ingested mission")
    ep = events_path(dcs_dir)
    lines = []
    if ep.exists():
        with open(ep, "rb") as f:
            f.seek(m["events_offset"])
            lines = f.read().decode("utf-8", "replace").splitlines()
    return camp.ingest(m["id"], lines)
