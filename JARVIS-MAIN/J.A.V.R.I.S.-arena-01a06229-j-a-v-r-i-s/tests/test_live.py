"""Live integration tests (opt-in: RUN_LIVE=1) — real commands on the host.

Scope discipline: only read-only operations and deliberately-failing privilege
paths run here. Real package mutations are covered by the distro-container
evaluation harness (CI), never on developer hosts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.core.fingerprint import build_profile
from jarvis.core.orchestrator import Orchestrator
from jarvis.execution.runner import LocalRunner
from jarvis.journal.sqlite import Journal, default_db_path
from jarvis.planner.models import TaskStatus
from jarvis.safety.approval import ApprovalPolicy

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def live_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state"


def test_real_system_info_task(live_env: Path) -> None:
    profile = build_profile()
    journal = Journal(default_db_path())
    runner = LocalRunner()
    orch = Orchestrator(profile, journal, runner, ApprovalPolicy(yes=True), echo=False)
    outcome = orch.run_intent("system info")
    assert outcome.status is TaskStatus.SUCCEEDED
    assert outcome.verification is not None and outcome.verification.ok
    assert "Linux" in (outcome.verification.checks[0][2] or "")


def test_real_search_reports_empty_honestly(live_env: Path) -> None:
    profile = build_profile()
    journal = Journal(default_db_path())
    orch = Orchestrator(profile, journal, LocalRunner(), ApprovalPolicy(yes=True), echo=False)
    outcome = orch.run_intent("search htop")
    # apt present but lists may be empty: the query itself must not crash;
    # it reports zero-or-more result lines and exits 0.
    assert outcome.status is TaskStatus.SUCCEEDED
    assert outcome.verification is not None
    assert "result line(s)" in outcome.verification.detail


def test_real_install_without_privileges_fails_cleanly(live_env: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("running as root; the unprivileged failure path cannot be exercised")
    if not shutil.which("sudo"):
        pytest.skip("sudo not installed")
    profile = build_profile()
    journal = Journal(default_db_path())
    runner = LocalRunner()
    orch = Orchestrator(profile, journal, runner, ApprovalPolicy(yes=True), echo=False)
    outcome = orch.run_intent("install htop")
    # Either the step fails cleanly on credentials (no password prompt is ever
    # issued) or — if passwordless sudo works — it succeeds. Both are honest;
    # what is forbidden is hanging, crashing, or silent partial states.
    assert outcome.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED)
    assert outcome.task_id is not None
    task = journal.get_task(outcome.task_id)
    assert task is not None
    assert task["status"] == outcome.status.value
    if outcome.status is TaskStatus.FAILED:
        joined = " ".join(s.get("stderr_tail", "") for s in outcome.steps)
        assert "password" in joined or "sudo" in joined or outcome.error


def test_real_cli_module_entry(live_env: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "jarvis", "--json", "status"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "JARVIS_STATE_DIR": str(live_env)},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["distro_id"] in {"debian", "ubuntu"}  # this host family
    assert data["package_manager"] == "apt"


def test_real_ollama_smoke_if_present() -> None:
    """Real-model smoke: runs only when an Ollama is actually reachable."""
    from jarvis.providers.ollama import OllamaProvider

    provider = OllamaProvider()
    if not provider.available():
        pytest.skip("no Ollama reachable (set OLLAMA_HOST to enable)")
    reply = provider.complete("Reply with strict JSON only.", 'Return {"ok": true}', timeout_s=30)
    assert '"ok"' in reply
