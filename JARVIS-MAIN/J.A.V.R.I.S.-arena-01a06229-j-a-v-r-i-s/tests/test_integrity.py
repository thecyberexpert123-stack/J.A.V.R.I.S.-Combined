"""Policy-state integrity (ADR-0013 M9c): baseline, drift, doctor CLI, canaries.

Scope objects point at tmp files so the real repository is never mutated by
tests; the doctor/status CLI tests monkeypatch ``default_scope`` the same way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.cli.app import _integrity_line, build_parser, main
from jarvis.safety import integrity

# -- baseline engine (tmp scope; real repo untouched) -------------------------


def seed_files(tmp_path: Path) -> None:
    """Create the scope files exactly once; tmp_scope() must stay a pure builder."""
    (tmp_path / "policy_a.json").write_text('{"v": 1}\n')
    (tmp_path / "kernel.py").write_text("FLAG = True\n")


def tmp_scope(tmp_path: Path) -> integrity.IntegrityScope:
    return integrity.IntegrityScope(
        files=(tmp_path / "policy_a.json", tmp_path / "kernel.py"), dirs=()
    )


def test_baseline_roundtrip_is_clean(tmp_path: Path) -> None:
    seed_files(tmp_path)
    baseline = tmp_path / "baseline.json"
    doc = integrity.write_baseline(baseline, env={}, scope=tmp_scope(tmp_path))
    assert doc["schema"] == integrity.BASELINE_SCHEMA
    report = integrity.verify(baseline, env={}, scope=tmp_scope(tmp_path))
    assert report.clean
    assert [row.status for row in report.rows] == ["ok", "ok"]


def test_changed_file_is_reported(tmp_path: Path) -> None:
    seed_files(tmp_path)
    baseline = tmp_path / "baseline.json"
    integrity.write_baseline(baseline, env={}, scope=tmp_scope(tmp_path))
    (tmp_path / "kernel.py").write_text("FLAG = False\n")  # the silent-relaxation attack
    report = integrity.verify(baseline, env={}, scope=tmp_scope(tmp_path))
    drift = {row.path.name: row.status for row in report.drift}
    assert drift == {"kernel.py": "changed"}
    assert not report.clean


def test_missing_and_added_files_are_reported(tmp_path: Path) -> None:
    seed_files(tmp_path)
    baseline = tmp_path / "baseline.json"
    scope_files = tmp_scope(tmp_path).files
    integrity.write_baseline(
        baseline, env={}, scope=integrity.IntegrityScope(files=scope_files, dirs=())
    )
    (tmp_path / "kernel.py").unlink()
    extra = tmp_path / "surprise.py"
    extra.write_text("import os  # not in baseline\n")
    report = integrity.verify(
        baseline,
        env={},
        scope=integrity.IntegrityScope(files=(*scope_files, extra), dirs=()),
    )
    statuses = {row.path.name: row.status for row in report.drift}
    assert statuses == {"kernel.py": "missing", "surprise.py": "added"}


def test_absent_optional_files_are_not_false_alarm(tmp_path: Path) -> None:
    ghost = tmp_path / "does-not-exist.marker"
    baseline = tmp_path / "baseline.json"
    integrity.write_baseline(
        baseline, env={}, scope=integrity.IntegrityScope(files=(ghost,), dirs=())
    )
    report = integrity.verify(
        baseline, env={}, scope=integrity.IntegrityScope(files=(ghost,), dirs=())
    )
    assert report.clean  # optional file absent on both sides: no drift, no crash


# -- doctor CLI ----------------------------------------------------------------


@pytest.fixture()
def patched_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    seed_files(tmp_path)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(integrity, "default_scope", lambda: tmp_scope(tmp_path))
    return tmp_path


def test_doctor_without_baseline_exits_2_with_guidance(
    patched_scope: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["doctor"]) == 2
    out = capsys.readouterr().out
    assert "no integrity baseline" in out
    assert "--write-baseline" in out


def test_doctor_write_then_verify_is_clean_and_json(
    patched_scope: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["doctor", "--write-baseline"]) == 0
    assert "baseline written" in capsys.readouterr().out
    assert main(["--json", "doctor"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["clean"] is True
    assert doc["entries"] == 2


def test_doctor_reports_drift_exit_1(
    patched_scope: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["doctor", "--write-baseline"]) == 0
    (patched_scope / "kernel.py").write_text("FLAG = False\n")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "DRIFT" in out and "[changed]" in out and "kernel.py" in out
    assert "--write-baseline" in out  # the deliberate re-baseline instruction


def test_status_line_reflects_baseline_states(patched_scope: Path) -> None:
    assert "no baseline" in _integrity_line()
    assert main(["doctor", "--write-baseline"]) == 0
    assert "verified (2 entries" in _integrity_line()
    (patched_scope / "kernel.py").write_text("FLAG = False\n")
    assert "DRIFT" in _integrity_line()


def test_status_never_crashes_on_integrity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))

    def boom() -> str:
        raise RuntimeError("probe exploded")

    monkeypatch.setattr("jarvis.cli.app._integrity_line", boom)
    assert main(["--json", "status"]) == 0  # the crash is contained like every status probe
    capsys.readouterr()  # drain


def test_doctor_parser_wiring() -> None:
    args = build_parser().parse_args(["doctor", "--write-baseline"])
    assert args.write_baseline is True
    args = build_parser().parse_args(["doctor", "--canaries"])
    assert args.canaries is True


# -- canaries ------------------------------------------------------------------


def test_canary_issue_and_read_are_round_trippable(tmp_path: Path) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path)}
    token = integrity.issue_canary("test", env=env)
    assert token.startswith(integrity.CANARY_PREFIX)
    records = integrity.read_canaries(env=env)
    assert len(records) == 1
    assert records[0]["canary"] == token
    assert records[0]["surface"] == "test"
    other = integrity.issue_canary("test", env=env)
    assert other != token  # per-invocation uniqueness is the point
    assert len(integrity.read_canaries(env=env)) == 2


def test_cli_suggest_human_output_carries_canary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    fake = {
        "id": "test:suggestion",
        "title": "a fake suggestion",
        "detail": "for canary testing",
        "command": "true",
        "evidence": [],
    }
    monkeypatch.setattr("jarvis.cli.app._suggest_target", lambda: [fake])
    assert main(["suggest"]) == 0
    out = capsys.readouterr().out
    assert "jarvis-canary-" in out
    assert "jarvis doctor --canaries" in out
    records = integrity.read_canaries()
    assert len(records) == 1 and records[0]["surface"] == "cli"


def test_cli_suggest_json_shape_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    fake = {
        "id": "test:suggestion",
        "title": "t",
        "detail": "d",
        "command": "true",
        "evidence": [],
    }
    monkeypatch.setattr("jarvis.cli.app._suggest_target", lambda: [fake])
    assert main(["--json", "suggest"]) == 0
    docs = json.loads(capsys.readouterr().out)
    assert isinstance(docs, list) and docs[0]["id"] == "test:suggestion"  # bare list, no wrapper


def test_doctor_canaries_listing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    integrity.issue_canary("mcp", env=None)
    assert main(["doctor", "--canaries"]) == 0
    out = capsys.readouterr().out
    assert "[mcp]" in out and integrity.CANARY_PREFIX in out


# -- missing baseline file is an honest error, not a fake pass -----------------


def test_verify_tolerates_missing_baseline_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        integrity.verify(tmp_path / "nope.json", env={}, scope=tmp_scope(tmp_path))


# -- the context store chain is part of the doctor's verdict -------------------


def test_doctor_flags_tampered_context_store(
    patched_scope: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import os
    import sqlite3

    from jarvis.context.store import ContextStore

    assert main(["doctor", "--write-baseline"]) == 0
    db_path = Path(os.environ["JARVIS_STATE_DIR"]) / "context.db"
    store = ContextStore(db_path)
    store.record_feedback("a:1", "accepted", reason="honest calibration")
    store.close()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE feedback SET reason = 'poisoned after the fact'")
    conn.commit()
    conn.close()
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "TAMPERED" in out and "a:1" in out
