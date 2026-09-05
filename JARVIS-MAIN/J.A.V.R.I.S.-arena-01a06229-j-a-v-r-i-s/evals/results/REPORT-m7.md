# JARVIS Evaluation Report — M7 addendum: Real-machine readiness

**Date:** 2026-09-02 · **Version:** 1.1.0 · **Scope:** M7 — closing the gap between "RC by engineering" and "trusted on a real machine"
**Companion to:** [REPORT-m6.md](REPORT-m6.md) — all M0–M6 gates remain in force and green.

---

## 1. Why this milestone exists

Owner review verdict on v1.0.0: **"RC by engineering, alpha by exposure."** The gates were
green, but no human had ever run JARVIS on a real machine, and the residual risks were
documented rather than closed. M7 closes what can be closed in code and makes the rest a
deliberate, staged human decision.

## 2. Deliverables (all implemented, tested, live-verified locally)

| # | Deliverable | Closes |
|---|---|---|
| 1 | **GUI focus TOCTOU guard** — focused window re-verified *after* consent, immediately before injection; focus change ⇒ abort with disclosure of old→new | risk #3: keystrokes landing in a different window |
| 2 | **`jarvis safety-check`** — live refusal battery through the real components (protected package, destructive NL, flag smuggling, protected file, T2 consent, GUI guard) with an **execution-blocked sentinel runner**: even a hypothetical refusal bug cannot touch the system; verdict `SAFETY CHECK PASSED` (7/7 observed) | "prove the kernel is alive on THIS machine" |
| 3 | **`jarvis do --preview`** — full plan + **blast radius** (max tier, root?, network?, commands, classified paths) without asking or executing | plan auditing before consent |
| 4 | **Auto-rollback** (`--auto-rollback`) — failed consented tasks are reversed automatically by reusing `undo()` end-to-end (artifact rebuild + kernel revalidation + verification) under the *original* task's consent; journal keeps the task `failed` + undo marked applied. Live-verified: file restored byte-identical after injected failure | risk #4: partial-failure state |
| 5 | **Cautious mode** (`jarvis cautious on/off/status`) — blocks T2+ even with `--yes` until each action is explicitly `--cautious-ok`'d; preview always allowed. Live-verified: T2 refused while ON | first-contact safety on a fresh machine |
| 6 | **Live-LLM injection corpus** (`tests/test_fault_injection_live.py`, marker `live_llm`) — 7 prompt-injection frames through a REAL local model; planner-or-kernel-must-refuse invariant; weekly CI lane (`llm-eval.yml`, workflow_dispatch + cron) installs Ollama + `qwen2.5:0.5b` and runs it — closing risk #2 with real-model evidence over time | risk #2: scripted-planner blind spot |
| 7 | **`docs/SAFE-TESTING.md`** — the verified/unverified map + the 4-rung testing ladder + reporting protocol | the human side of trust |

## 3. Verified (observed)

- ruff lint+format clean · mypy clean (43 files) · pytest **356 passed, 2 honest skips** (incl. 17 new M7 tests) · live 5 pass + 2 honest skips (live_llm needs a model)
- Packaging matrix **5/5 on the v1.1.0 artifacts** (debian/ubuntu deb, fedora rpm, arch makepkg→pacman, alpine wheel) — the matrix caught two more real defects in the 1.1.0 bump: an unquoted `depends=(python>=3.10)` (a bash redirect, not a dependency) and hardcoded 1.0.0 versions in the harness
- CI (unit/type/lint + M2 9/9 + M3 35/0 + M4 12/12 + M5 GUI) green on the M7 head; container eval green
- `jarvis safety-check` → **7/7 PASS** on this machine (and in CI via the standard gate)
- `--preview` blast radius: `tier=1 root=True network=True, commands: apt-get` observed live
- Cautious gate: T2 `--yes` refused while ON; `--cautious-ok` proceeds — observed live
- Auto-rollback: injected `tee` failure → task `failed`, file byte-identical, undo consumed — unit-verified with real journal

## 4. Still honest gaps

1. Real-model corpus runs only where a model exists (local Ollama / weekly CI lane) — first scheduled run will be the first real evidence.
2. Wayland desktop sessions remain fixture-verified only (unchanged from M5).
3. Cautious mode counts nothing yet — disabling is manual; a task-count hint may come later if needed.
4. The ladder's rungs 1–3 are *procedures for humans* — JARVIS can't verify a human followed them; SAFE-TESTING.md is the contract.
