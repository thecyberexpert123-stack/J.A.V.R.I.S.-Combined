"""Full task-lifecycle behavior: success, failure, verification, gates, undo,
interrupt, dry-run — all against a scripted runner and a temp journal."""

from __future__ import annotations

from conftest import FakeRunner, make_profile, make_result
from jarvis.core.orchestrator import Orchestrator
from jarvis.planner.models import TaskStatus, UndoStatus
from jarvis.safety.approval import ApprovalPolicy


def make_orch(journal, runner, *, yes: bool = True, root: bool = True) -> Orchestrator:  # type: ignore[no-untyped-def]
    profile = make_profile(is_root=root)
    return Orchestrator(profile, journal, runner, ApprovalPolicy(yes=yes), echo=False)


def test_unmatched_intent_is_refused_not_guessed(journal) -> None:  # type: ignore[no-untyped-def]
    outcome = make_orch(journal, FakeRunner()).run_intent("say hello to my little friend")
    assert outcome.status is TaskStatus.REFUSED
    assert outcome.exit_code() == 2
    assert "will not guess" in outcome.error
    assert "pkg.install" in outcome.hint


def test_install_success_flow(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("apt-get", "install"), make_result(0, "Setting up htop ...", "")),
            (("dpkg-query", "-W"), make_result(0, "ii  htop", "")),
        ]
    )
    orch = make_orch(journal, runner)
    outcome = orch.run_intent("install htop")
    assert outcome.status is TaskStatus.SUCCEEDED
    assert outcome.exit_code() == 0
    assert outcome.verification is not None and outcome.verification.ok
    assert outcome.undo_status is UndoStatus.AVAILABLE
    # install command recorded with root and noninteractive env
    run_argv, used_root, run_env = runner.calls[0]
    assert run_argv == ("apt-get", "install", "-y", "--", "htop")
    assert used_root is True
    assert run_env is not None and run_env["DEBIAN_FRONTEND"] == "noninteractive"
    # journal rows exist and undo artifact is retrievable
    task = journal.get_task(outcome.task_id)
    assert task is not None and task["status"] == "succeeded"
    assert journal.get_undo(outcome.task_id) is not None


def test_install_command_failure(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[(("apt-get", "install"), make_result(100, "", "E: Unable to locate package x"))]
    )
    orch = make_orch(journal, runner)
    outcome = orch.run_intent("install htop")
    assert outcome.status is TaskStatus.FAILED
    assert outcome.exit_code() == 1
    assert "exit code 100" in outcome.error
    # undo artifact kept even for failed mutations (partial state remediation)
    assert outcome.undo_status is UndoStatus.AVAILABLE


def test_verification_failure_after_successful_command(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("apt-get", "install"), make_result(0)),
            (("dpkg-query", "-W"), make_result(1, "", "dpkg-query: no entries found")),
        ]
    )
    orch = make_orch(journal, runner)
    outcome = orch.run_intent("install htop")
    assert outcome.status is TaskStatus.FAILED
    assert outcome.verification is not None and not outcome.verification.ok


def test_protected_removal_refused(journal) -> None:  # type: ignore[no-untyped-def]
    orch = make_orch(journal, FakeRunner())
    outcome = orch.run_intent("remove libc6")
    assert outcome.status is TaskStatus.REFUSED
    assert outcome.exit_code() == 2
    assert "boot-critical" in outcome.error
    # nothing executed
    assert not outcome.steps or all(s["status"] != "succeeded" for s in outcome.steps)


def test_t2_requires_consent_in_non_interactive_mode(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner()
    orch = make_orch(journal, runner, yes=False, root=True)
    outcome = orch.run_intent("upgrade system")
    assert outcome.status is TaskStatus.REFUSED
    assert outcome.exit_code() == 2
    assert "--yes" in outcome.error
    # refusal is journaled and auditable
    assert outcome.task_id is not None
    task = journal.get_task(outcome.task_id)
    assert task is not None and task["status"] == "refused"
    # and nothing executed
    assert runner.calls == []


def test_t2_with_consent_executes(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("apt-get", "update"), make_result(0)),
            (("apt-get", "upgrade"), make_result(0)),
        ]
    )
    orch = make_orch(journal, runner, yes=True)
    outcome = orch.run_intent("upgrade system")
    assert outcome.status is TaskStatus.SUCCEEDED
    assert outcome.tier == 2
    # upgrade has no automatic undo — honestly unavailable
    assert outcome.undo_status is UndoStatus.UNAVAILABLE


def test_svc_start_and_undo_roundtrip(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("systemctl", "start"), make_result(0)),
            (("systemctl", "is-active"), make_result(0, "active", "")),
            (("systemctl", "stop"), make_result(0)),
        ]
    )
    orch = make_orch(journal, runner)
    outcome = orch.run_intent("start ssh.service")
    assert outcome.status is TaskStatus.SUCCEEDED
    assert outcome.undo_status is UndoStatus.AVAILABLE
    task_id = outcome.task_id

    # undo: stop the service; post-condition 'not active' (exit != 0)
    undo_runner = FakeRunner(
        script=[
            (("systemctl", "stop"), make_result(0)),
            (("systemctl", "is-active"), make_result(3, "inactive", "")),
        ]
    )
    undo_outcome = make_orch(journal, undo_runner).undo(task_id)  # type: ignore[arg-type]
    assert undo_outcome.status is TaskStatus.SUCCEEDED
    original = journal.get_task(task_id)
    assert original is not None and original["status"] == "undone"
    artifact = journal.get_undo(task_id)
    assert artifact is not None and artifact["status"] == "applied"
    # undoing twice is refused
    second = make_orch(journal, undo_runner).undo(task_id)  # type: ignore[arg-type]
    assert second.status is TaskStatus.REFUSED


def test_undo_revalidates_tampered_journal(journal) -> None:  # type: ignore[no-untyped-def]
    # A user-editable journal must not become an execution primitive: plant an
    # artifact that removes a protected package.
    journal.begin_task("abcdef123456", "install htop", "pkg.install", 1, {}, {})
    journal.store_undo(
        "abcdef123456",
        {
            "reason": "tampered",
            "tier": 1,
            "steps": [
                {
                    "description": "evil",
                    "argv": ["apt-get", "remove", "-y", "--", "libc6"],
                    "requires_root": True,
                    "timeout_s": 300,
                    "extra_env": {},
                }
            ],
            "verify_checks": [],
        },
    )
    orch = make_orch(journal, FakeRunner())
    outcome = orch.undo("abcdef123456")
    assert outcome.status is TaskStatus.REFUSED
    assert "revalidation" in outcome.error
    assert "boot-critical" in outcome.error


def test_undo_without_artifact_refused(journal) -> None:  # type: ignore[no-untyped-def]
    outcome = make_orch(journal, FakeRunner()).undo("000000000000")
    assert outcome.status is TaskStatus.REFUSED


def test_interrupt_via_signal_exit_code(journal) -> None:  # type: ignore[no-untyped-def]
    # upgrade on apt has two steps; the second gets killed by a signal.
    runner = FakeRunner(
        script=[
            (("apt-get", "update"), make_result(0)),
            (("apt-get", "upgrade"), make_result(-15, "Partial upgrade...", "")),
        ]
    )
    orch = make_orch(journal, runner)
    outcome = orch.run_intent("upgrade system")
    assert outcome.status is TaskStatus.INTERRUPTED
    assert outcome.exit_code() == 130
    statuses = [s["status"] for s in outcome.steps]
    assert statuses == ["succeeded", "failed"]  # interrupted step recorded, none skipped beyond
    task = journal.get_task(outcome.task_id)
    assert task is not None and task["status"] == "interrupted"


def test_dry_run_executes_and_journals_nothing(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner()
    orch = make_orch(journal, runner)
    outcome = orch.run_intent("install htop", dry_run=True)
    assert outcome.status is TaskStatus.DRY_RUN
    assert outcome.exit_code() == 0
    assert runner.calls == []
    assert journal.recent_tasks() == []


def test_unsupported_backend_reported_honestly(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner()
    profile = make_profile(pm=None)
    orch = Orchestrator(profile, journal, runner, ApprovalPolicy(yes=True), echo=False)
    outcome = orch.run_intent("install htop")
    assert outcome.status is TaskStatus.FAILED
    assert "no supported package manager" in outcome.error

    from dataclasses import replace

    orch = Orchestrator(
        replace(profile, init_system="other:openrc"),
        journal,
        runner,
        ApprovalPolicy(yes=True),
        echo=False,
    )
    outcome = orch.run_intent("start ssh")
    assert outcome.status is TaskStatus.FAILED
    assert "systemd" in outcome.error


def test_privilege_error_marks_step_failed(journal) -> None:  # type: ignore[no-untyped-def]
    from jarvis.system.models import PrivilegeError

    runner = FakeRunner(script=[(("apt-get", "install"), PrivilegeError("no usable 'sudo'"))])
    outcome = make_orch(journal, runner).run_intent("install htop")
    assert outcome.status is TaskStatus.FAILED
    assert "failed to start" in outcome.error
    steps = outcome.steps
    assert steps[0]["status"] == "failed"
