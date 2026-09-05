"""CLI surface tests: parsing, exit codes, JSON output, human output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.cli.app import build_parser, main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "jarvis" in capsys.readouterr().out


def test_parser_requires_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_playbooks_json_lists_all(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json", "playbooks"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 58  # ADR-0016 breadth + ADR-0024 digest + ADR-0026 gui.app
    assert {entry["id"] for entry in data} >= {"pkg.install", "sys.info", "file.append"}


def test_playbooks_human_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["playbooks"]) == 0
    out = capsys.readouterr().out
    assert "pkg.install" in out
    assert "T2" in out


def test_status_json_reports_distro(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json", "status"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "distro_id" in data
    assert "package_manager" in data


def test_do_dry_run_json(capsys: pytest.CaptureFixture[str]) -> None:
    # This sandbox is Debian with apt present: the dry run builds a real plan
    # but executes and journals nothing.
    assert main(["--json", "do", "--dry-run", "install", "htop"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "dry_run"
    assert data["playbook"] == "pkg.install"
    assert data["steps"][0]["argv"] == ["apt-get", "install", "-y", "--", "htop"]


def test_do_unmatched_exit_code(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert main(["--json", "do", "make me a sandwich"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "refused"


def test_do_with_invalid_package_name_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert main(["--json", "do", "--", "install", "-rf"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "refused"
    assert "invalid" in data["error"]


def test_tasks_empty_journal(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert main(["tasks"]) == 0
    assert "no tasks journaled" in capsys.readouterr().out


def test_tasks_json_after_dry_run_stays_empty(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    main(["do", "--dry-run", "system info"])
    capsys.readouterr()  # drop human output of the dry run
    assert main(["--json", "tasks"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_undo_malformed_id(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert main(["--json", "undo", "../../etc/passwd"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "refused"
