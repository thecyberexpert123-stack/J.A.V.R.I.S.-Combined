"""Snapshot preflight behavior: tool detection, honest degradation, wiring."""

from __future__ import annotations

import json

from conftest import FakeRunner, make_profile, make_result
from jarvis.core.orchestrator import Orchestrator
from jarvis.safety.approval import ApprovalPolicy
from jarvis.safety.snapshots import SnapshotManager


def _manager(script=None, present=("snapper",)):  # type: ignore[no-untyped-def]
    runner = FakeRunner(script=script or [])
    mgr = SnapshotManager(runner, which=lambda b: f"/usr/bin/{b}" if b in present else None)
    return mgr, runner


def test_snapper_preferred_and_invoked() -> None:
    mgr, runner = _manager(
        script=[(("snapper", "create"), make_result(0, "", ""))], present=("snapper",)
    )
    result = mgr.create("task abc: pkg.upgrade")
    assert result.status == "created"
    assert result.tool == "snapper"
    argv, used_root, _env = runner.calls[0]
    assert argv[:2] == ("snapper", "create")
    assert any("jarvis" in part for part in argv)
    assert used_root is True


def test_timeshift_fallback() -> None:
    mgr, runner = _manager(
        script=[(("timeshift", "--create"), make_result(0, "", ""))], present=("timeshift",)
    )
    result = mgr.create("x")
    assert result.status == "created"
    assert result.tool == "timeshift"
    assert runner.calls[0][0][:2] == ("timeshift", "--create")


def test_no_tools_reports_unavailable_honestly() -> None:
    mgr, runner = _manager(present=())
    result = mgr.create("x")
    assert result.status == "unavailable"
    assert result.tool == "none"
    assert "snapper" in result.note()
    assert runner.calls == []


def test_all_tools_failing_reports_failure_with_detail() -> None:
    mgr, _runner = _manager(
        script=[
            (("snapper", "create"), make_result(1, "", "no config for 'root'")),
            (("timeshift", "--create"), make_result(1, "", "device not supported")),
        ],
        present=("snapper", "timeshift"),
    )
    result = mgr.create("x")
    assert result.status == "failed"
    # the last attempted tool's failure is reported
    assert result.tool == "timeshift"
    assert "device not supported" in result.detail


def test_orchestrator_t2_records_snapshot_metadata(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("apt-get", "update"), make_result(0)),
            (("apt-get", "upgrade"), make_result(0)),
        ]
    )
    snap_runner = FakeRunner(script=[(("snapper", "create"), make_result(0, "", "ID 42"))])
    manager = SnapshotManager(
        snap_runner, which=lambda b: "/usr/bin/snapper" if b == "snapper" else None
    )
    orch = Orchestrator(
        make_profile(),
        journal,
        runner,
        ApprovalPolicy(yes=True),
        echo=False,
        snapshot_manager=manager,
    )
    outcome = orch.run_intent("upgrade system")
    assert outcome.status.value == "succeeded"
    assert "snapper" in outcome.snapshot_note
    task_id = outcome.task_id
    raw = journal.get_meta(task_id, "snapshot")
    assert raw is not None
    meta = json.loads(raw)
    assert meta["status"] == "created"
    assert meta["tool"] == "snapper"
    # snapshot ran through its own runner, not the task runner
    assert all(c[0][0] != "snapper" for c in runner.calls)


def test_orchestrator_t1_skips_snapshots(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("apt-get", "install"), make_result(0, "ok", "")),
            (("dpkg-query", "-W"), make_result(0, "ii  x", "")),
        ]
    )
    calls: list[str] = []

    class Counting(SnapshotManager):
        def create(self, label: str):  # type: ignore[no-untyped-def]
            calls.append(label)
            return super().create(label)

    manager = Counting(FakeRunner(), which=lambda _b: None)
    orch = Orchestrator(
        make_profile(),
        journal,
        runner,
        ApprovalPolicy(yes=True),
        echo=False,
        snapshot_manager=manager,
    )
    outcome = orch.run_intent("install htop")
    assert outcome.status.value == "succeeded"
    assert outcome.snapshot_note == ""
    assert calls == []


def test_snapshot_failure_never_blocks_approved_task(journal) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(
        script=[
            (("apt-get", "update"), make_result(0)),
            (("apt-get", "upgrade"), make_result(0)),
        ]
    )
    manager = SnapshotManager(
        FakeRunner(script=[(("snapper", "create"), make_result(1, "", "boom"))]),
        which=lambda b: "/usr/bin/snapper" if b == "snapper" else None,
    )
    orch = Orchestrator(
        make_profile(),
        journal,
        runner,
        ApprovalPolicy(yes=True),
        echo=False,
        snapshot_manager=manager,
    )
    outcome = orch.run_intent("upgrade system")
    assert outcome.status.value == "succeeded"
    assert "failed" in outcome.snapshot_note
