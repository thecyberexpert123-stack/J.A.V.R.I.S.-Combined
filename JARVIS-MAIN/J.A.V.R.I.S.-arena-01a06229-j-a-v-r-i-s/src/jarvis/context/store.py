"""User context store (ADR-0012): feedback ledger now; preferences later (M8b).

Local, inspectable, deletable. Context tunes what JARVIS *suggests* — it never
grants authority to act.

M8b growth (ADR-0012): explicit preferences and house rules join the
ledger in the same store — still local, inspectable, deletable; still
tuning-only (they shape what is *suggested*, never what is allowed).
M9c hardening (ADR-0013): feedback text is untrusted ingress — it is scanned
for injection patterns at write time, and every hashed entry carries a content
hash chained into a table digest (``store_meta.chain_digest``), so silent row
edits, deletions, or forgeries are reported by ``verify_integrity()``. Rows
written before 1.4.0 have no hash (reported as legacy; they gain one on their
next upsert). Honest limitation: an attacker with arbitrary DB write access
can recompute hashes and the digest — this raises the cost of *invisible,
gradual* tampering, it is not a cryptographic anchor.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from jarvis.journal.sqlite import _utcnow, state_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    suggestion_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reason TEXT NOT NULL DEFAULT '',
    suggestion_title TEXT NOT NULL DEFAULT '',
    created_utc TEXT NOT NULL,
    entry_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    entry_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    rule_text TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    entry_hash TEXT NOT NULL DEFAULT ''
);
"""

# Pre-1.4.0 databases lack the hash column; CREATE IF NOT EXISTS cannot add it.
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("entry_hash", "ALTER TABLE feedback ADD COLUMN entry_hash TEXT NOT NULL DEFAULT ''"),
)

# Write-time scan: this table feeds future suggestions (M8b), so poisoned
# feedback would become poisoned suggestions — the memory-poisoning class from
# the landscape research. Patterns are deliberately tight to avoid refusing
# honest calibration reasons.
_SCAN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)",
        r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|your)",
        r"system\s*prompt\s*:",
        r"you\s+are\s+now\s+(?:a|an|the)\b",
        r"new\s+(?:high(?:est)?\s+priority\s+)?instructions\s*:",
        r"<\|[^>]*\|>",
    )
)


def _scan_untrusted(field: str, value: str) -> None:
    for pattern in _SCAN_PATTERNS:
        match = pattern.search(value)
        if match is not None:
            raise ValueError(
                f"{field} looks like prompt injection (pattern {pattern.pattern!r}); "
                "not recorded. Rephrase the reason without instruction-like text."
            )


def find_injection_pattern(text: str) -> str | None:
    """Public scan for AI-synthesized text (ADR-0014 D5).

    Returns the first matching pattern's source, or None. Same pattern family
    the context store enforces at write time — a model answer that reads like
    instructions to the operator is refused before it is ever shown.
    """
    for pattern in _SCAN_PATTERNS:
        if pattern.search(text) is not None:
            return pattern.pattern
    return None


def _row_hash(
    suggestion_id: object, decision: object, reason: object, title: object, created_utc: object
) -> str:
    canonical = "\x1f".join(
        (str(suggestion_id), str(decision), str(reason), str(title), str(created_utc))
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _chain_digest(entry_hashes: Sequence[str]) -> str:
    return hashlib.sha256("\x1f".join(sorted(entry_hashes)).encode("utf-8")).hexdigest()


def default_context_path(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "context.db"


class ContextStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        existing = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(feedback)")}
        for column, sql in _MIGRATIONS:
            if column not in existing:
                self._conn.execute(sql)
        self._conn.commit()

    def record_feedback(
        self, suggestion_id: str, decision: str, *, reason: str = "", title: str = ""
    ) -> None:
        if decision not in ("accepted", "rejected"):
            raise ValueError(f"invalid decision {decision!r}")
        _scan_untrusted("reason", reason)
        _scan_untrusted("title", title)
        created = _utcnow()
        entry_hash = _row_hash(suggestion_id, decision, reason, title, created)
        self._conn.execute(
            "INSERT INTO feedback (suggestion_id, decision, reason, suggestion_title,"
            " created_utc, entry_hash)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(suggestion_id) DO UPDATE SET decision=excluded.decision,"
            " reason=excluded.reason, suggestion_title=excluded.suggestion_title,"
            " created_utc=excluded.created_utc, entry_hash=excluded.entry_hash",
            (suggestion_id, decision, reason, title, created, entry_hash),
        )
        self._refresh_digest()
        self._conn.commit()

    def _refresh_digest(self) -> None:
        def rehash(table: str, meta_key: str) -> None:
            rows = self._conn.execute(
                f"SELECT entry_hash FROM {table} WHERE entry_hash != ''"
            ).fetchall()
            digest = _chain_digest([str(r["entry_hash"]) for r in rows])
            self._conn.execute(
                "INSERT INTO store_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (meta_key, digest),
            )

        rehash("feedback", "chain_digest")
        rehash("preferences", "chain_digest_preferences")
        rehash("rules", "chain_digest_rules")

    def decisions(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT suggestion_id, decision FROM feedback").fetchall()
        return {str(r["suggestion_id"]): str(r["decision"]) for r in rows}

    def feedback_rows(self) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT suggestion_id, decision, reason, suggestion_title, created_utc"
            " FROM feedback ORDER BY created_utc DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def verify_integrity(self) -> dict[str, object]:
        """Recompute hashes and the chain digest; report, never raise, on drift."""
        rows = self._conn.execute(
            "SELECT suggestion_id, decision, reason, suggestion_title, created_utc, entry_hash"
            " FROM feedback"
        ).fetchall()
        legacy = 0
        mismatched: list[str] = []
        hashes: list[str] = []
        for row in rows:
            entry_hash = str(row["entry_hash"])
            if not entry_hash:
                legacy += 1
                continue
            hashes.append(entry_hash)
            expected = _row_hash(
                row["suggestion_id"],
                row["decision"],
                row["reason"],
                row["suggestion_title"],
                row["created_utc"],
            )
            if expected != entry_hash:
                mismatched.append(str(row["suggestion_id"]))
        digest_ok: bool | None = None
        if hashes:
            stored = self._conn.execute(
                "SELECT value FROM store_meta WHERE key = 'chain_digest'"
            ).fetchone()
            digest_ok = _chain_digest(hashes) == (str(stored["value"]) if stored else "")

        def check_table(
            table: str, meta_key: str, columns: tuple[str, str, str]
        ) -> tuple[bool, bool, int]:
            """(content_ok, digest_ok, hashed_count) — content hashes are
            recomputed from row values, so edits are caught, not just
            additions/deletions."""
            rows_t = self._conn.execute(f"SELECT * FROM {table}").fetchall()
            hashes_t: list[str] = []
            for row_t in rows_t:
                stored_hash = str(row_t["entry_hash"])
                if not stored_hash:
                    continue  # legacy row: counted, not verifiable
                recomputed = _row_hash(
                    row_t[columns[0]], row_t[columns[1]], row_t[columns[2]], "", ""
                )
                if recomputed != stored_hash:
                    return False, False, len(hashes_t)
                hashes_t.append(stored_hash)
            stored_t = self._conn.execute(
                "SELECT value FROM store_meta WHERE key = ?", (meta_key,)
            ).fetchone()
            if not hashes_t:
                # Empty table: ok when never written or consistent with the
                # store's own refresh (sha256("")); a raw-SQL deletion without
                # refresh leaves a stale digest and is flagged here.
                if stored_t is None:
                    return True, True, 0
                return True, _chain_digest([]) == str(stored_t["value"]), 0
            digest_ok_t = _chain_digest(hashes_t) == (str(stored_t["value"]) if stored_t else False)
            return True, digest_ok_t, len(hashes_t)

        prefs_content_ok, prefs_ok, prefs_n = check_table(
            "preferences", "chain_digest_preferences", ("key", "value", "created_utc")
        )
        rules_content_ok, rules_ok, rules_n = check_table(
            "rules", "chain_digest_rules", ("id", "rule_text", "created_utc")
        )
        detail = ""
        if mismatched:
            detail = "content hash mismatch for: " + ", ".join(sorted(mismatched)[:3])
        elif digest_ok is False:
            detail = "feedback chain digest mismatch (rows edited in, added, or removed)"
        elif not prefs_content_ok:
            detail = "preference row content hash mismatch (edited after write)"
        elif not rules_content_ok:
            detail = "rule row content hash mismatch (edited after write)"
        elif not prefs_ok:
            detail = "preferences chain digest mismatch"
        elif not rules_ok:
            detail = "rules chain digest mismatch"
        return {
            "total": len(rows),
            "hashed": len(hashes),
            "legacy_unhashed": legacy,
            "row_hashes_ok": not mismatched,
            "chain_digest_ok": digest_ok,
            "preferences_hashed": prefs_n,
            "preferences_ok": prefs_content_ok and prefs_ok,
            "rules_hashed": rules_n,
            "rules_ok": rules_content_ok and rules_ok,
            "ok": (
                not mismatched
                and digest_ok is not False
                and prefs_content_ok
                and prefs_ok
                and rules_content_ok
                and rules_ok
            ),
            "detail": detail,
        }

    # -- M8b: explicit preferences and house rules (tuning-only) -------------

    def set_preference(self, key: str, value: str) -> None:
        if not key or len(key) > 64 or not value or len(value) > 200:
            raise ValueError("preference key must be 1..64 chars, value 1..200 chars")
        _scan_untrusted("preference value", value)
        created = _utcnow()
        entry_hash = _row_hash(key, value, created, "", "")
        self._conn.execute(
            "INSERT INTO preferences (key, value, created_utc, entry_hash) VALUES (?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
            " created_utc=excluded.created_utc, entry_hash=excluded.entry_hash",
            (key, value, created, entry_hash),
        )
        self._refresh_digest()
        self._conn.commit()

    def unset_preference(self, key: str) -> bool:
        cursor = self._conn.execute("DELETE FROM preferences WHERE key = ?", (key,))
        self._refresh_digest()
        self._conn.commit()
        return cursor.rowcount > 0

    def preferences(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM preferences ORDER BY key").fetchall()
        return {str(r["key"]): str(r["value"]) for r in rows}

    def add_rule(self, text: str) -> str:
        text = text.strip()
        if not text or len(text) > 200:
            raise ValueError("house rule must be 1..200 chars")
        _scan_untrusted("house rule", text)
        rule_id = "rule-" + _row_hash(text, "", "", "", "")[:12]
        created = _utcnow()
        entry_hash = _row_hash(rule_id, text, created, "", "")
        self._conn.execute(
            "INSERT INTO rules (id, rule_text, created_utc, entry_hash) VALUES (?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET rule_text=excluded.rule_text,"
            " created_utc=excluded.created_utc, entry_hash=excluded.entry_hash",
            (rule_id, text, created, entry_hash),
        )
        self._refresh_digest()
        self._conn.commit()
        return rule_id

    def remove_rule(self, rule_id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        self._refresh_digest()
        self._conn.commit()
        return cursor.rowcount > 0

    def rule_rows(self) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT id, rule_text, created_utc FROM rules ORDER BY created_utc"
        ).fetchall()
        return [dict(r) for r in rows]

    def forget_everything(self) -> dict[str, int]:
        """Delete the entire context store contents (owner-invoked; consented)."""
        counts: dict[str, int] = {}
        for table in ("feedback", "preferences", "rules"):
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            counts[table] = int(row["n"]) if row else 0
            self._conn.execute(f"DELETE FROM {table}")
        self._conn.execute("DELETE FROM store_meta")
        self._conn.commit()
        return counts

    def close(self) -> None:
        self._conn.close()
