# ADR-0033: Resumable task log — a crash leaves a truthful record and an offer, never a replay

- **Status:** **Proposed 2026-09-08 — docs only, paused for owner acceptance (TASKS.md D15).**
  Sequence item **C2** (research candidate; owner-gated because it touches the sole execution
  path). Nothing in `src/` changes with this ADR; the measurements below were made with the shipped
  1.23.0 kernel and throw-away probe scripts that are not committed.
- **Context (research):** `docs/RESEARCH-agent-construction-and-future-tech-2026.md` §2.3
  (Managed Agents: session = append-only event log, `wake(sessionId)` rebuilds the harness from it),
  §4.1 (durable execution: journal-and-replay engines resume after a crash, but side-effecting
  steps run *at least once* on replay and therefore need idempotency keys), §4.3 (JARVIS: a
  crash mid-plan should end in an *offer* — resume or undo — never an unattended resume;
  `pkg.install` twice is harmless, `file.append` twice is not; the owner question C2). The
  durable-execution literature is unanimous on the one point that matters here: the runtime
  can make *progress* durable, it cannot make a *side effect* exactly-once — "at-least-once is the
  honest default" and steps must be idempotent or deduplicated (JobRunr guide, Jun 2026; Temporal
  docs via the two 2026 write-ups in §9).
- **Context (measured, 2026-09-08, kernel 1.23.0):** the TASKS.md block for C2 said *measure
  first*. The local journals hold no interrupted multi-step task (this sandbox has only run
  probes), so the measurement is of **what the code leaves behind**, not of frequency:
  1. **Hard crash** (SIGKILL / OOM / power loss, simulated with `os._exit(9)` inside the second
     step of a two-part `run_plan`): the task row stays **`running` forever**, step 0 is recorded
     `succeeded`, step 1 has no row, and **no undo artifact exists** — `store_undo` runs *after*
     `_execute` in both `run_intent` and `run_plan` (orchestrator lines 292 and 494). The research
     doc's line "stores undo artifacts before the first step" (§4.3) is **wrong for the shipped
     code** and is corrected by this ADR.
  2. **Terminal closed** (SIGHUP to the JARVIS process while a step runs, real `LocalRunner`):
     JARVIS dies of the signal (no SIGHUP handler; only SIGINT/SIGTERM are the kill-switch), the
     child — started with `start_new_session=True` — **survives and completes its side effect**,
     and the journal shows the task `running` with **zero** step rows, because the step row is
     written only after `communicate()` returns.
  3. **Kill-switch between steps** (SIGINT arriving after step 0 exited, before step 1 started):
     step 1 is recorded `skipped`, the task ends **`failed`** (verification of the never-run part
     fails) with exit 1 — not `interrupted`/130. `test_interrupt_via_signal_exit_code` covers only
     the case where the signal lands *inside* a step (`exit_code < 0`).
  4. Nothing in `src/` reads `status = 'running'`; `jarvis tasks` prints it verbatim; the suggest
     engine and the briefing count only `failed`/`interrupted`; the undo path needs an artifact.
     A stale `running` task is therefore **invisible to every safety surface** and un-undoable.
  5. Multi-step catalog entries at T1+ today: `pkg.upgrade` (2 steps), `file.append` on an
     existing file (backup + `tee`), and every `run_plan` composite (LLM plans, ≤ 6 parts).
     Everything else at T1+ is a single command — a crash *around* it still produces finding 1.

## 1. What "resume" can and cannot mean for JARVIS

JARVIS steps are real commands with real effects; the kernel never inspects their bodies.
Findings 1–2 show the failure is not "the plan stopped" but "**the record is wrong**": a task
that says `running` when nothing is running, with no reversal path, after a step that may or
may not have happened. Durable-execution engines solve this by replaying from a log *and*
requiring idempotent steps; JARVIS cannot certify idempotency for `tee -a`, `mv`, `kill`, or
`apt-get upgrade`, and ADR-0017 D3 forbids the autonomous loop that replay would be. So the
decision below makes the *record* durable and truthful, makes the *reversal* available even after
a crash, and turns *continuation* into an explicit, per-playbook, owner-consented act — for the
minority of steps the kernel can honestly call idempotent.

## 2. Options considered

| # | Option | What it gives | Verdict |
|---|---|---|---|
| A | Keep today's behaviour ("undo only") | nothing new; finding 1 stays (undo is *not* available after a crash) | **Rejected** — the current contract is not what the research or README describe |
| B | **Truthful record + undo-before-execute + reported stale tasks + opt-in idempotent resume** | crash → next invocation reports the stale task with resume / undo / dismiss; undo works because the artifact now precedes the first step; resume only for playbooks flagged idempotent, only with consent | **Proposed** |
| C | Full durable replay (event-sourced steps, automatic continuation) | Temporal-shaped; needs idempotency the kernel cannot prove; violates ADR-0017 D3 (autonomous loop) and "no unsolicited action" | **Rejected** |
| D | SIGHUP handler that kills the child when the terminal closes | would prevent finding 2's orphan side effect | **Rejected as default** — `apt-get` half-killed is worse than `apt-get` completed; noted as an owner option (Q-D) |

## 3. Decision (proposed)

### D1 — Step lifecycle: `started` before the child runs (journal additive)

`_execute` records each step **twice**: a `started` row (argv, tier, `requires_root`, no exit
code) immediately before `runner.run`, then the existing `succeeded`/`failed` overwrite when it
returns (`record_step` is already `INSERT OR REPLACE`; the chain gets one more event per step —
tests pinning event counts are updated with the ADR, not silently). A crash now leaves a row that
says *which* step was in flight. New `steps.status` value `started` — additive; every reader
today treats unknown step statuses as text.

### D2 — Undo artifact stored **before** the first step, then confirmed

`store_undo(task_id, payload)` moves to just after `begin_task` (both paths) with the artifact
`status = "pending"`; after `_execute` the existing code path marks it `available` (new
`journal.confirm_undo(task_id)`), or removes it when the plan was `none_needed`/`unavailable`
exactly as today's condition decides. `get_undo` on a `pending` artifact after a crash returns it
(the wake-up path, D4, is the only consumer that accepts `pending`); `jarvis undo` on a live task
still requires `available` — no behaviour change for finished tasks. Result: finding 1's task
becomes **undoable** — with one honesty rule: the pre-built undo assumes the forward step ran, so
a crash *before* the child started makes the undo a no-op or a refusal by its own `verify_checks`
(e.g. `test -f` after `rm -f`), never an unrelated action.

### D3 — Stale tasks get a truthful terminal status

At wake-up the kernel closes any `running` task whose owning process is gone as
**`interrupted`** (new journal read `stale_tasks()`: `status = 'running'` **and** the recorded
process is not alive). "Alive" = `task_meta` `pid` + `/proc/<pid>/stat` starttime + boot id recorded
at `begin_task` (three values, so a recycled pid after reboot is not mistaken for a live run).
`finish_task(id, "interrupted")` appends a chain event; the `journal_chain` stays valid (the row is
re-hashed, not edited in place). `exit 130` semantics of the live kill-switch are untouched; this is
the *post-mortem* form of the same status. Finding 3's "signal between steps → `failed`" is also
corrected: if `self._interrupted` is set when the loop skips remaining steps, terminal is
`INTERRUPTED` (exit 130), not `FAILED` — one line in `_execute`, one new test.

### D4 — The offer: report on the next invocation, decide only with the owner

`jarvis do`, `jarvis ask`, `jarvis undo` and `jarvis tasks` call `report_stale()` first (via
`_build_orchestrator`; MCP and `serve` do **not** — they return the same information as an
additive `stale_tasks` list in `jarvis_status`/`jarvis status --json`, never a prompt). The report
is text, printed once per stale task:

```
[jarvis] task 9c87ccc08b75 was interrupted (process died during step 1/2: "install package(s): htop")
         undo   : jarvis undo 9c87ccc08b75          (pre-built artifact, revalidated at run)
         resume : jarvis resume 9c87ccc08b75        (allowed: remaining steps are idempotent)
         dismiss: jarvis tasks --dismiss 9c87ccc08b75
```

Nothing happens until the owner types one of them. `resume` is a new verb; `--dismiss` marks the
task `interrupted` with `task_meta dismissed=1` so it is not reported again. Reporting is
rate-limited to once per task and never blocks (a broken journal → the report is skipped with a
one-line warning, today's behaviour otherwise).

### D5 — Resume: per-playbook `idempotent` flag, remaining steps only, consent again

`Playbook` gains `idempotent: bool = False` (additive dataclass field; families set it
explicitly). `jarvis resume <task-id>` rebuilds the plan from the journal (`playbook_id`,
`params_json`, `intents` for composites) through the **same** `build`/policy/`check_argv`
path as a fresh run, drops the steps recorded `succeeded`, and re-runs the rest **only if every
remaining step's playbook is `idempotent`**; otherwise it refuses with the reason and points at
`undo`. It asks for consent again (`ApprovalPolicy.decide` at the plan's tier; `--yes` honoured
as everywhere) and journals a *new* task whose `task_meta resumes=<old id>` — the old task is
never mutated back to running. Initial flag values, each with its justification in the diff:
`idempotent = True` for `pkg.install`, `pkg.remove`, `pkg.cache.refresh`, `pkg.upgrade`
(package managers converge on the same end state), `fs.mkdir` (`-p`), `fs.touch`, `fs.link`
(`-sfn`), `svc.start|stop|enable|disable` (state-setting `systemctl` verbs); `False` for
`svc.restart` (a second restart is a second outage, not a no-op), `file.append`,
`fs.copy`/`fs.move`/`fs.remove`, `proc.kill*` (pids recycle), `gui.*`, and every T0 reader
(nothing to resume; they finish in milliseconds). Any playbook without an explicit
value is `False` — fail closed.

### D6 — What is *not* decided here

No SIGHUP handling change (Q-D). No automatic resume anywhere (ADR-0017 D3, charter). No
MCP `jarvis_resume` tool (consent story differs; recommendation). No change to `undo` for
finished tasks. No idempotency claim for composites beyond "all parts flagged".

## 4. Interfaces (additive only)

- Journal: new step status value `started`; new `undo_artifacts.status` value `pending`; new
  `task_meta` keys `pid`, `starttime`, `boot_id`, `dismissed`, `resumes`; new read methods
  `stale_tasks()`, `confirm_undo()`. No table or column changes; the chain covers every new write.
- CLI: new verb `jarvis resume <task-id> [--dry-run]`; `jarvis tasks --dismiss <task-id>`;
  the wake-up report line(s) on `do`/`ask`/`undo`/`tasks` when and only when a stale task
  exists (default output otherwise byte-identical; `--json` payloads gain an optional
  `stale_tasks` key).
- MCP: `jarvis_status` gains `stale_tasks: [...]` (additive; the HUD ignores unknown keys —
  checked for `argument_policy` in C1).
- Version on implementation: **1.24.0**.

## 5. Failure modes (each degrades to today's behaviour or safer)

| Situation | Behaviour |
|---|---|
| Journal unreadable at wake-up | report skipped with one stderr line; `do` proceeds as today |
| Owning process still alive (a second shell while a long `apt-get upgrade` runs) | not stale: pid+starttime+boot_id match → no report, nothing touched |
| Pid recycled after reboot | boot_id differs → stale (correct) |
| `/proc` unavailable (containers with hidepid) | liveness unknown → **not** reported as stale (fail closed: never mark a possibly-live task interrupted); `jarvis tasks` shows `running` as today |
| Undo artifact `pending` but the forward step never started | undo's own `verify_checks` decide; a no-op undo reports `verification failed` honestly, exactly like a failed undo today |
| `resume` on a task with a non-idempotent remaining step | refused with the step named; `undo` offered |
| Playbook removed/renamed since the crash | `resume` refuses ("playbook unknown"); `undo` still works from the artifact |
| Journal tampered between crash and resume | `resume` rebuilds through `build` + policy + `check_argv` — the journal supplies only `playbook_id`/params, never argv |
| Crash during the wake-up report itself | nothing was mutated before printing except `finish_task(interrupted)`, which is idempotent |

## 6. Verification plan (all offline; sandbox can run every part)

`tests/test_resume.py`: hard-crash simulation (fork + `os._exit` inside the runner) → journal
shows `started` row, `pending` undo; wake-up marks `interrupted` only when the recorded process is
dead (fake `/proc` reader); live-process case not stale; boot-id mismatch stale; report text;
`resume` drops succeeded steps, re-runs idempotent remainder through the real orchestrator with
`FakeRunner`, refuses non-idempotent remainder, asks consent (non-tty without `--yes` → refused as
today); `--dismiss`; signal-between-steps → `INTERRUPTED`/130; undo-before-execute confirmed on
success and consumed by `undo` after a crash; every chain-count test updated deliberately.
Existing suite: expected deltas are limited to chain event counts (`test_journal_chain.py` ×4)
and the finding-3 status; everything else must pass unchanged. Gates: ruff, format, mypy strict,
`unit_gate` non-live, M2, M3 (0 escapes), M4. Live: a real `jarvis do "install <pkg>"` killed with
`kill -9` mid-step on the owner's machine, then `jarvis tasks` → report → `jarvis undo`.

## 7. Owner decisions requested (D15)

- **Q-A · Go / no-go.** Implement B as specified, or keep "undo only" (A) and only fix the
  record (D1–D3, no `resume` verb)?
- **Q-B · Resume verb.** `jarvis resume <id>` as a new verb (proposed) or fold into
  `jarvis do --resume <id>`?
- **Q-C · Idempotent set.** Accept the D5 list; or `pkg.*` only; or none (record + undo only).
- **Q-D · Terminal close.** Keep today's behaviour (child completes; JARVIS dies; the record now
  says so) — proposed — or add a SIGHUP handler that forwards SIGTERM to the child?

## 8. Consequences

- A crash stops producing a lie in the journal. Undo exists for the task that needs it most.
  Continuation is possible where the kernel can vouch for it and asked for everywhere.
- Cost: one extra journal write per step (≈ 0.2 ms each per ADR-0028's measurement), three
  `task_meta` rows per task, and one `/proc` read per invocation when a `running` row exists.
- Not gained, deliberately: unattended recovery. The owner remains the one who decides what
  happens after a crash — the research's own conclusion (§4.5).

## 9. Sources

- In-repo: `core/orchestrator.py` (`_execute` 642–716, `store_undo` placement 292/494,
  `exit_code`), `journal/sqlite.py` (schema, `record_step` INSERT OR REPLACE, chain kinds),
  `execution/runner.py` (`start_new_session=True`, no SIGHUP handling), `cli/app.py`
  (`_build_orchestrator`, `_cmd_tasks`, `main` → 130 on `KeyboardInterrupt`),
  `tests/test_orchestrator.py::test_interrupt_via_signal_exit_code`, ADR-0017 D3, ADR-0028,
  research doc §2.3 / §4.1 / §4.3 / §4.5 / open question 2.
- Measurements: three probe scripts run 2026-09-08 against kernel 1.23.0 (findings 1–3 above);
  not committed.
- JobRunr, "What is durable execution? A practical guide" (2026-06-05) — at-least-once step
  semantics, "keep your side effects idempotent" `[search snippet]`.
- "Temporal signals: 7 idempotency slips" (2026-03-14) and Temporal, "Beyond state machines"
  (2026-07-20) — replay protects workflow progress, not external side effects; exactly-once only
  through explicit deduplication `[search snippets]`.
- Anthropic, "Scaling Managed Agents" (Apr 2026) — session as append-only event log,
  `wake(sessionId)` `[fetched in research II]`.
