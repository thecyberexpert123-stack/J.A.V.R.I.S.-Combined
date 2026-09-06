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
