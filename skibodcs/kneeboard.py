"""Scenario -> kneeboard PNG pages (Pillow only, no map tiles). One set per player aircraft type; deploy.py copies them
to Saved Games\\DCS\\Kneeboard\\<aircraft>\\ so the pages are in the cockpit when the mission starts.
Pages: 1 mission + comms card, 2 route, 3 briefing, 4 threats, 5 map, 6 data card (the printed equivalent of a DTC load -
steerpoints and radio presets as numbers to enter; real DTC files are module-specific and are NOT generated).
Lat/long needs pyproj (installed with pydcs); everything else is plain geometry."""
from __future__ import annotations
import math
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import catalog
from .schema import Scenario

W, H = 768, 1024
BG, INK, DIM, ACC, RED, BLUE = (246, 242, 230), (20, 20, 20), (95, 95, 90), (30, 60, 110), (170, 30, 30), (30, 80, 160)
NM = 1852.0
# Approximate engagement radii (nm) by template; for planning only, real ranges depend on target and altitude.
THREAT_NM = {"SA-2": 27, "SA-6": 13, "SA-8": 8, "SA-10": 40, "SA-11": 17, "SA-13": 3, "SA-15": 7, "ZSU-23": 1.4}


def _f(size: int) -> ImageFont.ImageFont:
    return ImageFont.load_default(size)


def _page(title: str, sc: Scenario) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 70], fill=ACC)
    d.text((24, 16), title, font=_f(38), fill=(255, 255, 255))
    d.text((W - 24, 28), f"{sc.meta.title} - {sc.meta.date} {sc.meta.start_time}Z", font=_f(18), fill=(220, 230, 245), anchor="rm")
    return im, d


def _rows(d, y: int, rows: list[tuple], cols: list[int], size: int = 24, gap: int = 12, head: bool = True) -> int:
    for i, r in enumerate(rows):
        font = _f(size)
        for x, cell in zip(cols, r):
            d.text((x, y), str(cell), font=font, fill=ACC if (head and i == 0) else INK)
        y += size + gap
        if head and i == 0:
            d.line([20, y - gap // 2, W - 20, y - gap // 2], fill=DIM, width=1)
    return y


def _wrap(d, y: int, text: str, size: int = 24, width: int = 52, x: int = 28) -> int:
    for line in textwrap.wrap(text, width) or [""]:
        d.text((x, y), line, font=_f(size), fill=INK)
        y += size + 8
    return y


def dm(lat: float, lon: float) -> str:
    def p(v, pos, neg, w):
        h = pos if v >= 0 else neg; v = abs(v); dg = int(v)
        return f"{h}{dg:0{w}d} {(v - dg) * 60:06.3f}"
    return f"{p(lat, 'N', 'S', 2)}  {p(lon, 'E', 'W', 3)}"


def _latlon(th: str, pt) -> str:
    try:
        ll = pt.latlng()
        return dm(ll.lat, ll.lng)
    except Exception:                                                 # noqa: BLE001 - no pyproj / odd terrain: omit, never crash
        return "-"


def _ref(sc: Scenario, a) -> str:
    return f"{a.near} {int(round(a.bearing)) % 360 or 360:03d}/{a.distance_nm:.0f}" if a.distance_nm else a.near


def _mission_page(sc: Scenario, f) -> Image.Image:
    im, d = _page("MISSION", sc)
    y = 100
    y = _rows(d, y, [("Callsign", f"{f.callsign}  x{f.count}"), ("Aircraft", f.aircraft), ("Task", f.task),
                     ("Start", f"{f.start_airbase} ({f.start_type})"), ("Theater", sc.meta.theater)], [28, 220], 28, 14, head=False)
    w = sc.weather
    y += 14
    d.text((28, y), "WEATHER", font=_f(24), fill=ACC); y += 38
    y = _rows(d, y, [("Wind", f"{int(w.wind_from_deg):03d} @ {int(w.wind_kt)} kt"), ("Clouds", w.clouds),
                     ("Visibility", f"{w.vis_km:.0f} km"), ("QNH", f"{w.qnh_mmhg:.0f} mmHg / {w.qnh_mmhg * 0.03937:.2f} inHg")],
               [28, 220], 26, 12, head=False)
    y += 14
    d.text((28, y), "COMMS", font=_f(24), fill=ACC); y += 38
    rows = [("Role", "Callsign", "Freq", "TACAN"), ("Flight", f.callsign, f"{sc.comms.flight_freq_mhz:.3f}", "")]
    if sc.comms.tower_freq_mhz:
        rows.append(("Tower", f.start_airbase, f"{sc.comms.tower_freq_mhz:.3f}", ""))
    for role, a in (("AWACS", sc.blue_support.awacs), ("Tanker", sc.blue_support.tanker), ("JTAC", sc.blue_support.jtac)):
        if a:
            rows.append((role, a.callsign, f"{a.freq_mhz:.3f}", a.tacan or ""))
    _rows(d, y, rows, [28, 170, 400, 600], 26, 14)
    return im


def _points(sc: Scenario, f):
    th = sc.meta.theater
    ab = catalog.find_airbase(th, f.start_airbase)
    pts = [("START", ab.position, f.start_airbase, 0, 0)]
    for w in f.route:
        pts.append((w.name, catalog.resolve_anchor(th, w.at), _ref(sc, w.at), w.alt_ft, w.speed_kt))
    return pts


def _route_page(sc: Scenario, f) -> Image.Image:
    im, d = _page("ROUTE", sc)
    pts = _points(sc, f)
    rows = [("#", "Name", "Reference", "Alt", "KTAS", "Leg")]
    for i, (name, pt, ref, alt, spd) in enumerate(pts):
        leg = ""
        if i:
            p0 = pts[i - 1][1]
            dx, dy = pt.x - p0.x, pt.y - p0.y
            brg = (math.degrees(math.atan2(dy, dx)) + 360) % 360
            leg = f"{brg:03.0f}/{math.hypot(dx, dy) / NM:.0f}"
        rows.append((i, name, ref, f"{int(alt):,}" if alt else "", int(spd) or "", leg))
    _rows(d, 100, rows, [24, 70, 190, 450, 560, 640], 22, 16)
    d.text((24, H - 40), "Leg = true bearing / nm from previous point", font=_f(18), fill=DIM)
    return im


def _brief_page(sc: Scenario) -> Image.Image:
    im, d = _page("BRIEFING", sc)
    y = 100
    for h, t in (("SITUATION", sc.briefing.situation), ("MISSION", sc.briefing.mission), ("EXECUTION", sc.briefing.execution),
                 ("THREATS", sc.briefing.threats), ("ROE", sc.briefing.roe)):
        if t:
            d.text((28, y), h, font=_f(24), fill=ACC); y += 34
            y = _wrap(d, y, t, 24, 48) + 14
    if y == 100:
        d.text((28, y), "(no briefing text)", font=_f(24), fill=DIM)
    if sc.objectives:
        d.text((28, max(y, 100) + 10), "OBJECTIVES", font=_f(24), fill=ACC)
        y = max(y, 100) + 48
        for o in sc.objectives:
            y = _wrap(d, y, f"[{o.priority}] {o.type} {o.target_group or ''}".strip(), 24, 48)
    return im


def _threat_page(sc: Scenario) -> Image.Image:
    im, d = _page("THREATS", sc)
    rows = [("Group", "Type", "Location", "Range")]
    for g in sc.red.groups:
        r = THREAT_NM.get(g.template)
        rows.append((g.id[:16], g.template, _ref(sc, g.position), f"~{r:g} nm" if r else ""))
    for a in sc.red.air:
        rows.append(("CAP", f"{a.aircraft} x{a.count}", _ref(sc, a.spawn), ""))
    y = _rows(d, 100, rows, [24, 220, 380, 640], 22, 16)
    d.text((24, y + 10), "Ranges are rough planning figures, not exact for your altitude.", font=_f(18), fill=DIM)
    return im


def _map_page(sc: Scenario, f) -> Image.Image:
    im, d = _page("MAP (north up)", sc)
    th = sc.meta.theater
    route = _points(sc, f)
    red = [(g, catalog.resolve_anchor(th, g.position)) for g in sc.red.groups]
    pts = [p[1] for p in route] + [p for _, p in red]
    xs, ys = [p.x for p in pts], [p.y for p in pts]            # x = north, y = east (metres)
    pad = 15 * NM
    n0, n1, e0, e1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    span = max(n1 - n0, e1 - e0, 40 * NM)
    cn, ce = (n0 + n1) / 2, (e0 + e1) / 2
    box = (24, 96, W - 24, H - 60)
    side = min(box[2] - box[0], box[3] - box[1])
    ox, oy = box[0] + (box[2] - box[0] - side) / 2, box[1]
    k = side / span

    def px(p):
        return (ox + side / 2 + (p.y - ce) * k, oy + side / 2 - (p.x - cn) * k)

    d.rectangle([ox, oy, ox + side, oy + side], outline=DIM, width=2)
    step = 10 if span / NM <= 120 else 20 if span / NM <= 300 else 50
    for i in range(1, int(span / NM / step) + 2):
        o = i * step * NM * k
        for xx in (ox + side / 2 + o, ox + side / 2 - o):
            if ox < xx < ox + side: d.line([xx, oy, xx, oy + side], fill=(220, 215, 200))
        for yy in (oy + side / 2 + o, oy + side / 2 - o):
            if oy < yy < oy + side: d.line([ox, yy, ox + side, yy], fill=(220, 215, 200))
    for name, ap in catalog.terrain(th).airports.items():       # airbases inside the frame
        x, y = px(ap.position)
        if ox < x < ox + side and oy < y < oy + side:
            d.ellipse([x - 4, y - 4, x + 4, y + 4], outline=INK, width=2)
            d.text((x + 7, y - 8), name, font=_f(16), fill=DIM)
    for g, p in red:
        x, y = px(p)
        r = THREAT_NM.get(g.template, 0) * NM * k
        if r > 2:
            d.ellipse([x - r, y - r, x + r, y + r], outline=RED, width=2)
        d.polygon([(x, y - 9), (x + 9, y + 7), (x - 9, y + 7)], fill=RED)
        d.text((x + 11, y - 9), f"{g.id[:10]} {g.template}", font=_f(16), fill=RED)
    prev = None
    for i, (name, p, *_rest) in enumerate(route):
        x, y = px(p)
        if prev:
            d.line([prev, (x, y)], fill=BLUE, width=3)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=BLUE)
        d.text((x + 10, y + 4), f"{i} {name}", font=_f(18), fill=BLUE)
        prev = (x, y)
    ns = ox + side - 40
    d.line([ns, oy + 50, ns, oy + 14], fill=INK, width=3); d.text((ns - 6, oy - 2), "N", font=_f(18), fill=INK)
    bar = step * NM * k
    d.line([ox + 10, oy + side - 14, ox + 10 + bar, oy + side - 14], fill=INK, width=4)
    d.text((ox + 14 + bar, oy + side - 26), f"{step} nm", font=_f(16), fill=INK)
    return im


def _data_card(sc: Scenario, f) -> Image.Image:
    im, d = _page("DATA CARD", sc)
    th = sc.meta.theater
    rows = [("STPT", "Name", "Lat / Long", "Alt")]
    for i, (name, pt, _ref_, alt, _s) in enumerate(_points(sc, f)[1:], 1):
        rows.append((i, name, _latlon(th, pt), f"{int(alt):,}"))
    y = _rows(d, 100, rows, [24, 90, 230, 650], 22, 16)
    y += 20
    d.text((24, y), "RADIO PRESETS", font=_f(24), fill=ACC); y += 38
    pre = [("Pre", "Use", "Freq")]
    n = 1
    for label, fr in (("Flight", sc.comms.flight_freq_mhz), ("Tower", sc.comms.tower_freq_mhz),
                      ("AWACS", sc.blue_support.awacs.freq_mhz if sc.blue_support.awacs else None),
                      ("Tanker", sc.blue_support.tanker.freq_mhz if sc.blue_support.tanker else None),
                      ("JTAC", sc.blue_support.jtac.freq_mhz if sc.blue_support.jtac else None)):
        if fr:
            pre.append((n, label, f"{fr:.3f}")); n += 1
    y = _rows(d, y, pre, [24, 110, 330], 24, 14)
    if sc.blue_support.tanker and sc.blue_support.tanker.tacan:
        d.text((24, y + 16), f"Tanker TACAN {sc.blue_support.tanker.tacan}", font=_f(24), fill=INK)
    return im


def make_kneeboards(sc: Scenario, outdir: str | Path) -> dict[str, list[Path]]:
    """Returns {aircraft_type: [png paths]} - exactly what deploy.deploy_mission(kneeboards=...) takes."""
    out: dict[str, list[Path]] = {}
    base = Path(outdir)
    for f in sc.player:
        folder = base / f.aircraft
        folder.mkdir(parents=True, exist_ok=True)
        pages = [("mission", _mission_page(sc, f)), ("route", _route_page(sc, f)), ("briefing", _brief_page(sc)),
                 ("threats", _threat_page(sc)), ("map", _map_page(sc, f)), ("datacard", _data_card(sc, f))]
        paths = []
        for n, im in pages:
            p = folder / f"{n}.png"
            im.save(p)
            paths.append(p)
        out.setdefault(f.aircraft, []).extend(paths)
    return out
