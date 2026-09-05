# ADR-0013: Architecture evolution — interoperability, verified skills, memory integrity, safe autonomy

- **Status:** Accepted and **fully implemented** (2026-09-03; owner go-ahead after the research + proposal presentation): **M9a** MCP server (1.3.0) · **M9c** integrity — `jarvis doctor`, context hash chain, canaries (1.4.0) · **M9d** charters (1.5.0) · **M9e** API-first GUI actions + **M9b** verified skill packs (1.6.0). Documented deviation: M9b packs are strict JSON, not the sketched YAML — the stdlib-only rule (ADR-0005) outranks the sketch; schema is otherwise as proposed, with tier ceilings structurally unnecessary (packs inherit the referenced playbook's tier and cannot override it). Research basis: [RESEARCH-agent-landscape-2026.md](../RESEARCH-agent-landscape-2026.md) (OpenClaw, Hermes, Open Interpreter, AutoGPT, OS-Copilot/UFO²/OSWorld field, MCP, skill-security ecosystem; all claims sourced there).
- **Context:** The owner directed a landscape study ("how others work, their disadvantages, then an enhancing architecture"). The study shows the field's systematic failures — unverified persistent state, instruction-pack supply chains, approval-as-boundary, non-determinism in the action path, pure-GUI fragility, autonomy without termination — while JARVIS's kernel already structurally answers several of them (ADR-0007/0008/0009). The gaps are interoperability, an ecosystem surface, memory integrity, safe recurrence, and API-first GUI actions.
- **Decision — the invariant holds: every new capability enters through the kernel, or it does not enter.** Phased plan (each phase = milestone-sized, gated, independently valuable):

## M9a — MCP server surface (interoperability, stdlib-only)
Expose the existing kernel to the ecosystem instead of reinventing tools:
- `jarvis mcp serve`: **MCP server over stdio** implemented with stdlib JSON-RPC 2.0 (guideline 16: no SDK dependency; the protocol's local transport is deliberately simple). Tools: `jarvis_do` (plays a playbook → same tiers/approval/journal; T2+ refuses without explicit per-call consent flag), `jarvis_explain` / `jarvis_facts` (knowledge), `jarvis_status` (fingerprint), `jarvis_suggest` (read-only), `jarvis_preview` (plan + blast radius). Resources: KB facts, journal task list.
- Harm model: an MCP client is just another untrusted-ingress front-end — identical standing to the CLI. Nothing bypasses tiers; there is **no** `eval`-style passthrough tool.
- Optional later: MCP **client** support with allowlist + per-server tier caps + scanning (Snyk/Mondoo threat categories), only after M9c's scanner exists.

## M9b — Verified skill packs (ecosystem, the anti-ClawHub)
Skills others ship as Markdown instructions the LLM reads at runtime; that design is precisely what got 12% of ClawHub compromised. JARVIS skills are **data that compile through the kernel**:
- A skill pack = `SKILL.yaml` (declarative: matchers → existing playbook primitives, params schema, tier ceiling) + **mandatory eval cases** + provenance (source URL + content hash).
- Loader validates schema, refuses anything referencing non-playbook primitives, runs the pack's evals, and records the hash in the integrity baseline (M9c). No runtime LLM interpretation of skill instructions, ever.
- Distribution later; local install + signature verification first. Rejected-skill categories mirror the scanner taxonomy: hidden-instruction patterns, network exfil, credential handling.

## M9c — Memory & config integrity (anti-drift, anti-poisoning)
Answer the "gradual security degradation" class OpenClaw documented:
- `jarvis doctor`: hash baseline (first run) of policy-relevant state — charters, skill packs, blocklists, KB files, CLI config — with `--write-baseline` explicit; drift alarm on every subsequent run and in `status`.
- Context store: **write-time scanning** of feedback/reasons (injection-pattern refusal) + hash-chained entries (tamper-evident, reusing the journal's artifact-hashing pattern); canary tokens embedded in suggestion output to detect leak paths.
- Journal already tamper-revalidates on undo (ADR-0008); this extends the same discipline to forward state.

## M9d — Charters as circuit-broken standing orders (safe heartbeats)
The M8c design hardened by AutoGPT's and OpenClaw's lessons:
- Charter = versioned, signed-local, revocable contract: playbook allowlist, tier ceiling (< T3, hard), schedule (systemd timer), **failure policy = pause**, per-run and monthly budget caps (steps + wall-clock), notification hook.
- Every charter run is a normal journaled task (same consent semantics at install time; runs are pre-authorized *by the charter*, scoped exactly to its allowlist); drift in charter bytes trips the M9c alarm; `jarvis charter revoke` kills timer + journal entry immediately.

## M9e — API-first GUI actions (the UFO² lesson)
- Backend order per capability becomes: native accessibility actions (AT-SPI `doAction`, DBus menus) → window-manager commands → synthetic input (last resort, consent-gated as today). Rationale: hybrid GUI+API measurably outperforms click-only agents, and control-detection is the field's top failure source.
- Extend the capability matrix with an `api` vs `injection` distinction so `gui status` shows which path each capability will take.

**Non-goals (explicit):** free-form code execution as a planner output (Open Interpreter trap); autonomous web browsing with system authority; remote/registrar skill distribution before signatures exist; any path where the model edits its own policy, skills, or charter bytes.

- **Consequences:** JARVIS gains ecosystem reach (any MCP client can wield a verified kernel), a supply-chain-safe skill story, tamper-evident state, safe recurrence, and field-aligned GUI semantics — each reusing the existing kernel, each independently shippable, none adding a parallel authority path. Sequencing: M9a → M9c → M9b → M9d → M9e (integrity machinery before distribution machinery).
