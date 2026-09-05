# Deep Research: How to build a JARVIS-class AI agent for Linux (2026)

- **Date:** 2026-09-04. **Commissioned by:** owner ("do a really deep research … about how an AI
  agent should be made for Linux, which is very close to JARVIS as seen in Marvel").
- **Method:** web research across ten query families (Marvel canon; agent-architecture surveys;
  memory systems; Linux desktop/computer-use; local voice stacks; agent security; proactivity;
  local inference; prior "JARVIS" projects; agent benchmarks), then synthesis against this
  project's actual source tree (v1.12.0, `4a2cdd3`).
- **Source tiers, honestly labeled:** `[arXiv]` = preprint/peer-reviewed research; `[eng]` =
  engineering blog or product documentation from a named team; `[vendor]` = vendor claims,
  uncorroborated; `[canon]` = film-behavior analysis of the fictional target. Numbers are quoted
  with their tier; where sources disagree, the range is given.

---

## 1. The target: what JARVIS does in the MCU

A behavior-level decomposition from film canon analysis [1] (corroborated by [2], [3]) yields
twelve capabilities. These are the specification the owner pointed at:

| # | Capability | Film evidence |
|---|---|---|
| F1 | Natural-language understanding of short, messy, context-heavy commands | "Pull up exploded view" executes with no clarifying question — the system maps a 3-word command to object, view, and interface from context |
| F2 | Persistent memory of preferences, projects, humor, working patterns | Remembers years of Tony's habits and design taste |
| F3 | Environment awareness | Knows what Tony is looking at, working on, wearing, flying in |
| F4 | Tool and computer use | Controls files, displays, diagnostics, feeds, renderers, databases |
| F5 | Domain expertise | Engines, flight, materials, power systems — enough to be genuinely useful |
| F6 | Data analysis and distillation | "Terabytes of calculations" — synthesizes sensor and network feeds |
| F7 | Multitasking | Many tasks in parallel, reported on completion ("The render is complete") |
| F8 | Autonomy with limited supervision | Handles unanticipated issues; Iron Man 3 autonomous suit piloting |
| F9 | Proactive reasoning | Surfaces information Tony did not ask for, when it is likely important |
| F10 | Calibrated interruption | Banter in the lab; brief confirmations during testing; warnings in danger |
| F11 | Permission judgment | Acts immediately, asks first, warns while executing — and protests ("Sir, there are still terabytes of calculations…") **while still executing** the ordered action |
| F12 | Physical-world integration | Sensors, actuators, robotics, machinery |

The canon dynamics that matter most for engineering are not the flashy ones: JARVIS **protests
but complies** (advice is separated from authority), **asks before ambiguous tasks**, and
**reports completion rather than narrating process**. F11 is, notably, the capability this
project has already implemented most rigorously — the film's "permission judgment" is exactly a
tier system with consent, and our kernel is stricter than the film's.

## 2. From Marvel to engineering requirements

Each film capability maps to a measurable engineering requirement, with a 2026 feasibility
verdict:

| Film | Engineering requirement | 2026 verdict |
|---|---|---|
| F1 | Intent layer: deterministic matching + LLM fallback + learned recall | **Solved** (this project has all three layers) |
| F2 | Persistent, provenance-tagged memory across sessions | **Mature patterns exist** (§3.1); integration is work, not research |
| F3 | Screen/session awareness without screenshots-first | **Linux is unusually good at this** — AT-SPI accessibility trees (§3.3) |
| F4 | Fixed, audited tool surface | **Solved pattern**: guarded playbooks + MCP; untyped free-form is the failure mode (§3.5) |
| F5 | Cited domain knowledge; abstain outside it | **Solved pattern**: cite-or-abstain KBs |
| F6 | Analysis synthesis over structured output | **Partial**: extract+aggregate playbooks; LLM synthesis still hallucination-prone |
| F7 | Parallel task execution with completion reporting | **Feasible but charter-hostile** (needs scheduler + consent queue); see §5 |
| F8 | Supervised autonomy loops | **The field's core unsolved problem** (long-horizon robustness, §6) |
| F9 | Proactive surfacing with learned restraint | **Emerging formalization** (§3.4): taxonomy + metrics exist as of 2026 |
| F10 | Register/interruption calibration | **Thin research**; productized only as "modes"; persona work is empirical (§3.6) |
| F11 | Tiered consent + refuse-while-advising | **Solved** — and this project already exceeds common practice |
| F12 | Actuators/robotics | Out of scope for a Linux desktop agent (D-Bus/device control is the honest ceiling) |

## 3. State of the art per subsystem

### 3.1 Memory: tiered, provenance-tagged, and increasingly file-shaped

The 2026 market consolidated around three architectures plus a strong vendor-native pattern [4]:

- **Letta/MemGPT** — the *OS paradigm*: context treated like virtual memory, paged in/out.
  Three tiers — core (2–4 KB, always in context), archival (vector store), recall (message log)
  — all managed by the model through function calls; "sleep-time compute" reorganizes memory
  asynchronously [4][5]. DMR benchmark 93.4% [6].
- **Zep/Graphiti** — the *temporal knowledge graph*: bi-temporal facts (event time vs ingestion
  time), three subgraph tiers (episode → semantic entity → community), retrieval via
  BM25 + embeddings + graph traversal with **no LLM calls at retrieval time**; DMR 94.8%,
  sub-200 ms retrieval [6][7].
- **Mem0** — two-phase pipeline (LLM extraction, then conflict detection + graph update) over a
  user/session/agent scope hierarchy; claims +26% answer accuracy vs baselines and ~90% token
  savings on long conversations [8] `[vendor]`.
- **Anthropic's file-based counter-trend** — the memory tool (public beta, Sonnet 4.5 era) is a
  plain file store the agent edits itself, ~84% token savings with context editing `[vendor]`
  [9]; Claude Code layers memory as curated instruction files plus agent-written `MEMORY.md`
  indexes with topic files — chosen for **transparency and user control**, deliberately
  rejecting vector-DB opacity [10][11].

Cross-cutting findings: episodic/semantic/procedural is the working taxonomy [4]; hybrid
vector+graph retrieval beats pure vector or pure graph [4]; **memory-aware planning** (retrieve
similar past tasks to bias new plans) is the emerging use [4]; and the security literature adds
a hard requirement — **memory poisoning is now a named attack class** (MINJA-style injection
through benign reads that persists until it influences later actions), so memory needs
provenance tagging and write-ahead validation [12][13].

**For JARVIS:** the file-based pattern (transparent, purge-able, hash-chainable) fits this
project's charter better than a vector store; the bi-temporal idea matters only if the owner
wants "what did I believe then" queries.

### 3.2 Planning and tool use: from chains to graphs, with a dual-system consensus

The 2026 multi-tool survey [14] documents the field's move from serial ReAct-style chains to
**structured graph-based execution** (DAG planners à la LLMCompiler) and **dual-system
designs** — a fast deterministic path for routine steps, a deliberative LLM path for hard ones.
Long-horizon orchestration now emphasizes: cognitive division of labor (subagents), semantic
routing, progress compression (COMPASS/Acon-style summaries of completed subtasks), and skill
libraries (Voyager's executable-skill memory). MCP became the dominant vertical tool layer —
Anthropic donated it to a foundation (Dec 2025) and the spec is heading toward streaming tool
outputs and cross-session state [15]. Evaluation reality check: on GAIA, humans score ~92%
while GPT-4 with plugins scored ~15% — orchestration, not raw model quality, is the bottleneck
[15].

The consensus that validates this project hardest: **typed tool schemas cut tool errors
significantly** [16], and the safest systems keep the model's decision *separate* from the
execution boundary — precisely JARVIS's match/plan/approve/execute split.

### 3.3 Linux desktop integration: AT-SPI-first grounding is the winning pattern

Linux is the best-documented desktop for agents in 2026 because of its accessibility stack:

- **AT-SPI2 over D-Bus** publishes every well-behaved GTK/Qt app's UI as a structured tree
  (roles, names, states, actions, coordinates) — "the desktop already publishes its UI"; this
  is a first-class API, the same one the Orca screen reader uses [17][18]. Grounding on
  accessibility trees removes the need for screenshot-OCR loops [19].
- Production-grade MCP servers now exist for the full spread of desktops:
  `computer-use-linux` (Rust; GNOME Wayland/X11, KWin, Hyprland, i3, COSMIC; screenshots,
  input via ydotool/uinput or XDG RemoteDesktop portals; a `doctor` readiness command; **no
  network by default**; a destructive `run_shell` tool gated behind an explicit opt-in env var)
  [20]; `kwin-mcp` (KWin EIS/libei input, virtual-display isolation via `dbus-run-session`,
  30 tools) [21]; Cua's driver (AT-SPI + XTEST, an agent cursor painted separately from the
  physical pointer, X11/XWayland) [22].
- Wayland/X11 split: Wayland is intentionally hostile to synthetic global input; the workable
  routes are portals (user confirms once per session), ydotoold (uinput), or compositor
  private interfaces (KWin EIS) [20][21].
- **The security boundary is real and named:** "AT-SPI exposes window contents to any client on
  your session bus" — the same trust boundary screen readers get [20]. One published agent-skill
  wrapper demonstrates the right hardening posture: HIGH-RISK classification, a blocked-app set
  (password managers, terminals, keyrings, polkit agents), blocked roles (password text fields),
  sensitive-name redaction, permission tiers (read-only vs standard), and per-operation audit
  logs [23].
- Benchmark anchor: OSWorld (369 real Ubuntu/Windows/macOS tasks, execution-based scoring) —
  human baseline ~72.4%; top agents crossed it in 2025–2026 (76.3% claimed Oct 2025 [24]
  `[vendor]`; top-5 runs 73.1–82.6% by early 2026 [25]) — but the efficiency re-analysis shows
  the best agents still take **1.4×–4.3× more steps than the human-minimum path** [26][25].
  Success ≠ efficiency; computers agents are not cheap yet.

### 3.4 Proactivity: a formal taxonomy finally exists

The 2026 framing (Google-led arXiv preprint) defines three levels [27]:

1. **Reactive** — runs only when prompted (no presence between requests).
2. **Scheduled** — runs on cron/webhook/event triggers (Cursor Automations, Claude Code
   Routines, Jules Scheduled Tasks are all Level 2) [27].
3. **Situation-aware** — monitors context continuously and *chooses between staying silent and
   surfacing an insight*, with an interruption policy **learned from feedback** (accept /
   dismiss / defer / edit / delegate) [27].

Key design vocabulary: the **insight** is the unit of proactive output, and each must be
*action-matched* — notify, question, draft, or stay silent; systems should report **silence
rates and denominators** (insights considered but not shown), not just trigger coverage [27].
ProactiveBench (6,790 real events) evaluates *when* to act unasked [28]. Product-design
principles converge on: configured autonomy (bounds expressible in natural language), graceful
presence ("if the agent has nothing important to report, it reports nothing"), transparency of
reasoning, and progressive trust [29]. Practical scheduler patterns: deferred follow-ups
("check the deployment in 30 min" with context embedded for the future self) and recurring
monitors that decide notify-vs-silence per run [28].

**Charter note:** Level 2 is implementable today on top of v1.12.0's resident doorway with
*propose-only* output; Level 3's learned interruption policy is a feedback problem — and this
project already has journal-backed feedback plumbing (suggestion accept/reject with canaries).

### 3.5 Security: injection is unsolved; containment is the durable answer

The blunt 2026 consensus, stated in multiple independent surveys: **"As of 2026, no fully
reliable defense against prompt injection exists"** [30][31][32]. Design accordingly:

- Durable controls are **privilege containment and provenance**, not filtering: per-task
  permission scopes, per-tool profiles, no root execution, sandboxed execution, and assuming
  injection *succeeds* — then ensuring the blast radius is small [30][32].
- **Spotlighting/datamarking** (delimiting and marking untrusted content) is the best measured
  model-side mitigation: attack success ~50% → <3% in the cited study [30].
- 2025–2026 incidents define the threat surface: EchoLeak (zero-click exfiltration chaining
  four bypasses including classifier evasion and a CSP failure) [30]; a CVSS-10 Gemini CLI
  supply-chain injection through malicious package documentation [33]; **CVE-2026-22708 in
  Cursor — the allowlist itself was poisoned so auto-approved commands delivered payloads** [34]
  (directly relevant to any allowlist design: allowlists are attack surface too); Codex CLI
  CVE-2025-59532 (agent output redefined its own sandbox boundary) [34]; and the Replit
  production-database deletion — **no attacker required**, the same permission model an attacker
  would exploit [34]. Safety failures and security failures have the same containment job.
- OWASP's agentic taxonomy (ASI01–ASI10) maps every threat to defense-in-depth controls:
  goal hijack, tool misuse, identity abuse, supply chain, unexpected code execution, memory
  poisoning, insecure inter-agent comm, cascading failures, trust exploitation, rogue agents —
  with kill-switches, circuit breakers, and immutable logs as the standing controls [30].
- HITL calibration guidance: require approval exactly for **irreversible actions, production
  data, and credential access**; auto-approve routine reads and sandboxed computes [33].

**For JARVIS:** the existing kernel (refusal-not-sanitization, tier gates, never-list, journal,
canaries, integrity doctor) already implements most of the durable list. The gaps are
sandboxing (nothing isolates a playbook's process beyond argv discipline) and provenance tags
on memory (once memory exists, §3.1).

### 3.6 Local inference: the SLM tier is agentic now; runtimes matter more than models

- Small models are function-call competent: Llama 3.1 8B ~89% overall tool-calling accuracy;
  Llama 3.2 3B is the best 3B tool-user (67% BFCL V2); Mistral Small 24B is cited as the best
  agentic model at its size; Qwen 3.5 9B fits 8 GB VRAM with multimodal input and 256K context
  [35][36]. Stanford's OpenJarvis project claims local models already handle **88.7% of
  single-turn queries** at interactive latency [37] `[vendor-adjacent]`.
- Runtime choice dominates experience: on Apple Silicon, MLX ~230 tok/s and MLC-LLM ~190 beat
  llama.cpp ~150 (short context) and Ollama 20–40 [38] `[arXiv]`; Ollama wins on ergonomics,
  llama.cpp on minimal footprint; vLLM wins multi-user concurrency by ~10× [39].
- Voice latency is a pipeline-property, not a model-property: streaming the LLM's output to TTS
  **at sentence boundaries** turns a 6–8 s assistant into 1–2 s on an RTX 3060 [40]. The
  canonical local voice stack is openWakeWord → faster-whisper → LLM → Piper (3–5× realtime
  CPU TTS), with Kokoro (82M StyleTTS2) as the naturalness upgrade [41][42]. openWakeWord ships
  a pretrained **"Hey Jarvis"** wake word [41]. Full-duplex speech-to-speech (Moshi, ~200 ms)
  exists but trades away tool use and model swappability [40]. Raspberry Pi 5/8GB can run the
  full stack at 8–25 s end-to-end — usable at the fixed-command tier, not conversation [43].

### 3.7 Prior "JARVIS" attempts and what they prove

- **OpenJarvis** (Stanford Scaling Intelligence Lab, Mar 2026, Apache-2.0): local-first agent
  framework; five composable primitives (Intelligence, Engine, Agents, Tools & Memory,
  Learning); built-in energy/latency benchmarking; explicitly a research release needing
  ~24 GB VRAM in default config [37]. Proves the local-first thesis; not a daily driver.
- **Microsoft JARVIS / HuggingGPT** and **JARVIS-1**: an LLM as controller over external models
  (and, in JARVIS-1, a Minecraft agent with multimodal memory + skill planning) — proves the
  orchestrator pattern, not product maturity [44].
- **Leon** (~17k stars, privacy-first assistant, long-running), **S.A.T.U.R.D.A.Y** (model-
  decoupled vocal-computing toolbox), assorted voice+face-recognition hobby stacks [44][45].
- No open-source project combines: consent-first kernel + guarded command families + honest
  undo + resident-but-authority-less residency. That combination is this project's actual
  differentiator, and this research found no evidence anyone else has built it.

## 4. What the field agrees on (convergent principles)

1. **Reasoning and execution must be separate systems** — the model proposes; a deterministic
   boundary validates and acts (this project's founding architecture, now industry consensus
   [14][16][30]).
2. **Typed, fixed tool schemas beat free-form** — errors drop when tools are typed and narrow
   [16]; untyped exec is the recurring incident cause [33][34].
3. **Privilege containment > detection** — assume injection succeeds; shrink blast radius
   [30][32].
4. **Memory must be tiered, transparent, and provenance-tagged** — with write-time validation
   against poisoning [4][12].
5. **Ground on structured state, not pixels, where the OS offers it** — AT-SPI on Linux [17][19].
6. **Proactivity is a policy problem, not a trigger problem** — silence is a first-class
   decision with reportable rates [27][29].
7. **Latency is an architecture property** — streaming/pipelining beats model swaps [40].
8. **Efficiency is the unsung benchmark** — winning agents are still 1.4–4.3× more steps than
   the human minimum [26].

## 5. Where the field disagrees / open problems

- **Autonomy loops:** agent-framework vendors push scheduled/triggered autonomy; the security
  literature's answer to "should it iterate unattended?" is effectively "only with containment
  you have tested" [30][34]. JARVIS's charter resolves this toward the human, stricter than the
  market.
- **Memory backends:** vector stores vs knowledge graphs vs files — benchmarks are close
  (93–95% DMR across leaders [4][6]); transparency and purge-ability argue for files at
  personal scale; graphs argue for temporal querying. Unresolved at small scale.
- **Computer-use grounding:** vision-first (OSWorld leaders) vs accessibility-first (Linux
  tooling) — vision generalizes, AT-SPI is cheaper, more reliable, and less privacy-hostile
  where available [17][19][25]. Likely hybrid in the long run.
- **Proactivity metrics** (IDQ/CGS/LL [27]) are proposed but have no consensus benchmark;
  ProactiveBench is the only public "when to act" suite [28].
- **Long-horizon robustness** — cascading errors, plan drift, and context poisoning remain
  open research problems with no shipped solution [14][30].

## 6. Gap analysis: JARVIS (this project, v1.12.0) vs the MCU target

| Capability | JARVIS (project) status | Gap class |
|---|---|---|
| F1 NLU | 56 guarded playbooks + deterministic matcher + LLM planner + neural recall | **met** |
| F11 permission judgment | Tier gates, approval policy, protected paths, never-list, journal, canaries | **exceeds canon rigor** |
| F4 tool use | 56 families + MCP + GUI capability matrix + resident doorway | **met for CLI scope**; no desktop-app control yet |
| F5 domain expertise | Cite-or-abstain knowledge base | **met** (narrow by design) |
| F6 analysis/distillation | Inspection families + KB answers | **partial** — no synthesis-over-sources playbook |
| F2 memory | Task journal only — no preference/pattern memory | **missing** (highest-leverage gap) |
| F3 environment awareness | None (no screen/session/mic awareness) | **missing** |
| F9 proactivity | None (doorway is availability, not initiative) | **missing** (L2 feasible now, propose-only) |
| F10 calibrated interruption | Terse CLI; tiers act as permission calibration | **partial** — no register/attention model |
| F7 multitasking | Sequential pipeline | **deliberate divergence** (charter) |
| F8 autonomy | None; proposals-only; human per request | **deliberate divergence** (charter; ADR-0017 D3) |
| F12 physical world | Out of scope (GUI control is the ceiling) | N/A |
| Voice | None | **missing** (mature local stack available) |
| Persona | None (name and disclosure only) | **missing** (thin layer, honest by design) |

## 7. Recommended roadmap (each step charter-compliant, owner-gated)

- **R1 — Voice front-end (v1.13 candidate).** openWakeWord ("Hey Jarvis" pretrained) →
  faster-whisper → the *existing* intent pipeline → Piper. Voice is an I/O adapter, not a new
  brain: every utterance enters through the same match/approve path; the consent model is
  unchanged (T2 still needs typed/voiced confirmation with the same journal record). Sentence-
  boundary streaming for sub-2 s responses on a modest GPU. Sources: [40][41][42].
- **R2 — Provenance-tagged file memory (v1.14 candidate).** A `memory/` store of small,
  human-readable files (Anthropic-pattern [9][10]) written (a) explicitly by the owner
  ("remember that…") or (b) as post-task summaries the owner can purge; every entry carries
  origin/session/source tags and passes the existing injection scan (write-ahead validation
  [12]); surfaced to the LLM planner as read-only context. No vector DB at personal scale.
- **R3 — Level-2 proactivity on the doorway (v1.15 candidate).** Scheduled, propose-only
  briefings (digest of journal outcomes, pending updates, disk pressure) with notify/silence
  decided per run; feedback (accept/dismiss) recorded in the journal to later learn the
  interruption policy (Level 3 later, per [27][29]). Silence rates reported. Never executes
  anything unprompted — the doorway stays "a doorway, never an actor."
- **R4 — Desktop awareness/computer use as a guarded family.** AT-SPI *read* tools (T0:
  list apps/windows, read tree) with the blocked-app/password-role/redaction pattern from [23];
  *action* tools (focus/click/type via portal or ydotool) as T2 with per-action consent; no
  shell tool (the `run_shell`-style escape hatch of [20] is rejected here). Wayland portals
  first. Sources: [17][19][20][21][23].
- **R5 — Parked (unchanged):** classifier retrain over the 56-playbook vocabulary; capability
  manifests (ADR-0017 D2); synthesis-over-sources playbook for F6.
- **Deliberate divergences to keep (documented, not "fixed"):** no unsupervised autonomy loops
  (F8), no parallel self-initiated task execution (F7), no actuators (F12). These are charter
  positions stricter than both the market and the film — the film's own JARVIS protests while
  complying; ours refuses and explains, which is the honest version.

## 8. Threats to carry forward

Injection is unsolved (assume compromise; contain) [30]; allowlists are attack surface
(Cursor CVE-2026-22708) [34] — JARVIS's allowlist is argv-frozen, but the pattern warns against
ever adding "approved command" conveniences; memory poisoning becomes possible the day R2
ships — provenance + write-ahead validation + purge are the controls [12]; computer-use tools
must never become a shell by another name (no `run_shell`, ever) [20][33]; efficiency debt —
even "superhuman" OSWorld agents waste 1.4–4.3× steps, so any future GUI automation should be
playbook-shaped, not free-form clicking [26].

## 9. Sources

1. D. Smit, "Iron Man Jarvis Capabilities" (film-behavior decomposition), 2026 —
   medium.com/@danieljsmit/iron-man-jarvis-capabilities-3fc263395d9e `[canon]`
2. "JARVIS: Tony Stark's Visionary AI Assistant…" — zenkaeurope.wordpress.com, 2024 `[canon]`
3. G. Solai, "Artificial Intelligence in Marvel," LinkedIn, 2018 `[canon]`
4. Zylos, "AI Agent Memory Architectures: From Context Windows to Persistent Knowledge,"
   2026-04 — zylos.ai/research/2026-04-05-ai-agent-memory-architectures-persistent-knowledge `[eng]`
5. AgentMarketCap, "Agent Memory at Scale 2026: Letta, Zep, Mem0, LangMem Compared," 2026-04 `[vendor]`
6. Rasmussen et al., "Zep: A Temporal Knowledge Graph Architecture for Agent Memory,"
   arXiv:2501.13956, 2025 `[arXiv]`
7. Graphiti — github.com/getzep/graphiti `[eng]`
8. Mem0 research, arXiv:2504.19413 + mem0.ai/blog/state-of-ai-agent-memory-2026 `[vendor]`
9. Anthropic, "Effective context engineering for AI agents," 2025-09 —
   anthropic.com/engineering/effective-context-engineering-for-ai-agents `[eng]`
10. DataStudios, "Claude Code Memory, CLAUDE.md, Persistent Instructions…" 2026-04 `[eng]`
11. Skywork, "Claude Memory: file-based hierarchy," 2025-09 `[eng]`
12. Iternal, "AI Agent Security Checklist (2026)" (OWASP ASI map; EchoLeak; datamarking
    ~50%→<3%) — iternal.ai/ai-agent-security-checklist `[eng]`
13. Multi-tool survey (MINJA memory-poisoning), arXiv:2603.22862, 2026 — see [14] `[arXiv]`
14. "The Evolution of Tool Use in LLM Agents: From Single-Tool Call to Multi-Tool
    Orchestration," arXiv:2603.22862, 2026 `[arXiv]`
15. MDPI, "LLM-Based Multi-Agent Orchestration: A Survey" (MCP/AAIF; GAIA 92% vs 15%),
    Future Internet 18(6):326, 2026 `[arXiv]`
16. FutureAGI, "LLM Agent Architectures in 2026," 2026-05 `[eng]`
17. J. Ojeda, "Stop Guessing Pixels: AT-SPI-First Grounding for Desktop Agents," 2026-08 —
    jocheojeda.com/2026/08/22/at-spi-first-grounding `[eng]`
18. lobehub linux-at-spi2 skill page (AT-SPI2 architecture; blocked-apps pattern) 2026 `[eng]`
19. isac322/kwin-mcp — github.com/isac322/kwin-mcp (AT-SPI tree grounding; KWin EIS) `[eng]`
20. agent-sh/computer-use-linux — github.com/agent-sh/computer-use-linux (support matrix;
    security boundary; opt-in run_shell) 2026 `[eng]`
21. Cua, "Inside Linux computer-use: AT-SPI, XTEST, and background agents," 2026-06 — cua.ai `[eng]`
22. (merged into [20]/[21] coverage)
23. lobehub linux-at-spi2 — security wrapper pattern (BLOCKED_APPS/ROLES, tiers, audit) `[eng]`
24. AGI Company, "The World's Most Capable Computer Agent" (OSWorld 76.26% vs human 72.36%),
    2025-10 `[vendor]`
25. "AgentAtlas: Beyond Outcome Leaderboards for LLM Agents," arXiv:2605.20530, 2026
    (OSWorld top-5 73.1–82.6%; human 72.4%) `[arXiv]`
26. "OSWORLD-HUMAN: Benchmarking the Efficiency of Computer-Use Agents," arXiv:2506.16042,
    2025 (1.4×–4.3× excess steps; WES 15.6–42.5%) `[arXiv]`
27. "Agentic Coding Needs Proactivity, Not Just Autonomy," arXiv:2605.06717 (Google), 2026
    (three-level taxonomy; insights; IDQ/CGS/LL; silence rates) `[arXiv]`
28. Zylos, "Autonomous Task Scheduling and Self-Directed Execution in AI Agents," 2026-06
    (ProactiveBench arXiv:2410.12361; deferred follow-ups) `[eng]`
29. Vanish Labs, "Proactive AI: Why Agents Should Initiate" (configured autonomy; graceful
    presence) — vanishlabs.ai/news/proactive-ai `[eng]`
30. Iternal checklist [12] (shared — injection unsolved; ASI01–10) `[eng]`
31. Atlan, "Prompt Injection Attacks on AI Agents," 2026-05 (privilege separation; blast
    radius) — atlan.com/know/prompt-injection-attacks-ai-agents `[eng]`
32. Help Net Security, "OWASP: prompt injection still drives most agentic AI security
    failures," 2026-06 — helpnetsecurity.com `[eng]`
33. LushBinary, "AI Agent Prompt Injection Defense: 2026 Production Playbook" (Gemini CLI
    CVSS-10; 10 layers; HITL calibration) — lushbinary.com `[eng]`
34. Help Net Security [32] (Cursor CVE-2026-22708 allowlist poisoning; Codex CVE-2025-59532;
    Replit) `[eng]`
35. InsiderLLM, "Best Local LLMs for Function Calling," 2026-07 — insiderllm.com `[eng]`
36. LocalAIMaster, "Best Small Language Models 2026," 2026-08 — localaimaster.com `[eng]`
37. ComputerTech, "OpenJarvis Review 2026: Stanford's Local-First AI Agent Framework"
    (88.7% single-turn claim), 2026-03 `[vendor-adjacent]`
38. "A Comparative Study of MLX, MLC-LLM, Ollama, llama.cpp," arXiv:2511.05502, 2025 `[arXiv]`
39. D-Central, "Ollama vs vLLM vs llama.cpp," 2026-08 `[eng]`
40. LocalAIMaster, "Build a Local Voice Assistant: Whisper + Ollama + Piper" (sentence-boundary
    streaming; Moshi comparison), 2026-06 `[eng]`
41. Maloyan, "The Best Fully-Local Voice Stack for Home Assistant (2026)" (openWakeWord "Hey
    Jarvis"; Piper vs Kokoro; hardware tiers), 2026-06 — maloyan.xyz `[eng]`
42. PromptQuorum, "Build a Fully Offline Voice Assistant in 2026" (latency thresholds),
    2026-08 `[eng]`
43. The 5090 Reports, "Raspberry Pi 5 local voice AI guide," 2026-07 `[eng]`
44. GetJarvis.eu, "Jarvis GitHub: 4 Open-Source Jarvis Projects," 2026-05 (OpenJarvis, Leon,
    MS JARVIS/HuggingGPT, sukeesh) `[eng]`
45. r/golang, "Project S.A.T.U.R.D.A.Y," 2023 `[eng]`

*Numbers quoted above inherit the tier of their source; `[vendor]` figures are uncorroborated
by independent benchmarks unless also labeled `[arXiv]`.*
