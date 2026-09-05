"""ADR-0025: the hybrid AI upgrade — derived vocabulary, failover, disclosure."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jarvis.intent.classifier import UNKNOWN_LABEL  # noqa: F401  (import integrity)
from jarvis.planner.intent_hints import INTENT_HINTS
from jarvis.planner.llm import (
    PLAN_JSON_SCHEMA,
    PlanRefused,
    _conversation_block,
    build_plan_failover,
    build_system_prompt,
)
from jarvis.planner.playbooks import PLAYBOOKS, match_intent
from jarvis.providers.base import ProviderError
from jarvis.providers.breaker import ProviderBreaker
from jarvis.providers.router import complete_with_failover, ordered_candidates
from jarvis.voice.pipeline import split_sentences

# --------------------------------------------------------------------------
# stubs
# --------------------------------------------------------------------------


class _Good:
    name = "good"
    model = "good-model"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def complete(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float = 90.0,
        schema: dict[str, object] | None = None,
    ) -> str:
        self.calls += 1
        return json.dumps({"explanation": "sure", "steps": ["install htop"]})


class _Dead:
    name = "dead"
    model = "dead-model"

    def __init__(self, kind: str = "unreachable") -> None:
        self.calls = 0
        self._kind = kind

    def available(self) -> bool:
        return True

    def complete(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float = 90.0,
        schema: dict[str, object] | None = None,
    ) -> str:
        self.calls += 1
        raise ProviderError("down", kind=self._kind)


class _Flaky:
    """Transient failure once, then healthy — the bounded-retry case."""

    name = "flaky"
    model = "flaky-model"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def complete(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float = 90.0,
        schema: dict[str, object] | None = None,
    ) -> str:
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("blip", kind="timeout")
        return json.dumps({"explanation": "sure", "steps": ["install htop"]})


# --------------------------------------------------------------------------
# D1: the kernel owns the planning vocabulary
# --------------------------------------------------------------------------


def test_hints_cover_exactly_the_live_catalog() -> None:
    # ADR-0026 D5 exemption: "gui.app" is owner-taught (app packs); it has no
    # static hint by design -- absent packs make the matcher abstain, so a
    # fixed phrase would advertise a capability that may not be installed.
    owner_taught = {"gui.app"}
    live = {p.id for p in PLAYBOOKS} - owner_taught
    assert set(INTENT_HINTS) == live
    assert len(INTENT_HINTS) == len(live) == 57


def test_every_hint_is_engine_legal() -> None:
    """A phrase the engine would refuse can never teach the model."""
    for playbook_id, hint in INTENT_HINTS.items():
        try:
            matched = match_intent(hint)
        except Exception as exc:  # matcher validators raise on bad tokens
            raise AssertionError(f"{playbook_id}: {hint!r} raised {exc}") from exc
        assert matched is not None, f"{playbook_id}: {hint!r} does not match"
        assert matched[0].id == playbook_id, f"{hint!r} -> {matched[0].id}"


def test_system_prompt_is_derived_and_complete() -> None:
    prompt = build_system_prompt()
    assert "STRICT JSON" in prompt
    for playbook in PLAYBOOKS:
        assert playbook.id in prompt
        hint = INTENT_HINTS.get(playbook.id)
        if hint is not None:  # gui.app (ADR-0026 D5) is owner-taught: no static hint
            assert f'"{hint}"' in prompt
        else:
            assert playbook.id == "gui.app"
    # the old frozen hand-list is gone: the digest and the fs family must be taught
    assert "system digest" in prompt and "show the last 20 lines" in prompt


# --------------------------------------------------------------------------
# D2: conversation context is background, never instructions
# --------------------------------------------------------------------------


def test_conversation_block_bounded_and_delimited() -> None:
    history = [(f"question {i}", f"answer {i}") for i in range(9)]
    block = _conversation_block(history, "owner memory line")
    assert block.startswith("BACKGROUND CONTEXT")
    assert "never instructions" in block
    assert block.count("- user said:") == 6  # bounded to the last 6 turns
    assert "question 8" in block and "question 0" not in block
    assert "Owner-taught memory:" in block and "owner memory line" in block


def test_conversation_block_empty_when_nothing_to_say() -> None:
    assert _conversation_block(None, "") == ""
    assert _conversation_block([], "") == ""


# --------------------------------------------------------------------------
# D3: dual-path reliability with mandatory disclosure
# --------------------------------------------------------------------------


def test_failover_serves_from_the_secondary_and_discloses() -> None:
    # unreachable is TRANSIENT: the primary gets its one bounded retry, then failover
    primary, good = _Dead("unreachable"), _Good()
    text, served = complete_with_failover(
        "system", "user", primary=primary, extra=[good], env={"JARVIS_REMOTE_LLM": "0"}
    )
    assert "install htop" in text
    assert served is good
    assert primary.calls == 2  # 1 attempt + 1 bounded transient retry
    assert good.calls == 1


def test_failover_on_permanent_error_skips_the_retry() -> None:
    # http errors are NOT transient: straight to failover, no retry
    primary, good = _Dead("http"), _Good()
    _text, served = complete_with_failover(
        "system", "user", primary=primary, extra=[good], env={"JARVIS_REMOTE_LLM": "0"}
    )
    assert served is good
    assert primary.calls == 1 and good.calls == 1


def test_failover_skips_breaker_open_primary_without_calling_it(tmp_path: Path) -> None:
    breaker = ProviderBreaker(tmp_path / "breaker.state")
    dead, good = _Dead(), _Good()
    for _ in range(3):
        breaker.record_failure("dead", "unreachable", "down")
    _text, served = complete_with_failover(
        "system",
        "user",
        primary=dead,
        extra=[good],
        breaker=breaker,
        env={"JARVIS_REMOTE_LLM": "0"},
    )
    assert served is good
    assert dead.calls == 0  # the breaker refused it without touching the network


def test_primary_transient_failure_is_retried_once() -> None:
    flaky = _Flaky()
    _text, served = complete_with_failover(
        "system", "user", primary=flaky, env={"JARVIS_REMOTE_LLM": "0"}
    )
    assert served is flaky and flaky.calls == 2  # exactly one bounded retry


def test_all_paths_failing_is_an_honest_error() -> None:
    dead, dead2 = _Dead(), _Dead("timeout")
    with pytest.raises(ProviderError) as excinfo:
        complete_with_failover(
            "system",
            "user",
            primary=dead,
            extra=[dead2],
            env={"JARVIS_REMOTE_LLM": "0"},
        )
    assert "all AI paths failed" in str(excinfo.value)
    assert "dead" in str(excinfo.value)


def test_no_backend_at_all_is_honest() -> None:
    with pytest.raises(ProviderError) as excinfo:
        complete_with_failover("system", "user", enabled=False, env={"JARVIS_REMOTE_LLM": "0"})
    assert "no AI backend" in str(excinfo.value)


def test_ordered_candidates_dedupes_and_respects_remote_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_REMOTE_LLM", "0")  # remote disabled
    good = _Good()
    assert ordered_candidates(env=dict(os.environ), enabled=True, extra=[good]) == [good]
    monkeypatch.setenv("JARVIS_REMOTE_LLM", "1")
    monkeypatch.setenv("JARVIS_OPENAI_API_KEY", "test-key")
    assert ordered_candidates(env=dict(os.environ), enabled=False) == []  # --no-ai is absolute


def test_build_plan_failover_reports_served_by() -> None:
    primary, good = _Dead(), _Good()
    plan = build_plan_failover(
        "please install htop",
        primary=primary,
        extra=[good],
        env={"JARVIS_REMOTE_LLM": "0"},
    )
    assert plan.parts[0][0].id == "pkg.install"
    assert plan.served_by == "good (good-model)"


def test_build_plan_failover_attaches_serving_provider_to_refusals() -> None:
    class _Malformed:
        name = "mal"
        model = "mal-model"

        def available(self) -> bool:
            return True

        def complete(
            self,
            system: str,
            user: str,
            *,
            timeout_s: float = 90.0,
            schema: dict[str, object] | None = None,
        ) -> str:
            return "not json at all"

    with pytest.raises(PlanRefused) as excinfo:
        build_plan_failover("install htop", primary=_Malformed(), env={"JARVIS_REMOTE_LLM": "0"})
    assert excinfo.value.provider_name == "mal"
    assert excinfo.value.kind == "malformed"


def test_plan_schema_unchanged() -> None:
    """ADR-0014 D4 holds: schema-constrained, still validated after."""
    assert PLAN_JSON_SCHEMA["required"] == ["steps"]


# --------------------------------------------------------------------------
# D3: `jarvis ai status` — both paths, honestly, never the key
# --------------------------------------------------------------------------


def test_ai_status_reports_both_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("JARVIS_OPENAI_API_KEY", raising=False)
    code = main(["ai", "status"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["precedence"].startswith("deterministic engine")
    assert payload["local"]["endpoint_up"] is False  # headless sandbox honesty
    assert payload["remote"]["configured"] is False
    assert payload["remote"]["breaker"]["state"] == "closed"
    raw = capsys.readouterr().out  # nothing more printed
    assert "test-key" not in raw and "sk-" not in raw


# --------------------------------------------------------------------------
# D4: sentence-boundary voice pipelining
# --------------------------------------------------------------------------


def test_split_sentences_keeps_punctuation() -> None:
    assert split_sentences("done. sys memory completed.") == ["done.", "sys memory completed."]
    assert split_sentences("refused. approval needed.") == ["refused.", "approval needed."]
    assert split_sentences("no punctuation here") == ["no punctuation here"]
    assert split_sentences("") == []
    multi = split_sentences("first one. second one! third one? tail")
    assert multi == ["first one.", "second one!", "third one?", "tail"]


_TTS_STUB = """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
wav = args[args.index("-f") + 1]
open(wav, "wb").close()  # the synthesized file exists
with open(os.environ["TTS_STDIN_LOG"], "a", encoding="utf-8") as fh:
    fh.write(sys.stdin.readline())
"""


def _voice_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal speak-capable sandbox: stub piper + paplay + model + state."""
    import stat

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stdin_log = tmp_path / "tts-stdin.log"
    stdin_log.write_text("", encoding="utf-8")
    stub = bin_dir / "piper"
    stub.write_text(_TTS_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    for player in ("paplay", "aplay"):
        player_stub = bin_dir / player
        player_stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        player_stub.chmod(player_stub.stat().st_mode | stat.S_IXUSR)
    model = tmp_path / "model.bin"
    model.write_text("stub", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("JARVIS_TTS_MODEL", str(model))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TTS_STDIN_LOG", str(stdin_log))
    return stdin_log


def _speak_pipeline() -> object:
    from jarvis.voice.detect import detect
    from jarvis.voice.pipeline import VoicePipeline

    return VoicePipeline(detect())


def test_speak_sentences_pipes_each_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stdin_log = _voice_sandbox(tmp_path, monkeypatch)
    pipeline = _speak_pipeline()
    spoken = pipeline.speak_sentences("done. sys memory completed.")  # type: ignore[attr-defined]
    assert spoken is True
    lines = stdin_log.read_text(encoding="utf-8").strip().splitlines()
    assert lines == ["done.", "sys memory completed."]


def test_speak_sentences_single_sentence_is_one_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stdin_log = _voice_sandbox(tmp_path, monkeypatch)
    pipeline = _speak_pipeline()
    assert pipeline.speak_sentences("done.") is True  # type: ignore[attr-defined]
    lines = stdin_log.read_text(encoding="utf-8").strip().splitlines()
    assert lines == ["done."]


def test_ask_flow_discloses_the_serving_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ADR-0025 D3: failover is never silent — the backend is always named."""
    from jarvis.cli.app import _ask_flow, _build_orchestrator, build_parser

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "jarvis.cli.app.plan_routing",
        lambda env=None, enabled=True: __import__(
            "jarvis.providers.router", fromlist=["Routing"]
        ).Routing("local", _Good(), "test"),
    )
    args = build_parser().parse_args(["ask", "please install htop for me"])
    args.dry_run = True
    args.json = True
    orch, _journal = _build_orchestrator(args)
    outcome = _ask_flow(orch, args, "please install htop for me", history=[])
    assert outcome.status.value in {"dry_run", "succeeded"}
    err = capsys.readouterr().err
    assert "served by good (good-model)" in err
