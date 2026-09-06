"""SQLite audit journal: tasks, steps, undo artifacts.

Every mutating task leaves a complete, replayable record here *before* it is
executed (undo artifacts are stored before the first step runs). The database
lives under the JARVIS state directory with 0600 permissions — it contains a
detailed picture of the machine and must not be world-readable.

Evidence chain (ADR-0028): every write to a journaled table appends one event
to ``journal_chain`` *inside the same transaction* — the SHA-256 of the row as
it now stands, linked to the previous event's hash. ``verify_chain()`` re-derives
the whole chain and compares each row's latest hash with the row as it exists
now, so edits, deletions and forgeries made outside this module are reported
by ``jarvis doctor``. Pre-chain rows are absorbed once on first open as
``legacy`` events (hashed as found; earlier edits are unknowable and said so).
Honest limitation, unchanged from M9c: arbitrary write access to the file can
recompute everything — the chain makes tampering *visible*, not impossible.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id               TEXT PRIMARY KEY,
    created_utc      TEXT NOT NULL,
    intent_text      TEXT NOT NULL,
    playbook_id      TEXT NOT NULL,
    tier             INTEGER NOT NULL,
    params_json      TEXT NOT NULL,
    fingerprint_json TEXT NOT NULL,
    status           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    task_id      TEXT NOT NULL REFERENCES tasks(id),
    seq          INTEGER NOT NULL,
    description  TEXT NOT NULL,
    argv_json    TEXT NOT NULL,
    requires_root INTEGER NOT NULL,
    tier         INTEGER NOT NULL,
    status       TEXT NOT NULL,
    exit_code    INTEGER,
    stdout_tail  TEXT NOT NULL DEFAULT '',
    stderr_tail  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (task_id, seq)
);
CREATE TABLE IF NOT EXISTS undo_artifacts (
    task_id      TEXT PRIMARY KEY REFERENCES tasks(id),
    payload_json TEXT NOT NULL,
    status       TEXT NOT NULL,
    applied_by   TEXT
);
CREATE TABLE IF NOT EXISTS task_meta (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (task_id, key)
);
CREATE TABLE IF NOT EXISTS unknown_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc   TEXT NOT NULL,
    request_text  TEXT NOT NULL,
    reason        TEXT NOT NULL,
    alternatives  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal_chain (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc  TEXT NOT NULL,
    kind         TEXT NOT NULL,
    ref          TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    entry_hash   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS journal_chain_ref ON journal_chain (ref, seq);
CREATE TABLE IF NOT EXISTS journal_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CHAIN_VERSION = 1

# (ref prefix, table, primary-key columns) — the tables the chain covers.
# ``ref`` is "<prefix>:<pk values joined by ':'>"; task ids are hex and step
# seqs/meta keys never contain ':' in practice, but the ref is a label — the
# verifier always re-reads rows by the primary key tuple, never by parsing ref.
_CHAINED: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("task", "tasks", ("id",)),
    ("step", "steps", ("task_id", "seq")),
    ("undo", "undo_artifacts", ("task_id",)),
    ("meta", "task_meta", ("task_id", "key")),
    ("unknown", "unknown_requests", ("id",)),
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row_content_hash(table: str, row: sqlite3.Row) -> str:
    """Canonical hash of a row as it stands: table name + sorted column/value JSON."""
    # sqlite3.Row iterates *values*, so column names must come from .keys();
    # zip() keeps the pairing explicit instead of relying on that quirk.
    payload = dict(zip(row.keys(), tuple(row), strict=True))
    return _sha256(table + "\x1f" + json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _event_hash(
    seq: int, created_utc: str, kind: str, ref: str, content_hash: str, prev_hash: str
) -> str:
    return _sha256(
        "\x1f".join((str(seq), created_utc, kind, ref, content_hash, prev_hash)),
    )


def _ref(prefix: str, key: tuple[object, ...]) -> str:
    return prefix + ":" + ":".join(str(k) for k in key)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_dir(env: dict[str, str] | None = None) -> Path:
    """Resolve the JARVIS state directory.

    Precedence: ``$JARVIS_STATE_DIR`` > ``$XDG_STATE_HOME/jarvis`` >
    ``~/.local/state/jarvis``. Created 0700 on first use.
    """
    env_map = dict(os.environ) if env is None else dict(env)
    raw = env_map.get("JARVIS_STATE_DIR")
    if raw:
        path = Path(raw)
    else:
        xdg = env_map.get("XDG_STATE_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "state"
        path = base / "jarvis"
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def default_db_path(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "journal.db"


class Journal:
    """Thin, explicit persistence layer (no ORM)."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        os.chmod(db_path, 0o600)
        self._absorb_legacy_rows()

    # -- evidence chain (ADR-0028) -----------------------------------------
    def _absorb_legacy_rows(self) -> None:
        """One-time backfill: give every pre-chain row a ``legacy`` event.

        Runs under BEGIN IMMEDIATE so two processes opening the same old
        database cannot both backfill; the second one blocks, then sees the
        ``chain_since`` marker and returns.
        """
        marker = self._conn.execute(
            "SELECT value FROM journal_meta WHERE key = 'chain_since'"
        ).fetchone()
        if marker is not None:
            return
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            marker = self._conn.execute(
                "SELECT value FROM journal_meta WHERE key = 'chain_since'"
            ).fetchone()
            if marker is None:
                for prefix, table, pk in _CHAINED:
                    order = ", ".join(pk)
                    for row in self._conn.execute(f"SELECT * FROM {table} ORDER BY {order}"):
                        key = tuple(row[c] for c in pk)
                        self._append_event(
                            "legacy", _ref(prefix, key), _row_content_hash(table, row)
                        )
                self._conn.execute(
                    "INSERT INTO journal_meta (key, value) VALUES ('chain_since', ?), "
                    "('chain_version', ?)",
                    (_utcnow(), str(CHAIN_VERSION)),
                )
            self._conn.execute("COMMIT")
        except BaseException:
            # BEGIN IMMEDIATE itself may have failed (lock timeout): only roll
            # back a transaction that actually opened, so the real error surfaces.
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def _append_event(self, kind: str, ref: str, content_hash: str) -> None:
        """Link one write event to the chain tail.

        Ordering invariant (ADR-0028 D2): callers invoke this *after* their row
        DML and *before* ``commit()``, i.e. inside the transaction that already
        holds SQLite's RESERVED lock — so no other writer can commit between
        reading the tail here and inserting the linked event.
        """
        tail = self._conn.execute(
            "SELECT seq, entry_hash FROM journal_chain ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = str(tail["entry_hash"]) if tail is not None else ""
        seq = int(tail["seq"]) + 1 if tail is not None else 1
        # AUTOINCREMENT never reuses a number: if events were deleted from the
        # tail, sqlite_sequence is ahead of ``seq`` and the gap stays visible.
        counter = self._conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'journal_chain'"
        ).fetchone()
        if counter is not None and int(counter["seq"]) >= seq:
            seq = int(counter["seq"]) + 1
        created = _utcnow()
        entry_hash = _event_hash(seq, created, kind, ref, content_hash, prev_hash)
        self._conn.execute(
            "INSERT INTO journal_chain (seq, created_utc, kind, ref, content_hash,"
            " prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?)",
            (seq, created, kind, ref, content_hash, prev_hash, entry_hash),
        )
        self._conn.execute(
            "INSERT INTO journal_meta (key, value) VALUES ('chain_head', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (entry_hash,),
        )

    def _chain_row(
        self, prefix: str, table: str, pk: tuple[str, ...], key: tuple[object, ...]
    ) -> None:
        """Hash the row identified by ``key`` as it now stands and append an event.

        A write that affected no row (e.g. ``finish_task`` on an unknown id)
        appends nothing — there is no new state to attest.
        """
        where = " AND ".join(f"{c} = ?" for c in pk)
        row = self._conn.execute(f"SELECT * FROM {table} WHERE {where}", key).fetchone()
        if row is None:
            return
        self._append_event("write", _ref(prefix, key), _row_content_hash(table, row))

    def verify_chain(self) -> dict[str, object]:
        """Re-derive the evidence chain; report, never raise (ADR-0028 D3)."""
        events = self._conn.execute("SELECT * FROM journal_chain ORDER BY seq").fetchall()
        problems: list[str] = []
        prev_hash = ""
        expected_seq = 1
        legacy = 0
        latest: dict[str, str] = {}
        for event in events:
            seq = int(event["seq"])
            if seq != expected_seq:
                problems.append(f"event sequence gap before seq {seq} (events deleted)")
                expected_seq = seq
            expected_seq += 1
            if str(event["prev_hash"]) != prev_hash:
                problems.append(f"event {seq} does not link to its predecessor")
            recomputed = _event_hash(
                seq,
                str(event["created_utc"]),
                str(event["kind"]),
                str(event["ref"]),
                str(event["content_hash"]),
                str(event["prev_hash"]),
            )
            if recomputed != str(event["entry_hash"]):
                problems.append(f"event {seq} hash mismatch (event edited)")
            prev_hash = str(event["entry_hash"])
            if str(event["kind"]) == "legacy":
                legacy += 1
            latest[str(event["ref"])] = str(event["content_hash"])
        counter = self._conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'journal_chain'"
        ).fetchone()
        last_seq = int(events[-1]["seq"]) if events else 0
        if counter is not None and int(counter["seq"]) > last_seq:
            problems.append(
                f"{int(counter['seq']) - last_seq} trailing event(s) deleted"
                f" (counter at {int(counter['seq'])}, last event {last_seq})"
            )
        head = self._conn.execute(
            "SELECT value FROM journal_meta WHERE key = 'chain_head'"
        ).fetchone()
        stored_head = str(head["value"]) if head is not None else ""
        if stored_head != prev_hash:
            problems.append("chain head does not match the last event")
        chain_ok = not problems

        # Every row's current content must equal its latest attested hash, and
        # every row must have been attested at all.
        row_problems: list[str] = []
        unchained: list[str] = []
        total_rows = 0
        seen: set[str] = set()
        for prefix, table, pk in _CHAINED:
            for row in self._conn.execute(f"SELECT * FROM {table}"):
                total_rows += 1
                ref = _ref(prefix, tuple(row[c] for c in pk))
                seen.add(ref)
                attested = latest.get(ref)
                if attested is None:
                    unchained.append(ref)
                elif attested != _row_content_hash(table, row):
                    row_problems.append(f"{ref} differs from its last attested write")
        for ref in latest:
            if ref not in seen:
                row_problems.append(f"{ref} was attested but the row is gone (deleted)")
        rows_ok = not row_problems

        detail = ""
        if problems:
            detail = problems[0]
        elif row_problems:
            detail = "; ".join(sorted(row_problems)[:3])
        elif unchained:
            detail = (
                f"{len(unchained)} row(s) never attested (written outside jarvis, or by a"
                f" pre-chain version): " + ", ".join(sorted(unchained)[:3])
            )
        return {
            "events": len(events),
            "legacy": legacy,
            "rows": total_rows,
            "chain_ok": chain_ok,
            "rows_ok": rows_ok,
            "unchained_rows": len(unchained),
            "detail": detail,
            "ok": chain_ok and rows_ok and not unchained,
        }

    # -- tasks ------------------------------------------------------------
    def begin_task(
        self,
        task_id: str,
        intent_text: str,
        playbook_id: str,
        tier: int,
        params: dict[str, object],
        fingerprint: dict[str, object],
    ) -> None:
        self._conn.execute(
            "INSERT INTO tasks (id, created_utc, intent_text, playbook_id, tier,"
            " params_json, fingerprint_json, status) VALUES (?,?,?,?,?,?,?,?)",
            (
                task_id,
                _utcnow(),
                intent_text,
                playbook_id,
                int(tier),
                json.dumps(params, sort_keys=True),
                json.dumps(fingerprint, sort_keys=True),
                "running",
            ),
        )
        self._chain_row("task", "tasks", ("id",), (task_id,))
        self._conn.commit()

    def finish_task(self, task_id: str, status: str) -> None:
        self._conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        self._chain_row("task", "tasks", ("id",), (task_id,))
        self._conn.commit()

    def mark_undone(self, task_id: str) -> None:
        self.finish_task(task_id, "undone")

    def get_task(self, task_id: str) -> dict[str, object] | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["params"] = json.loads(str(record.pop("params_json")))
        record["fingerprint"] = json.loads(str(record.pop("fingerprint_json")))
        return record

    def recent_tasks(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT id, created_utc, intent_text, playbook_id, tier, status"
            " FROM tasks ORDER BY created_utc DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    # -- unknown requests --------------------------------------------------
    def record_unknown_request(
        self, request_text: str, reason: str, alternatives: list[str]
    ) -> None:
        """Owner-review record of a request nothing could map (ADR-0014 D6).

        This is growth-loop input, not authority: only the owner turns it
        into a skill pack or KB fact.
        """
        self._conn.execute(
            "INSERT INTO unknown_requests (created_utc, request_text, reason, alternatives)"
            " VALUES (?,?,?,?)",
            (
                _utcnow(),
                request_text[:200],
                reason[:200],
                json.dumps(alternatives)[:600],
            ),
        )
        rowid = self._conn.execute("SELECT last_insert_rowid() AS id").fetchone()
        self._chain_row("unknown", "unknown_requests", ("id",), (int(rowid["id"]),))
        self._conn.commit()

    def recent_unknown_requests(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT created_utc, request_text, reason, alternatives FROM unknown_requests"
            " ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            record = dict(row)
            record["alternatives"] = json.loads(str(record["alternatives"]))
            out.append(record)
        return out

    # -- steps ------------------------------------------------------------
    def record_step(
        self,
        task_id: str,
        seq: int,
        description: str,
        argv: list[str],
        requires_root: bool,
        tier: int,
        status: str,
        exit_code: int | None = None,
        stdout_tail: str = "",
        stderr_tail: str = "",
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO steps (task_id, seq, description, argv_json,"
            " requires_root, tier, status, exit_code, stdout_tail, stderr_tail)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                int(seq),
                description,
                json.dumps(argv),
                int(requires_root),
                int(tier),
                status,
                exit_code,
                stdout_tail,
                stderr_tail,
            ),
        )
        self._chain_row("step", "steps", ("task_id", "seq"), (task_id, int(seq)))
        self._conn.commit()

    def steps_for_task(self, task_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM steps WHERE task_id = ? ORDER BY seq", (task_id,)
        ).fetchall()
        out = []
        for row in rows:
            record = dict(row)
            record["argv"] = json.loads(str(record.pop("argv_json")))
            out.append(record)
        return out

    # -- undo artifacts -----------------------------------------------------
    def store_undo(self, task_id: str, payload: dict[str, object]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO undo_artifacts (task_id, payload_json, status) VALUES (?,?,?)",
            (task_id, json.dumps(payload, sort_keys=True), "available"),
        )
        self._chain_row("undo", "undo_artifacts", ("task_id",), (task_id,))
        self._conn.commit()

    def get_undo(self, task_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT payload_json, status, applied_by FROM undo_artifacts WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "payload": json.loads(str(row["payload_json"])),
            "status": row["status"],
            "applied_by": row["applied_by"],
        }

    def set_meta(self, task_id: str, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO task_meta (task_id, key, value) VALUES (?,?,?)",
            (task_id, key, value),
        )
        self._chain_row("meta", "task_meta", ("task_id", "key"), (task_id, key))
        self._conn.commit()

    def get_meta(self, task_id: str, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM task_meta WHERE task_id = ? AND key = ?", (task_id, key)
        ).fetchone()
        return None if row is None else str(row["value"])

    def mark_undo_applied(self, task_id: str, undo_task_id: str) -> None:
        self._conn.execute(
            "UPDATE undo_artifacts SET status = 'applied', applied_by = ? WHERE task_id = ?",
            (undo_task_id, task_id),
        )
        self._chain_row("undo", "undo_artifacts", ("task_id",), (task_id,))
        self._conn.commit()
