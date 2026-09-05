"""Provider HTTP behavior against a local stub server (real sockets, no mocks)."""

from __future__ import annotations

from typing import cast

import pytest

from conftest import StubHTTPServer
from jarvis.providers.base import ProviderError
from jarvis.providers.ollama import OllamaProvider
from jarvis.providers.openai_compatible import OpenAICompatibleProvider


def _ollama(server: StubHTTPServer) -> OllamaProvider:
    return OllamaProvider(host=server.url, model="test-model")


def _openai(server: StubHTTPServer, key: str = "sk-test") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(base_url=server.url, model="test-model", api_key=key)


def test_ollama_available_probes_tags(stub_server: object) -> None:
    server = cast(StubHTTPServer, stub_server)
    provider = _ollama(server)
    assert provider.available() is True


def test_ollama_unreachable_is_unavailable() -> None:
    dead = OllamaProvider(host="127.0.0.1:1")  # nothing listens on port 1
    assert dead.available() is False


def test_ollama_complete_returns_content(stub_server: object) -> None:
    server = cast(StubHTTPServer, stub_server)
    server.queue({"message": {"content": '{"explanation": "ok", "steps": ["system info"]}'}})
    provider = _ollama(server)
    out = provider.complete("sys", "do it")
    assert '"steps"' in out


def test_ollama_complete_malformed_envelope(stub_server: object) -> None:
    server = cast(StubHTTPServer, stub_server)
    server.queue({"unexpected": "shape"})
    with pytest.raises(ProviderError, match=r"message\.content"):
        _ollama(server).complete("sys", "do it")


def test_openai_complete_returns_content(stub_server: object) -> None:
    server = cast(StubHTTPServer, stub_server)
    server.queue({"choices": [{"message": {"content": '{"steps": []}'}}]})
    provider = _openai(server)
    out = provider.complete("sys", "do it")
    assert '"steps"' in out


def test_openai_unavailable_without_key(stub_server: object) -> None:
    server = cast(StubHTTPServer, stub_server)
    assert _openai(server, key="").available() is False
    assert _openai(server, key="  ").available() is False
    assert _openai(server).available() is True


def test_openai_complete_without_key_raises(stub_server: object) -> None:
    server = cast(StubHTTPServer, stub_server)
    with pytest.raises(ProviderError, match="JARVIS_OPENAI_API_KEY"):
        _openai(server, key="").complete("sys", "do it")


def test_openai_http_error_surfaces_detail(stub_server: object) -> None:
    server = cast(StubHTTPServer, stub_server)
    server.queue({"error": "bad model"}, status=404)
    with pytest.raises(ProviderError, match="HTTP 404"):
        _openai(server).complete("sys", "do it")


def test_openai_non_json_body(stub_server: object) -> None:
    server = cast(StubHTTPServer, stub_server)
    server.queue("<html>not json</html>")
    with pytest.raises(ProviderError, match="non-JSON"):
        _openai(server).complete("sys", "do it")
