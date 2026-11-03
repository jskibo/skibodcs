"""One entry point: `python -m skibodcs.voice.app`.
  --text    type what you'd say (no audio needed; good for testing anywhere)
  default   joystick PTT -> Whisper -> Router -> Piper -> headset"""
from __future__ import annotations
import argparse
import tomllib
from pathlib import Path

from ..llm import OllamaClient
from .cockpit import load_table
from .link import DCSLink, HookClient, HookStatus
from .router import Router
from .state import World


GEAR_ALIASES = {"gear": ["landing gear", "wheels", "undercarriage"], "hook": ["tailhook", "arresting hook"],
                "master_arm": ["master arm", "weapons arm"]}


def build(cfg: dict):
    world = World(magvar_east=cfg.get("magvar_east", 0.0))
    if "theater" in cfg:
        from .theater import load_theater
        load_theater(world, cfg["theater"], cfg.get("wind_from"))
    table = load_table(cfg["airframe_table"])
    llm = OllamaClient(cfg["ollama"]["model"], cfg["ollama"]["host"]) if "ollama" in cfg else None
    index = None
    if cfg.get("controls_file") and Path(cfg["controls_file"]).exists():
        from .. import controls as cl
        _, cs = cl.load(cfg["controls_file"])
        index = cl.ControlIndex(cs)
        index.merge_curated(table, GEAR_ALIASES)
    router = Router(llm, table, world, cfg.get("callsign", "Viper 1-1"), cfg.get("awacs", "Magic"),
                    cfg.get("wingman", "Viper 1-2"), index=index)
    return world, router


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="skibodcs.toml")
    ap.add_argument("--text", action="store_true")
    a = ap.parse_args(argv)
    cfg = tomllib.loads(Path(a.config).read_text())
    world, router = build(cfg)
    link = DCSLink(world, cfg.get("telemetry_port", 14501), cfg.get("command_port", 14500))
    link.start()
    hook = HookClient(port=cfg.get("hook_command_port", 14510))
    HookStatus(world, cfg.get("hook_status_port", 14511)).start()

    def apply_cockpit(r, say) -> None:
        """Send clicks; read the cockpit argument before/after so we never claim a switch moved when it did not."""
        if not r.cockpit:
            return
        before = {a: link.read_arg(a) for a, _ in r.checks}
        if not link.send_all(r.cockpit):
            say("DCS not reachable: cockpit commands not sent."); return
        if r.checks:
            import time as _t; _t.sleep(0.5)
            for a, name in r.checks:
                after = link.read_arg(a)
                if before.get(a) is not None and after is not None and abs(after - before[a]) < 1e-3:
                    say(f"{name} unchanged.")

    seq_runner: dict = {"cur": None}

    def run_sequence(name: str, say) -> None:
        import threading
        from ..sequence import SequenceRunner, load_sequences
        f = cfg.get("sequence_file")
        seqs = load_sequences(f) if f and Path(f).exists() else {}
        steps = seqs.get(name)
        if not steps:
            say(f"No {name.replace('_', ' ')} sequence available for this aircraft yet."); return
        runner = SequenceRunner(lambda d, c, v: link.send(d, c, v), say)
        seq_runner["cur"] = runner
        threading.Thread(target=lambda: runner.run(steps), daemon=True).start()

    def run_wingman(r) -> list[str]:
        """Send each wingman command; speak only what the sim confirmed."""
        from . import brevity as bv
        out = []
        wcs = bv.callsign_speech(cfg.get("wingman", "Viper 1-2"))
        for cmd in r.wingman:
            ok, detail = hook.request(cmd)
            out.append(f"{wcs}, {detail}." if ok else f"{wcs}, unable, {detail}.")
        return out

    if a.text:
        print("type what you'd say; blank line quits")
        while (line := input("> ").strip()):
            r = router.handle(line)
            print(f"[{r.source}]", *r.speech, *(f"(note: {n})" for n in r.notes))
            apply_cockpit(r, lambda m: print("  ", m))
            for line in run_wingman(r):
                print("  wingman:", line)
            for name in r.sequence:
                run_sequence(name, lambda m: print("  sequence:", m))
            if r.abort_sequence and seq_runner["cur"]:
                seq_runner["cur"].abort()
        return 0

    from .audio import FasterWhisperSTT, PiperTTS, PTTRecorder, play_wav, radio_fx
    stt = FasterWhisperSTT(**cfg.get("stt", {}))
    tts = PiperTTS(cfg["tts"]["model"])
    ptt = PTTRecorder(**cfg.get("ptt", {}))
    while True:
        wav = ptt.record_while_held()
        if not wav:
            continue
        r = router.handle(stt.transcribe(wav))
        spoken: list[str] = []
        apply_cockpit(r, spoken.append)
        for name in r.sequence:
            run_sequence(name, spoken.append)
        if r.abort_sequence and seq_runner["cur"]:
            seq_runner["cur"].abort()
        for line in r.speech + run_wingman(r) + spoken:
            play_wav(radio_fx(tts.synthesize(line)))


if __name__ == "__main__":
    raise SystemExit(main())
