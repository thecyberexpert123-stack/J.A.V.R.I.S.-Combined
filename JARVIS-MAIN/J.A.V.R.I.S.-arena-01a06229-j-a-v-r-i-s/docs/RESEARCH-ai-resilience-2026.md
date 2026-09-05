# RESEARCH: AI failure semantics, unknown situations, and no-AI operation (2026-09-04)

Owner-directed study behind ADR-0014 (M10): *what does the agent do when the AI fails, how does it
process unknown situations, how does it work with no AI at all, and what does a proper AI
integration look like?* All claims below are sourced; internal evidence cites this repository.

## R1. Production failures live in the orchestration layer, not the model

- "Production failures in LLM systems stem mostly from orchestration issues, not model quality.
  Missing retry logic, poor context window management, and unhandled tool call failures cause the
  majority of outages" — MLflow's 2026 engineering guide ([mlflow.org](https://mlflow.org/articles/llm-application-architecture-a-2026-engineers-guide/)).
  The model layer must treat the model as "a replaceable component, not a hard dependency", with
  caching and fallback chains at the access layer.
- Failure causes observed in production agents: silent provider model updates shifting output
  characteristics, input distribution shift, and drift in retrieved documents — i.e. the agent must
  expect its AI to change underneath it
  ([trantorinc.com](https://www.trantorinc.com/blog/ai-agent-failure-modes-what-goes-wrong-design-resilience)).
- Practitioner norm for tool-calling agents: "strict schema validation plus allowlists before any
  tool runs … frameworks often default to *no validation*" — validation dies at the schema gate
  before anything executes ([r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1r288w3/how_common_is_it_to_validate_llm_output_before/)).

**JARVIS today:** the propose/dispose split (ADR-0007) already implements the allowlist norm —
every LLM step is re-validated through the *real* playbook matchers (`planner/llm.py`), the model
never emits commands, and the kernel disposes. Confirmed correct by R1.

## R2. When the AI is down: the degradation ladder and the circuit breaker

- A trusted ladder for model unavailability: (1) retry **briefly**, only when the same path has a
  real chance — short timeout, tight cap; (2) switch only to a *contract-compatible* fallback;
  (3) **reduce capability on purpose**; (4) hand off cleanly when trust matters more than
  continuity ([buildmvpfast.com](https://www.buildmvpfast.com/blog/graceful-degradation-ai-agents-fallback-model-unavailable-2026)).
- Circuit breakers complement retries/fallbacks: retries handle transient glitches but "don't
  detect persistent failures" and can create retry storms; breakers stop hammering a failing
  dependency (CLOSED → OPEN on threshold, HALF-OPEN probes recovery)
  ([zylos.ai](https://zylos.ai/research/2026-02-20-graceful-degradation-ai-agent-systems/),
  [trantorinc.com](https://www.trantorinc.com/blog/ai-agent-failure-modes-what-goes-wrong-design-resilience)).
- The user-facing contract of a degraded mode must answer three questions immediately: **what
  changed, what still works, what happens next** — "the UI should reveal the degraded contract
  faster than your logs reveal the root cause" (buildmvpfast). And degraded state must be
  communicated "so downstream consumers can calibrate their trust" (zylos).
- For a CLI invoked process-per-command, a breaker is only meaningful if it **persists across
  processes**; JARVIS already has the exact precedent: charter run-state persists as `.state`
  files *deliberately outside* the integrity scope (M9d), because it is operational, not policy.

**JARVIS gap found:** providers fail honestly per-call (classified `ProviderError`, honest
refusals) but nothing remembers failure across invocations — a hung local model costs a fresh
long timeout on every `ask`, forever. **Fixed in M10:** a persisted three-state breaker per
provider, plus a one-line honest disclosure on every degraded result.

## R3. Unknown situations: structural abstention, not prompt-begging

- AbstentionBench (20 LLMs, 35k+ queries): models "inappropriately respond definitively" to
  unanswerable/underspecified/false-premise questions; abstention recall is poor even for strong
  reasoners — "accurate reasoning ≠ good abstention" and crafted prompts "boost recall but are
  insufficient" ([arXiv 2506.09038](https://arxiv.org/pdf/2506.09038),
  [emergentmind](https://www.emergentmind.com/topics/abstentionbench)).
- Mitigations that move the frontier: rewarding "I don't know" explicitly (I-CALM,
  [arXiv 2604.03904](https://arxiv.org/html/2604.03904)) and self-consistency-based conformal
  policies with distribution-free risk bounds
  ([arXiv 2405.01563](https://arxiv.org/html/2405.01563)). Common thread: abstention must be a
  **structural outcome with a reward/cost structure**, not an instruction the model is hoped to
  follow.
- "The model does not know when it is wrong … if you have no check, you consume it as truth";
  temperature 0 makes wrong answers *repeatable*, not correct — the defense is an output contract:
  schema validation, confidence gating, cross-reference checks
  ([dev.to](https://dev.to/vhub_systems_ed5641f65d59/how-to-validate-llm-outputs-in-production-before-they-break-your-pipeline-ahl)).

**JARVIS mapping:** cite-or-abstain (ADR-0009) is already the correct abstention *structure* for
answers; propose/dispose is the structure for actions. M10 extends both to the AI-assisted paths:
an AI answer may only cite fact IDs from the evidence envelope it was actually given (unknown or
empty citations → forced abstain), and an unexpressible request must land in a *useful* refusal:
nearest known intents, a journal record the owner can review, and teaching paths — the
"what changed / what still works / what happens next" contract applied to "I don't know".

## R4. Structured output is necessary but not sufficient

- Ollama supports constrained generation via a JSON **Schema** in `format`
  ([docs.ollama.com](https://docs.ollama.com/capabilities/structured-outputs)); JARVIS currently
  sends `format: "json"` (free JSON, prompt-described shape).
- But even with format constrained, "the service layer still needs parse-normalize-validate
  logic … Ollama and clients can disagree on exact strings even when format is set", and
  temperature belongs at 0 for structured steps
  ([glukhov.org](https://www.glukhov.org/llm-performance/ollama/llm-structured-output-with-ollama-in-python-and-go/)).

**Decision:** upgrade the planner wire to a real JSON schema *and keep* the strict
post-validate (belt and suspenders), matching R1's allowlist norm.

## R5. Operating with no AI at all

The chain-of-responsibility pattern for degraded agents ends in a "rule-based fallback
(deterministic responses for common queries)" before human escalation (zylos). JARVIS inverts the
frame: the deterministic engine is the *primary* (engine-first routing, ADR-0007), the model is an
accelerator for what playbooks cannot express. With no backend, the agent refuses honestly instead
of guessing (already implemented); M10 adds the explicit operator kill switch (`--no-ai` /
`JARVIS_NO_AI=1`) so "no AI" becomes a declared, testable contract rather than an accident of a
missing Ollama install — air-gapped and audit-friendly.

## R6. What M10 builds from this (summary → ADR-0014)

| Research finding | ADR-0014 decision |
| --- | --- |
| R1: validate + allowlist before execution | keep propose/dispose; add schema-constrained planner wire |
| R2: breaker with persistent state; degraded-mode disclosure | persisted 3-state breaker per provider; one-line disclosure on every degraded result |
| R2: failure classification | typed failure taxonomy (`unreachable/timeout/http/malformed/consent-shape`) in outcome JSON + `status` |
| R3: structural abstention; useful "I don't know" | AI answers cite-only-from-evidence or abstain; unknown requests → nearest intents + journal record + teaching hint |
| R4: schema AND post-validate | planner sends JSON Schema; validation unchanged |
| R5: no-AI is a contract | `--no-ai` / `JARVIS_NO_AI=1`; no-AI suite green end-to-end |
