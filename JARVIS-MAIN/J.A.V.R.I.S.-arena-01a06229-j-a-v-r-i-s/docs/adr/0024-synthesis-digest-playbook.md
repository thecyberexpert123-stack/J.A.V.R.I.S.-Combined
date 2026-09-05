# ADR-0024: Synthesis-over-sources digest — the F6 playbook (`sys.digest`)

- **Status:** Accepted and implemented (2026-09-04; owner-directed "continue" — roadmap item R5b
  from `docs/RESEARCH-jarvis-agent-linux-2026.md`).
- **Context:** The research scores F6 ("data analysis and distillation") as *partial*: extract +
  aggregate playbooks exist, but "LLM synthesis [is] still hallucination-prone", and the gap
  line is verbatim — "no synthesis-over-sources playbook". The catalog's inspection family
  already produces trustworthy raw facts; what is missing is a playbook that *composes* those
  facts into one finding with the citation discipline of the rest of the engine.

## Decision

**D1 — The synthesis is computed, never generated.** `sys.digest` (tier T0, read-only) runs
exactly three source commands — the *same pinned argv* as three existing catalog playbooks:
`df -h` (`fs.disk_free`), `free -h` (`sys.memory`), `uptime` (`sys.uptime`). The synthesis
itself is a pure-stdlib function (`jarvis.system.digest.synthesize_digest`) over their captured
stdout — no LLM anywhere in the path. The research's caution about synthesis quality is met by
making synthesis deterministic arithmetic with disclosed thresholds, not generation.

**D2 — Verify IS the synthesis.** The playbook's VERIFY stage consumes the runner's captured
step results and returns `Verification(ok=…, detail=<digest>)`: the digest is computed by the
same pipeline stage that already exists for post-conditions, flows into the standard outcome,
and is journaled with the task like any verification detail. **Zero engine/orchestrator
changes.** Every digest line names its source playbook; the detail header discloses
"computed deterministically from N read-only sources (no LLM)".

**D3 — Disclosed thresholds, honest unreadable sources.** Fixed constants: warn at disk used
≥ 85% (root filesystem), memory used ≥ 85% (available vs total), load-1 > CPU core count.
A source whose output cannot be parsed becomes an explicit `[source unreadable: …]` line —
never a guess, never a fabricated number; `ok` is true iff at least one source was readable
(partial synthesis is honest, empty synthesis is a failed task). Warnings are findings, not
failures: they change the digest lines, not the task status.

**D4 — Catalog grows 56 → 57 by the breadth discipline.** One id, T0, no new argument slots,
no user data in any argv, "read-only; nothing to reverse" undo — the same rule every ADR-0016
entry followed. The ADR-0021 charter check is updated (briefings still add nothing; the catalog
grew by its own ADR). Per the ADR-0023 cadence, the trainer derives the new vocabulary from
`PLAYBOOKS` automatically: the corpus gains a `sys.digest` template family, the gates are
re-earned, and the shipped `model.json` is retrained in the same milestone — the
vocabulary==catalog pin keeps staleness loud.

**D5 — Authority unchanged.** The digest reads three T0 sources and reports; it proposes and
executes nothing beyond them (warnings are text, never follow-up actions — no unsolicited
action). Reconstruction stays frozen per ADR-0023 D4: the classifier may rank `sys.digest` in
disclosures, `suggest_intent` gains no extractor for it. Bare matcher only: "system digest",
"health check", "analyze my system" and close variants — anchored so nothing
already-matched (`system info`, `fs.disk_free`'s phrasings, …) is shadowed.

## Consequences

- F6 moves from *partial* to *shipped-for-system-sources*: one phrase yields a cited,
  deterministic health digest instead of four separate commands.
- The pattern is reusable: future sources (thermals, battery, service states) join by adding
  one source step + one pure parser + one disclosed threshold — each with its own review.
- What is deliberately not here: LLM-written narrative over the numbers (the research's
  hallucination trap), threshold auto-tuning from history (would need its own consent story),
  and any write-path digestion.
