"""Optional speech server for the Mac Studio: Whisper + Piper behind two HTTP endpoints, so the sim PC spends no CPU on speech.
  python -m skibodcs.voice.server --port 8765 --stt-model small.en --tts-model /path/en_US-lessac-medium.onnx
POST /stt  body = WAV bytes            -> {"text": "..."}
POST /tts  body = {"text": "..."}      -> WAV bytes
GET  /health                           -> {"ok": true}
LAN only, no authentication: bind to the LAN address, never expose it to the internet.
UNVERIFIED: the real Whisper/Piper backends never ran in the build sandbox (tests use fakes)."""
from __future__ import annotations
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_server(stt, tts, host: str = "0.0.0.0", port: int = 8765) -> ThreadingHTTPServer:
    lock = threading.Lock()                        # one model call at a time; Whisper/Piper are not guaranteed thread-safe

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            self._json(200, {"ok": True}) if self.path == "/health" else self._json(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            try:
                if self.path == "/stt":
                    with lock:
                        self._json(200, {"text": stt.transcribe(body)})
                elif self.path == "/tts":
                    text = str(json.loads(body or b"{}").get("text", "")).strip()
                    if not text:
                        self._json(400, {"error": "empty text"}); return
                    with lock:
                        self._send(200, tts.synthesize(text), "audio/wav")
                else:
                    self._json(404, {"error": "not found"})
            except Exception as e:                  # noqa: BLE001 - report to the client, keep serving
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), H)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0"); ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--stt-model", default="small.en"); ap.add_argument("--stt-device", default="cpu")
    ap.add_argument("--stt-compute", default="int8"); ap.add_argument("--tts-model", required=True)
    a = ap.parse_args(argv)
    from .audio import FasterWhisperSTT, PiperTTS
    srv = make_server(FasterWhisperSTT(a.stt_model, a.stt_device, a.stt_compute), PiperTTS(a.tts_model), a.host, a.port)
    print(f"speech server on {a.host}:{a.port}")
    srv.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
