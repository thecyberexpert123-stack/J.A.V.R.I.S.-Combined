# ADR-0014: AI failure semantics — breaker, taxonomy, grounded answers, no-AI contract (M10)

- **Status:** Accepted and implemented (2026-09-04, owner-directed: "what will the Agent do when
  the AI fails… unknown situation… how will it do without using an AI… proper AI integration").
  Research basis: [RESEARCH-ai-resilience-2026.md](../RESEARCH-ai-resilience-2026.md) (degradation
  ladders, circuit breakers, AbstentionBench abstention findings, structured-output practice; all
  claims sourced there).
- **Context:** ADR-0007 made the model propose and the kernel dispose; ADR-0003 routes local-first
  with honest refusal when no backend exists; ADR-0009 enforces cite-or-abstain. Audit against the
  research found five gaps: no memory of provider failure across CLI invocations (a hung model
  re-imposes its full timeout on every request, forever); provider failures collapse into one
  opaque string; the KB-miss path for `explain` has no AI extension (the model can propose
  *actions* but cannot help *answer*, even when cited knowledge exists that a strict matcher
  misses); an unknown request is a blind refusal with no nearest-alternatives, no journal record,
  no teaching path; and "no AI" is only an accident of a missing install, not an operator contract.

## Decisions

**D1 — Persisted per-provider circuit breaker (`providers/breaker.py`).** Three states
(CLOSED/OPEN/HALF-OPEN), threshold = 3 consecutive failures, cooldown = 300 s. State persists at
`state_dir()/ai/breaker.state` — the M9d charter precedent: operational state, deliberately *not*
`*.json`, outside the M9c integrity scope (it is not policy; policy drift remains the doctor's
witness). Wall-clock cooldown so it survives process boundaries (CLI is process-per-command);
half-open allows exactly one probe. A corrupted state file resets cleanly and is disclosed. A
malformed *output* counts as a provider failure (model unhealthy); an honest "unexpressible"
(empty steps) does **not** — the model is healthy, the request is out of vocabulary.

**D2 — Failure taxonomy (`ProviderError.kind`).** Every provider failure is classified:
`unreachable | timeout | http | malformed | key-missing`. The class surfaces in `jarvis ask`
output (text + JSON), in `status`, and in the breaker record — degraded-mode disclosure per R2:
what changed (AI path failed, class), what still works (deterministic engine, KB, journal), what
happens next (breaker state, how to disable/retry). No behavior is decided by the class; it is
disclosure, not policy.

**D3 — No retries on the planner path.** One attempt, then honest failure + breaker record. A
bounded retry doubles worst-case interactive latency for a transient class we cannot reliably
identify at this layer; the breaker already prevents retry storms (R2). Documented as a
deliberate deviation from the "retry briefly" rung: the CLI's interactivity budget outranks it.

**D4 — Structured planner wire.** Ollama gets the planner's real JSON Schema in `format`
(constrained generation); OpenAI-compatible gets `json_schema` response format when a schema is
supplied. Strict post-validation is unchanged — schema-constrained output is still untrusted
input (R4). Additive `schema` kwarg on the provider `Protocol` (internal API; both in-repo
backends updated).

**D5 — Grounded AI answers on KB misses (`knowledge/ai_answer.py`).** `jarvis explain` keeps its
deterministic cite-or-abstain answer *first and unchanged*; only on a KB miss, and only when the
operator has not disabled AI, does the planner backend get one bounded chance to synthesize an
answer **from an evidence envelope of real KB facts** (ids, claims, sources; capped). The output
contract: `{answer, fact_ids[], abstain}` — citations must be a subset of the supplied evidence;
empty/unknown citations or `abstain:true` → forced abstain (R3: structure, not prompts). Answer
text is injection-scanned (same pattern family as the M9c write-time scanner) and length-capped;
the cited facts get the same on-machine verification rendering as deterministic answers. Any
failure falls back to the deterministic refusal with a one-line disclosure. `abstain` is
*rewarded* in the prompt contract exactly as I-CALM rewards it: an honest abstention is a good
outcome, never an error. The MCP `jarvis_explain` tool stays deterministic-only — the
`javris-frontend/1` contract is frozen and its clients deserve latency-stable read-only answers
(documented deviation between CLI and MCP surfaces).

**D6 — Unknown situations are processed, not just refused.** When neither the engine nor (if
enabled) the planner can map a request: top-3 nearest known intents (difflib over the playbook
catalog), a journal `unknown_requests` record (capped, with the alternatives) the owner can review
as growth input — proactivity proposes, consent executes — and a hint that names the teaching
paths (`jarvis playbooks`, `jarvis grow --help`, skill packs). Structured as `reason:
"unknown-request"` in JSON output. This is the "I don't know" that R3 shows models must be forced
into: JARVIS forces it *architecturally* (nothing executes without a playbook match) and then
makes the abstention useful.

**D7 — The no-AI contract.** `--no-ai` (CLI) or `JARVIS_NO_AI=1` (env) disables every model path
in one switch — routing returns "none" with an honest note, `explain` stays purely deterministic,
and the whole suite passes with AI absent (air-gap/audit mode). The existing
`JARVIS_REMOTE_LLM=0` (remote-only kill switch) remains; `--no-ai` is the stronger, total switch.
Without either, behavior is exactly the shipped engine-first behavior: no model is contacted when
a playbook matches (unchanged, tested).

**D8 — Status/doctor disclose AI health; neither widens authority.** `status` gains an AI breaker
line (per-provider state); `doctor` reports AI backend state **informationally only** — env-dependent
provider config is not policy bytes and must not enter the M9c baseline (a model upgrade is not
drift). Nothing in this ADR lets a model, a breaker, or a status line execute, consent, or modify
policy: the kernel remains the only door (ADR-0013 invariant).

## Consequences

- New modules: `providers/breaker.py`, `knowledge/ai_answer.py`; journal gains an
  `unknown_requests` table (idempotent `CREATE TABLE IF NOT EXISTS`); additive changes to
  `ProviderError` (kind), provider `complete` (schema kwarg), `plan_routing` (enabled kwarg),
  `PlanRefused` (kind), `Answer` (ai_text field, default ""). Internal API additions only; CLI
  exit codes and JSON status shape unchanged (guideline 17).
- The model still never sees argv, paths, or the right to consent; evidence envelopes expose KB
  claims/sources only. Provider failures now have memory, so a dead Ollama degrades the *second*
  and later `ask` calls to instant honest refusals instead of fresh timeouts.
- Honest limitations: the breaker cannot distinguish "model down" from "model deprecated by the
  upstream provider" (both are provider failures); wall-clock cooldown trusts the local clock
  (documented; charter precedent accepts the same); nearest-intent ranking is lexical, not
  semantic — it suggests candidates, never executes them.
