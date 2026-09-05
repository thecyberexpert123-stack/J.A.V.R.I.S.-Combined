"""Local Ollama provider (default planning backend, ADR-0003 local-first).

Talks to the Ollama HTTP API directly (no SDK). JSON output mode is requested
(``format: "json"``) and temperature pinned to 0 for reproducible planning.
"""

from __future__ import annotations

import os

from jarvis.providers.base import ProviderError, endpoint_up, post_json

DEFAULT_HOST = "127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2"


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str | None = None, model: str | None = None) -> None:
        raw = host if host is not None else os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
        if "://" not in raw:
            raw = f"http://{raw}"
        self._base = raw.rstrip("/")
        self.model = model or os.environ.get("JARVIS_LOCAL_MODEL") or DEFAULT_MODEL

    def available(self) -> bool:
        return endpoint_up(f"{self._base}/api/tags", timeout_s=1.0)

    def complete(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float = 90.0,
        schema: dict[str, object] | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # ADR-0014 D4: constrain generation with a real JSON Schema when
            # one is supplied; free JSON mode remains the fallback shape.
            "format": schema if schema is not None else "json",
            "options": {"temperature": 0},
        }
        data = post_json(f"{self._base}/api/chat", payload, timeout_s=timeout_s)
        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderError("ollama response is missing message.content")
        return str(message["content"])
