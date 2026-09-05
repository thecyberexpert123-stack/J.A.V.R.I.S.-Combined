"""M7 real-machine readiness: TOCTOU guard, preview/blast-radius, cautious mode,
auto-rollback, safety-check battery."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from conftest import FakeRunner
from jarvis.core.fingerprint import build_profile
from jarvis.core.orchestrator import Orchestrator
from jarvis.execution.runner import ExecResult
from jarvis.gui.service import GuiPolicyError, GuiService
from jarvis.journal.sqlite import Journal, state_dir
from jarvis.planner.models import PlannedStep
from jarvis.safety.approval import ApprovalPolicy, ApprovalRefused
from jarvis.safety.disclosure import blast_radius
from jarvis.safety.selftest import run_battery
from jarvis.safety.tiers import Tier


def _result(stdout: str = "", exit_code: int = 0) -> ExecResult:
    return ExecResult(exit_code=exit_code, stdout_tail=stdout, stderr_tail="")


def _which(names: tuple[str, ...]):  # type: ignore[no-untyped-def]
    return lambda name: f"/usr/bin/{name}" if name in names else None


@pytest.fixture()
def journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "j.db")


# -- TOCTOU guard ---------------------------------------------------------------


class SequenceRunner(FakeRunner):
    """Returns script entries in ORDER (consuming each on match) — unlike
    FakeRunner's first-match semantics. Models probe results that change
    between calls (the TOCTOU scenario)."""

    def __init__(self, sequence: list[tuple[tuple[str, ...], ExecResult]]) -> None:
        self._seq = list(sequence)
        self.executed: list[tuple[str, ...]] = []
        super().__init__()

    def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
        key = tuple(argv)
        self.calls.append((key, kwargs.get("requires_root", False), None))
        for i, (prefix, value) in enumerate(self._seq):
            if key[: len(prefix)] == prefix:
                self._seq.pop(i)
                self.executed.append(key)
                assert isinstance(value, ExecResult)
                return value
        return ExecResult(0, "", "", False)


def test_type_aborts_when_focus_changes_mid_approval(journal: Journal) -> None:
    probe = ("xdotool", "getactivewindow", "getwindowname")
    runner = SequenceRunner(
        [
            (probe, _result("xterm — honest")),
            (probe, _result("Firefox — SURPRISE")),
        ]
    )
    service = GuiService(
        runner,
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool",)),
    )
    with pytest.raises(GuiPolicyError, match="focus changed during approval"):
        service.type_text("payload")
    assert not any(c[:2] == ("xdotool", "type") for c in runner.executed), (
        "injection must not run after a focus change"
    )


def test_key_aborts_when_focus_changes_mid_approval(journal: Journal) -> None:
    probe = ("xdotool", "getactivewindow", "getwindowname")
    runner = SequenceRunner(
        [
            (probe, _result("xterm — a")),
            (probe, _result("xterm — b")),
        ]
    )
    service = GuiService(
        runner,
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool",)),
    )
    with pytest.raises(GuiPolicyError, match="TOCTOU guard"):
        service.key("Return")


def test_type_proceeds_when_focus_stable(journal: Journal) -> None:
    probe = ("xdotool", "getactivewindow", "getwindowname")
    runner = SequenceRunner(
        [
            (probe, _result("xterm — stable")),
            (probe, _result("xterm — stable")),
            (("xdotool", "type"), _result()),
        ]
    )
    service = GuiService(
        runner,
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool",)),
    )
    outcome = service.type_text("hi")
    assert outcome.status == "done"
    assert any(c[:2] == ("xdotool", "type") for c in runner.executed)


# -- blast radius -----------------------------------------------------------------


def test_blast_radius_summary() -> None:
    steps = [
        {"argv": ["apt-get", "update"], "requires_root": True, "tier": 1},
        {"argv": ["apt-get", "install", "-y", "--", "htop"], "requires_root": True, "tier": 1},
        {"argv": ["tee", "-a", "/etc/sysctl.conf"], "requires_root": False, "tier": 2},
        {"argv": ["tee", "-a", "/home/me/notes.txt"], "requires_root": False, "tier": 1},
    ]
    radius = blast_radius(steps)
    assert radius["requires_root"] is True
    assert radius["network"] is True
    assert radius["max_tier"] == 2
    assert "apt-get" in radius["commands"] and "tee" in radius["commands"]
    assert radius["paths"]["system"] == ["/etc/sysctl.conf"]
    assert radius["paths"]["home"] == ["/home/me/notes.txt"]


def test_blast_radius_empty_plan() -> None:
    radius = blast_radius([])
    assert radius["commands"] == [] and radius["requires_root"] is False


# -- cautious mode ------------------------------------------------------------------


def test_cautious_blocks_t2_even_with_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    marker = state_dir() / "cautious"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("on\n", encoding="utf-8")
    orch = Orchestrator(
        build_profile(),
        Journal(tmp_path / "j.db"),
        FakeRunner(),
        ApprovalPolicy(yes=True),
        echo=False,
    )
    outcome = orch.run_intent("upgrade the system")
    assert outcome.status.value == "refused"
    assert "cautious mode is ON" in (outcome.error or "")


def test_cautious_ok_overrides_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    marker = state_dir() / "cautious"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("on\n", encoding="utf-8")
    orch = Orchestrator(
        build_profile(),
        Journal(tmp_path / "j.db"),
        FakeRunner(),
        ApprovalPolicy(yes=True),
        echo=False,
        cautious_ok=True,
    )
    outcome = orch.run_intent("upgrade the system")
    assert outcome.status.value != "refused" or "cautious" not in (outcome.error or "")


def test_cautious_does_not_gate_t1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    marker = state_dir() / "cautious"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("on\n", encoding="utf-8")
    orch = Orchestrator(
        build_profile(),
        Journal(tmp_path / "j.db"),
        FakeRunner(),
        ApprovalPolicy(yes=True),
        echo=False,
    )
    outcome = orch.run_intent("system info")
    assert outcome.status.value == "succeeded"


# -- auto-rollback -------------------------------------------------------------------


def test_auto_rollback_restores_failed_file_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    target = tmp_path / "notes.txt"
    target.write_text("original\n", encoding="utf-8")

    class FailingSecond(FakeRunner):
        """cp backup succeeds; tee append fails -> task FAILED -> undo restores."""

        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            result = super().run(argv, **kwargs)
            if argv[0] == "tee":
                return ExecResult(exit_code=1, stdout_tail="", stderr_tail="boom")
            return result

    orch = Orchestrator(
        build_profile(),
        Journal(tmp_path / "j.db"),
        FailingSecond(),
        ApprovalPolicy(yes=True),
        echo=False,
        auto_rollback=True,
    )
    outcome = orch.run_intent(f"append hello to {target}")
    assert outcome.status.value == "failed"
    assert outcome.rolled_back is True
    assert outcome.rollback_task_id
    assert target.read_text(encoding="utf-8") == "original\n"
    task_row = Journal(tmp_path / "j.db").get_task(str(outcome.task_id))
    assert task_row is not None and task_row["status"] == "failed"
    undo_row = Journal(tmp_path / "j.db").get_undo(str(outcome.task_id))
    assert undo_row is not None and undo_row["status"] != "available"  # undo consumed by rollback


def test_no_auto_rollback_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    target = tmp_path / "notes.txt"
    target.write_text("original\n", encoding="utf-8")

    class FailingSecond(FakeRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            result = super().run(argv, **kwargs)
            if argv[0] == "tee":
                return ExecResult(exit_code=1, stdout_tail="", stderr_tail="boom")
            return result

    orch = Orchestrator(
        build_profile(),
        Journal(tmp_path / "j.db"),
        FailingSecond(),
        ApprovalPolicy(yes=True),
        echo=False,
    )
    outcome = orch.run_intent(f"append hello to {target}")
    assert outcome.status.value == "failed"
    assert outcome.rolled_back is False
    # undo artifact IS available for the user to apply manually
    assert orch._journal.get_undo(str(outcome.task_id)) is not None


# -- safety-check battery ------------------------------------------------------------


def test_safety_check_battery_all_pass() -> None:
    results = run_battery()
    assert results, "battery must contain checks"
    failed = [r for r in results if not r.ok]
    assert not failed, f"battery failures: {[(r.name, r.detail) for r in failed]}"


def test_safety_check_battery_covers_the_ladder() -> None:
    results = run_battery()
    names = " ".join(r.name for r in results)
    for expected in (
        "protected-package",
        "destructive",
        "smuggling",
        "protected file",
        "T2 requires explicit consent",
        "GUI injection",
        "nothing executed",
    ):
        assert expected in names, f"battery missing check for {expected!r}"


# -- approval guard still intact (sanity for the skip_consent path) -------------------


def test_undo_still_requires_consent_by_default(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "j.db")
    orch = Orchestrator(
        build_profile(),
        journal,
        FakeRunner(),
        ApprovalPolicy(yes=False, stdin=io.StringIO()),
        echo=False,
    )
    with pytest.raises(ApprovalRefused):
        orch._policy.decide(
            Tier.T2,
            [
                PlannedStep(description="x", argv=("tee", "-a", "/etc/sysctl.conf"), tier=Tier.T2),
            ],
        )


# -- CLI surface -----------------------------------------------------------------------


def test_cli_preview_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "do", "--preview", "install", "htop"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["preview"]["status"] == "dry_run"
    assert data["blast_radius"]["network"] is True
    assert "apt-get" in data["blast_radius"]["commands"]


def test_cli_safety_check(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "safety-check"]) == 0
    docs = _json_docs(capsys.readouterr().out)
    assert len(docs) >= 2
    checks, verdict = docs[:-1], docs[-1]
    assert checks, "expected per-check docs"
    assert all(isinstance(d, dict) and d.get("ok") is True for d in checks), (
        f"failed checks: {checks}"
    )
    assert isinstance(verdict, dict) and verdict["failed"] == 0


def test_cli_cautious_roundtrip(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["cautious", "on"]) == 0
    assert main(["--json", "cautious", "status"]) == 0
    assert _json_docs(capsys.readouterr().out)[-1] == {"cautious": True}
    assert main(["cautious", "off"]) == 0
    assert main(["--json", "cautious", "status"]) == 0
    assert _json_docs(capsys.readouterr().out)[-1] == {"cautious": False}


def _json_docs(text: str) -> list[object]:  # type: ignore[type-arg]
    """Extract JSON documents from a stream that may contain human-readable text."""
    decoder = json.JSONDecoder()
    docs: list[object] = []
    idx = text.find("{")
    while idx != -1:
        try:
            obj, end = decoder.raw_decode(text, idx)
            docs.append(obj)
            idx = text.find("{", end)
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
    return docs
