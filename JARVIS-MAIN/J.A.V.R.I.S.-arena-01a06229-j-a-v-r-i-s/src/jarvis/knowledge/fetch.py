"""Opt-in online verification of KB citations (ADR-0009).

Two transports, both allowlisted:
- torvalds/linux kernel-doc refs are verified through the GitHub Contents API
  (works where raw hosts are blocked);
- generic URLs must match an explicit prefix allowlist or the request is
  refused before it is made.

Enabled only with JARVIS_ONLINE_DOCS=1. Results are cached in the state dir.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.client import HTTPMessage
from pathlib import Path
from typing import IO

from jarvis.journal.sqlite import state_dir

ONLINE_ENV = "JARVIS_ONLINE_DOCS"

_GITHUB_API = "https://api.github.com/repos/{repo}/contents/{ref}"

# No request is ever made to a URL outside these prefixes.
ALLOWED_PREFIXES: tuple[str, ...] = (
    "https://docs.kernel.org/",
    "https://raw.githubusercontent.com/torvalds/linux/",
    "https://api.github.com/repos/torvalds/linux/",
    "https://man7.org/",
    "https://www.freedesktop.org/software/systemd/man/",
    "https://manpages.debian.org/",
    "https://wiki.archlinux.org/",
    "https://wiki.alpinelinux.org/",
    "https://docs.fedoraproject.org/",
    "https://help.ubuntu.com/",
    "https://www.debian.org/",
)


class OnlineDisabled(RuntimeError):
    """JARVIS_ONLINE_DOCS is not enabled (this is the normal state)."""


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates every redirect against the allowlist BEFORE following it.

    Without this, a redirect from an allowlisted host would be followed
    blindly — the allowlist must bound the whole redirect chain, not just the
    first hop.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        _check_allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER: urllib.request.OpenerDirector | None = None


def _opener() -> urllib.request.OpenerDirector:
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(SafeRedirectHandler())
    return _OPENER


class OnlineRefused(RuntimeError):
    """The URL is outside the allowlist — refused before any request."""


def online_enabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else dict(os.environ)
    return source.get(ONLINE_ENV, "0") == "1"


def _check_allowed(url: str) -> None:
    if not any(url.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise OnlineRefused(
            f"URL is outside the knowledge allowlist: {url[:80]}… "
            f"(allowed prefixes: {len(ALLOWED_PREFIXES)})"
        )


@dataclass(frozen=True)
class OnlineCheck:
    ref: str
    reachable: bool
    http_status: int | None
    detail: str
    checked_url: str
    checked_utc: str


def verify_kernel_doc(repo: str, ref: str, *, timeout_s: float = 20.0) -> OnlineCheck:
    """Verify a kernel documentation path exists upstream (GitHub Contents API).

    Uses ``GITHUB_TOKEN`` from the environment when present (authenticated
    limits: 1000+ req/h instead of 60 — CI shares one egress IP across
    matrix legs, so unauthenticated runs flake on the rate limit). A single
    polite retry is made when GitHub says rate-limited (429, or 403 with
    ``x-ratelimit-remaining: 0``), bounded to 5 s regardless of Retry-After;
    the retry is disclosed in the returned detail. The token is never logged.
    """
    url = _GITHUB_API.format(repo=repo, ref=ref)
    _check_allowed(url)
    headers = {
        "Accept": "application/vnd.github.raw+json",
        "User-Agent": "jarvis-kb",
        **_github_auth_headers(),
    }
    check = _github_contents_request(ref, url, headers, timeout_s)
    assert check is not None  # _github_contents_request never returns None
    if _is_rate_limited(check.http_status, check.detail):
        time.sleep(_bounded_retry_after(check.detail))
        retried = _github_contents_request(ref, url, headers, timeout_s)
        assert retried is not None
        if not _is_rate_limited(retried.http_status, retried.detail):
            return OnlineCheck(
                retried.ref,
                retried.reachable,
                retried.http_status,
                f"{retried.detail} (retried once after rate-limit)",
                retried.checked_url,
                retried.checked_utc,
            )
    return check


def _github_auth_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _is_rate_limited(status: int | None, detail: str) -> bool:
    if status == 429:
        return True
    return status == 403 and "rate-limit" in detail


def _bounded_retry_after(detail: str) -> float:
    """Retry-After honored up to 5 s (a CLI must not stall on GitHub's sake)."""
    try:
        value = float(detail.split("retry-after:", 1)[1])
    except (IndexError, ValueError):
        return 2.0
    return max(0.5, min(value, 5.0))


def _github_contents_request(
    ref: str, url: str, headers: dict[str, str], timeout_s: float
) -> OnlineCheck:
    """One Contents-API request, as an OnlineCheck (never raises for HTTP)."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    req = urllib.request.Request(url, headers=dict(headers))
    try:
        with _opener().open(req, timeout=timeout_s) as resp:
            size = len(resp.read())
            return OnlineCheck(ref, True, resp.status, f"{size} bytes fetched", url, stamp)
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}"
        response_headers = exc.headers
        remaining = response_headers.get("x-ratelimit-remaining") if response_headers else None
        rate_limited = exc.code == 429 or (exc.code == 403 and remaining == "0")
        if rate_limited:
            retry_after = response_headers.get("Retry-After") if response_headers else None
            detail = f"{detail}|rate-limit|retry-after:{retry_after or ''}"
        return OnlineCheck(ref, False, exc.code, detail, url, stamp)
    except urllib.error.URLError as exc:
        return OnlineCheck(ref, False, None, f"unreachable: {exc.reason}", url, stamp)


def verify_url(url: str, *, timeout_s: float = 20.0) -> OnlineCheck:
    """HEAD-equivalent existence check for an allowlisted doc URL."""
    _check_allowed(url)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "jarvis-kb"})
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with _opener().open(req, timeout=timeout_s) as resp:
            return OnlineCheck(url, True, resp.status, "reachable", url, stamp)
    except urllib.error.HTTPError as exc:
        # some static hosts reject HEAD; fall back to GET range probe
        if exc.code in (403, 405):
            return _get_probe(url, timeout_s=timeout_s, stamp=stamp)
        return OnlineCheck(url, False, exc.code, f"HTTP {exc.code}", url, stamp)
    except urllib.error.URLError as exc:
        return OnlineCheck(url, False, None, f"unreachable: {exc.reason}", url, stamp)


def _get_probe(url: str, *, timeout_s: float, stamp: str) -> OnlineCheck:
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-kb", "Range": "bytes=0-64"})
    try:
        with _opener().open(req, timeout=timeout_s) as resp:
            return OnlineCheck(url, True, resp.status, "reachable (GET probe)", url, stamp)
    except urllib.error.URLError as exc:
        return OnlineCheck(url, False, None, f"unreachable: {exc.reason}", url, stamp)


def cache_path() -> Path:
    return state_dir() / "knowledge-cache.json"


def store_checks(checks: list[OnlineCheck]) -> None:
    path = cache_path()
    existing: dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            existing = {}
    for check in checks:
        existing[check.ref] = {
            "reachable": check.reachable,
            "http_status": check.http_status,
            "detail": check.detail,
            "checked_utc": check.checked_utc,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
