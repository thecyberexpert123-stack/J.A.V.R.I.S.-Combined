"""Vision fallback: describe a screenshot via a local Ollama vision model.

Abstains loudly when no model is reachable — a missing vision backend never
produces a fabricated description (owner requirement: no hallucination).
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from collections.abc import Mapping
from pathlib import Path

DEFAULT_MODEL = "llava"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

MAX_IMAGE_BYTES = 20 * 1024 * 1024


class VisionUnavailable(RuntimeError):
    """Ollama (or the vision model) is not reachable — honest abstention."""


def _base_url(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else dict(os.environ)
    return source.get("JARVIS_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")


def vision_model(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else dict(os.environ)
    return source.get("JARVIS_VISION_MODEL", DEFAULT_MODEL)


def describe_image(
    image_path: Path,
    question: str = "Describe what is on this screen concisely.",
    *,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 120.0,
) -> str:
    """Send a screenshot to the local Ollama vision model and return its text."""
    data = image_path.read_bytes()
    if not data:
        raise VisionUnavailable(f"screenshot {image_path} is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise VisionUnavailable(f"screenshot {image_path} exceeds {MAX_IMAGE_BYTES} bytes")

    payload = json.dumps(
        {
            "model": vision_model(env),
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": question,
                    "images": [base64.b64encode(data).decode("ascii")],
                }
            ],
        }
    ).encode("utf-8")
    url = f"{_base_url(env)}/api/chat"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise VisionUnavailable(
            f"no reachable Ollama vision model at {url} ({exc.__class__.__name__})"
        ) from exc
    message = body.get("message") if isinstance(body, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise VisionUnavailable("vision model returned no description")
    return content.strip()
