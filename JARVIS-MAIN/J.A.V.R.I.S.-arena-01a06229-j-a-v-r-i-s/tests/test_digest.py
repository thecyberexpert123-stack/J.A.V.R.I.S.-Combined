"""ADR-0024: synthesis-over-sources digest — computed, never generated."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.execution.runner import ExecResult
from jarvis.intent.classifier import rank_intents, suggest_intent
from jarvis.planner.playbooks import PLAYBOOKS, match_intent
from jarvis.system.digest import synthesize_digest

_DF = (
    "Filesystem      Size  Used Avail Use% Mounted on\n"
    "/dev/sda1       110G   47G   58G  45% /\n"
    "tmpfs           3.9G     0  3.9G   0% /dev/shm\n"
)
_DF_WARN = _DF.replace("  45% /", "  91% /")
_FREE = (
    "               total        used        free      shared  buff/cache   available\n"
    "Mem:            15Gi       6.2Gi       2.1Gi       300Mi       7.1Gi       8.9Gi\n"
    "Swap:          4.0Gi          0B       4.0Gi\n"
)
_UPTIME = " 14:32:01 up 3 days,  4:11,  2 users,  load average: 0.52, 0.49, 0.44\n"


# --------------------------------------------------------------------------
# catalog + matcher (ADR-0024 D4/D5)
# --------------------------------------------------------------------------


def test_digest_is_the_57th_readonly_playbook() -> None:
    digest = next(pb for pb in PLAYBOOKS if pb.id == "sys.digest")
    assert int(digest.tier) == 0
    assert "no LLM" in digest.description


@pytest.mark.parametrize(
    "text",
    [
        "system digest",
        "machine digest",
        "health check",
        "run a health check",
        "analyze my system",
        "analyse the machine",
        "digest the system",
        "system overview",
        "system health report",
        "synthesize the system state",
        "system report",
    ],
)
def test_matcher_accepts_digest_phrases(text: str) -> None:
    matched = match_intent(text)
    assert matched is not None and matched[0].id == "sys.digest"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("system info", "sys.info"),
        ("system summary", "sys.info"),
        ("system status", "sys.info"),
        ("how much disk space is free", "fs.disk_free"),
        ("show memory usage", "sys.memory"),
        ("digest my email", None),
        ("system", None),
        ("health", None),
    ],
)
def test_matcher_never_shadows_existing_intents(text: str, expected: str | None) -> None:
    matched = match_intent(text)
    assert (matched[0].id if matched else None) == expected


def test_build_runs_only_the_three_source_argv() -> None:
    digest = next(pb for pb in PLAYBOOKS if pb.id == "sys.digest")
    steps = digest.build({}, None)  # type: ignore[arg-type]
    assert [step.argv for step in steps] == [
        ("df", "-h"),
        ("free", "-h"),
        ("uptime",),
    ]
    assert all(int(step.tier) == 0 for step in steps)
    assert all(not step.requires_root for step in steps)
    assert all("source:" in step.description for step in steps)


def test_suggestion_abstains_disclosure_ranks() -> None:
    # ADR-0023 D4 holds: no extractor for the new family.
    assert suggest_intent("health check") is None
    assert suggest_intent("analyze my system") is None
    labels = [label for label, _prob in rank_intents("analyze my system")]
    assert "sys.digest" in labels


# --------------------------------------------------------------------------
# the pure synthesizer (ADR-0024 D1/D3)
# --------------------------------------------------------------------------


def test_digest_is_deterministic_and_cited() -> None:
    first = synthesize_digest(_DF, _FREE, _UPTIME, cores=8)
    second = synthesize_digest(_DF, _FREE, _UPTIME, cores=8)
    assert first == second
    assert first.ok is True and first.sources_readable == 3 and first.warnings == 0
    assert "no LLM" in first.lines[0]
    assert "[source: fs.disk_free]" in first.lines[1]
    assert "[source: sys.memory]" in first.lines[2]
    assert "[source: sys.uptime]" in first.lines[3]
    assert "45% used" in first.lines[1] and "41% used" in first.lines[2]
    assert "3/3 sources readable" in first.lines[4]


def test_thresholds_warn_with_disclosed_constants() -> None:
    report = synthesize_digest(_DF_WARN, _FREE, _UPTIME, cores=2)
    assert "91% used — WARN (threshold 85% used)" in report.lines[1]
    assert report.warnings == 1
    hot = synthesize_digest(_DF_WARN, _FREE, "up 1 min, load average: 9.00, 8.00, 7.00", cores=2)
    assert "WARN (load1 > 2 cores)" in hot.lines[3]
    assert hot.warnings == 2
    # warnings are findings, not failures
    assert hot.ok is True


def test_unreadable_sources_are_disclosed_never_guessed() -> None:
    empty = synthesize_digest("", "", "")
    assert empty.ok is False and empty.sources_readable == 0
    assert empty.lines[1].startswith("[source unreadable: fs.disk_free")
    assert empty.lines[2].startswith("[source unreadable: sys.memory")
    assert empty.lines[3].startswith("[source unreadable: sys.uptime")
    assert "0/3 sources readable" in empty.lines[4]
    for line in empty.lines:
        assert "used" not in line.replace("unreadable", "") or "source unreadable" in line


def test_partial_synthesis_is_honest() -> None:
    report = synthesize_digest(_DF, "", _UPTIME, cores=4)
    assert report.ok is True and report.sources_readable == 2
    assert "[source unreadable: sys.memory" in report.lines[2]
    assert "2/3 sources readable" in report.lines[4]


def test_free_without_available_column_is_unreadable() -> None:
    old_free = "Mem:          15Gi       6.2Gi       2.1Gi\n"
    report = synthesize_digest(_DF, old_free, _UPTIME, cores=4)
    assert "[source unreadable: sys.memory" in report.lines[2]


def test_digest_lines_are_hygiened() -> None:
    weird = _DF.replace("/dev/sda1", "/dev/sda1\x00bad\x1f[")
    report = synthesize_digest(weird, _FREE, _UPTIME, cores=4)
    assert all("\x00" not in line and "\x1f" not in line for line in report.lines)


# --------------------------------------------------------------------------
# the verify wiring (ADR-0024 D2: verify IS the synthesis)
# --------------------------------------------------------------------------


def _result(text: str) -> ExecResult:
    return ExecResult(exit_code=0, stdout_tail=text, stderr_tail="")


def test_verify_returns_the_digest_as_verification_detail() -> None:
    from jarvis.planner.playbooks import _verify_digest

    verification = _verify_digest(
        {},
        None,
        None,  # type: ignore[arg-type]
        [_result(_DF), _result(_FREE), _result(_UPTIME)],
    )
    assert verification.ok is True
    assert verification.checks == ()
    assert "[source: fs.disk_free]" in verification.detail
    assert verification.detail.startswith("digest: computed deterministically")


def test_verify_handles_missing_step_results() -> None:
    from jarvis.planner.playbooks import _verify_digest

    verification = _verify_digest({}, None, None, None)  # type: ignore[arg-type]
    assert verification.ok is False
    assert "unreadable" in verification.detail


def test_verify_skips_optional_missing_source() -> None:
    from jarvis.planner.playbooks import _verify_digest

    verification = _verify_digest(
        {},
        None,
        None,  # type: ignore[arg-type]
        [_result(_DF), None, _result(_UPTIME)],
    )
    assert verification.ok is True
    assert "[source unreadable: sys.memory" in verification.detail


def test_digest_undo_is_readonly() -> None:
    from jarvis.planner.models import UndoStatus

    digest = next(pb for pb in PLAYBOOKS if pb.id == "sys.digest")
    undo = digest.undo({}, None)  # type: ignore[arg-type]
    assert undo.status is UndoStatus.NONE_NEEDED
    assert "read-only" in undo.reason


# --------------------------------------------------------------------------
# CLI surface (deterministic, dry-run; no execution in tests)
# --------------------------------------------------------------------------


def test_cli_dry_run_lists_the_three_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    code = main(["--json", "do", "--dry-run", "system digest"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["playbook"] == "sys.digest" and data["status"] == "dry_run"
    argvs = [tuple(step["argv"]) for step in data["steps"]]  # type: ignore[index]
    assert argvs == [("df", "-h"), ("free", "-h"), ("uptime",)]
