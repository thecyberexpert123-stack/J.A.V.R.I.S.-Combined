# Agent Experience Log — combined repository

Cross-cutting notes only. Each sub-project keeps its own detailed log:

- kernel: [`JARVIS-MAIN/…/AGENT-EXPERIENCE.md`](JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s/AGENT-EXPERIENCE.md)
- HUD: [`JARVIS-GUI/…/AGENT-EXPERIENCE.md`](JARVIS-GUI/J.A.V.R.I.S.-GUI-arena-01a0667a-j-a-v-r-i-s-gui/AGENT-EXPERIENCE.md) (Round 10 covers this audit)

---

## 2026-09-06 · First audit of the combined tree

**What "test this project" turned into.** Both projects arrived with green
gates and long, candid logs of their own. Re-running the gates confirmed them
(kernel 856/2 skips; HUD 306 unit + 103 QML at the start) and would have been a
defensible place to stop. It was not the right place. The defects worth the
owner's attention were all in the *seam* between the two projects — how the HUD
interprets what the kernel says, and whether the HUD's own controls can reach
the code its tests exercise — and no per-project gate looks there. The method
that found them was the same each time: drive the real object through a
sequence a person would perform, and read what comes out.

**Three findings, in order of severity as I see it.**

1. *Consent offered for refusals that consent cannot lift.* The kernel's
   `status: "refused"` envelope is shared by four guards; only the approval
   policy is lifted by `allow: true`. I proved the others by re-sending with
   consent and receiving the same sentence. The HUD keyed its APPROVE button on
   the tier alone. No damage was possible — the kernel is unconditional about
   these — but a consent dialog that misstates what the owner can authorise is
   the one dialog that must not. Fixed at the classifier, keyed on the kernel's
   own words, fail-closed when it names no guard.
2. *A feature with no entry point.* `connectAgent()` was implemented, tested
   and unreachable. The console's `help` advertised verbs that could only ever
   answer "not connected". Found by typing what `help` said to type.
3. *Silent dead ends.* The state table forbade `PROCESSING -> STANDBY`, and
   the controller skipped illegal transitions quietly by design. Six ordinary
   sequences ended with the header reporting a request in flight when nothing
   was. The owner chose the minimal table change over a redesign.

**Two things about the combined repository itself.** The import dropped the
executable bit on seven scripts, including the one the kernel's packaging and
release workflows exec directly; nothing in either test suite looks at a file
mode, so this was visible only by diffing blob modes against upstream. And the
tree had no root-level orientation at all — the two READMEs each describe one
half, and the wiring contract is documented from both sides but linked from
neither root. Both fixed.

**What I asked rather than decided.** Whether to add a console verb, a visible
control, or both (both); whether to widen the state table minimally or redesign
it (minimal); whether to fix or merely document the refusal classification
(fix); and whether root-level docs and sub-project touch-ups were in scope
(yes). Each was a product or architectural decision, not an implementation
detail, and each was put to the owner before code changed.

**Honesty notes.** My first refusal fixtures were typed from memory and were
wrong; the live end-to-end run against the real CLI caught it, and the
committed fixtures are now verbatim captures. The two M4 grounding misses are
GitHub reachability from the sandbox, verified with and without a token, and
are recorded as an environment limit rather than glossed. The resident HTTP
transport was not re-driven live this round. Nothing was merged; `main` was not
touched.

---

## 2026-09-06 · Deep research II (cross-cutting note)

The research task that followed the audit lives in the kernel's docs
(`JARVIS-MAIN/…/docs/RESEARCH-agent-construction-and-future-tech-2026.md`) and
its detailed experience entry is in the kernel's log. Two things touch the
combined tree specifically: (1) the MCP `2026-07-28` findings apply to *both*
halves — the kernel echoes any date-shaped `protocolVersion` and the HUD pins
`2025-03-26`, and neither uses the newly deprecated Roots/Sampling/Logging; a
migration, if wanted, is a two-repo change and is posed to the owner as a
question, not started; (2) the environment-signal candidates (suspend/resume,
lock, network, battery, idle) would be sensed by the kernel's opt-in doorway and
*surfaced* by the HUD — a seam that the audit showed is exactly where defects
hide, so any future ADR on it should specify the wire shape first. No code, no
commit, no push this turn.

## 2026-09-06 · Sequence item C6 (cross-cutting note)

The first follow-through item touched only the kernel's eval harness, so the
substantive log lives in the kernel `AGENT-EXPERIENCE.md`. Two things matter at
the combined-repo level: (1) the inspection step found that the M2 driver had
been un-rerunnable locally (fixed `/tmp` state dir + ADR-0014 breaker → 6/9
false failures on the 4th run within five minutes) — invisible in CI, visible
the moment someone iterates in a checkout like this one; (2) the GUI half is
untouched by C6, and the next item that crosses the seam is C7 (MCP
`protocolVersion`), which remains an owner question. Working tree still
uncommitted pending the owner's commit instruction (`TASKS.md` A4 / D3).

## 2026-09-06 · Sequence item C11 (cross-cutting note)

Kernel-only again (journal + `doctor`); the GUI never reads the journal
directly — it goes through the MCP `journal://tasks` resource, whose payload is
unchanged — so nothing crosses the seam. The one combined-repo consequence:
`jarvis doctor` can now exit 1 on a machine where it exited 0, *iff* the journal
was edited outside jarvis; anyone scripting `doctor` in the GUI's future health
panel should treat the new `journal_chain` JSON key as part of `clean`. Still
uncommitted pending the owner's commit instruction (`TASKS.md` A4 / D3).

## 2026-09-06 · Sequence item C3 (cross-cutting note)

Kernel-only in code, but it changes what the HUD's resident mode can rely on:
`jarvis-serve.service` is now supervised (`Type=notify` + `WatchdogSec=30`),
so a doorway that stops answering `/v1/health` is restarted by systemd within
about 32 seconds instead of staying "active (running)" forever. The HUD's
`bridge/resident.py` polls `/v1/health` and already treats a refused connection
as "resident unavailable → fall back to stdio", so no GUI change is needed; a
future HUD health panel could show `systemctl --user show jarvis-serve -p
StatusText` for the same line the doorway sends. The finding worth carrying
across both halves: user-manager sandboxing directives and `sudo -n` are
mutually exclusive — anything in this tree that may escalate cannot be
confined by unit directives alone.

## 2026-09-06 · Sequence item C1 (cross-cutting note)

Kernel-only again, with one seam the HUD should know about: the MCP
`jarvis_status` payload and `jarvis status --json` now carry an additive
`argument_policy: {state, rules}` key. The GUI's status panel renders the
fingerprint fields it knows and ignores unknown keys (checked: no schema
assertion on the payload), so nothing changes there today; a later HUD item
could surface `state: malformed` as a warning badge, because that state means
the kernel is refusing T1+ playbooks until `jarvis policy lint` passes. Refusals
from the policy arrive through the same `status: refused` + `error` shape as
every other refusal, so the HUD's existing refusal rendering shows the rule id
and the owner's reason verbatim.


## 2026-09-08 · C12 — owner-added item, design phase

The owner extended the sequence with a self-authoring-skills feature and a
reference repository (Ada-SI). Kernel-only again (ADR-0032; nothing in `src/`),
but one HUD note for later: if Tier A ships, `jarvis grow forge` proposals
appear only under `proposals/skills/` until the owner installs them, so the
HUD's skill/status panel needs no change — installed packs still surface
through `jarvis skill list` exactly as today. A future "pending proposals"
badge would read the proposals directory, never the forge transcript, which
carries the raw request text (potential prompt-injection payload) and should
be shown, if at all, escaped and read-only.

## 2026-09-08 · C2 — design phase, measured first

Kernel-only (ADR-0033; nothing in `src/`). HUD note: if accepted, `jarvis status --json` and the
MCP `jarvis_status` payload gain an additive `stale_tasks` list; the HUD may render it as a
badge ("1 interrupted task — open a terminal to decide") but must not offer a resume button
itself — the consent for `resume` is a shell-side act in the proposal, exactly like `--yes`.
