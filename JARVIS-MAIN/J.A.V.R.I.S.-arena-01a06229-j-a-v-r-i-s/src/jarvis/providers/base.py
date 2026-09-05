"""LLM provider abstraction (ADR-0003, ADR-0007).

A deliberately thin interface over stdlib ``urllib`` — no provider SDKs. The
router (providers.router) picks local-first; sensitive execution is never
decided here: providers only *propose*, the safety kernel *disposes*.
"""

from __future__ import annotations

import contextlib
import json as _json
import urllib.error
import urllib.request
from enum import Enum
from typing import Protocol


class FailureKind(str, Enum):
    """Why a provider call failed (ADR-0014 D2) — disclosure, not policy."""

    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http"
    MALFORMED = "malformed"
    KEY_MISSING = "key-missing"
    BREAKER_OPEN = "breaker-open"


class ProviderError(RuntimeError):
    """A provider request failed (unreachable, HTTP error, malformed envelope)."""

    def __init__(self, message: str, *, kind: FailureKind | str = FailureKind.MALFORMED) -> None:
        super().__init__(message)
        self.kind = FailureKind(kind)


class Provider(Protocol):
    """Minimal contract every backend implements."""

    name: str
    model: str

    def available(self) -> bool:
        """Cheap check whether this backend is configured/reachable."""
        ...

    def complete(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float = 90.0,
        schema: dict[str, object] | None = None,
    ) -> str:
        """One-shot chat completion returning the assistant text.

        *schema* (ADR-0014 D4) is a JSON-Schema document the backend should
        constrain its output to when it can; callers validate the output
        regardless — schema-constrained output is still untrusted input.
        """
        ...


def post_json(
    url: str,
    payload: dict[str, object],
    *,
    timeout_s: float,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    """POST a JSON document and parse the JSON response (raises ProviderError)."""
    data = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        raise ProviderError(
            f"request to {url} timed out after {timeout_s:.0f}s", kind="timeout"
        ) from exc
    except urllib.error.HTTPError as exc:
        detail = ""
        with contextlib.suppress(Exception):
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise ProviderError(f"HTTP {exc.code} from {url}: {detail}", kind="http") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach {url}: {exc.reason}", kind="unreachable") from exc
    try:
        parsed = _json.loads(body)
    except _json.JSONDecodeError as exc:
        raise ProviderError(f"non-JSON response from {url}") from exc
    if not isinstance(parsed, dict):
        raise ProviderError(f"unexpected response shape from {url}")
    return parsed


def endpoint_up(url: str, *, timeout_s: float) -> bool:
    """True if a GET to *url* returns within the timeout (any HTTP response)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            resp.read()
            return True
    except Exception:
        return False
