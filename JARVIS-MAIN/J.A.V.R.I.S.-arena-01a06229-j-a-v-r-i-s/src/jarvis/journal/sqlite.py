"""SQLite audit journal: tasks, steps, undo artifacts.

Every mutating task leaves a complete, replayable record here *before* it is
executed (undo artifacts are stored before the first step runs). The database
lives under the JARVIS state directory with 0600 permissions — it contains a
detailed picture of the machine and must not be world-readable.
"""

from __future__ import annotations

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
"""


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
        self._conn.commit()

    def finish_task(self, task_id: str, status: str) -> None:
        self._conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
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
        self._conn.commit()
