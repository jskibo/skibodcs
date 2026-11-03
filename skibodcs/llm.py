"""Minimal LLM client layer. Stdlib only. Ollama's /api/chat accepts a JSON
schema in `format`, which constrains decoding to that schema."""
from __future__ import annotations
import json
import urllib.request
from typing import Protocol


class LLM(Protocol):
    def chat(self, messages: list[dict], schema: dict | None = None) -> str: ...


class OllamaClient:
    def __init__(self, model: str, host: str = "http://localhost:11434",
                 temperature: float = 0.2, timeout: float = 120.0, num_ctx: int = 8192,
                 think: bool = False, keep_alive: str = "30m"):
        self.model, self.host = model, host.rstrip("/")
        self.temperature, self.timeout, self.num_ctx = temperature, timeout, num_ctx
        self.think, self.keep_alive = think, keep_alive

    def chat(self, messages: list[dict], schema: dict | None = None) -> str:
        # think=False: reasoning models (qwen3, gpt-oss) must not spend seconds "thinking" before a one-line intent;
        # keep_alive keeps the model loaded between radio calls.
        body = {"model": self.model, "messages": messages, "stream": False, "think": self.think, "keep_alive": self.keep_alive,
                "options": {"temperature": self.temperature, "num_ctx": self.num_ctx}}
        if schema is not None:
            body["format"] = schema
        req = urllib.request.Request(f"{self.host}/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["message"]["content"]
