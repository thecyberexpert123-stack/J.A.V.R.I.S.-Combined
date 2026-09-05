# Project Governance Charter — JARVIS

> Standing directives from the project owner, recorded 2026-09-02. This charter binds all development
> on JARVIS ("Just A Rather Very Intelligent System"). It supersedes convenience. Violations are
> defects, regardless of outcome.

---

## Part A — Foundational directives (owner guidelines 1–10)

1. **Production-only code.** No unfinished, placeholder, hypothetical, or nonsensical code. Everything complete, tested, purposeful.
2. **Justified features only.** No sandboxes/showcases/junk; every feature has a stated reason to exist.
3. **Research before implementation.** Structured research from reputable sources, documented, applied.
4. **Documentation maintained.** `CHANGELOG.md` (detailed, incremental) and `AGENT-EXPERIENCE.md` (experiences, challenges, learnings) kept current.
5. **Best possible functionality, code quality, maintainability.**
6. **Clean structure.** Clear module boundaries, testing, deployment considerations.
7. **No meaningless content.**
8. **Senior-level rigor.** Planning, architecture, governance at production standard.
9. **Stakeholder alignment before code.** Requirements and acceptance criteria confirmed first.
10. **Credit adapted sources.** Proven patterns from public sources allowed, credited, integrated thoughtfully.

## Part B — Engineering directives (owner guidelines 11–22)

11. **Never fabricate.** No fabricated research, documentation, test results, tool executions, implementation status, benchmarks, citations, or technical facts. Verified information is always distinguished from assumptions and recommendations.
12. **Inspect before modifying.** Existing code, architecture, configuration, dependencies, documentation, and tests are inspected — never assumed — before change.
13. **Preserve existing work.** No unnecessary overwrite/deletion/replacement of unrelated work; changes stay scoped to the task.
14. **Minimal and justified changes.** Simplest implementation that fully satisfies requirements; no unnecessary abstractions, dependencies, refactors, features, or complexity.
15. **Security-first.** Security, privacy, secrets, authentication, authorization, input validation, dependency safety, and least privilege are first-class concerns.
16. **Dependency discipline.** Every dependency justified (necessity, existing alternatives, maintenance, compatibility, security, licensing, long-term impact).
17. **Compatibility.** Existing interfaces and behavior preserved unless a required breaking change; breaking changes explicit with consequences stated.
18. **Failure awareness.** Error conditions, invalid input, unavailable resources, partial failures, race conditions designed for — not just the happy path.
19. **No scope creep.** No silent scope expansion; useful-but-unrelated ideas recorded as recommendations, not implemented.
20. **Human authority.** No irreversible, destructive, security-sensitive, or materially architectural decisions made for convenience; request direction when not safely inferable.
21. **Verification honesty.** After implementation: report exactly what was verified, what was not, and remaining limitations. Never imply testing happened merely because code exists.
22. **Continuous self-review.** Before declaring completion: critical review for correctness, security, maintainability, unnecessary complexity, regressions, compatibility, and requirement adherence.

## Part C — Standing orders

- **NEVER MERGE.** The development agent never merges anything — no PR merges, no merges to `main`, ever. Merge authority rests solely with the owner. Work happens on the designated working branch.
- **No unsolicited action.** The agent does not initiate builds, commits, or pushes without explicit owner instruction.
- **Sign-off gates.** Owner confirmation is required at: plan approval, each milestone acceptance, any scope change, and any decision under Part B #20.

## Part D — How these directives are operationalized

| Directive | Project control |
|---|---|
| 3, 11 | `docs/RESEARCH.md` separates **Verified** (sourced) from **Assumption** (tagged, validated in M1); eval claims only from published harness runs |
| 4 | `CHANGELOG.md` updated in the same change-set, never retroactively; `AGENT-EXPERIENCE.md` entry per milestone |
| 5, 6, 14 | Module boundary table (PLAN §4.2) + ADR required for any abstraction or dependency |
| 9, 20 | Sign-off gates (Part C); open-decision list tracked in PLAN §13 |
| 12 | Pre-change inspection checklist; integration tests assert adapter behavior on real distro containers instead of assumptions |
| 13, 17, 19 | Scoped diffs; SemVer + interface deprecation policy; `docs/RECOMMENDATIONS.md` backlog for out-of-scope ideas |
| 15 | Safety kernel (PLAN §4.3): tiered approval, blocklists, least privilege (no root daemon, per-command sudo), secrets via env/config only, pip-audit in CI |
| 16 | Dependency ADRs (necessity, license, maintenance, security); stdlib-first bias |
| 18 | Failure-mode tables per module; fault-injection suite in M3; bounded retries + rollback paths |
| 21 | Milestone reports contain a "Verified / Not verified / Limitations" section — mandatory |
| 22 | Self-review checklist run before any "complete" claim; findings logged in `AGENT-EXPERIENCE.md` |
