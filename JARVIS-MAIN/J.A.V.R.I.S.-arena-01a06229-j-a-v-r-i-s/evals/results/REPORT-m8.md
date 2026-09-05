# JARVIS Evaluation Report — M8 addendum: adaptive initiative (M8a shipped; M8b–M8d designed)

**Date:** 2026-09-03 · **Version:** 1.2.0 · **Scope:** M8a suggestion engine (ADR-0012)
**Companion to:** [REPORT-m7.md](REPORT-m7.md) — all M0–M7 gates remain in force and green.

---

## 1. The design decision (owner-directed)

The owner asked how Marvel-style behaviors — helpful *unrequested* actions, self-development
over time, deep user context — could be designed for JARVIS. ADR-0012 records the answer and
its single governing invariant:

> **Proactivity proposes; consent executes. Context tunes what is suggested; it never grants
> authority to act. JARVIS may grow in knowledge, calibration, and skill library (supervised);
> it may never modify its own code, safety policy, or authority.**

## 2. M8a — shipped and verified

| Piece | Guarantee |
|---|---|
| `jarvis suggest` | 3 deterministic, evidence-backed rules: undo-orphans (failed tasks with available artifacts), stale package index (>14 d), distro-relevant pitfall briefing (KB fact + its sources) |
| Cite-or-abstain for suggestions | every suggestion lists its evidence (journal record or KB fact with sources); nothing is suggested "on a hunch" |
| Read-only by construction | the engine holds no Runner — it *cannot* execute; accept prints the exact command, which flows through the normal consent path |
| Feedback ledger | `accept`/`reject --reason` in the local context store; handled suggestions suppressed; rejections demand a reason (calibration signal) |
| Inspectability | `jarvis context show` + status line — the store says what it is and what it is not ("tunes suggestions; never grants authority") |

**Observed:** 13 new tests (rules, evidence, suppression, determinism, journal-resilience, CLI
flow) — suite **370 passed + 2 honest skips**; live flow verified (suggest → accept with
command → reject with reason → suppression → context show).

## 3. Designed, deliberately not built yet (M8b–M8d)

- **M8b context store:** preferences, inferred routines (marked inferred), house rules;
  inspectable/deletable/local-only; remote-LLM redaction rules.
- **M8c charters:** revocable standing orders on systemd timers; every run a normal journaled
  task; tier-capped below T3; rate-limited; instant revoke.
- **M8d growth loop:** JARVIS drafts KB/playbook proposals as PRs; CI gates; owner merges.

Each reuses the existing kernel; none adds a parallel authority path. The never-bend list
(ADR-0012) — no self-modification, no autonomous T3, context never increases action authority —
applies to all of them.

## 4. Honest gaps

1. Suggestions are rule-based (3 rules) — coverage grows with M8b context and M8d growth, not by magic.
2. The feedback ledger records decisions; ranking/calibration *use* of it arrives with M8b.
3. Charters (M8c) do not exist yet — recurring automation still requires the human to run the command (by design, for now).
