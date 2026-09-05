"""Composite plan execution (run_plan): multi-part lifecycle, undo, gates."""

from __future__ import annotations

from conftest import FakeRunner, make_profile, make_result
from jarvis.core.orchestrator import Orchestrator
from jarvis.planner.models import TaskStatus, UndoStatus
from jarvis.planner.playbooks import match_intent
from jarvis.safety.approval import ApprovalPolicy


def make_orch(journal, runner, *, yes: bool = True) -> Orchestrator:  # type: ignore[no-untyped-def]
    return Orchestrator(
        make_profile(is_root=True), journal, runner, ApprovalPolicy(yes=yes), echo=False
    )


def _part(text: str):  # type: ignore[no-untyped-def]
    playbook, params = match_intent(text)
    assert playbook is not None
    return playbook, params


def test_empty_plan_refused(journal) -> None:  # type: ignore[no-untyped-def]
    outcome = make_orch(journal, FakeRunner()).run_plan("x", [])
    assert outcome.status is TaskStatus.REFUSED
    assert "empty plan" in outcome.error


def test_multi_part_plan_success_and_composite_undo(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("apt-get", "install"), make_result(0, "Setting up htop", "")),
            (("dpkg-query", "-W"), make_result(0, "ii  htop", "")),
            (("uname", "-a"), make_result(0, "Linux host 6.1 x86_64", "")),
            (("df", "-h"), make_result(0, "/dev/sda1 50G 20G 30G 40% /", "")),
            (("free", "-h"), make_result(0, "Mem: 8Gi", "")),
        ]
    )
    orch = make_orch(journal, runner)
    outcome = orch.run_plan(
        "set up monitoring",
        [_part("install htop"), _part("system info")],
        explanation="monitoring setup",
        provider_label="local:ollama/llama3.2",
    )
    assert outcome.status is TaskStatus.SUCCEEDED
    assert outcome.playbook_id == "plan"
    assert outcome.verification is not None and outcome.verification.ok
    assert outcome.undo_status is UndoStatus.AVAILABLE
    # composite journal row exists with intents + explanation
    task = journal.get_task(outcome.task_id)
    assert task is not None
    assert task["playbook_id"] == "plan/local:ollama/llama3.2"
    params = task["params"]
    assert params["intents"] == ["pkg.install", "sys.info"]
    assert params["explanation"] == "monitoring setup"
    # undo artifact reverses parts last-first: sys.info has no undo -> just remove
    artifact = journal.get_undo(outcome.task_id)
    assert artifact is not None
    steps = artifact["payload"]["steps"]
    assert [s["argv"][0] for s in steps] == ["apt-get"]


def test_unreversible_part_poisons_composite_undo(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("apt-get", "update"), make_result(0)),
            (("apt-get", "upgrade"), make_result(0)),
        ]
    )
    orch = make_orch(journal, runner, yes=True)  # T2 consented
    outcome = orch.run_plan("freshen up", [_part("upgrade system")])
    assert outcome.status is TaskStatus.SUCCEEDED
    assert outcome.undo_status is UndoStatus.UNAVAILABLE
    assert "cannot be reversed" in outcome.undo_reason


def test_t2_plan_requires_consent_and_journals_refusal(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner()
    orch = make_orch(journal, runner, yes=False)
    outcome = orch.run_plan("freshen up", [_part("upgrade system")])
    assert outcome.status is TaskStatus.REFUSED
    assert outcome.exit_code() == 2
    assert "--yes" in outcome.error
    assert runner.calls == []
    task = journal.get_task(outcome.task_id)
    assert task is not None and task["status"] == "refused"


def test_unsupported_part_fails_whole_plan(journal) -> None:  # type: ignore[no-untyped-def]

    runner = FakeRunner()
    profile = make_profile(is_root=True, init="other:openrc")
    orch = Orchestrator(profile, journal, runner, ApprovalPolicy(yes=True), echo=False)
    outcome = orch.run_plan("start and report", [_part("start ssh"), _part("system info")])
    assert outcome.status is TaskStatus.FAILED
    assert "svc.start" in outcome.error
    assert "systemd" in outcome.error
    assert runner.calls == []


def test_dry_run_plan_executes_nothing(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner()
    orch = make_orch(journal, runner)
    outcome = orch.run_plan(
        "set up monitoring",
        [_part("install htop"), _part("system info")],
        dry_run=True,
    )
    assert outcome.status is TaskStatus.DRY_RUN
    assert outcome.exit_code() == 0
    assert len(outcome.steps) == 4  # 1 install + 3 sysinfo steps
    assert runner.calls == []
    assert journal.recent_tasks() == []


def test_part_failure_keeps_undo_artifact(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(script=[(("apt-get", "install"), make_result(100, "", "E: boom"))])
    orch = make_orch(journal, runner)
    outcome = orch.run_plan("set up", [_part("install htop"), _part("system info")])
    assert outcome.status is TaskStatus.FAILED
    assert outcome.undo_status is UndoStatus.AVAILABLE
    assert journal.get_undo(outcome.task_id) is not None
