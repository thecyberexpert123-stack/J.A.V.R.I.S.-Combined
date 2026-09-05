"""Rate-limit resilience of the GitHub Contents verification path (v1.10.2).

The live CI legs share one egress IP; unauthenticated api.github.com calls
flake at 60 req/h. These tests pin the remedy: GITHUB_TOKEN is honored
(never logged), a rate-limited call retries exactly once with a bounded
wait, and the retry is disclosed in the returned detail.
"""

from __future__ import annotations

from typing import cast

import pytest

from conftest import StubHTTPServer
from jarvis.knowledge import fetch as fetch_module
from jarvis.knowledge.fetch import verify_kernel_doc


@pytest.fixture()
def _allow_stub(monkeypatch: pytest.MonkeyPatch, stub_server: object) -> StubHTTPServer:
    """Point the (allowlist-guarded) fetcher at the local stub server."""
    server = cast(StubHTTPServer, stub_server)

    def allow(url: str) -> None:
        assert url.startswith(server.url)

    monkeypatch.setattr(fetch_module, "_check_allowed", allow)
    monkeypatch.setattr(fetch_module, "_GITHUB_API", server.url + "/repos/{repo}/contents/{ref}")
    return server


def test_token_sent_and_never_leaked(
    _allow_stub: StubHTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "sk-secret-token")
    _allow_stub.queue_get({"content": "", "encoding": "none"})
    check = verify_kernel_doc("torvalds/linux", "Documentation/x.rst")
    assert check.reachable
    request = _allow_stub.requests[0]
    assert isinstance(request, dict)
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers.get("Authorization") == "Bearer sk-secret-token"
    assert "sk-secret-token" not in check.detail  # token never surfaces in output


def test_no_token_means_unauthenticated(
    _allow_stub: StubHTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _allow_stub.queue_get({"content": "", "encoding": "none"})
    verify_kernel_doc("torvalds/linux", "Documentation/x.rst")
    request = _allow_stub.requests[0]
    assert isinstance(request, dict)
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert "Authorization" not in headers


def test_rate_limit_retried_once_with_disclosure(
    _allow_stub: StubHTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(fetch_module.time, "sleep", lambda _s: None)  # bound the wait in tests
    _allow_stub.queue_get({"message": "Too Many Requests"}, status=429)
    _allow_stub.queue_get({"content": "", "encoding": "none"})
    check = verify_kernel_doc("torvalds/linux", "Documentation/x.rst")
    assert check.reachable
    assert "retried once after rate-limit" in check.detail
    assert len(_allow_stub.requests) == 2


def test_persistent_rate_limit_is_honest(
    _allow_stub: StubHTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(fetch_module.time, "sleep", lambda _s: None)
    _allow_stub.queue_get({"message": "Too Many Requests"}, status=429)
    _allow_stub.queue_get({"message": "still limited"}, status=429)
    check = verify_kernel_doc("torvalds/linux", "Documentation/x.rst")
    assert not check.reachable
    assert check.http_status == 429
    assert "rate-limit" in check.detail


def test_plain_403_is_not_treated_as_rate_limit(
    _allow_stub: StubHTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _allow_stub.queue_get({"message": "nope"}, status=403)
    check = verify_kernel_doc("torvalds/linux", "Documentation/x.rst")
    assert not check.reachable
    assert check.http_status == 403
    assert len(_allow_stub.requests) == 1  # no retry for a plain 403
