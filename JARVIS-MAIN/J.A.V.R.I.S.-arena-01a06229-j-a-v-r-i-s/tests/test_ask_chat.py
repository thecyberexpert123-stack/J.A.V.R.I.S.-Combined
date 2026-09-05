"""CLI `ask` routing: engine fast path, provider branches, honest refusals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from conftest import StubHTTPServer
from jarvis.cli.app import main


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StubHTTPServer:
    """Local-only planner pointed at a stub server; remote disabled."""
    server = StubHTTPServer()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OLLAMA_HOST", server.url)
    monkeypatch.setenv("JARVIS_LOCAL_MODEL", "test-model")
    monkeypatch.setenv("JARVIS_REMOTE_LLM", "0")
    monkeypatch.delenv("JARVIS_OPENAI_API_KEY", raising=False)
    return server


def test_engine_fast_path_skips_llm(
    isolated_env: object, capsys: pytest.CaptureFixture[str]
) -> None:
    server = cast(StubHTTPServer, isolated_env)
    assert main(["--json", "ask", "--dry-run", "install", "htop"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["playbook"] == "pkg.install"
    assert data["status"] == "dry_run"
    assert server._queue == []  # the LLM was never consulted


def test_planner_valid_plan_dry_run(
    isolated_env: object, capsys: pytest.CaptureFixture[str]
) -> None:
    server = cast(StubHTTPServer, isolated_env)
    server.queue(
        {
            "message": {
                "content": '{"explanation": "setup", "steps": ["install htop", "system info"]}'
            }
        }
    )
    assert main(["--json", "ask", "--dry-run", "set", "up", "monitoring"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["playbook"] == "plan"
    assert data["status"] == "dry_run"
    assert data["undo"]["status"] == "available"
    argvs = [s["argv"][0] for s in data["steps"]]
    assert "apt-get" in argvs and "uname" in argvs


def test_planner_invalid_json_refused(
    isolated_env: object, capsys: pytest.CaptureFixture[str]
) -> None:
    server = cast(StubHTTPServer, isolated_env)
    server.queue({"message": {"content": "I would just install htop for you!"}})
    assert main(["--json", "ask", "set", "up", "monitoring"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "refused"
    assert "not valid JSON" in data["error"]


def test_planner_unknown_step_refused(
    isolated_env: object, capsys: pytest.CaptureFixture[str]
) -> None:
    server = cast(StubHTTPServer, isolated_env)
    server.queue({"message": {"content": '{"steps": ["flurb the frobnicator"]}'}})
    assert main(["--json", "ask", "do", "the", "thing"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "refused"
    assert "does not map" in data["error"]


def test_no_backend_refused_with_setup_hint(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:1")  # nothing there
    monkeypatch.setenv("JARVIS_REMOTE_LLM", "0")
    assert main(["--json", "ask", "set", "up", "monitoring"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "refused"
    # ADR-0014 D6: a request nothing can map is a *processed* unknown.
    assert data["error"].startswith("unknown-request")
    assert "Ollama" in data["hint"]  # setup guidance survives
    assert "did you mean" in data["hint"]  # nearest intents disclosed


def test_remote_used_when_local_down(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = StubHTTPServer()
    try:
        monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:1")  # local down
        monkeypatch.delenv("JARVIS_REMOTE_LLM", raising=False)
        monkeypatch.setenv("JARVIS_OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("JARVIS_OPENAI_BASE_URL", server.url)
        server.queue(
            {
                "choices": [
                    {"message": {"content": '{"explanation": "x", "steps": ["system info"]}'}}
                ]
            }
        )
        assert main(["--json", "ask", "--dry-run", "briefing"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["playbook"] == "plan"
        assert data["status"] == "dry_run"
    finally:
        server.close()


def test_planner_backend_unreachable_fails_honestly(
    isolated_env: object, capsys: pytest.CaptureFixture[str]
) -> None:
    server = cast(StubHTTPServer, isolated_env)
    server.queue({}, status=500)
    assert main(["--json", "ask", "set", "up", "monitoring"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "failed"
    assert "planning backend failed" in data["error"]


def test_chat_quit_via_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    with open("/dev/null") as null_stdin:
        monkeypatch.setattr("sys.stdin", null_stdin)  # EOF immediately
        assert main(["chat"]) == 0
    out = capsys.readouterr().out
    assert "JARVIS chat" in out
