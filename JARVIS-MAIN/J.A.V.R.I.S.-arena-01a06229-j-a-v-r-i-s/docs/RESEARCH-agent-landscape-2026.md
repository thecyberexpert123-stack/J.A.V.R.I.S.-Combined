# Agent Landscape Research — how the 2026 field works, where it fails, and what JARVIS should learn

**Date:** 2026-09-03 · **Method:** web research (30+ sources, all cited inline) + first-hand codebase knowledge of JARVIS v1.2.1 · **Companion decision:** [ADR-0013](0013-architecture-evolution.md)

> Guideline compliance: every claim below is sourced; JARVIS-side assessments cite our own ADRs/eval reports; nothing is claimed from memory alone.

---

## 1. Our baseline (what is being enhanced)

JARVIS v1.2.1: 13-module safety-kernel architecture — deterministic playbooks → tiered approval (T0–T2; T3 refused) → argv-only execution → journal/undo → cite-or-abstain knowledge (upstream-verified vs torvalds/linux) → capability-matrix GUI control → read-only suggestions + feedback ledger. Evidence: 70/70 distro execution eval, 35-vector injection gate (0 escapes), 15/15 GUI tasks on real X, 5/5 install matrix, 372 tests. ADRs 0001–0012.

---

## 2. The landscape: how each system works

### 2.1 OpenClaw (fka Clawdbot/Moltbot) — the viral personal-agent gateway

**How it works** [nebius.com/blog/posts/openclaw-security; brilworks.com/blog/what-is-openclaw; medium.com/@nimritakoul01 OpenClaw Architecture; entelligence.ai/blogs/openclaw; dev.to same; bibek-poudel.medium.com]:
- TypeScript monorepo, hub-and-spoke: a local **Gateway** daemon (control plane: channel auth, routing, sessions, policy) + **agent runtime** (LLM loop, tool calls) + **channel connectors** (WhatsApp, Telegram, Slack, Discord, Signal, iMessage — 20+) + **skills** + **memory**.
- **Skills are Markdown** (`SKILL.md` + scripts), loaded on demand from the ClawHub registry (100+ community skills); context assembly injects only names/descriptions, the model reads skill files when it deems relevant.
- **Memory is files**: `AGENTS.md` (behavior), `SOUL.md` (personality), `TOOLS.md`, `MEMORY.md`, timestamped conversation logs. No database.
- **Heartbeat**: periodic proactive checks ("speak up when there's a reason"); cron jobs; sub-agent spawning; MCP support via a bridge (mcporter); Web Control UI; mobile nodes.
- Single-user trust model by design ("anyone with Gateway access is a trusted operator"); DM pairing for unknown senders.

**Documented disadvantages** [thehackernews.com OpenClaw AI Agent Flaws; github.com/centminmod/explain-openclaw prompt-injection-attacks.md; alibabacloud.com blog; blogs.cisco.com; eastondev.com]:
1. **CVE-2026-25253** (CVSS 8.8) remote code execution.
2. **Poisoned skill supply chain**: 341 of 2,857 ClawHub skills (~12%) found malicious (keyloggers, AMOS stealer); Cisco documented a skill performing silent `curl` exfiltration plus prompt injection to bypass safety guidelines.
3. **Indirect prompt injection at scale**: CNCERT (China) warned of "inherently weak default security configurations" and restricted use in government systems; PromptArmor demonstrated **link-preview exfiltration** — the agent is tricked into building an attacker-domain URL with sensitive query params, exfiltrating on message render without any click.
4. **Persistent-state attacks with no drift detection**: "gradual security degradation" — injection edits `MEMORY.md`/config/cron one plausible step at a time; nothing tracks drift from a known-good baseline and each session is blind to the pattern.
5. Plaintext API keys in configs; thousands of instances internet-exposed; prompt injection declared out-of-scope for the project's bug bounty.

### 2.2 Hermes Agent (Nous Research) — the self-improving personal agent

**How it works** [tencentcloud.com techpedia 143930; codersera.com hermes-agent-guide; aiprofitboardroom.com hermes-agent-architecture; petronellatech.com; tosea.ai guide]:
- MIT, Feb 2026; background daemon; "harness is the body, the model is the brain" — 200+ model backends.
- **Three-layer memory** (working / episodic / procedural) in local SQLite with FTS5; **memory entries security-scanned before storage** (injection/exfiltration pattern detection).
- **Closed-loop self-learning**: reviews own performance and writes/iterates its own skill files ("backpropagation for prompts, not weights"); skills via agentskills.io.
- Surfaces: CLI/TUI/desktop/web + 14+ messaging platforms; automation via cron, loops, heartbeats, subagents, Kanban; **A2A protocol** interop + reads shared instruction files (agents.md/claude.md); one-file identity export.

**Disadvantages** (from the same sources + class analysis):
1. The self-modifying skill loop is the **trust hard-problem**: skills the agent wrote itself are exactly the persistent state an injection can poison (OpenClaw's failure class, one abstraction higher).
2. Same messaging-channel attack surface class as OpenClaw (untrusted senders → agent with system access).
3. Skill provenance/verification is thinner than the emerging scanner ecosystem assumes (no mandatory signed provenance in the documented design).

### 2.3 Open Interpreter — natural language → code on your real machine

**How it works** [starlog.is openinterpreter; deepwiki.com OpenInterpreter; docs.openinterpreter.com SAFE_MODE; github SAFE_MODE.md]:
- Provider-agnostic LLM emits markdown code blocks → shown for approval → executed via Python `exec()`/Node/shell **on the real system**; errors fed back for self-repair; OS mode; optional Docker sandbox; safe mode = experimental semgrep scanning, docs state "does not provide any guarantees of safety or security."

**Disadvantages** (starlog.is "Gotcha" analysis is explicit):
1. **Approval is not a security boundary**: a human reviewing probabilistic code will not reliably catch a subtle `rm -rf` with a complex glob or data exfiltration interleaved between legitimate operations; "no static analysis, no sandboxing by default, no rate limiting."
2. **Non-determinism is a showstopper for automation**: the same prompt produces different code across runs; "a script that worked yesterday might fail today."
3. Weaker local models produce "subtly broken operations that fail in dangerous ways."

### 2.4 GUI/computer-use agents (OS-Copilot/FRIDAY, UFO², OSWorld field)

**How they work / state of the art** [zylos.ai 2026 computer-use survey; arxiv 2504.14603 UFO²; emergentmind.com OS-Copilot; huggingface.co papers index]:
- Sense–plan–act loops over screenshots + accessibility APIs; OS-Copilot adds multi-timescale memory and self-created tools (FRIDAY, +35% via tool learning); UFO² is a "Desktop AgentOS" with HostAgent + per-app AppAgents.
- Scores on OSWorld: GPT-4o ≈ 20.6%, UI-TARS ≈ 24.6–47.5, **VLAA-GUI 77.5% (2026 frontier, surpassing the 72.4% human baseline in single pass)**, CoAct-1 **60.76% using "coding as actions"** (terminal/script instead of clicking).

**Disadvantages / lessons** [UFO² paper §6; zylos.ai]:
1. **Pure clicking is the wrong abstraction**: UFO² error analysis — >62% of failures are *control-detection* on non-standard UIs; hybrid **GUI+native-API** execution "improves completion by over 8%" and cuts fragility; richest API availability (Office) doubles success vs GUI-only baselines.
2. Cross-application workflows remain the hardest class (single digits historically; still weakest even for leaders).
3. OS-Copilot authors: evaluation brittleness (state-delta inference), safety/interpretability "partially realized," personalization at scale unresolved.

### 2.5 AutoGPT — the cautionary tale that validates our design

**What happened** [github.com/vectara/awesome-agent-failures autogpt case study; mmntm.net autogpt-lessons; builtin.com; sider.ai review]:
- Infinite loops (vague goals → "more work needed" forever), perfectionism bias, no progress/repetition detection, unbounded cost; the team **pivoted away from unconstrained autonomy**: "autonomy without boundaries is chaos… Design for controllability. Let humans set the boundaries. Let AI execute within them."
- Also instructive: they **removed vector databases** for simple JSON storage ("we over-engineered this").

**Lessons for JARVIS**: concrete termination criteria (our `verify` checks), progress detection (our journal), resource budgets (per-step timeouts exist; plan-level budgets worth adding), human-set boundaries (our tiers/charters) — all already core here; AutoGPT is post-hoc validation of ADR-0007.

### 2.6 MCP (Model Context Protocol) — the interoperability standard

**State** [sureprompts.com MCP guide; openclaw.direct MCP news; presenc.ai ecosystem stats; chatforest.com ecosystem report]:
- Open JSON-RPC 2.0 standard (Anthropic, Nov 2024; donated to the Agentic AI Foundation/Linux Foundation Dec 2025; backed by Anthropic, OpenAI, Google, Microsoft). Primitives: **tools, resources, prompts**; transports: stdio (local) and HTTP/SSE (remote); capability negotiation on connect.
- Ecosystem: ~8,000–12,000+ distinct servers (Q2 2026); registries (Glama 71k+ listings incl. duplicates); enterprise pattern: private servers + central registry + **human-in-the-loop approval for sensitive operations** (Pinterest case study).
- Known pains: quality/signal-to-noise, security scanning now an industry (see 2.7), stateful→stateless transport transition.

### 2.7 The agent-skill security ecosystem

[snyk agent-scan; labs.snyk.io skill inspector; mcpservers.org sentry skill-scanner; microsoft agent-governance-toolkit; mondoo ai-agent-security]:
- Threat taxonomy converging: prompt injection (91% of confirmed malicious skills), malicious code/backdoors, credential handling, untrusted third-party content, tool poisoning/shadowing, toxic flows, **memory poisoning**.
- Emerging defenses: pre-install skill scanners (Snyk Agent Scan, Mondoo 6-layer, Sentry skill-scanner), **write-time memory scanning + hash-based integrity verification** (Microsoft MemoryGuard), canary tokens, MCP server scanning.
- This industry exists *because* the default agent architectures store unverified persistent state — see 2.1 #4.

---

## 3. Cross-cutting synthesis: where the field systematically fails

| Failure class | Seen in | Root cause |
|---|---|---|
| Untrusted content reaches a privileged executor | OpenClaw, Hermes-class, all browsing agents | LLM mediates between untrusted text and system authority |
| Persistent state is unverified → drift/poisoning | OpenClaw (MEMORY.md/config/cron), memory-based agents | No integrity baseline; cross-session blindness |
| Supply chain of instruction-packs | ClawHub (12% malicious), skills marketplaces | Instructions-as-data with no scanning/provenance |
| Approval treated as a security boundary | Open Interpreter | Human skim of probabilistic output ≠ control |
| Non-determinism in the automation path | Open Interpreter, pure-LLM planners | Free-form code/reasoning where deterministic logic belongs |
| Pure-GUI abstraction fragility | UFO² error analysis | Screenshots + synthetic input instead of OS APIs |
| Autonomy without termination/budgets | AutoGPT | No "good-enough" criteria, no progress detection |
| Integration silos | pre-MCP frameworks | n×m bespoke tool wiring |

---

## 4. Where JARVIS already leads (evidence-based)

1. **Kernel separation** ("LLM proposes, kernel disposes", ADR-0007) is the structural answer to failure classes 1, 4, 5 — our planner cannot emit free-form commands; playbooks are deterministic code with verify-checks (termination) and undo (reversal). AutoGPT's hard-won conclusions were our ADRs from day one.
2. **Untrusted-ingress discipline** (ADR-0008: journal re-validation) anticipates the memory-poisoning class; our 35-vector gate includes tampered-journal attacks.
3. **Cite-or-abstain knowledge** (ADR-0009) with CI-verified upstream citations is stricter than anything surveyed.
4. **Capability-matrix GUI** (ADR-0010) already follows the honest-degradation principle the GUI field lacks; the UFO²/CoAct data now tell us how to go further (§5.3).
5. **Zero runtime dependencies** (ADR-0005) — no supply chain to poison at the package level.

## 5. Where JARVIS lags — and the architecture response (→ ADR-0013)

| Gap vs field | Evidence | Response |
|---|---|---|
| No interoperability surface (others' tools can't use our kernel; we can't use theirs) | MCP is "table stakes" (§2.6) | **M9a: MCP server exposing playbooks/knowledge/status as tools** (stdlib JSON-RPC/stdio — no SDK dependency); optional MCP *client* behind the same tier/allowlist/scanning gates |
| No skill ecosystem (our playbooks are code-only; others ship thousands of installable skills) | ClawHub scale vs ClawHub's 12% malware (§2.1/2.7) | **M9b: verified skill packs** — Markdown-declared, compiled to validated plan structures through the kernel (never LLM-read-at-runtime), mandatory eval cases, provenance, scanner (injection/network/exfil patterns), signature verification |
| No memory integrity baseline (drift/poisoning class) | OpenClaw degradation attacks; MemoryGuard (§2.7) | **M9c: hardened context/memory** — hash-baseline of config/skills/policy with `jarvis doctor` drift detection; context store write-time scanning; canary tokens in suggestions |
| Recurring automation (charters) not yet shipped; field shows heartbeats are the killer feature *and* the biggest risk | OpenClaw heartbeat, Hermes cron (§2.1/2.2) | **M9d: charters with circuit breakers** — rate limits, failure pause, drift alarm, budget caps, instant revoke (existing M8c design + AutoGPT lessons) |
| GUI injection-first posture vs field's API-first evidence | UFO² >62% control-detection failures; hybrid +8–19% (§2.4) | **M9e: API-first GUI actions** — prefer AT-SPI actions/DBus over synthetic input; injection becomes last resort (already consent-gated) |
| Remote-model breadth (200+ models elsewhere; we do Ollama + OpenAI-compatible) | Hermes comparison (§2.2) | Optional later: OpenRouter-compatible provider (config-only; still behind the same kernel) |

**Sequencing principle** (guideline 14/19): M9a and M9c are the highest value-per-risk (interoperability and integrity); M9b unlocks the ecosystem effect but must land *after* the scanner (M9c's machinery); M9d builds on both; M9e is an incremental backend improvement. Each phase keeps the invariant: **new capability enters through the kernel or it doesn't enter.**
