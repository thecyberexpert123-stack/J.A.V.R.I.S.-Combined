"""OpenAI-compatible remote provider (opt-in, user-supplied key — ADR-0003).

Works with any chat-completions endpoint speaking the OpenAI wire format
(OpenAI, OpenRouter, vLLM, LM Studio, ...). The key is read from the
environment only — never from project files, never logged.
"""

from __future__ import annotations

import os

from jarvis.providers.base import ProviderError, post_json

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
KEY_ENV = "JARVIS_OPENAI_API_KEY"


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._base = (
            base_url or os.environ.get("JARVIS_OPENAI_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.environ.get("JARVIS_OPENAI_MODEL") or DEFAULT_MODEL
        self._key = api_key if api_key is not None else os.environ.get(KEY_ENV, "")

    def available(self) -> bool:
        return bool(self._key.strip())

    def complete(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float = 90.0,
        schema: dict[str, object] | None = None,
    ) -> str:
        if not self._key.strip():
            raise ProviderError(
                f"remote provider selected but {KEY_ENV} is not set; "
                "export the key or disable remote planning (JARVIS_REMOTE_LLM=0)",
                kind="key-missing",
            )
        if schema is not None:
            response_format: dict[str, object] = {
                "type": "json_schema",
                "json_schema": {"name": "jarvis_plan", "strict": True, "schema": schema},
            }
        else:
            response_format = {"type": "json_object"}
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": response_format,
        }
        data = post_json(
            f"{self._base}/chat/completions",
            payload,
            timeout_s=timeout_s,
            headers={"Authorization": f"Bearer {self._key}"},
        )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("openai-compatible response has no choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderError("openai-compatible response choice is malformed")
        message = first.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderError("openai-compatible response is missing message.content")
        return str(message["content"])
