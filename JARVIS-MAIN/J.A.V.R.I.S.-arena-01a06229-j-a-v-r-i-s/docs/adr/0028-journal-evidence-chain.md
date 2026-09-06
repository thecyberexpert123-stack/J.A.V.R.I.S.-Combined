# ADR-0028: Hash-linked task journal — the evidence chain (M9c extended to what was executed)

- **Status:** Accepted and implemented (2026-09-06; owner-directed "continue" sequence, `TASKS.md`
  item B-C11, pre-approved as low-risk in decision D4; origin: deep research II
  `docs/RESEARCH-agent-construction-and-future-tech-2026.md` §3.4 (SAL evidence chain), §3.5
  (OWASP ASI10 / ACS runtime evidence), candidate C11).
- **Context:** M9c (ADR-0013) made the *context store* tamper-evident: every feedback/preference/
  rule row carries a content hash and the hashes are chained into a digest that `jarvis doctor`
  re-derives. The **task journal** — the record of what JARVIS actually planned, consented to and
  executed (`tasks`, `steps`, `undo_artifacts`, `task_meta`, `unknown_requests`) — had no hash or
  digest at all (`grep hash|digest journal/sqlite.py` → nothing). ADR-0008 re-validates *undo
  artifacts* against domain rules before replaying them, which stops a tampered artifact from
  smuggling a write, but nothing tells the owner that a status was flipped from `failed` to
  `succeeded`, a step row was deleted, or a task was inserted after the fact. SAL (arXiv:2604.22136)
  names the missing piece: a hash-linked evidence chain that records every decision for replay.
- **Context (why not a literal copy of M9c):** the M9c digest is `sha256(sorted(row hashes))`,
  recomputed from *whatever rows exist* on every write. That is adequate for a store that changes
  a few times a week. The journal is written on every task, every step and every brief-timer
  run, so a deleted row would be **healed into a fresh, valid digest by the next legitimate
  write** — within minutes on a live machine. Shipping that as "deletions are detected" would be
  false confidence. Journal rows are also updated in place (`finish_task` rewrites `status`,
  `mark_undo_applied` rewrites the artifact), so a chain over mutable rows has no stable subject.
  The chain therefore links **write events**, append-only, each to its predecessor.

## Decision

**D1 — An append-only chain of write events, `prev_hash`-linked.** Two additive tables:
`journal_chain(seq INTEGER PRIMARY KEY AUTOINCREMENT, created_utc, kind, ref, content_hash,
prev_hash, entry_hash)` and `journal_meta(key, value)`. Every mutating `Journal` method
(`begin_task`, `finish_task`/`mark_undone`, `record_step`, `store_undo`, `mark_undo_applied`,
`set_meta`, `record_unknown_request`) appends one event **inside the same SQLite transaction as
its row write**: `content_hash` = SHA-256 of the canonical JSON of the affected row *as it now
stands* (re-read by primary key, so writer and verifier hash the same bytes through one function);
`prev_hash` = the previous event's `entry_hash` (`""` for genesis); `entry_hash` = SHA-256 over
`[seq, created_utc, kind, ref, content_hash, prev_hash]`. `journal_meta.chain_head` tracks the
latest `entry_hash`. `ref` names the row: `task:<id>`, `step:<task>:<seq>`, `undo:<task>`,
`meta:<task>:<key>`, `unknown:<rowid>`. Per write the cost is one indexed `SELECT` of the tail
and one `INSERT` — O(1), no extra commit.

**D2 — Correct under concurrent writers by construction.** The row DML runs first and takes
SQLite's RESERVED lock; the tail `SELECT` and the event `INSERT` run inside that same
transaction, so no second writer can commit between reading the tail and linking to it. This is
an ordering invariant of `journal/sqlite.py` (documented at the helper), not a new lock. Each
process/thread keeps its own connection exactly as today.

**D3 — `verify_chain()` reports, never raises.** It checks (a) `seq` is contiguous from 1 with
no gaps (an interior deletion cannot be healed: `AUTOINCREMENT` never reuses a number);
(b) `sqlite_sequence` for `journal_chain` is not ahead of the last event (tail truncation);
(c) every `entry_hash` recomputes and every `prev_hash` equals its predecessor's `entry_hash`;
(d) `chain_head` equals the last event; (e) for every `ref` the **latest** event's
`content_hash` equals the hash of the row as it exists now (an edit after the fact, a status
flip, a deleted row) and (f) every row in the five tables has at least one event (a row inserted
directly, or written by an older jarvis after a downgrade, is reported as *unchained* — both
possibilities are named in the detail). The result is a dict (`events`, `legacy`, `rows`,
`chain_ok`, `rows_ok`, `unchained_rows`, `detail`, `ok`) in the same shape as the context store's
`verify_integrity()`.

**D4 — Existing journals migrate additively and are covered from the first open.** On open, if
`journal_meta.chain_since` is absent the store takes `BEGIN IMMEDIATE`, writes one `legacy`
event per existing row of every chained table (hashing the row as it is *now*), records
`chain_since`/`chain_version`, and commits; a second process opening the same old DB at the same
moment blocks on the lock and then finds the marker. No column of any existing table changes;
`get_task`, `steps_for_task`, `recent_tasks`, `get_undo`, `get_meta` return exactly the dicts
they returned before. Legacy events are counted separately and their rows are verified from the
upgrade onward — edits *before* the upgrade are unknowable and are said so.

**D5 — `jarvis doctor` is the verdict surface; no new verb.** `doctor` already re-derives the
context-store chain and folds it into `clean`. It now also runs `Journal.verify_chain()`, prints
`journal chain  : ok (N events, L legacy)` or `TAMPERED — <detail>`, includes `"journal_chain"`
in `--json`, and returns 1 when the chain fails (the same exit code it already uses for baseline
drift and context-store tampering). `jarvis status`, the MCP `journal://tasks` resource and every
CLI verb keep their output byte-for-byte.

**D6 — Honest limitation, unchanged from M9c.** Anyone with arbitrary write access to
`journal.db` can rewrite events, `sqlite_sequence` and the head. The chain raises the cost of
*invisible* tampering from "edit one cell" to "recompute a linked chain consistently"; it is
not a cryptographic anchor. Anchoring the head off-machine or in the M9c baseline is deliberately
**not** done here: the head moves on every write, so a baseline pin would drift immediately, and
a silent anchor written by `doctor` would turn a read-only verb into a writer. Both are recorded
as owner options in `TASKS.md` (C11b), not decided.

## Failure modes

| Precondition absent / fault | Behaviour |
|---|---|
| Fresh install, empty journal | Chain tables created with the schema; `verify_chain()` → `ok`, 0 events. |
| Pre-1.21 journal with rows | One-time backfill on first open (`legacy` events, O(rows)); measured below. Verdict `ok` with `legacy = rows`. |
| Older jarvis writes to a chained DB (downgrade) | Rows land unchained → next `doctor` reports `unchained_rows` with both explanations. Nothing breaks. |
| Event `INSERT` fails (disk full, I/O error) | Same transaction as the row write → both roll back; the caller sees the exception exactly as it would for a failed row write today. |
| `journal_chain` emptied by hand | Next write gets `seq = sqlite_sequence + 1` → gap from 1 → reported as deleted events; `chain_head` mismatch also reported. |
| `finish_task`/`mark_undo_applied` on an id that has no row | `UPDATE` affects nothing (as today); no event is appended because nothing was written. |
| Concurrent writers (doorway thread + CLI + timer) | Serialized by the RESERVED lock inside each write transaction (D2); busy-timeout behaviour unchanged (5 s default). |
| Very large journal at `doctor` time | `verify_chain()` is O(events + rows) and runs only under the explicit `doctor` verb. |

## Consequences

- Post-incident replay of the journal becomes tamper-evident at the same cost class as M9c, with
  deletions and status flips that a digest-only design would have healed or missed now reported.
- `jarvis doctor` can newly return 1 on a machine where it returned 0 — only when the journal has
  been altered outside `Journal`. That is the intended change of verdict and is called out in the
  CHANGELOG as such.
- Schema additive; module APIs unchanged plus one new method; `doctor --json` gains one key.
  Runtime code changed (`journal/sqlite.py`, `cli/app.py`) → this item targets the **next minor
  (1.21.0)**; the version bump and release heading are applied at the commit/tag step the owner
  authorizes (RELEASING.md convention), not silently in the working tree.
- Not verified here: GitHub Actions on the changed tree (`api.github.com` unreachable). Everything
  else (tamper matrix, legacy migration, concurrency, timing) is verified by tests and recorded in
  `TASKS.md` §B-C11.
