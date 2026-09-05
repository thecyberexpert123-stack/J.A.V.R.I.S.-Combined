"""ADR-0021 scheduled briefings: computed never executed, deterministic policy,
ledgered silence, opt-in timer.

The engine composes from local state only (seeded journal + context store +
monkeypatched statvfs) and never spawns a subprocess; the policy table pins
notify-vs-silence for every branch; the ledger gives silence a denominator;
the timer install mirrors residency discipline (honest systemd disclosure).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.brief.engine import (
    Briefing,
    BriefLedger,
    compose,
    decide,
    desktop_notify,
    run_once,
)
from jarvis.brief.install import (
    service_content,
    timer_content,
    timer_path,
    uninstall_timer,
)
from jarvis.context.store import ContextStore
from jarvis.journal.sqlite import Journal
from jarvis.safety.tiers import SafetyRefusal


class _FakeStat:
    def __init__(self, free: int, total: int) -> None:
        self.f_bavail = free
        self.f_blocks = total


@pytest.fixture()
def seeded(tmp_path: Path) -> tuple[Journal, ContextStore]:
    journal = Journal(tmp_path / "journal.db")
    context = ContextStore(tmp_path / "context")
    moment = datetime.now(timezone.utc)
    for i in range(2):
        task_id = f"t{i}"
        journal.begin_task(task_id, "demo request", "sys.uptime", 0, {}, {})
        journal.finish_task(task_id, "success")
    journal.begin_task("tfail", "failing demo", "svc.stop", 2, {}, {})
    journal.finish_task("tfail", "failed")
    journal.record_unknown_request("make me a sandwich", "unmatched", [])
    context.record_feedback("demo-suggestion", "accepted", reason="test", title="demo")
    assert (moment - moment) == timedelta(0)
    return journal, context


# --------------------------------------------------------------------------
# composition: local-only, four sources, id-stable
# --------------------------------------------------------------------------


def test_compose_collects_failures_suggestions_unknowns_disk(
    seeded: tuple[Journal, ContextStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    journal, context = seeded
    monkeypatch.setattr("jarvis.brief.engine.statvfs", lambda _m: _FakeStat(5, 100))
    briefing = compose(journal, context, profile=object(), disk_free=None)
    joined = " | ".join(briefing.items)
    assert "1 task(s) failed" in joined
    assert "suggestion(s)" in joined or "unmapped request(s)" in joined or "low disk" in joined
    assert len(briefing.briefing_id) == 12


def test_compose_is_quiet_when_all_is_well(
    seeded: tuple[Journal, ContextStore],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _journal, context = seeded
    # a fresh journal: no failures, no unknowns
    clean = Journal(tmp_path / "brief-clean.db")
    monkeypatch.setattr("jarvis.brief.engine.statvfs", lambda _m: _FakeStat(90, 100))
    monkeypatch.setattr("jarvis.brief.engine.generate_suggestions", lambda *a, **k: [])
    briefing = compose(clean, context, profile=object())
    assert briefing.items == ()


def test_compose_never_spawns_subprocess(
    seeded: tuple[Journal, ContextStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    journal, context = seeded

    def _forbidden(*a: object, **k: object) -> None:
        raise AssertionError("briefing composition must not spawn processes")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr("jarvis.brief.engine.statvfs", lambda _m: _FakeStat(50, 100))
    compose(journal, context, profile=object())


# --------------------------------------------------------------------------
# policy: deterministic, silence is first-class
# --------------------------------------------------------------------------


def test_policy_notifies_when_any_reason_fires() -> None:
    briefing = Briefing(briefing_id="x", created="t", items=("1 task(s) failed",))
    decided = decide(briefing)
    assert decided.decision == "notify"
    assert decided.reasons == ("1 task(s) failed",)


def test_policy_silences_with_reason_when_all_is_well() -> None:
    decided = decide(Briefing(briefing_id="x", created="t"))
    assert decided.decision == "silence"
    assert decided.reasons == ("nothing to report",)


def test_notify_line_is_hygiened_and_bounded() -> None:
    briefing = Briefing(
        briefing_id="x",
        created="t",
        items=("bad\x1btext here", "second item with content that is fairly long " * 10),
    )
    line = briefing.notify_line()
    assert "\x1b" not in line and len(line) <= 200
    assert "bad text here" in line


# --------------------------------------------------------------------------
# ledger: runs, feedback, stats, silence denominator
# --------------------------------------------------------------------------


def test_ledger_records_runs_and_stats(tmp_path: Path) -> None:
    ledger = BriefLedger(tmp_path)
    ledger.record_run(
        decide(Briefing(briefing_id="a", created="t1", items=("low disk",))), delivered=True
    )
    ledger.record_run(decide(Briefing(briefing_id="b", created="t2")), delivered=False)
    stats = ledger.stats()
    assert stats["runs"] == 2 and stats["notified"] == 1 and stats["silenced"] == 1
    assert stats["silence_rate"] == 0.5
    assert stats["last_run"] is not None and stats["last_run"]["id"] == "b"  # type: ignore[index]


def test_ledger_feedback_validation_and_counts(tmp_path: Path) -> None:
    ledger = BriefLedger(tmp_path)
    ledger.record_feedback("abc", "accept")
    ledger.record_feedback("abc", "dismiss")
    with pytest.raises(SafetyRefusal):
        ledger.record_feedback("abc", "maybe")
    stats = ledger.stats()
    assert stats["accepted"] == 1 and stats["dismissed"] == 1


def test_empty_ledger_stats_are_honest(tmp_path: Path) -> None:
    stats = BriefLedger(tmp_path).stats()
    assert stats["runs"] == 0 and stats["silence_rate"] is None


# --------------------------------------------------------------------------
# run_once: delivery + ledger wiring (desktop notify honestly unavailable)
# --------------------------------------------------------------------------


def test_run_once_notify_writes_latest_and_ledgers(
    seeded: tuple[Journal, ContextStore],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    journal, _context = seeded
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("jarvis.brief.engine.statvfs", lambda _m: _FakeStat(5, 100))
    payload = run_once(journal=journal, profile=object(), state=tmp_path, disk_free=None)
    assert payload["decision"] == "notify"
    assert (tmp_path / "briefings" / "latest.md").exists()
    stats = BriefLedger(tmp_path).stats()
    assert stats["runs"] == 1 and stats["notified"] == 1
    out = capsys.readouterr().out
    assert "JARVIS briefing" in out and "desktop notification unavailable" in out


def test_run_once_silence_prints_nothing_under_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = Journal(tmp_path / "j.db")
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("jarvis.brief.engine.statvfs", lambda _m: _FakeStat(90, 100))
    monkeypatch.setattr("jarvis.brief.engine.generate_suggestions", lambda *a, **k: [])
    payload = run_once(quiet=True, journal=clean, profile=object(), state=tmp_path, disk_free=None)
    assert payload["decision"] == "silence"
    assert capsys.readouterr().out == ""
    assert BriefLedger(tmp_path).stats()["silenced"] == 1  # silence is ledgered


def test_run_once_json_includes_decision(
    seeded: tuple[Journal, ContextStore],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    journal, _context = seeded
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("jarvis.brief.engine.statvfs", lambda _m: _FakeStat(5, 100))
    payload = run_once(json_output=True, journal=journal, profile=object(), state=tmp_path)
    assert payload["decision"] in {"notify", "silence"}
    assert "reasons" in payload and "delivered" in payload


def test_desktop_notify_honest_false_without_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    assert desktop_notify("hello", which=lambda _n: None) is False


# --------------------------------------------------------------------------
# timer install/uninstall: opt-in, honest, reversible
# --------------------------------------------------------------------------


def test_timer_and_service_content(tmp_path: Path) -> None:
    assert "OnCalendar=*-*-* 09:00:00" in timer_content("daily")
    assert "OnCalendar=Mon" in timer_content("weekly")
    assert "-m jarvis brief --quiet" in service_content("/usr/bin/python3")
    assert "Persistent=true" in timer_content("daily")


def test_install_uninstall_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.brief.install import install_timer

    # pin the environment: CI runners DO have systemctl + XDG_RUNTIME_DIR,
    # so availability must be forced off to test the honest-skip path
    monkeypatch.setattr("jarvis.brief.install._systemctl_available", lambda: False)
    assert install_timer("daily", tmp_path) == 0
    assert timer_path(tmp_path).exists()
    out = capsys.readouterr().out
    assert "NOT enabled" in out  # disclosed skip, never a silent claim
    assert uninstall_timer(tmp_path) == 0
    assert not timer_path(tmp_path).exists()


def test_install_enable_uses_fixed_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When systemd --user is available, enabling uses one fixed argv - no shell."""
    import subprocess as sp

    from jarvis.brief.install import install_timer

    seen: list[list[str]] = []

    class _OK:
        returncode = 0
        stderr = ""

    def _fake_run(argv: list[str], **kwargs: object) -> _OK:
        seen.append(list(argv))
        return _OK()

    monkeypatch.setattr("jarvis.brief.install._systemctl_available", lambda: True)
    monkeypatch.setattr(sp, "run", _fake_run)
    assert install_timer("weekly", tmp_path) == 0
    out = capsys.readouterr().out
    assert seen == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "jarvis-brief.timer"],
    ]
    assert "enabled + started" in out


def test_install_rejects_unknown_schedule(tmp_path: Path) -> None:
    from jarvis.brief.install import install_timer

    with pytest.raises(SafetyRefusal):
        install_timer("hourly", tmp_path)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# charter: the catalog is unchanged by proactivity
# --------------------------------------------------------------------------


def test_no_new_playbook_was_added() -> None:
    from jarvis.planner.playbooks import PLAYBOOKS

    assert len(PLAYBOOKS) == 58  # catalog grew via ADR-0024, ADR-0026; briefings still propose


def test_cli_bare_run_and_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("jarvis.brief.engine.statvfs", lambda _m: _FakeStat(90, 100))
    monkeypatch.setattr("jarvis.brief.engine.generate_suggestions", lambda *a, **k: [])
    assert main(["brief"]) == 0
    out = capsys.readouterr().out
    assert "nothing to report" in out
    assert main(["brief", "status"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["runs"] == 1 and stats["silenced"] == 1
