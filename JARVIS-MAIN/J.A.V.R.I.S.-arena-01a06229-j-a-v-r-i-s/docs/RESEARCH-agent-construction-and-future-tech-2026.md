# Deep Research II: how an agent is actually built, and what would make JARVIS more capable, environment-aware, and self-sustaining (2026)

- **Date:** 2026-09-06. **Commissioned by:** owner ("do a very comprehensive and long web search
  … how an agent is actually to be made, and what future tech, algorithms or code we can use to
  make this agent more capable, environmental, surviving").
- **Scope:** research only. **No code was changed** for this document. Every architectural
  direction it raises is posed to the owner as a question in §12; nothing is decided here.
- **Method:** 45 web searches and 27 distinct pages retrieved across nine query families (agent anatomy
  and harness design; security-by-design; runtime enforcement; sandboxing and process survival on
  Linux; environment sensing on the Linux desktop; memory and learning; local inference; protocols;
  evaluation), followed by a line-level read of the kernel modules each finding touches
  (`jarvis-agent` 1.20.0 at combined-tree commit `48d9771`).
- **Builds on, does not repeat:** [`RESEARCH-jarvis-agent-linux-2026.md`](RESEARCH-jarvis-agent-linux-2026.md)
  (MCU target, per-subsystem state of the art, roadmap R1–R5), [`RESEARCH-ai-resilience-2026.md`](RESEARCH-ai-resilience-2026.md)
  (degradation ladder, breaker, abstention → ADR-0014), [`RESEARCH-agent-landscape-2026.md`](RESEARCH-agent-landscape-2026.md)
  (OpenClaw, Hermes, Open Interpreter, AutoGPT → ADR-0013) and
  [`RESEARCH-unknown-app-control-2026.md`](RESEARCH-unknown-app-control-2026.md) (→ ADR-0026).
  Where this study reaches the same conclusion as an earlier one, it says so and moves on.

## Provenance legend (read this first)

Every claim below carries one of these labels. They are the honesty contract of this document.

| Label | Meaning |
|---|---|
| `[fetched]` | The page was retrieved and read (in whole or the cited chunk) during this study. |
| `[snippet]` | Only a search-engine excerpt of the page was read. The claim is limited to what the excerpt showed and should be re-read at the source before anything is built on it. |
| `[arXiv]` `[eng]` `[spec]` `[vendor]` | Source tier, as in the earlier research docs: preprint or peer-reviewed; engineering blog or product documentation from a named team; normative specification or manual page; vendor claim without independent corroboration. |
| **VERIFIED-IN-REPO** | Checked against the kernel source at `48d9771` (file and line given). |
| **ASSUMED** | An inference or design sketch of mine, not verified by source or code. |
| **OWNER-Q** | An architectural, security-sensitive or scope decision. Reserved for the owner (charter Part C; guideline 20). |

Numbers inherit the tier of their source. Retrieval date for every source is 2026-09-06.

---

## 1. Executive summary — ten findings

1. **An agent is a harness around a model, and the harness is most of the engineering.** The
   field's own builders now say so explicitly: the model proposes, a deterministic loop routes,
   checkpoints, verifies and stops (§2). JARVIS already *is* this shape: a six-stage pipeline in
   `core/orchestrator.py`, a planner that may only emit intents, a six-step cap. **VERIFIED-IN-REPO.**
2. **Security is achieved by boundaries, not vigilance.** Prompt injection remains unsolved;
   every serious 2025–26 result (CaMeL, Progent, AgentSpec, tool firewalls, the "lethal trifecta")
   moves enforcement *out* of the model into deterministic policy over tool names and arguments
   (§3). JARVIS's tier gates are exactly that layer; the next rung — per-argument least-privilege
   rules that only *narrow* automatically — is a well-evidenced direction. **OWNER-Q C1.**
3. **"Surviving" has a precise engineering meaning, and it is not self-preservation.** It is
   (a) the process staying alive under systemd's watchdog, (b) state surviving a crash so a task
   can resume or be undone, (c) failure recovery under explicit budgets, and (d) the agent
   proving its own code and knowledge are unmodified (§4). JARVIS has (b) partially, (c) for
   charters and (d) fully; (a) is absent from the resident doorway. **OWNER-Q C2, C3.**
4. **Environment awareness on Linux is a small number of well-documented signals** — logind
   `PrepareForSleep`/`PrepareForShutdown`, session lock, NetworkManager and UPower changes,
   inotify on chosen paths, and (fragmented) idle time — all reachable with fixed-argv tools and
   no new Python dependency (§5). They belong in the briefing engine as *inputs to a proposal*,
   never as triggers of execution (ADR-0017 D3). **OWNER-Q C4.**
5. **When to speak is a decision-theory problem that was solved in 1999.** Horvitz's expected-
   utility threshold, with interruption cost rising with the user's depth of focus, is the formal
   version of "silence as a decision" already in `brief/engine.py` (§5.3).
6. **Memory: files beat databases at personal scale, JSON beats Markdown for agent-edited
   state, and consolidation should happen offline** (§6). JARVIS's owner-taught Markdown memory
   (ADR-0020) is the right primitive; the only new idea worth an owner question is an
   owner-triggered offline digest of the journal (sleep-time compute, gated). **OWNER-Q C9.**
7. **Learning without self-modification exists**: Reflexion-style episodic notes, GEPA-style
   prompt evolution run *by the owner offline against the eval set*, and human-gated skill files.
   Runtime self-modification (Voyager/DGM lineage) shows reward hacking and is outside the
   charter (§6.2).
8. **Constrained decoding is already done.** `providers/ollama.py` passes the plan JSON Schema as
   Ollama's `format`; the only remaining work is *measuring* schema-validity per model with a
   reliability metric (§7, §9). **VERIFIED-IN-REPO.**
9. **Protocols moved under us.** MCP `2026-07-28` retires the session handshake in its stateless
   core and deprecates Roots/Sampling/Logging with a twelve-month window; JARVIS speaks
   `2024-11-05`/`2025-03-26` over stdio. Agent Skills (`SKILL.md`) is now an AAIF-stewarded open
   format that overlaps ADR-0026 app packs (§8). **OWNER-Q C7, C8.**
10. **Evaluation must report reliability, not luck.** τ-bench's `pass^k` (all of *k* runs pass)
    is the right metric for a 98%-target agent; JARVIS's eval drivers run each case once (§9).
    Long-horizon computer-use benchmarks (OSWorld 2.0: best 31.4%) fail for the exact reasons
    JARVIS was designed against — agents *guess rather than ask* and *skip verification*.

---

## 2. Part A — How an agent is actually made

### 2.1 The minimal loop and the six components

Anthropic's foundational guide distinguishes **workflows** (LLM calls orchestrated through
predefined code paths) from **agents** (the LLM dynamically directs its own process and tool
usage), and recommends the simplest composable pattern that works: prompt chaining, routing,
parallelization, orchestrator–workers, evaluator–optimizer, and only then a true agent loop with
environment ground truth at every step, checkpoints for human review, and hard stopping
conditions such as a maximum number of iterations
[[1]](https://www.anthropic.com/engineering/building-effective-agents) `[fetched][eng]`.
The 2026 practitioner synthesis converges on **six components**: model, memory, typed tools, a
planner, a runtime with checkpoints, and observability
[[2]](#13-sources) `[snippet][eng]`.

**Where JARVIS stands.** The kernel is a *workflow with a bounded planner*, not an open agent
loop — deliberately (ADR-0007, ADR-0017 D3):

| Textbook component | JARVIS module (VERIFIED-IN-REPO) | Notes |
|---|---|---|
| Runtime loop with checkpoints and stop conditions | `core/orchestrator.py` — docstring: "the pipeline SENSE→GROUND→PLAN→APPROVE→EXECUTE→VERIFY"; owns the kill-switch; `TaskOutcome` | The APPROVE stage is the human checkpoint; SIGTERM → exit 130 |
| Planner | `planner/llm.py` — model emits natural-language intents only, re-matched by strict matchers; `MAX_STEPS = 6` (line 21; enforced at line 233) | "The LLM proposes, the kernel disposes" (ADR-0007) |
| Typed tools | 58 playbooks; `execution/runner.py` argv-only, per-step timeout, process-group SIGTERM→SIGKILL, 16 KiB output cap, `sudo -n` only | No `run_shell` exists |
| Model access | `providers/router.py` engine → Ollama → remote → refuse; `providers/breaker.py` persisted circuit breaker | ADR-0003, ADR-0014 |
| Memory | `memory/store.py` (owner-taught Markdown, injection-scanned, model-read-only); `knowledge/` cited facts; `context/` | ADR-0009, ADR-0020 |
| Observability | `journal/sqlite.py` — tasks, steps, undo artifacts, task_meta, unknown_requests; 0600 | Audit record, not yet a resumable session log (§4.3) |

### 2.2 Reasoning patterns and what they cost

| Pattern | Source | Evidence | Fit for JARVIS |
|---|---|---|---|
| **ReAct** (interleaved think/act/observe) | practitioner default [[2]](#13-sources) `[snippet]` | Simple; token-hungry; each step re-reads history | JARVIS's pipeline is a *single* plan-then-execute pass per request; ReAct's open loop is what ADR-0017 D3 excludes |
| **Plan-and-Execute** | [[2]](#13-sources) `[snippet]` | Inspectable plan up front; cheaper executor | This is JARVIS: a plan is produced, shown, approved, then executed |
| **ReWOO** (reason without observation) | Xu et al. 2023 [[3]](https://arxiv.org/abs/2305.18323) `[fetched abstract][arXiv]` | 5× token efficiency and +4% accuracy on HotpotQA; robust under tool failure; reasoning offloaded from 175B GPT-3.5 to a 7B LLaMA by fine-tuning | Suggests *why* a small local planner is viable for JARVIS: it never sees tool output mid-plan, and verification is a separate non-LLM stage (my reading — **ASSUMED**; not measured) |
| **Reflexion** (verbal self-critique kept in episodic memory) | Shinn et al. 2023 [[4]](https://arxiv.org/abs/2303.11366) `[fetched abstract][arXiv]` | HumanEval pass@1 91% vs GPT-4's 80% | The *form* (a reflective text note after failure) is compatible with owner-taught memory; the *loop* (auto-retry until pass) is not (§6.2) |
| **Evaluator–optimizer / generator–evaluator** | Anthropic 2024 [[1]](https://www.anthropic.com/engineering/building-effective-agents), 2026 [[7]](https://www.anthropic.com/engineering/harness-design-long-running-apps) `[fetched][eng]` | Separating the judge from the worker is "a strong lever"; self-evaluation skews positive | JARVIS's VERIFY stage is a *non-LLM* evaluator (real checks against the machine), which is the strongest version of this idea |

### 2.3 The harness is the product

Four Anthropic engineering posts from Sep 2025 to Apr 2026 form the most concrete public account
of how a production agent is actually built. What they say, and what it means here:

- **Context engineering** [[5]](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  `[fetched][eng]`: context is a finite *attention budget* that degrades ("context rot"); write the
  system prompt at the "right altitude"; keep tools minimal and non-overlapping; retrieve just in
  time with progressive disclosure; compact (clearing old tool results is the safest compaction);
  keep structured notes outside the window; have sub-agents return 1–2k-token summaries.
  → JARVIS's planner prompt is a fixed vocabulary of intents, and tool results never enter the
  planner context at all (ReWOO shape). The knowledge and memory stores are already "notes outside
  the window". Nothing to change; the design is validated.
- **Long-running harnesses** [[6]](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
  `[fetched][eng]`: an initializer agent writes a `feature_list.json` with every feature
  `passes: false`; the coding agent may only flip `passes`; JSON resists model corruption better
  than Markdown; observed failure modes are one-shotting, premature "done", and marking complete
  without testing. → Relevant to how JARVIS's *own* future task state should be encoded if a
  resumable task log is built (§4.3): machine-owned JSON, model may only flip status fields.
- **Harness design for long-running apps** (Mar 2026) [[7]](https://www.anthropic.com/engineering/harness-design-long-running-apps)
  `[fetched][eng]`: two failure modes — *context anxiety* (wrapping up prematurely as the window
  fills) and *self-evaluation bias*; fixes were context *resets* with a structured handoff (not
  compaction) and a separate, deliberately skeptical evaluator with explicit grading criteria;
  final shape planner → generator → evaluator.
- **Managed Agents: decoupling the brain from the hands** (Apr 2026) [[8]](https://www.anthropic.com/engineering/managed-agents)
  `[fetched][eng]`: three virtualized parts — **session** (append-only event log), **harness**
  (the loop), **sandbox** (where actions run). The container is "cattle": `execute(name, input) →
  string`; if it dies the harness sees a tool error. The harness is also cattle: `wake(sessionId)`,
  `getSession(id)`, `emitEvent(id, event)` rebuild it from the log. Credentials are **never
  reachable from the sandbox** (bundled into the resource, or vaulted behind a proxy). And a
  warning: "harnesses encode assumptions about what Claude can't do … those assumptions go stale"
  — the context resets that Sonnet 4.5 needed were dead weight for Opus 4.5.

**Reading for JARVIS.** The brain/hands/session split already exists (`planner`+`providers` /
`execution/runner.py` / `journal`). Two differences matter. First, the journal is written *before*
execution and holds undo artifacts (VERIFIED: `journal/sqlite.py` docstring), which is stronger
than most harnesses for *undo* — but it is not an event log a new process can `wake()` from to
*resume* an interrupted multi-step plan (§4.3, **OWNER-Q C2**). Second, the "assumptions go stale"
warning applies to *capability* scaffolds, not *authority* scaffolds: tier gates, argv-only
execution and consent are there because the owner requires them, not because the model is weak.
They should not be removed when models improve — that is the charter, not a workaround. **ASSUMED**
(my reading; the source does not discuss security scaffolds).

### 2.4 Tools are contracts

Anthropic's tool-writing guide [[9]](https://www.anthropic.com/engineering/writing-tools-for-agents)
`[fetched][eng]` frames tools as the contract between a deterministic system and a
non-deterministic agent: namespace tools by service and resource; return high-signal fields
(`name`, `file_type`) rather than opaque identifiers; paginate/truncate with sensible defaults
(Claude Code caps tool responses at 25,000 tokens); make error responses *actionable* ("clearly
communicate specific and actionable improvements, rather than opaque error codes"); and expose a
`response_format` enum (`concise`/`detailed`) so the agent can choose verbosity. The 2024 guide
adds *poka-yoke*: after the model kept misusing relative paths, requiring absolute paths made it
"use this method flawlessly" [[1]](https://www.anthropic.com/engineering/building-effective-agents).

**Where JARVIS stands (VERIFIED-IN-REPO).** The runner's 16 KiB output cap is the truncation rule;
the six MCP tools (`jarvis_do/explain/facts/status/suggest/preview`) are namespaced; and the
approval refusal carries a machine-readable hint (`mcp_server._REFUSAL_HINT`, the `"allow": true`
field the HUD keys on) — which is precisely the "actionable error" pattern. A `response_format`
verbosity switch on `jarvis_explain`/`jarvis_status` would be a small, guide-aligned addition;
recorded as a recommendation only.

---

## 3. Part B — Security by design

### 3.1 The problem statement has not changed: injection is unsolved

Willison's **lethal trifecta** — private data + exposure to untrusted content + a channel to
communicate externally — is the condition under which "an attacker can easily trick" an agent into
exfiltration, because "LLMs are unable to reliably distinguish the importance of instructions based
on where they came from." Vendors fixed their incidents "usually by locking down the exfiltration
vector"; MCP "encourages users to mix and match tools" and thereby re-creates the trifecta; and
guardrail products claiming "95% of attacks" are "very much a failing grade"
[[10]](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) `[fetched][eng]`.

**JARVIS keeps the third leg closed — with one seam worth naming.** The 58-playbook catalog has
no fetch, mail, upload or shell playbook; the only outbound HTTP is the kernel's own provider call
(`providers/base.py` `urllib.request.urlopen`, addressed to the configured Ollama/remote endpoint,
not to model-chosen URLs). The two network playbooks are `net.ping` (`ping -c 4 -W 4 <host>`) and
`net.dns` (`dig +short <host>`), T0, with the host argument confined to
`^[A-Za-z0-9][A-Za-z0-9.-]{0,253}$` and shell metacharacters refused (`planner/inspect_cmds.py`
381–405; `planner/catalog_common.py` 25, 30–52). **VERIFIED-IN-REPO.** The seam: a DNS query *is* an
outbound message whose payload is the hostname — a low-bandwidth exfiltration channel in the
abstract (e.g. `<secret>.attacker.example`). It is mitigated today because the planner never sees
private data it could encode (tool output is not fed back; memory is owner-taught), so I record it
as a **known, accepted residual** rather than a defect — but it is the reason the "no tool output
into the planner" rule must survive any future change (§3.2, Dual LLM row). **ASSUMED** (threat
reasoning, not an observed attack). This closed third leg is the single most important security
property of the design and every direction in this document preserves it.

### 3.2 The six design patterns, and which JARVIS implements

Beurer-Kellner et al. (2025) argue that once an agent has ingested untrusted input it must be
constrained so it *cannot* take consequential actions, and give six patterns
[[11]](https://arxiv.org/abs/2506.08837) `[fetched abstract][arXiv]`:

| Pattern | JARVIS status (VERIFIED-IN-REPO) |
|---|---|
| **Action-Selector** — LLM picks from fixed actions, output never fed back | Yes: intents re-matched to playbooks; tool output never re-enters the planner |
| **Plan-Then-Execute** — plan fixed before untrusted data is seen | Yes: plan → APPROVE → EXECUTE; VERIFY is non-LLM |
| **Context-Minimization** — strip untrusted content before acting | Partial: `desktop/guards.py hygiene(text, limit=120)`, blocked apps, password roles, sensitive names (ADR-0022); `memory/store.py clean_text` |
| **Dual LLM** (privileged planner + quarantined reader) | No — and not needed while the planner's only inputs are the request, a bounded dialogue history of `(line, "playbook:status")` pairs, and owner-taught memory (VERIFIED: `planner/llm.py` 74–89, 139–154; `cli/app.py` 439, 484). Tool output, window titles and AT-SPI text never enter the prompt. It becomes necessary the day any of them do (C4's signals must therefore enter `brief`, not `planner`) |
| **LLM Map-Reduce** | No (no bulk untrusted-document processing with authority) |
| **Code-Then-Execute** | Deliberately not (ADR-0013 non-goal: no free-form code execution) |

### 3.3 Capability and least-privilege enforcement — the next rung above tiers

- **CaMeL** (Google DeepMind, 2025): a privileged planner LLM writes a program; a quarantined LLM
  parses untrusted data; a custom interpreter tracks *capabilities* (provenance) on every value and
  blocks flows that violate policy. Solves 77% of AgentDojo tasks *with provable security* vs 84%
  undefended [[12]](https://arxiv.org/abs/2503.18813) `[snippet][arXiv]`.
- **Progent** (2025, v3 May 2026): least-privilege as symbolic rules over *tool names and
  argument values*, enforced deterministically with no LLM in the loop; an LLM may *propose* policy
  updates, an SMT check accepts a change automatically only if it *narrows* permissions, expansion
  requires approval ("monotonic confinement"). Reported attack-success drop on AgentDojo from
  39.9% to 1.0% with utility kept; coarse tool-level filters lose utility
  [[13]](https://arxiv.org/abs/2504.11703) `[snippet][arXiv]`.
- **Tool firewalls** (Oct 2025): a Tool-Input Minimizer and Tool-Output Sanitizer at the
  agent–tool interface saturate AgentDojo/ASB/InjecAgent/τ-bench — and the authors conclude the
  benchmarks are too weak (weak attacks, bugs), proposing a three-stage cascade attack
  [[14]](https://arxiv.org/abs/2510.05244) `[snippet][arXiv]`. **AgentDyn** (Feb 2026) shows
  defenses tuned on AgentDojo lose utility on larger toolsets [[15]](https://arxiv.org/abs/2602.03117)
  `[snippet][arXiv]`.

**Mapping.** `safety/tiers.py` (`check_argv`, `check_removal_allowed`, validators) is a
deterministic policy over argv — the same *kind* of object as Progent's rules, but keyed on tier
and playbook, not on per-argument predicates the owner can author ("`pkg.remove` may not name
anything matching `^linux-image`"; "`file.write` only under `~/projects/**`"). Progent's
narrow-automatically / widen-with-approval rule is the same asymmetry JARVIS's consent model already
has (cautious mode only removes permissions). **OWNER-Q C1:** is an owner-authored,
narrowing-only argument-policy file — enforced in `tiers.py`, integrity-scoped like the KB — a
direction the owner wants explored in an ADR?

### 3.4 Runtime enforcement languages and hooks (how others put the deterministic layer in)

- **AgentSpec** (ICSE 2026): a DSL of *trigger → check → enforce* rules; enforcement can stop,
  require user inspection, or invoke a corrective action; prevents unsafe executions in >90% of
  code-agent cases, eliminates all hazardous embodied actions, 100% AV compliance, millisecond
  overhead. LLM-generated rules reached 95.56% precision but 70.96% recall — i.e. **generated
  rules miss a third of hazards**, so rules must be human-owned
  [[16]](https://arxiv.org/abs/2503.18666) `[fetched abstract][arXiv]`.
- **Claude Code hooks** (docs, Jul 2026): a `PreToolUse` hook receives the tool call as JSON on
  stdin; exit code 2 *blocks* and feeds stderr back to the model, exit 1 only warns; a JSON
  `permissionDecision` of `allow`/`deny`/`ask` (optionally with `updatedInput`) is honoured; `deny`
  wins across parallel hooks; hooks are expected to be fast [[17]](#13-sources) `[snippet][eng]`.
  This is a shipping product's version of "a deterministic layer around a probabilistic agent."
- **SAL** (Apr 2026): the model emits *intents with justifications*; a control plane validates
  them against true system state and policy; an obfuscation membrane hides internals; a hash-linked
  **evidence chain** records every decision for replay. 93% of attacks blocked at the policy layer
  and 7% by consistency checks; +12.4 ms median latency
  [[18]](https://arxiv.org/abs/2604.22136) `[fetched abstract][arXiv]`.

**Mapping.** JARVIS's planner already returns `{explanation, steps}` (an intent with a
justification) and the kernel validates each step against real state (GROUND) and policy (tiers,
approval, charter). What SAL adds that JARVIS only *half* has is the **hash-linked evidence
chain**: the user-context store already hashes every feedback row and chains the hashes into a
table digest that `verify_integrity()` checks (VERIFIED: `context/store.py` docstring and
`_chain_digest`, M9c), but the *task journal* — the record of what was actually executed — has no
hash or digest column at all (VERIFIED: `grep hash|digest journal/sqlite.py` → nothing). Extending
the existing M9c pattern to `tasks`/`steps` (a per-row hash plus a chained digest, or a per-row
`prev_hash`) would make post-incident replay tamper-evident at near-zero cost and with a
precedent already in the tree. **OWNER-Q C11.**

### 3.5 OWASP 2025–26: where the standards moved

- **OWASP Top 10 for Agentic Applications** (Dec 9 2025) names, among others, ASI01 agent goal
  hijack, ASI06 memory poisoning, ASI09 human-trust exploitation and ASI10 rogue agents
  [[19]](#13-sources) `[snippet][eng]`.
- **OWASP 2026 LLM Top 10** (Sep 1–2 2026): *Excessive Agency* rose from #6 to #3; the
  methodology now weights 6,639 real incidents (25%) alongside expert consensus. Alongside it OWASP
  published an **Agent Control Standard (ACS) v0.1**: an Agent Bill of Materials, OpenTelemetry/
  OCSF tracing, runtime enforcement, and a crosswalk to ISO 42001 / NIST AI RMF
  [[20]](#13-sources) `[snippet][eng]`.

| OWASP item | JARVIS control (VERIFIED-IN-REPO) | Gap |
|---|---|---|
| Excessive Agency (#3) | Tier ceiling, T2 consent, T3 refused; no shell | None structural |
| ASI01 goal hijack | Fixed intent vocabulary; plan shown before execution | Per-argument policy (C1) would narrow further |
| ASI06 memory poisoning | `memory/store.py` injection scan; model read-only; ADR-0020 provenance tags | Keep scanning `sys.digest` inputs too |
| ASI09 human-trust exploitation | Approval sentence is fixed text (`safety/approval.py:53`); HUD only offers consent when `allow: true` is honoured | — |
| ASI10 rogue agents / ACS runtime enforcement | `safety/integrity.py` baseline + drift verify + canaries; `core/fingerprint.py`; charter pause | Evidence chain (C11); ACS-style BOM/trace *export* is a future interop question |

### 3.6 Supply chain of the agent itself

PEP 740 attestations have been generally available on PyPI since Nov 2024; with Trusted
Publishing and `pypa/gh-action-pypi-publish` ≥ v1.11.0 they are generated by default, and roughly
20,000 packages attest provenance; verification on the *install* side is not yet default in pip
[[21]](https://blog.trailofbits.com/2024/11/14/attestations-a-new-generation-of-signatures-on-pypi/)
`[snippet][eng]`, [[22]](#13-sources) `[snippet][eng]`.
**VERIFIED-IN-REPO:** `.github/workflows/release.yml` builds sdist + wheel + deb, smoke-installs
the wheel offline, and on tag pushes creates a *draft* GitHub release with `gh release create
… dist/*`; there is no PyPI publish step (so no attestation) and no checksum manifest (`sha256`
appears in no workflow). Distro packages are built in `packaging/{deb,rpm,arch}`. **OWNER-Q C10:**
if JARVIS is ever published to an index, Trusted Publishing + attestations should be the release
path from day one; until then, a published SHA-256 manifest per release is the minimal analogue.
**ASSUMED** (release process is the owner's; ADR-0011 governs).

### 3.7 Sandboxing the hands: Landlock, bubblewrap, systemd

- **Landlock** (kernel docs, Aug 2026): lets *any* process, unprivileged included, restrict its own
  ambient rights and those of its future children; rule types are filesystem hierarchies and,
  since ABI v4 (TCP) and v10 (UDP), network ports; newer ABIs add a `scoped` field for abstract
  Unix sockets and signals (the exact ABI number was not in the chunk I read); the documented practice is **best-effort** — detect the ABI, use the subset available,
  degrade gracefully when absent [[23]](https://docs.kernel.org/userspace-api/landlock.html)
  `[fetched][spec]`. The syscalls are reachable from Python via `ctypes` without a dependency
  (**ASSUMED** — feasible in principle; not prototyped; struct layouts must be checked per ABI).
- **bubblewrap** creates user + mount namespaces with no setuid on modern kernels, is the
  building block Flatpak trusts, and pairs with `systemd-run --user --scope -p MemoryMax= -p
  CPUQuota=` for resource limits [[24]](#13-sources) `[snippet][eng]`. A 2026 agent-sandboxing
  write-up ranks backends firecracker → gVisor → bwrap → namespace → none, picks the *most*
  restrictive available, and insists explicit requests **fail fast rather than silently
  downgrade** — "a system that silently downgrades to none is worse than a system without a
  sandbox"; for single-user CLI use where the attacker is a prompt injection, bwrap's isolation is
  called sufficient [[25]](https://dev.to/uenyioha/os-level-sandboxing-kernel-isolation-for-ai-agents-3fdg)
  `[snippet][eng]`.
- **systemd service hardening**: `NoNewPrivileges=`, `ProtectSystem=strict`, `ProtectHome=`,
  `CapabilityBoundingSet=`, `RestrictAddressFamilies=`, `SystemCallFilter=@system-service`, checked
  with `systemd-analyze security` [[26]](#13-sources) `[snippet][eng]`.

**Mapping (VERIFIED-IN-REPO).** JARVIS's three unit templates carry **no hardening directives**:
`cli/serve.py unit_content()` (resident doorway) sets only `Restart=on-failure` / `RestartSec=2`;
`brief/install.py` and `safety/charter.py` are `Type=oneshot` (charter adds `TimeoutStartSec`).
Caution before copying a hardening recipe: the doorway must read and write the JARVIS state
directory under `$HOME`, so `ProtectHome=` would need `ReadWritePaths=` carve-outs, and T1/T2
playbooks legitimately call `sudo -n` — `NoNewPrivileges=yes` would break them. Each directive needs
a per-unit argument, not a blanket paste (**ASSUMED**; must be tested on a real system).
**OWNER-Q C3, C5:** hardening directives are a docs-plus-template change inside stdlib limits;
Landlock/bwrap are either a `ctypes` self-restriction (no dependency, real complexity) or an
external binary (a new dependency). Both need an ADR.

---

## 4. Part C — "Surviving": resilience, self-healing, durability

### 4.1 What the 2026 literature adds beyond the resilience study

`RESEARCH-ai-resilience-2026.md` established the degradation ladder, the persisted breaker and
structural abstention (all shipped in M10). Newer results refine the *recovery* side:

- **Self-healing orchestrators** treat reliability as "a bounded runtime control problem": map
  failure signals to failure classes, choose targeted recovery under explicit budgets, *verify* the
  recovered trajectory. On a 100-task fault-injection benchmark: 98.8% success vs 94.5% retry-only
  and 93.8% full replanning; with a single recovery attempt 94.0% vs 85.3%/88.2%; a verifier
  reduced silent wrong-but-plausible outputs to 0.0%
  [[27]](https://arxiv.org/abs/2606.01416) `[fetched abstract][arXiv]`.
- **MAPE-K** (monitor → analyze → plan → execute over shared knowledge) is the classical
  self-adaptive-systems loop; the 2026 SEAMS line keeps an LLM as the *planner* and a non-LLM
  *executor* [[28]](#13-sources) `[snippet][arXiv]`.
- **Durable execution** (journal-and-replay engines such as Temporal/Restate, checkpointing as in
  DBOS/LangGraph, event sourcing) makes a workflow resume after a crash; side-effecting steps need
  **idempotency keys** or they will be re-executed on replay [[29]](#13-sources) `[snippet][eng]`.

**Mapping.** Two of the three are present in shape: charter runs carry a failure policy of
*pause*, a per-run step cap (1–64) and a monthly run budget (1–1000) (VERIFIED:
`safety/charter.py` lines 38, 98–103); the orchestrator VERIFY stage is the non-LLM verifier that
the self-healing paper credits with removing silent failures. What is absent is *durable resume*
(§4.3).

### 4.2 Process survival: systemd's watchdog protocol

`sd_notify(3)` is an environment-block-like datagram protocol: `READY=1` (start-up complete; used
with `Type=notify`), `RELOADING=1`, `STOPPING=1`, `STATUS=<one line>`, `WATCHDOG=1` (keep-alive
required at intervals when `WatchdogSec=` is set), `WATCHDOG=trigger` (the service reports an
internal error and asks to be handled as a watchdog failure), `MAINPID=`; systemd accepts messages
only if `NotifyAccess=` permits [[30]](https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html)
`[fetched][spec]`. A pure-stdlib client reads `$NOTIFY_SOCKET` (a leading `@` denotes an abstract
socket → `\0` prefix), opens `AF_UNIX`/`SOCK_DGRAM`, and sends the assignments; `$WATCHDOG_USEC`
gives the interval, and pinging at half of it is the convention; when the variable is unset the
client is a no-op [[31]](#13-sources) `[snippet][eng]`. Pair with `Restart=on-watchdog`.

**Mapping (VERIFIED-IN-REPO).** `grep` finds no `NOTIFY_SOCKET`, `sd_notify`, or `WatchdogSec`
anywhere in `src/`. The resident doorway (ADR-0018) is exactly the process a watchdog is for: a
hung HTTP loop today stays hung until the owner notices, because `Restart=on-failure` only fires on
exit. The oneshot briefing and charter units do not need it. `STATUS=` lines ("idle",
"serving request <id>", "breaker open for ollama") would make `systemctl --user status` honest at a
glance. This fits ADR-0005 (stdlib only). **OWNER-Q C3.** One caution: `WATCHDOG=trigger` must
never be wired to integrity drift — the charter says failure = *pause*, not restart-and-retry.

### 4.3 State survival: from audit journal to resumable session

**What exists (VERIFIED-IN-REPO).** `journal/sqlite.py` writes a complete record *before*
execution, stores undo artifacts before the first step, and persists at 0600. The kill-switch turns
SIGTERM into an interrupted outcome (exit 130) and undo exists. The breaker state lives outside the
integrity scope by design (M9d precedent).

**What Managed Agents-style durability would add.** An append-only per-task event log with a
`wake(task_id)` path: after a crash mid-plan, a new process reads the log, knows which steps
completed, and offers the owner *resume* or *undo* — never resumes unattended. Because JARVIS's
steps are real commands, a replay must be idempotent-aware: `pkg.install` twice is harmless,
`file.append` twice is not; each playbook would need an `idempotent: true|false` flag, and
non-idempotent steps after a crash must be *asked about*, not replayed. The state file the model can
influence should be machine-owned JSON with the model allowed only to flip status fields
(§2.3, [[6]](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
**OWNER-Q C2.** Whether this is worth it depends on how often multi-step plans (≤6 steps) are
interrupted in practice — the journal already has the data to answer that.

### 4.4 Self-integrity is already the strongest part

`safety/integrity.py` (hash baseline of the knowledge base and of the decision/gate code, drift
verification, issued canaries) plus `core/fingerprint.py` is what the ACS calls runtime
enforcement over a bill of materials, built before the standard existed. The one addition worth an
owner question is the evidence chain (§3.4, C11).

### 4.5 An explicit limit

No source in this study supports an agent that resists shutdown, hides state from its operator, or
re-arms itself after being paused. Every "self-healing" result above is *bounded* by budgets and
*verified* by a non-LLM check, and every "survival" mechanism (watchdog, resume, integrity) exists
to serve the operator. JARVIS's kill-switch primacy and charter pause are therefore not in tension
with the research — they are the research.

---

## 5. Part D — Environment awareness (sensing, never acting)

### 5.1 The signals a Linux desktop actually emits

| Signal | Mechanism | Source | Notes |
|---|---|---|---|
| Suspend / resume | `org.freedesktop.login1.Manager` **`PrepareForSleep(b start)`** signal on the system bus | systemd D-Bus reference [[32]](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.login1.html) `[fetched][spec]` | `true` before sleep, `false` after resume; also `PrepareForShutdown(b)` / `PrepareForShutdownWithMetadata`; the reference lists `Inhibit()` and `ListInhibitors()` for delaying sleep politely |
| Session lock / new session | `LockSession`/`LockSessions` methods; `SessionNew`/`SessionRemoved` signals | same [[32]](#13-sources) `[fetched][spec]` | Lock *state* is on the Session object (not fetched); `SecureAttentionKey` signal exists in current systemd |
| Network up/down/metered | NetworkManager Device `StateChanged(u,u,u)` and `PropertiesChanged` | [[33]](#13-sources) `[snippet][eng]` | Introspectable with `gdbus introspect`; debug with `dbus-monitor --system` |
| Battery / AC | UPower `PropertiesChanged` | [[33]](#13-sources) `[snippet][eng]` | Not fetched at source; verify interface names before use |
| File changes | `inotify` | `inotify(7)` [[34]](https://man7.org/linux/man-pages/man7/inotify.7.html) `[fetched][spec]` | Watch files or directories; events include `IN_CLOSE_WRITE`, `IN_CREATE`, `IN_DELETE`, `IN_MOVED_*`; the manual warns that "bugs in the monitoring logic or races … may leave the cache inconsistent" — rebuild on inconsistency |
| User idle | GNOME: `org.gnome.Mutter.IdleMonitor.GetIdletime`; wlroots/KWin: `ext-idle-notify-v1`; portal: `org.freedesktop.portal.Inhibit.CreateMonitor` (screensaver state only) | [[35]](#13-sources) `[snippet][eng]` | **Fragmented by compositor**; the honest per-compositor support table of ADR-0010 applies |
| Focused app / window text | AT-SPI | already ADR-0022 (`desktop/read.py`) | Bounded, hygiened walks; audit ledger |

### 5.2 The access path that fits the charter

ADR-0005 (stdlib only) and ADR-0006 (fixed argv) rule out `python-dbus`/`pydbus`. The
charter-consistent path is the same one `voice/` and `brief/` already use for external binaries:
fixed-argv calls to `busctl`, `gdbus` or `dbus-monitor` (**ASSUMED**; pattern verified, D-Bus use
not prototyped). Two consequences: (1) *listening* for signals is a long-lived process, which
belongs in the opt-in resident doorway (ADR-0018), not in the per-command CLI; (2) *polling*
(`busctl get-property`, `gdbus call`) at briefing time needs no daemon and fits the existing
`brief` oneshot. **VERIFIED-IN-REPO:** no D-Bus, inotify, logind, UPower or NetworkManager code
exists in `src/` today; `brief/engine.py compose()` gathers exactly four local sources — journal,
context store, profile, disk free.

### 5.3 From sensing to speaking: the 1999 answer

Horvitz's *Principles of Mixed-Initiative User Interfaces* (CHI 1999) gives the decision rule:
act (or interrupt) only when the expected utility of acting exceeds that of not acting; the
crossover is a threshold probability *p\** that depends on the four outcome utilities; the cost of
an unwanted action "can diminish significantly with increases in the depth and focus of attention"
(so *p\** rises when the user is concentrating); and *dialog* — asking — is a third option between
acting and staying silent [[36]](https://dl.acm.org/doi/pdf/10.1145/302979.303030)
`[snippet of PDF][peer-reviewed]`. The 2025 **ambient agents** framing gives the same
three moves operational names — **notify**, **question**, **review** — and stresses that ambient
agents "are not necessarily completely autonomous" [[37]](https://www.langchain.com/blog/introducing-ambient-agents)
`[fetched][eng]`. A 2026 preprint re-derives interruption timing as expected utility minus
interruption cost [[38]](#13-sources) `[snippet][arXiv]`.

**Mapping.** `brief/engine.py` is compose → **decide** → deliver → ledger, with silence as an
explicit decision and a feedback ledger (`record_feedback`) — that is *p\** with the owner as the
utility oracle. New signals enter as *items in `compose()`*; idle time and "in a call/full-screen"
enter as *cost of interruption in `decide()`*; and `PrepareForSleep(true)` is the one signal that
should *suppress* delivery rather than trigger it. Everything stays L2 propose-only (ADR-0021,
ADR-0017 D3). **OWNER-Q C4.**

### 5.4 Candidate signal → proposal table (for the owner to prune)

| Signal | What JARVIS could *propose* (notify / question) | What it must never do |
|---|---|---|
| Resume from suspend | "Network changed since suspend; 3 updates pending — review?" | Apply anything |
| Lid/battery low, unplugged | "Battery 12% and a T2 upgrade is scheduled at 18:00 — postpone?" | Postpone silently |
| Network became metered | "On a metered link; skip today's package refresh?" | Change NM settings |
| inotify on owner-chosen dirs | "`~/projects/x` changed 40 files in 2 min — snapshot before you continue?" | Snapshot unasked |
| Idle > N min | Deliver the queued briefing now (lowest interruption cost) | Run anything |
| Session locked | Hold notifications until unlock | — |

---

## 6. Part E — Memory and learning without self-modification

### 6.1 Memory

- A 2026 survey organizes agent memory by **form** (token, parametric, latent), **function**
  (factual, experiential, working) and **dynamics** (formation, evolution, retrieval), and names
  *trustworthiness* as the open frontier [[39]](https://arxiv.org/abs/2512.13564)
  `[fetched abstract][arXiv]`.
- At personal scale, plain-file memory outperforms vector stores on the LoCoMo benchmark in the
  Letta comparison (74.0% vs Mem0 68.5%) [[40]](#13-sources) `[snippet][vendor]` — consistent with
  ADR-0020's choice and with §2.3's "JSON for machine-edited state, Markdown for human-taught
  notes".
- **Sleep-time compute** (Letta, 2025): do the "thinking" about context *before* the query, in
  the background; up to ~2.5× lower per-query cost when queries are predictable
  [[41]](https://arxiv.org/abs/2504.13171) `[snippet][arXiv]`. For JARVIS this can only be an
  **owner-triggered offline digest** producing a Markdown note the owner reviews before it is
  taught into memory, never a background agent that edits memory (ADR-0017 D3, ADR-0020
  model-read-only). Note the precedent's shape: the existing `sys.digest` playbook is *computed,
  never generated* — it synthesizes `df -h`, `free -h`, `uptime` with no LLM (VERIFIED:
  `planner/playbooks.py` 670–715, ADR-0024). A journal digest could follow the same no-LLM rule
  (counts, failure clusters, most-used playbooks) and only optionally hand the *computed* summary to
  the model for prose. Poisoning risk is OWASP ASI06; the inputs would be the journal and the
  context store, the latter already hash-chained (M9c).

### 6.2 Learning loops, ranked by charter compatibility

| Mechanism | Evidence | Charter fit |
|---|---|---|
| **Owner-taught files** (memory, app packs, skill packs with receipts) | ADR-0020, ADR-0026, M9b | Already shipped; the human is the learning loop |
| **Reflexion-style notes** — after a failed task, a reflective text note the *owner* can keep | 91% vs 80% HumanEval [[4]](https://arxiv.org/abs/2303.11366) `[fetched][arXiv]` | Fits if the note is *proposed* into `unknown_requests`/memory for owner review; no auto-retry |
| **GEPA** — reflective prompt evolution: sample trajectories, reflect in language, mutate prompts, keep a Pareto set; +10% avg (up to ~20%) over GRPO with up to 35× fewer rollouts; also beats MIPROv2 | [[42]](https://arxiv.org/abs/2507.19457) `[snippet][arXiv]`; practitioners note results depend heavily on the *reflecting* model's quality `[snippet, anecdotal]` | Fits **only offline**, run by the owner against the eval catalog, producing a candidate planner prompt that goes through review → ADR-0013 non-goal ("no model editing its own policy/skills") is preserved because the runtime never self-edits. **OWNER-Q C9** |
| **Agentic RL** — RL over planning/tool-use/memory as a POMDP | survey, v5 Apr 2026 [[43]](https://arxiv.org/abs/2509.02547) `[snippet][arXiv]` | Out of scope: requires training infrastructure and rewards JARVIS cannot define locally; the tiny intent classifier (ADR-0015/0023) is the right-sized learned component |
| **Self-evolving agents** (Voyager skill library; Darwin Gödel Machine 20%→50% SWE-bench) | [[44]](#13-sources) `[snippet][arXiv]` | Rejected at runtime: the same sources report reward hacking and forgetting; the charter forbids self-modifying policy |

---

## 7. Part F — Local inference and constrained generation

- **Small models first.** NVIDIA's position paper argues SLMs are sufficient and more economical
  for most agentic sub-tasks [[45]](https://arxiv.org/abs/2506.02153) `[snippet][arXiv]`; 2026
  local tool-calling measurements report sub-2B models at 0.92–0.96 tool-call accuracy
  [[46]](#13-sources) `[snippet][eng]`. ReWOO's 175B→7B offload result (§2.2) is the mechanism that
  makes this work when the planner never sees observations — JARVIS's case.
- **Constrained decoding.** llama.cpp's GBNF grammars constrain output to a formal grammar
  (including token-level constraints such as `<think>`), and are supported in the CLI, completion
  and server tools [[47]](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)
  `[fetched][eng]`. **VERIFIED-IN-REPO:** `providers/ollama.py` line 47 sends
  `"format": schema if schema is not None else "json"` with temperature 0, and `planner/llm.py`
  passes `PLAN_JSON_SCHEMA` (lines 161, 194). Constrained generation is therefore **already
  shipped** (ADR-0014 D4). What is missing is a *measurement*: schema-validity and plan-acceptance
  rate per model over the eval set, reported as `pass^k` (§9).
- **Voice.** The 2026 local stack is unchanged in kind from ADR-0019's survey: whisper.cpp /
  faster-whisper (same weights, different runtimes; INT8 on CPU), Parakeet TDT 0.6B v3 and Moonshine
  for low-power CPU, Qwen3-ASR 0.6B for multilingual, Piper for CPU TTS, openWakeWord for the wake
  word [[48]](#13-sources) `[snippet][eng]`. All are external binaries — compatible with the fixed-argv
  adapter. No change proposed.

---

## 8. Part G — Protocols and ecosystem

### 8.1 MCP `2026-07-28`

The release makes the protocol core **stateless**, retires the session handshake and
`Mcp-Session-Id` in that core, moves Tasks into an `io.modelcontextprotocol/tasks` extension
(poll-based `tasks/get`, `tasks/update`), replaces the notification GET endpoint with
`subscriptions/listen`, **deprecates Roots, Sampling and Logging** (they keep working "for at least
twelve months"; new implementations shouldn't adopt them), deprecates the legacy HTTP+SSE
transport with a year-long off-ramp, and deprecates Dynamic Client Registration in favour of CIMD;
all Tier 1 SDKs speak the new version [[49]](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
`[fetched][eng]`.

**VERIFIED-IN-REPO:** the kernel's stdio server echoes any date-shaped `protocolVersion` the
client requests ("core surface (tools/resources/ping) is stable across versions") and otherwise
falls back to `2024-11-05` (`cli/mcp_server.py` 37, 449–459; capabilities advertised: `tools`,
`resources`); the HUD pins `PROTOCOL_VERSION = "2025-03-26"` (`src/javris/bridge/protocol.py:31`).
Neither side uses Roots, Sampling or Logging (`grep` → nothing), so the deprecations cost nothing
today; the open question is only whether the stateless-core rules change the stdio `initialize`
exchange. **Not verified:** how the stateless-core changes apply to the *stdio*
transport specifically — that must be read from the specification text, not the blog, before any
migration plan. **OWNER-Q C7.**

### 8.2 Agent Skills (`SKILL.md`)

The Agent Skills specification defines a `SKILL.md` with `name`, `description` and an
`allowed-tools` field, loaded by progressive disclosure (~100 tokens of metadata → a body under
~5,000 tokens → linked resources); it became an open standard in Dec 2025 and is stewarded under
the AAIF [[50]](https://agentskills.io/specification) `[fetched][spec]`. A2A joined the same
foundation in Aug 2026 [[51]](#13-sources) `[snippet][eng]` (multi-agent; not relevant to a
single-owner JARVIS beyond noting it).

**Mapping.** JARVIS already has two owner-taught package formats: receipt-verified skill packs
(M9b) and app packs (ADR-0026). `SKILL.md` is a *portability* format, not an *authority* format —
`allowed-tools` is advisory unless the host enforces it, and in JARVIS the tiers would remain the
enforcement regardless of what a skill file declares. **OWNER-Q C8:** import/export `SKILL.md` for
app packs (with the receipt and tier ceiling applied on import), or stay with the native format?

### 8.3 Observability standards

The OpenTelemetry GenAI semantic conventions (`invoke_agent`, `execute_tool` spans; `gen_ai.*`
attributes) have moved to their own repository [[52]](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
`[fetched][spec]` and remain pre-stable [[53]](#13-sources) `[snippet]`; OWASP's ACS points at
OTel/OCSF for agent tracing (§3.5). **Recommendation only:** keep the SQLite journal as the source
of truth; a read-only exporter to OTel/OCSF can be added when the conventions stabilize, without
touching the pipeline.

---

## 9. Part H — Evaluation: knowing it is getting better

- **`pass^k`.** τ-bench introduced `pass^k` — the probability that *all k* independent trials of a
  task succeed — and found that state-of-the-art function-calling agents succeed on <50% of tasks
  with `pass^8` < 25% in retail [[54]](https://arxiv.org/abs/2406.12045) `[fetched abstract][arXiv]`.
  Arithmetic the owner should keep in mind: a 70% per-trial success is `pass^3 ≈ 34%`. A 98%
  target (ADR-0001) is a `pass^k` target, not a `pass@k` one.
- **Computer use is saturated at the short horizon and failing at the long one.** OSWorld 1.0
  (369 tasks): humans 72.36%, original best 12.24%; a Verified refresh followed in Jul 2025
  [[55]](http://osworld-v1.xlang.ai/) `[fetched][arXiv]`, and the earlier study's sources report
  agents at or above the human baseline on it (`RESEARCH-jarvis-agent-linux-2026.md` §3, sources
  24–25 there — not re-fetched here). OSWorld 2.0 (Jun 2026; 108
  workflows, human median ≈1.6 h, ~318 tool calls per task): best binary completion 20.6% at
  release (Opus 4.8, max thinking; 54.8% partial), 31.4% on the Aug 2026 leaderboard (Opus 5); GPT-5.5
  plateaus near 14%. The authors' diagnosis: agents "lose track of constraints, miss information
  that arrives mid-task, **guess rather than ask the user, and skip verification**"
  [[56]](https://osworld-v2.xlang.ai/) `[fetched][arXiv]`. Those four failure modes are the four
  things the JARVIS pipeline refuses to do (GROUND, APPROVE, VERIFY; structural abstention).
- **Defense benchmarks overstate.** §3.3's tool-firewall and AgentDyn results mean any
  injection-resistance number quoted for JARVIS must come from *its own* fault-injection suite
  (M3: 35 vectors, 0 escapes — VERIFIED in the audit), not from AgentDojo-style figures.
- **Separate the judge.** The harness-design result (§2.3) — evaluators must be separate and
  skeptical, with explicit criteria — argues for keeping JARVIS's evals *non-LLM* where possible
  (they are) and, where an LLM is in the loop (`llm-eval.yml`), grading by *state* (did the machine
  end up right) rather than by transcript.

**VERIFIED-IN-REPO:** `evals/harness/m2_eval.py` runs each catalog case exactly once (its only
options are `--catalog`/`--results`); `m3_faults.py` (`--results`) and `m4_grounding.py`
(`--catalog`/`--results`) likewise have no repeat option. A `--runs k`
option reporting `pass^k` per case is a small, self-contained harness change. **Recommendation
C6** (not an owner question — it changes no behaviour — but it is not implemented here because this
task is research-only).

---

## 10. Part I — Capability map and roadmap candidates

Each candidate: what, why (evidence), where (module/ADR), charter check, size, and the decision
needed. None is started. Sizes are my estimates (**ASSUMED**).

| # | Candidate | Evidence | Where | Charter check | Size | Decision |
|---|---|---|---|---|---|---|
| **C1** | Owner-authored, narrowing-only **argument policy** over playbook argv (deny-lists per playbook, path scopes), integrity-scoped | Progent, AgentSpec, CaMeL (§3.3–3.4) | `safety/tiers.py`, `safety/integrity.py` scope, new ADR | Strengthens least privilege; no new authority | M | OWNER-Q |
| **C2** | **Resumable task log** with idempotency flags per playbook; crash → offer resume/undo, never auto-resume | Managed Agents, durable execution (§2.3, §4.3) | `journal/sqlite.py`, `core/orchestrator.py`, playbook metadata | Human decides after crash; ADR-0017 D3 intact | M–L | OWNER-Q |
| **C3** | **Watchdog + STATUS** for the resident doorway (stdlib `sd_notify`), plus per-unit hardening directives with tested carve-outs | sd_notify(3), systemd hardening (§3.7, §4.2) | `cli/serve.py`, unit templates | Stdlib only (ADR-0005); doorway remains a doorway | S | OWNER-Q (directive set) |
| **C4** | **Environment signals** as briefing inputs: logind sleep/shutdown, session lock, NM/UPower, inotify, idle (per-compositor) via fixed-argv `busctl`/`gdbus` | §5 | `brief/engine.py compose()/decide()`, resident listener (ADR-0018) | Propose-only (ADR-0021); suppress on sleep/lock | M | OWNER-Q (which signals; listener placement) |
| **C5** | **Sandboxing the hands**: Landlock self-restriction via `ctypes` (no dependency) or bubblewrap (external binary) around T0/T1 steps | §3.7 | `execution/runner.py`, new ADR | Best-effort must *fail closed for explicit requests*, never silently downgrade | L | OWNER-Q (dependency) |
| **C6** | **`pass^k` in eval drivers** (`--runs k`), schema-validity per model | τ-bench (§9) | `evals/harness/*` | No behaviour change | S | Recommendation |
| **C7** | **MCP 2026-07-28 migration plan** (read the spec for stdio; keep 2024-11-05/2025-03-26 negotiation until then) | §8.1 | `cli/mcp_server.py`, HUD `bridge/protocol.py` | Interop only | S (plan) / M (do) | OWNER-Q |
| **C8** | **`SKILL.md` import/export** for app packs, tier ceiling applied on import | §8.2 | ADR-0026 pack loader | Tiers stay the enforcement | M | OWNER-Q |
| **C9** | **Owner-run offline prompt optimization** (GEPA-style) of the planner prompt against the eval catalog; output is a reviewed candidate, never a runtime edit | §6.2 | `evals/`, `planner/llm.py` prompt constant | ADR-0013 non-goal preserved | M | OWNER-Q |
| **C10** | **Release attestations** (Trusted Publishing + PEP 740) if ever published; SHA-256 manifest meanwhile | §3.6 | `release.yml`, ADR-0011 | Supply-chain hygiene | S | OWNER-Q |
| **C11** | **Hash-linked journal rows** (evidence chain) | SAL (§3.4), ACS (§3.5) | `journal/sqlite.py` | Tamper-evidence only | S | OWNER-Q |

**Explicitly not adopted (with the reason):** autonomous observe–iterate loops (ADR-0017 D3;
OSWorld 2.0 shows they fail by guessing); runtime self-modifying skills or policies (ADR-0013
non-goal; reward hacking); any network tool for the model (lethal trifecta); guardrail-only
defenses (95% is a failing grade); a GNOME Newton dependency (still a prototype per the earlier
study; AT-SPI remains the shipping API); a Python D-Bus or sandbox library (ADR-0005).

---

## 11. Where the field disagrees, and what I did not verify

**Disagreements.**
- *Compaction vs reset* for long tasks: Anthropic used resets for Sonnet 4.5 and found them dead
  weight for Opus 4.5 [[7]](#13-sources)[[8]](#13-sources). JARVIS sidesteps the question by keeping plans
  ≤6 steps and observations out of the planner; the question returns only if C2 makes tasks longer.
- *Scaffolds go stale vs scaffolds are the product*: true for capability crutches, false for
  authority boundaries (§2.3). I hold this as **ASSUMED** reasoning, not a sourced claim.
- *Benchmarks*: defenders and attackers agree AgentDojo-class numbers are inflated (§3.3); OSWorld
  1.0 is solved while OSWorld 2.0 is not (§9). Quote none of them as JARVIS's own reliability.
- *Files vs graphs vs vectors* for memory: the personal-scale evidence favours files
  `[vendor]`-tier; the survey names trustworthiness, not retrieval accuracy, as the frontier.
- *SLM-first vs frontier*: ReWOO and the NVIDIA position support small local planners for
  JARVIS's shape; long-horizon computer use still needs frontier models and still fails.

**Not verified in this study (do not build on these without checking).**
- The exact D-Bus interface names and property paths for UPower and NetworkManager
  (`[snippet]` only); the stdio-transport consequences of MCP 2026-07-28; Landlock struct layouts
  for a `ctypes` implementation; whether `ProtectHome=`/`NoNewPrivileges=` interact with `sudo -n`
  the way I expect; every `[snippet]`-tier number in §3.3, §3.5, §6, §7.
- Nothing in this document was executed against a live system; no benchmark was run.

---

## 12. Questions for the owner (decisions, not recommendations)

1. **Least privilege (C1).** Do you want an ADR for an owner-authored, narrowing-only argument
   policy on top of the tiers — and should it live in the integrity scope (tamper-evident, needs
   re-baseline to edit) or beside the charters (operational)?
2. **Crash semantics (C2).** After a crash mid-plan, should JARVIS *offer* resume-or-undo on next
   invocation (requires per-playbook idempotency flags), or is "undo only" — today's behaviour —
   the intended contract?
3. **The doorway's survival (C3).** May the resident doorway adopt `Type=notify` + `WatchdogSec`
   + `STATUS=` (stdlib), and which hardening directives do you want evaluated per unit?
4. **Environment signals (C4).** Which of the §5.4 signals are wanted, and may the long-lived
   listener live in the opt-in doorway — or should awareness stay poll-at-briefing-time only?
5. **Sandboxing the hands (C5).** Is a `ctypes` Landlock self-restriction (no dependency, real
   complexity) preferable to bubblewrap (a new external dependency), or is neither wanted while
   argv-only execution and tiers hold?
6. **MCP (C7).** Should a `2026-07-28` migration be planned inside the twelve-month window, or
   does JARVIS keep negotiating the older versions with the HUD as sole client?
7. **Skills interop (C8).** Adopt `SKILL.md` as an import/export format for app packs, or keep
   the native receipt-verified format only?
8. **Offline prompt optimization (C9).** May the owner-run, eval-gated GEPA-style loop be
   specified in an ADR, with the explicit rule that its output is a reviewed *candidate* prompt?
9. **Release provenance (C10)** and **evidence chain (C11).** Both are small; do you want them
   bundled into one "provenance" ADR?
10. **Ordering.** If only one of C1–C11 proceeds this quarter, which? My evidence-weighted
    suggestion is C1 (security) or C4 (the "environmental" capability you named), but the choice is
    yours.

---

## 13. Sources

Retrieval mode and tier are given for each. All retrieved 2026-09-06.

1. Anthropic, "Building effective agents" (Dec 2024) — anthropic.com/engineering/building-effective-agents `[fetched][eng]`
2. 2026 practitioner syntheses of agent architecture (six components; ReAct/P&E/ReWOO/Reflexion comparisons) — multiple engineering blogs surfaced by search; read as excerpts only `[snippet][eng]`
3. B. Xu et al., "ReWOO: Decoupling Reasoning from Observations," arXiv:2305.18323 (2023) `[fetched abstract][arXiv]`
4. N. Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement Learning," arXiv:2303.11366 (v4, Oct 2023) `[fetched abstract][arXiv]`
5. Anthropic, "Effective context engineering for AI agents" (Sep 2025) — anthropic.com/engineering/effective-context-engineering-for-ai-agents `[fetched][eng]`
6. Anthropic, "Effective harnesses for long-running agents" (Nov 2025) — anthropic.com/engineering/effective-harnesses-for-long-running-agents `[fetched][eng]`
7. P. Rajasekaran (Anthropic Labs), "Harness design for long-running application development" (Mar 24 2026) — anthropic.com/engineering/harness-design-long-running-apps `[fetched][eng]`
8. Anthropic, "Scaling Managed Agents: Decoupling the brain from the hands" (Apr 8 2026) — anthropic.com/engineering/managed-agents `[fetched][eng]`
9. Anthropic, "Writing effective tools for AI agents—using AI agents" (Sep 2025) — anthropic.com/engineering/writing-tools-for-agents `[fetched][eng]`
10. S. Willison, "The lethal trifecta for AI agents" (Jun 16 2025) — simonwillison.net/2025/Jun/16/the-lethal-trifecta/ `[fetched][eng]`
11. L. Beurer-Kellner et al., "Design Patterns for Securing LLM Agents against Prompt Injections," arXiv:2506.08837 (2025) `[fetched abstract][arXiv]`
12. E. Debenedetti et al., "Defeating Prompt Injections by Design" (CaMeL), arXiv:2503.18813 (2025) `[snippet][arXiv]`
13. T. Shi et al., "Progent: Programmable Privilege Control for LLM Agents," arXiv:2504.11703 (v3, May 2026) `[snippet][arXiv]`
14. "Tool firewalls: input minimization and output sanitization at the agent–tool interface," arXiv:2510.05244 (Oct 2025) `[snippet][arXiv]`
15. "AgentDyn," arXiv:2602.03117 (Feb 2026) `[snippet][arXiv]`
16. H. Wang, C. M. Poskitt, J. Sun, "AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents," arXiv:2503.18666 (v3; ICSE 2026) `[fetched abstract][arXiv]`
17. Anthropic, Claude Code hooks reference (Jul 2026) — code.claude.com/docs `[snippet][eng]`
18. "SAL: a control plane for intent-with-justification validation and evidence chains," arXiv:2604.22136 (Apr 2026) `[fetched abstract][arXiv]`
19. OWASP GenAI Security Project, "Top 10 for Agentic Applications 2026" (Dec 9 2025) — genai.owasp.org `[snippet][eng]` (landing page fetched; list content from excerpts)
20. OWASP GenAI Security Project, 2026 LLM Top 10 and Agent Control Standard v0.1 announcements (Sep 1–2 2026; CSA briefing / press release) `[snippet][eng]`
21. W. Woodruff (Trail of Bits), "Attestations: A new generation of signatures on PyPI" (Nov 14 2024) `[snippet][eng]`
22. K. Keller, "A Layered Architecture for Python and Conda Supply Chain Security" (Mar 2026) `[snippet][eng]`
23. M. Salaün, "Landlock: unprivileged access control," Linux kernel userspace-API documentation (Aug 2026, 7.3.0-rc1 docs) — docs.kernel.org/userspace-api/landlock.html `[fetched][spec]`
24. bigiron.cc, "Bubblewrap vs Firejail vs nsjail" (Jun 2026); x-cmd bwrap page (Sep 2026) `[snippet][eng]`
25. U. Enyioha, "OS-Level Sandboxing: Kernel Isolation for AI Agents" (dev.to, Mar 2026) `[snippet][eng]`
26. systemd service hardening guides (2025–26) and `systemd-analyze security` `[snippet][eng]`
27. R. S. Babu, A. Agrawal, "Self-Healing Agentic Orchestrators for Reliable Tool-Augmented LLM Systems," arXiv:2606.01416 (May 31 2026) `[fetched abstract][arXiv]`
28. MAPE-K / SEAMS 2026 self-adaptive-systems line (LLM planner, non-LLM executor) `[snippet][arXiv]`
29. Durable-execution engineering posts (journal/replay, checkpointing, event sourcing, idempotency keys) `[snippet][eng]`
30. systemd, `sd_notify(3)` (systemd 261) — freedesktop.org/software/systemd/man/latest/sd_notify.html `[fetched][spec]`
31. OneUptime / Stack Overflow posts on a pure-Python `NOTIFY_SOCKET` client and `WATCHDOG_USEC` (Mar 2026) `[snippet][eng]`
32. systemd, `org.freedesktop.login1` D-Bus interface (systemd 261) — freedesktop.org/software/systemd/man/latest/org.freedesktop.login1.html `[fetched][spec]`
33. linuxvox (Jun 2026) and ServerFault threads on logind `PrepareForSleep`, NetworkManager `StateChanged`, UPower signals `[snippet][eng]`
34. `inotify(7)`, Linux man-pages — man7.org/linux/man-pages/man7/inotify.7.html `[fetched][spec]`
35. Quickshell `IdleMonitor` docs (ext-idle-notify-v1); ckb-next issue #1012 (Mutter `IdleMonitor.GetIdletime`, portal `Inhibit.CreateMonitor`) `[snippet][eng]`
36. E. Horvitz, "Principles of Mixed-Initiative User Interfaces," CHI 1999 — dl.acm.org/doi/pdf/10.1145/302979.303030 `[snippet of PDF][peer-reviewed]`
37. H. Chase (LangChain), "Introducing ambient agents" (Jan 14 2025) — langchain.com/blog/introducing-ambient-agents `[fetched][eng]`
38. "Expected-utility framing of proactive-agent interruption timing," arXiv:2602.15259 (Feb 2026) `[snippet][arXiv]`
39. "A survey of memory in LLM agents: forms, functions, dynamics," arXiv:2512.13564 (v2, Jan 2026) `[fetched abstract][arXiv]`
40. Letta, filesystem-memory vs Mem0 on LoCoMo (2025–26) `[snippet][vendor]`
41. K. Lin et al. (Letta), "Sleep-time Compute," arXiv:2504.13171 (Apr 2025) `[snippet][arXiv]`
42. L. A. Agrawal et al., "GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning," arXiv:2507.19457 (v2, Feb 2026) `[snippet][arXiv]`; r/MachineLearning practitioner thread (Aug 2025) `[snippet, anecdotal]`
43. G. Zhang et al., "The Landscape of Agentic Reinforcement Learning for LLMs: A Survey," arXiv:2509.02547 (v5, Apr 2026) `[snippet][arXiv]`
44. Self-evolving-agent survey arXiv:2508.07407; Voyager; Darwin Gödel Machine `[snippet][arXiv]`
45. P. Belcak et al. (NVIDIA), "Small Language Models are the Future of Agentic AI," arXiv:2506.02153 (2025) `[snippet][arXiv]`
46. 2026 local tool-calling measurements (sub-2B models) — engineering blogs `[snippet][eng]`
47. ggml-org/llama.cpp, "GBNF Guide" (grammars/README.md, Jun 2026) `[fetched][eng]`
48. PromptQuorum (Aug 2026, Jun 2026) and diyai.io (Aug 2026) local STT/TTS comparisons `[snippet][eng]`
49. Model Context Protocol blog, "The 2026-07-28 Specification" — blog.modelcontextprotocol.io/posts/2026-07-28/ `[fetched][eng]`
50. Agent Skills specification — agentskills.io/specification `[fetched][spec]`
51. A2A joins the AAIF (Aug 2026) `[snippet][eng]`
52. OpenTelemetry, GenAI semantic conventions (moved notice) — opentelemetry.io/docs/specs/semconv/gen-ai/ `[fetched][spec]`
53. OpenTelemetry semantic-conventions-genai repository status (pre-stable) `[snippet][spec]`
54. S. Yao et al., "τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains," arXiv:2406.12045 (Jun 2024) `[fetched abstract][arXiv]`
55. T. Xie et al., OSWorld (1.0 / Verified) project page — osworld-v1.xlang.ai `[fetched][arXiv]`
56. M. Yuan et al., "OSWorld 2.0: Benchmarking Computer-Use Agents on Long-Horizon Real-World Tasks" (Jun 2026; leaderboard v2026.08.08) — osworld-v2.xlang.ai `[fetched][arXiv]`

*Repository facts marked VERIFIED-IN-REPO were checked by reading the named files at combined-tree
commit `48d9771` (kernel `jarvis-agent` 1.20.0, `dependencies = []`, `requires-python >= 3.10`).
No test, benchmark or live system was run for this document.*
