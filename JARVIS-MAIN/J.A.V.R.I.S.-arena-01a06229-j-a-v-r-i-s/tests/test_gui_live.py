"""Live GUI tests (RUN_LIVE=1): honest behavior on THIS machine, headless or not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.gui.detect import probe

pytestmark = pytest.mark.live


def test_gui_probe_never_crashes() -> None:
    env = probe()
    assert env.session_type in ("x11", "wayland", "headless")


def test_cli_gui_status_honest(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    assert main(["--json", "gui", "status"]) == 0
    data = json.loads(capsys.readouterr().out)
    session = data["session"]
    if probe().headless:
        assert session["session_type"] == "headless"
        caps = data["capabilities"]
        assert caps["type_text"]["backend"] is None


def test_cli_gui_wizard_honest(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    assert main(["--json", "gui", "wizard"]) == 0
    checks = json.loads(capsys.readouterr().out)
    assert checks and all({"name", "ok", "detail", "fix"} <= set(c) for c in checks)
