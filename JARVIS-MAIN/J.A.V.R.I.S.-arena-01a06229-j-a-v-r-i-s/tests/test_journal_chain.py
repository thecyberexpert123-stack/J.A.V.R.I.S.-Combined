"""ADR-0028: the task journal's evidence chain.

Covers the tamper matrix (edit, delete, forge, event deletion at the tail and
in the interior, head rewrite), the additive migration of a pre-chain
database (built with a schema-only replica of the pre-1.21 layout), the
"write that affected no row appends nothing" rule, concurrency across
processes (D2) and the doctor surface (D5). ``verify_chain`` must report and
never raise.
"""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
from itertools import pairwise
from pathlib import Path

import pytest

from jarvis.cli.app import main
from jarvis.journal.sqlite import CHAIN_VERSION, Journal

# The journal layout before ADR-0028 (no journal_chain / journal_meta): used to
# manufacture a "pre-chain" database exactly as an older jarvis would leave it.
_PRE_CHAIN_SCHEMA = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, intent_text TEXT NOT NULL,
    playbook_id TEXT NOT NULL, tier INTEGER NOT NULL, params_json TEXT NOT NULL,
    fingerprint_json TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE steps (
    task_id TEXT NOT NULL REFERENCES tasks(id), seq INTEGER NOT NULL,
    description TEXT NOT NULL, argv_json TEXT NOT NULL, requires_root INTEGER NOT NULL,
    tier INTEGER NOT NULL, status TEXT NOT NULL, exit_code INTEGER,
    stdout_tail TEXT NOT NULL DEFAULT '', stderr_tail TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (task_id, seq)
);
CREATE TABLE undo_artifacts (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id), payload_json TEXT NOT NULL,
    status TEXT NOT NULL, applied_by TEXT
);
CREATE TABLE task_meta (
    task_id TEXT NOT NULL REFERENCES tasks(id), key TEXT NOT NULL, value TEXT NOT NULL,
    PRIMARY KEY (task_id, key)
);
CREATE TABLE unknown_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_utc TEXT NOT NULL,
    request_text TEXT NOT NULL, reason TEXT NOT NULL, alternatives TEXT NOT NULL
);
"""


def _journal_with_one_task(path: Path) -> Journal:
    journal = Journal(path)
    journal.begin_task("t1", "install htop", "pkg.install", 1, {"names": ["htop"]}, {"d": "x"})
    journal.record_step(
        "t1", 0, "install", ["apt-get", "install", "-y", "--", "htop"], True, 1, "succeeded", 0
    )
    journal.store_undo("t1", {"steps": [], "verify_checks": []})
    journal.set_meta("t1", "snapshot", json.dumps({"status": "skipped"}))
    journal.finish_task("t1", "succeeded")
    journal.record_unknown_request("do the thing", "no match", ["a", "b"])
    return journal


def _raw(path: Path, sql: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(sql)
    conn.commit()
    conn.close()


# -- happy path -----------------------------------------------------------------


def test_fresh_journal_verifies_clean_with_no_events(tmp_path: Path) -> None:
    report = Journal(tmp_path / "j.db").verify_chain()
    assert report == {
        "events": 0,
        "legacy": 0,
        "rows": 0,
        "chain_ok": True,
        "rows_ok": True,
        "unchained_rows": 0,
        "detail": "",
        "ok": True,
    }


def test_every_write_links_one_event_inside_its_transaction(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    journal = _journal_with_one_task(db)
    report = journal.verify_chain()
    assert report["ok"] and report["chain_ok"] and report["rows_ok"]
    # begin, step, undo, meta, finish, unknown -> six events over five rows
    assert (report["events"], report["rows"], report["legacy"]) == (6, 5, 0)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    events = conn.execute("SELECT * FROM journal_chain ORDER BY seq").fetchall()
    assert [e["ref"] for e in events] == [
        "task:t1",
        "step:t1:0",
        "undo:t1",
        "meta:t1:snapshot",
        "task:t1",
        "unknown:1",
    ]
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5, 6]
    assert events[0]["prev_hash"] == ""
    for previous, current in pairwise(events):
        assert current["prev_hash"] == previous["entry_hash"]
    head = conn.execute("SELECT value FROM journal_meta WHERE key = 'chain_head'").fetchone()
    assert head["value"] == events[-1]["entry_hash"]
    since = conn.execute("SELECT value FROM journal_meta WHERE key = 'chain_since'").fetchone()
    assert since is not None
    version = conn.execute("SELECT value FROM journal_meta WHERE key='chain_version'").fetchone()
    assert version["value"] == str(CHAIN_VERSION)
    # the finish event attests the *updated* row, so the two task events differ
    assert events[0]["content_hash"] != events[4]["content_hash"]


def test_write_that_affects_no_row_appends_nothing(tmp_path: Path) -> None:
    journal = _journal_with_one_task(tmp_path / "j.db")
    journal.finish_task("does-not-exist", "succeeded")
    journal.mark_undo_applied("does-not-exist", "undo-1")
    assert journal.verify_chain()["events"] == 6


def test_public_read_api_shape_is_unchanged(tmp_path: Path) -> None:
    journal = _journal_with_one_task(tmp_path / "j.db")
    task = journal.get_task("t1")
    assert task is not None
    assert set(task) == {
        "id",
        "created_utc",
        "intent_text",
        "playbook_id",
        "tier",
        "params",
        "fingerprint",
        "status",
    }
    assert set(journal.steps_for_task("t1")[0]) == {
        "task_id",
        "seq",
        "description",
        "argv",
        "requires_root",
        "tier",
        "status",
        "exit_code",
        "stdout_tail",
        "stderr_tail",
    }
    assert set(journal.recent_tasks(1)[0]) == {
        "id",
        "created_utc",
        "intent_text",
        "playbook_id",
        "tier",
        "status",
    }
    undo = journal.get_undo("t1")
    assert undo is not None and set(undo) == {"payload", "status", "applied_by"}


# -- tamper matrix (each reopened through a fresh Journal, as `doctor` does) -------


def test_edited_row_is_reported(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _journal_with_one_task(db)
    _raw(db, "UPDATE tasks SET status = 'failed' WHERE id = 't1'")
    report = Journal(db).verify_chain()
    assert report["ok"] is False and report["chain_ok"] is True and report["rows_ok"] is False
    assert report["detail"] == "task:t1 differs from its last attested write"
    # putting the value back restores the verdict: the chain attests content, not time
    _raw(db, "UPDATE tasks SET status = 'succeeded' WHERE id = 't1'")
    assert Journal(db).verify_chain()["ok"] is True


def test_edited_step_output_is_reported(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _journal_with_one_task(db)
    _raw(db, "UPDATE steps SET exit_code = 1, stderr_tail = 'x' WHERE task_id = 't1'")
    assert "step:t1:0 differs" in str(Journal(db).verify_chain()["detail"])


def test_deleted_row_is_reported(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _journal_with_one_task(db)
    _raw(db, "DELETE FROM steps WHERE task_id = 't1'")
    report = Journal(db).verify_chain()
    assert report["ok"] is False
    assert report["detail"] == "step:t1:0 was attested but the row is gone (deleted)"


def test_forged_row_is_reported_as_unchained(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _journal_with_one_task(db)
    _raw(
        db,
        "INSERT INTO tasks VALUES ('evil', '2026-01-01T00:00:00+00:00', 'x', 'pkg.install',"
        " 1, '{}', '{}', 'succeeded')",
    )
    report = Journal(db).verify_chain()
    assert report["ok"] is False and report["unchained_rows"] == 1
    assert "never attested" in str(report["detail"]) and "task:evil" in str(report["detail"])


def test_deleting_trailing_events_is_reported(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _journal_with_one_task(db)
    _raw(db, "DELETE FROM journal_chain WHERE seq > 4")
    report = Journal(db).verify_chain()
    assert report["chain_ok"] is False
    assert str(report["detail"]).startswith("2 trailing event(s) deleted")
    # ...and a later legitimate write does not heal it: AUTOINCREMENT keeps the gap
    Journal(db).record_unknown_request("again", "no match", [])
    report = Journal(db).verify_chain()
    assert report["ok"] is False and "gap" in str(report["detail"])


def test_deleting_interior_event_is_reported(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _journal_with_one_task(db)
    _raw(db, "DELETE FROM journal_chain WHERE seq = 2")
    report = Journal(db).verify_chain()
    assert report["chain_ok"] is False
    assert report["detail"] == "event sequence gap before seq 3 (events deleted)"


def test_edited_event_and_rewritten_head_are_reported(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _journal_with_one_task(db)
    _raw(db, "UPDATE journal_chain SET kind = 'legacy' WHERE seq = 1")
    report = Journal(db).verify_chain()
    assert report["chain_ok"] is False and "event 1 hash mismatch" in str(report["detail"])
    _raw(db, "UPDATE journal_chain SET kind = 'write' WHERE seq = 1")
    assert Journal(db).verify_chain()["ok"] is True
    _raw(db, "UPDATE journal_meta SET value = 'deadbeef' WHERE key = 'chain_head'")
    assert Journal(db).verify_chain()["detail"] == "chain head does not match the last event"


def test_emptied_chain_table_is_reported_even_after_new_writes(tmp_path: Path) -> None:
    db = tmp_path / "j.db"
    _journal_with_one_task(db)
    _raw(db, "DELETE FROM journal_chain")
    journal = Journal(db)
    journal.record_unknown_request("after wipe", "no match", [])
    report = journal.verify_chain()
    assert report["ok"] is False
    # the new event took seq 7 (counter never reuses) -> visible gap from 1
    assert "gap" in str(report["detail"])
    assert report["unchained_rows"] == 5  # the original rows lost their attestations


# -- migration of a pre-chain database -----------------------------------------


def _pre_chain_db(path: Path, tasks: int) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_PRE_CHAIN_SCHEMA)
    for i in range(tasks):
        tid = f"{i:012x}"
        conn.execute(
            "INSERT INTO tasks VALUES (?, '2026-09-01T00:00:00+00:00', 'install htop',"
            " 'pkg.install', 1, '{}', '{}', 'succeeded')",
            (tid,),
        )
        conn.execute(
            "INSERT INTO steps VALUES (?, 0, 'install', '[\"apt-get\"]', 1, 1, 'succeeded',"
            " 0, '', '')",
            (tid,),
        )
    conn.commit()
    conn.close()


def test_pre_chain_database_is_absorbed_once_and_verified_from_then_on(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    _pre_chain_db(db, tasks=25)
    journal = Journal(db)  # first open with the chain -> backfill
    report = journal.verify_chain()
    assert report["ok"] is True
    assert (report["events"], report["legacy"], report["rows"]) == (50, 50, 50)
    # old rows are readable exactly as before
    task = journal.get_task(f"{3:012x}")
    assert task is not None and task["status"] == "succeeded" and task["params"] == {}
    # second open: no second backfill
    assert Journal(db).verify_chain()["events"] == 50
    # a post-upgrade edit of an old row is caught
    _raw(db, f"UPDATE tasks SET status = 'failed' WHERE id = '{7:012x}'")
    assert f"task:{7:012x} differs" in str(Journal(db).verify_chain()["detail"])
    # new writes after the upgrade chain onto the legacy events
    Journal(db).record_unknown_request("post-upgrade", "no match", [])
    report = Journal(db).verify_chain()
    assert report["events"] == 51 and report["legacy"] == 50 and report["chain_ok"] is True


def test_rows_written_by_a_pre_chain_version_after_upgrade_are_unchained(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    Journal(db)  # chained, empty
    # simulate a downgrade: an older jarvis inserts a row without an event
    _raw(
        db,
        "INSERT INTO tasks VALUES ('old1', '2026-09-01T00:00:00+00:00', 'x', 'pkg.install',"
        " 1, '{}', '{}', 'succeeded')",
    )
    report = Journal(db).verify_chain()
    assert report["ok"] is False and report["unchained_rows"] == 1
    assert "pre-chain version" in str(report["detail"])


# -- concurrency (ADR-0028 D2) --------------------------------------------------


def _writer(db: str, tag: str, count: int) -> None:
    journal = Journal(Path(db))
    for i in range(count):
        tid = f"{tag}{i:011x}"
        journal.begin_task(tid, "x", "pkg.install", 1, {}, {})
        journal.record_step(tid, 0, "s", ["true"], False, 0, "succeeded", 0)
        journal.finish_task(tid, "succeeded")


def _opener(db: str) -> None:
    Journal(Path(db))


def test_concurrent_writer_processes_produce_one_contiguous_chain(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_writer, args=(str(db), tag, 40)) for tag in "abc"]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=120)
    assert [proc.exitcode for proc in procs] == [0, 0, 0]
    report = Journal(db).verify_chain()
    assert report["ok"] is True
    assert (report["events"], report["rows"]) == (3 * 40 * 3, 3 * 40 * 2)


def test_simultaneous_first_opens_backfill_exactly_once(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    _pre_chain_db(db, tasks=60)
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_opener, args=(str(db),)) for _ in range(4)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=120)
    assert [proc.exitcode for proc in procs] == [0, 0, 0, 0]
    report = Journal(db).verify_chain()
    assert report["ok"] is True and (report["events"], report["legacy"]) == (120, 120)


# -- doctor surface (ADR-0028 D5) ------------------------------------------------


@pytest.fixture
def doctor_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Baseline over a tiny scope so `doctor` reaches the store/chain checks."""
    from jarvis.safety import integrity

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    scope_file = tmp_path / "scope.json"
    scope_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        integrity, "default_scope", lambda: integrity.IntegrityScope(files=(scope_file,), dirs=())
    )
    assert main(["doctor", "--write-baseline"]) == 0
    return tmp_path / "state"


def test_doctor_reports_journal_chain_ok(
    doctor_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _journal_with_one_task(doctor_env / "journal.db")
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "journal chain  : ok (6 events over 5 rows, 0 legacy)" in out
    assert main(["--json", "doctor"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["clean"] is True
    assert doc["journal_chain"]["ok"] is True and doc["journal_chain"]["events"] == 6


def test_doctor_flags_tampered_journal_exit_1(
    doctor_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = doctor_env / "journal.db"
    _journal_with_one_task(db)
    _raw(db, "UPDATE tasks SET status = 'failed' WHERE id = 't1'")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "journal chain  : TAMPERED" in out
    assert "task:t1 differs from its last attested write" in out
    assert "journal evidence chain FAILED" in out
    assert main(["--json", "doctor"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["clean"] is False and doc["journal_chain"]["ok"] is False
    # the pre-existing keys are still there for anyone reading the JSON
    assert {"baseline_version", "entries", "drift", "context_store"} <= set(doc)
