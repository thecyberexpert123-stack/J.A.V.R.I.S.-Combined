"""Charters: circuit-broken standing orders (ADR-0013 M9d).

Covers schema validation, the install consent gate, run-time precheck gates
(paused/revoked, allowlist drift, tier ceiling, monthly budget), the failure
circuit breaker, unit generation, and the integrity-scope integration.
All execution goes through the scripted FakeRunner; no systemd is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import FakeRunner, make_result
from jarvis.cli.app import build_parser, main
from jarvis.safety import charter as ch


def good_doc(**overrides: Any) -> dict[str, object]:
    doc: dict[str, object] = {
        "schema": 1,
        "id": "nightly-cache",
        "request": "update the package cache",
        "playbooks": ["pkg.cache.refresh"],
        "tier_ceiling": 1,
        "max_steps_per_run": 8,
        "monthly_run_budget": 30,
        "on_calendar": "daily",
        "timeout_start_sec": 900,
        "failure_policy": "pause",
        "created_utc": "2026-09-03T00:00:00+00:00",
    }
    doc.update(overrides)
    return doc


class FakeJournal:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def recent_tasks(self, limit: int = 20) -> list[dict[str, object]]:
        return self._rows[:limit]


# -- schema & invariants -------------------------------------------------------


def test_good_doc_validates() -> None:
    assert ch.validate_charter(good_doc()) == []


def test_t3_ceiling_is_never_charterable() -> None:
    errors = ch.validate_charter(good_doc(tier_ceiling=3))
    assert any("tier_ceiling" in e for e in errors)


def test_allowlisted_playbook_above_ceiling_is_refused() -> None:
    errors = ch.validate_charter(good_doc(playbooks=["pkg.upgrade"], tier_ceiling=1))
    assert any("pkg.upgrade" in e and "above the charter ceiling" in e for e in errors)


def test_unknown_playbook_and_bad_fields_are_refused() -> None:
    assert any(
        "unknown playbook" in e for e in ch.validate_charter(good_doc(playbooks=["nope.drop"]))
    )
    assert any("id" in e for e in ch.validate_charter(good_doc(id="Bad_ID")))
    assert any(
        "on_calendar" in e for e in ch.validate_charter(good_doc(on_calendar="daily\nrm -rf"))
    )
    assert any("max_steps_per_run" in e for e in ch.validate_charter(good_doc(max_steps_per_run=0)))
    assert any(
        "monthly_run_budget" in e for e in ch.validate_charter(good_doc(monthly_run_budget=2000))
    )


def test_write_charter_refuses_invalid_and_writes_valid(tmp_path: Path) -> None:
    with pytest.raises(ch.CharterError):
        ch.write_charter(good_doc(tier_ceiling=3), env={"JARVIS_STATE_DIR": str(tmp_path)})
    path = ch.write_charter(good_doc(), env={"JARVIS_STATE_DIR": str(tmp_path)})
    assert (
        path.is_file()
        and ch.state_path("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path)}).is_file()
    )
    assert ch.read_state("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path)})["status"] == "active"


def test_load_charter_validates_on_read(tmp_path: Path) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path)}
    path = ch.write_charter(good_doc(), env=env)
    tampered = json.loads(path.read_text())
    tampered["playbooks"] = ["pkg.upgrade"]  # tampered below its ceiling
    path.write_text(json.dumps(tampered))
    with pytest.raises(ch.CharterError, match="validation"):
        ch.load_charter("nightly-cache", env=env)


# -- circuit-breaker accounting ------------------------------------------------


def test_count_recent_runs_window_and_garbage_rows() -> None:
    rows = [
        {"playbook_id": "pkg.cache.refresh", "created_utc": "2026-09-03T00:00:00+00:00"},
        {"playbook_id": "pkg.cache.refresh", "created_utc": "2026-01-01T00:00:00+00:00"},  # old
        {"playbook_id": "other", "created_utc": "2026-09-03T00:00:00+00:00"},  # not allowlisted
        {"playbook_id": "pkg.cache.refresh", "created_utc": "garbage"},  # skipped, not fatal
    ]
    assert ch.count_recent_runs(FakeJournal(rows), ["pkg.cache.refresh"]) == 1


def test_failure_policy_pauses_and_success_resets_failures(tmp_path: Path) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path)}
    ch.write_charter(good_doc(), env=env)
    state = ch.record_firing("nightly-cache", "failed", env=env)
    assert state["status"] == "paused" and state["failures"] == 1
    assert "failure policy" in str(state["paused_reason"])
    state = ch.record_firing("nightly-cache", "succeeded", env=env)
    assert state["status"] == "paused"  # recording does not resume; owner does


# -- systemd unit generation (pure) --------------------------------------------


def test_unit_documents_carry_the_breakers() -> None:
    service, timer = ch.unit_documents(good_doc(), "/usr/local/bin/jarvis")
    assert "ExecStart=/usr/local/bin/jarvis charter run nightly-cache" in service
    assert "TimeoutStartSec=900" in service
    assert "OnCalendar=daily" in timer and "Persistent=true" in timer


def test_systemctl_user_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ch.shutil, "which", lambda _: None)
    ok, detail = ch.systemctl_user(["daemon-reload"])
    assert ok is False and "systemctl not found" in detail


# -- install consent (the real T2 gate) ----------------------------------------


def test_install_without_consent_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    code = main(
        [
            "charter",
            "install",
            "nightly-cache",
            "--request",
            "update the package cache",
            "--playbook",
            "pkg.cache.refresh",
            "--no-timer",
        ]
    )
    assert code == 2  # non-tty without --yes: the ApprovalPolicy gate refuses
    assert not (tmp_path / "state" / "charters" / "nightly-cache.json").exists()


def test_install_with_explicit_consent_writes_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    code = main(
        [
            "--yes",
            "charter",
            "install",
            "nightly-cache",
            "--request",
            "update the package cache",
            "--playbook",
            "pkg.cache.refresh",
            "--no-timer",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "charter contract" in out and "failure->pause" in out
    assert "policy state changed" in out
    contract = json.loads((tmp_path / "state" / "charters" / "nightly-cache.json").read_text())
    assert contract["playbooks"] == ["pkg.cache.refresh"]


def test_install_invalid_contract_refused_pre_consent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    code = main(
        [
            "--yes",
            "charter",
            "install",
            "nightly-cache",
            "--request",
            "update the package cache",
            "--playbook",
            "pkg.upgrade",
            "--tier-ceiling",
            "1",
            "--no-timer",
        ]
    )
    assert code == 2  # validation happens before the consent prompt
    assert not (tmp_path / "state" / "charters").exists()


# -- run flow through the kernel ------------------------------------------------


def make_run_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runner: FakeRunner) -> Path:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("jarvis.cli.app.LocalRunner", lambda: runner)
    return tmp_path


def install_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **overrides: Any) -> None:
    argv = [
        "--yes",
        "charter",
        "install",
        "nightly-cache",
        "--request",
        "update the package cache",
        "--playbook",
        "pkg.cache.refresh",
        "--no-timer",
        *(
            ["--monthly-runs", str(overrides["monthly_runs"])]
            if "monthly_runs" in overrides
            else []
        ),
    ]
    assert main(argv) == 0


def test_run_happy_path_journals_and_updates_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = FakeRunner()
    make_run_env(monkeypatch, tmp_path, runner)
    install_default(monkeypatch, tmp_path)
    assert main(["charter", "run", "nightly-cache"]) == 0
    state = ch.read_state("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path / "state")})
    assert state["runs"] == 1 and state["status"] == "active"
    assert runner.calls  # the playbook really executed through the runner


def test_run_dry_run_leaves_state_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = FakeRunner()
    make_run_env(monkeypatch, tmp_path, runner)
    install_default(monkeypatch, tmp_path)
    assert main(["charter", "run", "nightly-cache", "--dry-run"]) == 0
    state = ch.read_state("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path / "state")})
    assert state["runs"] == 0
    assert runner.calls == []  # dry-run never executes


def test_run_failure_pauses_then_next_run_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = FakeRunner(script=[(("apt-get", "update"), make_result(100, "", "E:boom"))])
    make_run_env(monkeypatch, tmp_path, runner)
    install_default(monkeypatch, tmp_path)
    assert main(["charter", "run", "nightly-cache"]) == 1  # the firing failed
    state = ch.read_state("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path / "state")})
    assert state["status"] == "paused"  # circuit breaker opened
    code = main(["charter", "run", "nightly-cache"])  # the next firing refuses
    assert code == 2


def test_monthly_budget_exhaustion_pauses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = FakeRunner()
    make_run_env(monkeypatch, tmp_path, runner)
    install_default(monkeypatch, tmp_path, monthly_runs=1)
    assert main(["charter", "run", "nightly-cache"]) == 0  # budget 1/1 used
    code = main(["charter", "run", "nightly-cache"])  # second firing: over budget
    assert code == 2
    state = ch.read_state("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path / "state")})
    assert state["status"] == "paused" and "budget" in str(state["paused_reason"])


def test_tampered_contract_is_caught_at_run_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = FakeRunner()
    make_run_env(monkeypatch, tmp_path, runner)
    install_default(monkeypatch, tmp_path)
    contract_path = tmp_path / "state" / "charters" / "nightly-cache.json"
    tampered = json.loads(contract_path.read_text())
    tampered["playbooks"] = ["pkg.upgrade"]  # above the T1 ceiling
    contract_path.write_text(json.dumps(tampered))
    code = main(["charter", "run", "nightly-cache"])
    assert code == 2  # load-time validation refuses the tampered contract outright
    assert runner.calls == []  # nothing ran


def test_semantic_drift_pauses_via_precheck(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Valid schema, but the request stops resolving to an allowlisted playbook
    (e.g. the registry changed): precheck pauses instead of improvising."""
    runner = FakeRunner()
    make_run_env(monkeypatch, tmp_path, runner)
    install_default(monkeypatch, tmp_path)
    contract_path = tmp_path / "state" / "charters" / "nightly-cache.json"
    drifted = json.loads(contract_path.read_text())
    drifted["request"] = "frobnicate the widget"  # single valid line; matches nothing
    contract_path.write_text(json.dumps(drifted))
    code = main(["charter", "run", "nightly-cache"])
    assert code == 2
    state = ch.read_state("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path / "state")})
    assert state["status"] == "paused"  # circuit breaker opened by precheck
    assert "no longer matches any playbook" in str(state["paused_reason"])
    assert runner.calls == []


def test_revoked_charter_refuses_forever(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = FakeRunner()
    make_run_env(monkeypatch, tmp_path, runner)
    install_default(monkeypatch, tmp_path)
    assert main(["charter", "revoke", "nightly-cache"]) == 0
    assert main(["charter", "run", "nightly-cache"]) == 2
    state = ch.read_state("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path / "state")})
    assert state["status"] == "revoked"
    assert runner.calls == []


def test_pause_resume_cycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = FakeRunner()
    make_run_env(monkeypatch, tmp_path, runner)
    install_default(monkeypatch, tmp_path)
    assert main(["charter", "pause", "nightly-cache"]) == 0
    assert main(["charter", "run", "nightly-cache"]) == 2
    assert main(["charter", "resume", "nightly-cache"]) == 0
    assert main(["charter", "run", "nightly-cache"]) == 0
    state = ch.read_state("nightly-cache", {"JARVIS_STATE_DIR": str(tmp_path / "state")})
    assert state["status"] == "active" and state["runs"] == 1


# -- integrity integration ------------------------------------------------------


def test_charters_sit_inside_the_integrity_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from jarvis.safety.integrity import default_scope

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    install_default(monkeypatch, tmp_path)
    names = {path.name for path in default_scope().entries()}
    assert "nightly-cache.json" in names  # contract bytes are baselined...
    assert "nightly-cache.state" not in names  # ...operational state is not


def test_charter_parser_wiring() -> None:
    args = build_parser().parse_args(["charter", "run", "x", "--dry-run"])
    assert args.charter_command == "run" and args.dry_run is True
    args = build_parser().parse_args(
        ["charter", "install", "x", "--request", "r", "--playbook", "p"]
    )
    assert args.charter_command == "install" and args.tier_ceiling == 1
