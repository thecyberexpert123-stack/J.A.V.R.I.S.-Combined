"""Journal round-trip and state-directory resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.journal.sqlite import Journal, default_db_path, state_dir


def test_task_roundtrip(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.db")
    journal.begin_task(
        "abcdef123456",
        "install htop",
        "pkg.install",
        1,
        {"names": ["htop"]},
        {"distro_id": "debian"},
    )
    journal.record_step(
        "abcdef123456",
        0,
        "install htop",
        ["apt-get", "install", "-y", "--", "htop"],
        True,
        1,
        "succeeded",
        exit_code=0,
        stdout_tail="Setting up htop",
    )
    journal.finish_task("abcdef123456", "succeeded")

    task = journal.get_task("abcdef123456")
    assert task is not None
    assert task["status"] == "succeeded"
    assert task["params"] == {"names": ["htop"]}
    steps = journal.steps_for_task("abcdef123456")
    assert steps[0]["argv"] == ["apt-get", "install", "-y", "--", "htop"]
    assert steps[0]["exit_code"] == 0

    recent = journal.recent_tasks(limit=5)
    assert [t["id"] for t in recent] == ["abcdef123456"]


def test_undo_artifact_lifecycle(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.db")
    journal.begin_task("abcdef123456", "install htop", "pkg.install", 1, {}, {})
    payload = {"reason": "removes htop", "steps": [], "verify_checks": []}
    assert journal.get_undo("abcdef123456") is None
    journal.store_undo("abcdef123456", payload)
    artifact = journal.get_undo("abcdef123456")
    assert artifact is not None
    assert artifact["status"] == "available"
    assert artifact["payload"] == payload
    journal.mark_undo_applied("abcdef123456", "fedcba654321")
    artifact = journal.get_undo("abcdef123456")
    assert artifact is not None
    assert artifact["status"] == "applied"
    assert artifact["applied_by"] == "fedcba654321"


def test_journal_file_permissions(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    Journal(db)
    mode = db.stat().st_mode & 0o777
    assert mode == 0o600


def test_state_dir_env_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom"
    monkeypatch.setenv("JARVIS_STATE_DIR", str(custom))
    assert state_dir() == custom
    monkeypatch.delenv("JARVIS_STATE_DIR")
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg))
    assert state_dir() == xdg / "jarvis"
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert state_dir() == tmp_path / "home" / ".local" / "state" / "jarvis"


def test_default_db_path_inside_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert default_db_path() == tmp_path / "journal.db"
