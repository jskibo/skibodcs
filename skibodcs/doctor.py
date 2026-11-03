"""`skibodcs doctor`: one command that says which half of the DCS link is up, so a failure needs no guessing."""
from __future__ import annotations
import socket
from pathlib import Path


def _tcp_open(port: int, host: str = "127.0.0.1", timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def diagnose(dcs_dir: Path | None, lines: int = 12, export_port: int = 14500, hook_port: int = 14510) -> str:
    out = []
    ex, hk = _tcp_open(export_port), _tcp_open(hook_port)
    out.append(f"Export link (cockpit clicks, telemetry)  TCP {export_port}: {'UP' if ex else 'DOWN'}")
    out.append(f"Hook link   (wingman, missions)          TCP {hook_port}: {'UP' if hk else 'DOWN'}")
    if not ex:
        out.append("  Export DOWN: DCS is not in a mission, or Scripts\\skibodcs_export.lua did not load. Look for 'skibodcs export:' lines below.")
    if not hk:
        out.append("  Hook DOWN: DCS is not running a mission yet (the Hook opens its port when a mission starts).")
    if dcs_dir is None:
        out.append("No Saved Games\\DCS folder found; pass --dcs-dir to read dcs.log.")
        return "\n".join(out)
    beacon = Path(dcs_dir) / "skibodcs" / "export_loaded.txt"
    if beacon.exists():
        tail = beacon.read_text(encoding="utf-8", errors="replace").splitlines()[-4:]
        out.append("Export module beacon (skibodcs/export_loaded.txt), newest last: " + " | ".join(tail))
    else:
        out.append("Export module beacon: NONE - Export.lua never ran skibodcs_export.lua (check Scripts\\Export.lua for an error or an early return above our block).")
    log = Path(dcs_dir) / "Logs" / "dcs.log"
    if not log.exists():
        out.append(f"No log yet: {log}")
        return "\n".join(out)
    hits = [ln.rstrip() for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if "skibodcs" in ln.lower()]
    out.append(f"--- last {min(lines, len(hits))} skibodcs lines in {log.name} ---")
    out += hits[-lines:] or ["(none: the hook and export module never loaded; run `skibodcs install`)"]
    return "\n".join(out)
