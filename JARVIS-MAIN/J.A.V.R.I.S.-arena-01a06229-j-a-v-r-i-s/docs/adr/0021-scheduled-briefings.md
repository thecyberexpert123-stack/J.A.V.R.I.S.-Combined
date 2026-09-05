# ADR-0021: Level-2 proactivity — scheduled propose-only briefings, silence as a decision

- **Status:** Accepted and implemented (2026-09-04; owner-directed "continue" — roadmap item R3
  from `docs/RESEARCH-jarvis-agent-linux-2026.md`).
- **Context:** The research milestone formalized proactivity as three levels (Reactive /
  Scheduled / Situation-Aware) and named the design rule that matters here: the *insight* is
  the unit of proactive output, silence is a first-class decision, and systems should be able
  to report what they considered and declined to show. JARVIS's charter adds the hard
  constraint: the agent never initiates *action* — so a briefing may read local state and
  propose, but must never execute.

## Decision

**D1 — Briefings are computed, never executed.** `src/jarvis/brief/engine.py` composes a
briefing from four local, zero-subprocess sources: the task journal (recent failures),
the existing evidence-backed suggestions engine (`suggest.engine`, already journal/context-only),
unknown requests (what nothing could map — the owner's growth queue), and disk pressure via
`os.statvfs` (stdlib stat, not a `df` subprocess). **No playbook is added; the catalog stays
56**; a briefing runs no command, needs no consent, and is safe by construction.

**D2 — The v1 policy is deterministic and inspectable.** Notify iff any of: ≥1 failed task in
the recent journal window, ≥1 active suggestion, or free disk % under the threshold (default
15, owner-tunable). Otherwise the outcome is **silence with a recorded reason**. Every run —
notified or silent — appends one line to `<state>/briefings/ledger.jsonl` (decision, reasons,
id). `jarvis brief status` reports totals and the silence rate: the denominator-aware
transparency the 2026 proactivity literature calls for. Learning the policy from feedback
(Level 3) is parked; this release only records the data.

**D3 — Delivery is presentation, never action.** A notify writes `<state>/briefings/latest.md`
and, when `notify-send` exists and is not disabled, raises one hygiened desktop notification
(single line ≤200 chars, fixed argv — the same external-binary discipline as the voice stack).
Stdout printing honors `--quiet` (timer mode: file/ledger only). Nothing is ever executed,
scheduled side-effects included.

**D4 — Feedback is recorded, not acted on.** `jarvis brief accept|dismiss <id>` appends to the
ledger. `status` shows the counts. No acceptance currently changes anything — the guard rails
come before the learning.

**D5 — Scheduling is opt-in, mirroring residency.** `jarvis brief install [--on daily|weekly]`
writes a systemd **user** timer + service (`jarvis-brief.timer` → `python -m jarvis brief
--quiet`) and enables it via `systemctl --user`; when systemd-user is unavailable the files
are still written and the skip is disclosed with the manual command. `uninstall` reverses;
packaging never enables it. The doorway (ADR-0018) stays "a doorway, never an actor" — the
timer composes text, which is not action.

## Consequences

- The agent now has a polite, bounded presence: it may knock once a day with facts you taught
  it to watch for, and it keeps receipts for every knock it declined to make.
- Level 3 (learned interruption policy from accept/dismiss) is a future owner-gated step; the
  ledger schema is designed for it (reasons and feedback share one append-only file).
- Composition sources are intentionally conservative: journal, suggestions, unknown requests,
  statvfs. Command-based checks (pending package updates via the simulation flag) stay parked —
  they would be the first case of a scheduled trigger running subprocesses, and that exception
  deserves its own ADR.
