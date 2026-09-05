# ADR-0017: Dragon Fly AI (DFA) alignment — the owner's architecture, assessed and adopted as our descriptive frame

- **Status:** Accepted as documentation (2026-09-04; owner suggestion: "as Suggestion I am telling
  you an AI Architecture, which I had derived myself. If it is useful for this project, you use
  it"). No code change required — assessed conformance is already structural; one delta adopted as
  a proposal (capability manifest), one delta deliberately diverged (autonomous iterate-loop).

## Context

The owner proposed an architecture they derived — **Dragon Fly AI (DFA)** — summarized by its own
closing line: *"the model provides reasoning, the tools provide capabilities, the orchestrator
provides control, and the execution environment provides action."* DFA's principles: capability
separation (each tool = one clearly defined capability, understood through interface and
description); reasoning separated from execution (a model's decision must never automatically
equal an unrestricted action — validation, permissions, logging, iteration limits sit between
decision and execution); composability and model swappability; optional evolution into
coordinated multi-component systems.

The assessment below was made against the actual source tree at `1b5d8eb` (v1.11.0). The honest
headline: **JARVIS already implements DFA** — independently derived, which is the strongest kind
of validation an architecture suggestion can receive. Adopting DFA therefore means (a) recording
the mapping so future contributors share one vocabulary, (b) taking the one genuinely new idea,
and (c) documenting one deliberate divergence so it is never "fixed" by accident.

## Decision

**D1 — The four DFA layers map one-to-one onto JARVIS's existing modules.** No re-plumbing:

| DFA layer | JARVIS realization (evidence) |
|---|---|
| Model = reasoning | `providers/` (`base`, `router`, `ollama`, `openai_compatible`) — the model is a swappable planner component behind a breaker; `--no-ai` runs the engine fully deterministically; LLM plans are hard-bounded (`MAX_STEPS = 6`, `planner/llm.py`) |
| Tools = capabilities | `planner/` playbooks — each a clearly defined capability (`id`, description, tier, match → validate → fixed-argv build → verify → undo); 56 as of ADR-0016; new families compose in without redesigning the agent (which ADR-0016 just demonstrated) |
| Orchestrator = control | the pipeline (match → plan → **approve** → execute → verify): `safety/approval.py` consent gates, `safety/tiers.py` tier gates, journal state, dry-run/preview, undo built before execution |
| Execution = action | `execution/runner.py` + `safety/` — no shell, static-argv checks, refusal-not-sanitization (ADR-0006), root policy, snapshots |

DFA's central safety claim — *"an LLM's decision should not automatically equal an unrestricted
system action"* — is verbatim JARVIS's founding rule (charter; ADR-0006/0007/0013): the planner
proposes, matchers and the kernel dispose.

**D2 — Adopted: capability manifests (the one genuinely new delta).** DFA says a tool is
understood "through its interface and description." JARVIS exposes descriptions and tiers
(`jarvis playbooks --json`, MCP tool descriptions) but not yet a machine-readable **parameter
interface** per playbook (argument slots, their kinds, undo class). Proposed as the next
milestone (v1.12.0, owner-gated): emit per-playbook manifests from the existing spec/factory
metadata — no new authority, purely descriptive surface for MCP consumers, the LLM planner, and
this project's own audit tooling.

**D3 — Diverged, deliberately: the autonomous observe-iterate loop.** DFA describes interpreting a
task, executing tools, observing results, and *"iteratively continuing toward the desired
objective."* JARVIS terminates: one plan, consent, execution, verify, undo — and if more work is
needed, the **human** types the next request. Proposals from the M11 model are text to type,
never self-executing. This is not a gap; it is the owner's guideline ("no blind execution, ever")
taking DFA's own control principle one step stricter than DFA itself. Any future agentic loop
would require explicit owner direction and a new ADR.

**D4 — Multi-component evolution: aligned already.** DFA's "specialized subsystems" trend maps to
what exists: the MCP surface (machine clients), the GUI capability matrix (contract-side,
identity-parity-tested), the proposals-only neural intent subsystem, the knowledge and integrity
doctors. JARVIS grows sidecar components without growing the kernel — DFA's composability, again.

## Consequences

- Contributors may use DFA vocabulary (reasoning/capabilities/control/action) interchangeably with
  the module map above; PLAN.md remains the normative architecture document.
- v1.12.0 candidate (D2) is recorded and owner-gated; no code moves until the owner says so.
- The D3 divergence is now explicit policy: an "iterative agent loop" issue/PR can be rejected by
  pointing here, the same way ADR-0013 rejects passthrough.
- No test, CLI, wire, or packaging change in this decision (docs-only).

## External sources

- Owner-provided DFA system overview (this conversation, 2026-09-04) — quoted principles:
  capability separation; reasoning vs execution; iteration limits and controls between decision
  and execution; "the model provides reasoning, the tools provide capabilities, the orchestrator
  provides control, and the execution environment provides action."
