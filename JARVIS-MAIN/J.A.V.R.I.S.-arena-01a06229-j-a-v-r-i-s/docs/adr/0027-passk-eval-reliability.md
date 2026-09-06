# ADR-0027: `pass^k` reliability reporting in the eval drivers (harness only)

- **Status:** Accepted and implemented (2026-09-06; owner-directed "continue" sequence,
  `TASKS.md` item B-C6, pre-approved as low-risk in decision D4; origin: deep research II
  `docs/RESEARCH-agent-construction-and-future-tech-2026.md` §9 / candidate C6).
- **Context:** ADR-0001 defines success as **≥ 98 % verified on the scoped catalog**. τ-bench
  (Yao et al., arXiv:2406.12045, §3) shows why a single pass over a catalog cannot support a
  reliability claim: it introduces `pass^k` — *the chance that all k i.i.d. trials of a task
  succeed, averaged over tasks* — and observes that agents with > 60 % average success fall
  below 25 % at `pass^8`. A 98 % target is therefore a `pass^k` target, not a `pass@k` one.
  Until this ADR every driver under `evals/harness/` ran each case exactly once (`m2_eval.py`
  and `m4_grounding.py` accepted only `--catalog`/`--results`), so the suite could measure
  *whether* a case passed but never *how consistently*.
- **Context (defect found during inspection):** `m2_eval.py` pinned each case's state to the
  persistent directory `/tmp/jarvis-m2-eval-<case-id>`. Three cases (`malformed-json-refused`,
  `unknown-intent-refused`, `injection-step-refused`) correctly record one ADR-0014 breaker
  failure per invocation; with the breaker's threshold of 3 and 300 s cooldown, the **fourth
  driver invocation within five minutes failed 6/9** with `planning backend failed
  (FailureKind.BREAKER_OPEN)` — false failures caused by the harness, not the kernel.
  Reproduced on 2026-09-06 (invocations 1–3: 9/9; invocation 4: 6/9). CI never observed it
  because every job is a fresh runner. Any `--runs k` with k ≥ 4 is impossible without fixing
  this, so per-run state isolation is a precondition of the feature, not scope creep.

## Decision

**D1 — `--runs K` on the two side-effect-free catalog drivers.** `m2_eval.py` (planner, scripted
LLM) and `m4_grounding.py` (cite-or-abstain) gain `--runs K` (`int`, `≥ 1`, default `1`). Each
catalog case is executed `K` times through the real CLI exactly as today; a case passes only if
**all `K` runs** meet its expectations. The default reproduces today's behaviour: at `--runs 1`
the console output is identical and the exit-code semantics are unchanged (`1` if any case has
any failing run, else `0`). The CI invocations in `.github/workflows/ci.yml` are not changed.

**D2 — The metric is τ-bench's estimator, computed once, shared.** `evals/harness/passk.py`
implements `pass^k = E_task[ C(c,k) / C(n,k) ]` for `c` successful out of `n` runs
(`math.comb`, stdlib), the curve `pass^1 … pass^n` from a single `n`-run session, and the
console rendering. `pass^1` is the plain mean success rate — at `n = 1` it equals today's
`passed/total`, which is what the unit tests pin. The module is stdlib-only and lives in the
harness, not in `src/jarvis` (no runtime code is touched).

**D3 — Results are additive; existing fields keep their meaning.** Suite summaries gain
`runs` (K) and `pass_hat` (`{"1": …, …, "K": …}`, rounded to 4 dp). Per-case records gain
`passes` (c), `runs` (n) and `runs_detail` (one entry per run: the per-run fields above plus what
was previously console-only — `error` and `elapsed_s` for M2, `unverifiable` for M4). Existing per-case fields (`status`, `detail`, `llm_requests`, `fact`, `machine`) carry
the **first run's** values, so a `--runs 1` record is today's record plus new keys. `failures`
/ `passed` / `schema_valid_plans` / `unverifiable_claims` keep their names; at `K > 1` they are
evaluated over all runs (a case counts as passed only when every run passed; a claim without
citation in *any* run is an unverifiable claim). No consumer of the JSON exists in-repo other
than CI's artifact write, so this is additive by construction; it is still recorded as an
interface change here (guideline 17).

**D4 — State isolation per run.** `m2_eval.py` gives every `(case, run)` a fresh
`tempfile.mkdtemp(prefix="jarvis-m2-eval-<case-id>-")` state directory (honours `TMPDIR`,
mode `0700`); it is removed when the run passes and **kept, with its path printed**, when the
run fails — the journal inside is the debugging evidence the old fixed path used to offer.
`m4_grounding.py` keeps its `setdefault` contract (an explicit `JARVIS_STATE_DIR` is respected
and never deleted); when the caller did not set one, each run gets its own temporary directory.
This closes the breaker-accumulation defect above for both drivers.

**D5 — Drivers deliberately excluded.** `m1_eval.py` mutates the host (real package
installs/removals inside distro containers); repeating a case changes the pre-state the
expectations were written for, so `pass^k` there needs idempotent catalog design first (owner
question, not a flag). `m3_faults.py` wraps one in-process pytest run of deterministic fault
vectors and only sees the aggregate verdict — there is no per-case surface to fold. `m5_gui.py`
needs a real X stack (Xvfb + i3) that is absent in this sandbox and already runs a 20-minute CI
job; multiplying it is an owner cost decision. All three keep their current interfaces.

**D6 — Where `pass^k` becomes informative is named, not claimed.** Both instrumented drivers are
deterministic under CI conditions (scripted LLM; KB-only answers), so `--runs K` there measures
*harness and kernel determinism* — which is exactly how D4's defect surfaced. Genuine
stochasticity enters only with a real model: (a) the weekly `llm-eval.yml` lane
(`tests/test_fault_injection_live.py`, 7-payload corpus, `temperature: 0` pinned in
`providers/ollama.py` yet not bit-reproducible across Ollama runs) and (b) `m4_grounding.py`
on a host where Ollama is reachable, where the two refusal cases exercise the grounded-AI
abstention path (`knowledge/ai_answer.py`) instead of the KB alone. Extending `pass^k` to (a)
means changing a workflow and a live test that cannot be executed from this sandbox; it is
recorded as follow-up **C6b** in `TASKS.md` for the owner to schedule, not landed unverified.

## Failure modes

| Precondition absent / fault | Behaviour |
|---|---|
| `--runs` omitted | `K = 1`; identical console output, exit codes and pass/fail semantics to before this ADR. |
| `--runs 0`, negative or non-integer | `argparse` rejects the value (exit 2) before any case runs. |
| A run times out or the CLI emits non-JSON | Recorded as `driver_error` for that run (unchanged handling); the case fails; remaining runs and cases still execute. |
| Temporary directory cannot be created | `tempfile.mkdtemp` raises before the run — the driver stops with a traceback rather than silently sharing state. |
| Failing run's state dir left behind | Intentional (D4); path is printed; nothing is auto-deleted on failure. |
| Stub LLM port exhaustion at large K | One ephemeral-port server per `(case, run)`, closed in `finally`; 9 cases × K servers are sequential, never concurrent. |

## Consequences

- Reliability can now be *measured* in the lane CI already runs: `python evals/harness/m2_eval.py
  --catalog evals/catalog/m2.json --results out.json --runs 5` yields the `pass^1 … pass^5`
  curve; a flaky case shows as `passes < runs` with the failing run's detail.
- A latent local-rerun defect is closed (D4); the fix is also what makes `K ≥ 4` possible.
- Nothing in the shipped package changes; the version is not bumped (harness/docs only, per the
  `RELEASING.md` precedent that tooling-only changes ship without a tag). The owner decides
  whether the sequence's items roll into a release together.
- Not verified here: the real-model lane (no Ollama in the sandbox), and CI execution of the
  unchanged invocations (`api.github.com` unreachable). Both are stated in `TASKS.md` §B-C6.
