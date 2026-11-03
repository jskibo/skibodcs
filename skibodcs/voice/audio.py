"""Audio interfaces. Real backends import their libs lazily so the rest of the
app (and the tests) work on machines without audio/ML packages.
NOTE: real backends below are UNTESTED in the build sandbox."""
from __future__ import annotations
import io
import wave
from typing import Protocol


class STT(Protocol):
    def transcribe(self, wav: bytes) -> str: ...


class TTS(Protocol):
    def synthesize(self, text: str) -> bytes: ...          # returns WAV bytes


class FasterWhisperSTT:
    """CPU int8 by default: small, no VRAM contention with DCS. Use device='cuda' to move it."""
    def __init__(self, model: str = "small.en", device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import WhisperModel
        self.m = WhisperModel(model, device=device, compute_type=compute_type)

    def transcribe(self, wav: bytes) -> str:
        segs, _ = self.m.transcribe(io.BytesIO(wav), language="en", beam_size=1,
                                    vad_filter=True)
        return " ".join(s.text for s in segs).strip()


class PiperTTS:
    """Runs Piper as `python -m piper -m MODEL -f out.wav` (the pip package `piper-tts`; works inside the venv with no PATH setup).
    `-m` / `-f` are accepted by both the current Python CLI and the old C++ binary, unlike --output_file vs --output-file.
    Pass piper_exe to use a standalone piper.exe instead."""
    def __init__(self, model_path: str, piper_exe: str | None = None):
        self.model, self.exe = model_path, piper_exe

    def command(self, out_path: str) -> list[str]:
        import sys
        base = [self.exe] if self.exe else [sys.executable, "-m", "piper"]
        return base + ["-m", self.model, "-f", out_path]

    def synthesize(self, text: str) -> bytes:
        import os, subprocess, tempfile
        fd, out = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        try:
            r = subprocess.run(self.command(out), input=text.encode(), capture_output=True)
            if r.returncode != 0:
                raise RuntimeError("piper failed: " + r.stderr.decode(errors="replace")[-300:])
            with open(out, "rb") as f:
                return f.read()
        finally:
            os.unlink(out)


def _http_error(e: Exception) -> str:
    import json, urllib.error
    if isinstance(e, urllib.error.HTTPError):
        try:
            return f"HTTP {e.code}: {json.loads(e.read()).get('error', '')}"
        except Exception:                                            # noqa: BLE001
            return f"HTTP {e.code}"
    return str(e)


class RemoteSTT:
    """Whisper running on another machine (see voice/server.py). Raises RuntimeError with the reason on failure."""
    def __init__(self, url: str, timeout: float = 15.0):
        self.url, self.timeout = url.rstrip("/"), timeout

    def transcribe(self, wav: bytes) -> str:
        import json, urllib.request
        req = urllib.request.Request(self.url + "/stt", data=wav, headers={"Content-Type": "audio/wav"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return str(json.loads(r.read()).get("text", "")).strip()
        except Exception as e:                                       # noqa: BLE001
            raise RuntimeError(f"speech server STT failed: {_http_error(e)}") from e


class RemoteTTS:
    def __init__(self, url: str, timeout: float = 15.0):
        self.url, self.timeout = url.rstrip("/"), timeout

    def synthesize(self, text: str) -> bytes:
        import json, urllib.request
        req = urllib.request.Request(self.url + "/tts", data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except Exception as e:                                       # noqa: BLE001
            raise RuntimeError(f"speech server TTS failed: {_http_error(e)}") from e


def radio_fx(wav: bytes, lo: float = 300.0, hi: float = 3400.0, drive: float = 1.8) -> bytes:
    """Band-limit to the radio passband and add mild clipping. Pure numpy."""
    import numpy as np
    with wave.open(io.BytesIO(wav)) as w:
        n, sr, ch = w.getnframes(), w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / sr)
    X[(f < lo) | (f > hi)] = 0
    y = np.tanh(np.fft.irfft(X, len(x)) * drive)
    y = y / max(1e-6, float(np.abs(y).max())) * 0.9
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr)
        o.writeframes((y * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def play_wav(wav: bytes):
    import sounddevice as sd, soundfile as sf
    data, sr = sf.read(io.BytesIO(wav))
    sd.play(data, sr); sd.wait()


class PTTRecorder:
    """Records while a joystick button (or key) is held. Needs sounddevice + pygame."""
    def __init__(self, joystick_index: int = 0, button: int = 0, samplerate: int = 16000):
        import pygame
        pygame.init(); pygame.joystick.init()
        self.js = pygame.joystick.Joystick(joystick_index); self.js.init()
        self.button, self.sr, self.pg = button, samplerate, pygame

    def _held(self) -> bool:
        self.pg.event.pump()
        return bool(self.js.get_button(self.button))

    def record_while_held(self) -> bytes | None:
        import time, numpy as np, sounddevice as sd
        while not self._held():
            time.sleep(0.01)
        chunks = []
        with sd.InputStream(samplerate=self.sr, channels=1, dtype="int16",
                            callback=lambda d, f, t, s: chunks.append(d.copy())):
            while self._held():
                time.sleep(0.01)
        if not chunks:
            return None
        pcm = np.concatenate(chunks).tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as o:
            o.setnchannels(1); o.setsampwidth(2); o.setframerate(self.sr); o.writeframes(pcm)
        return buf.getvalue()
