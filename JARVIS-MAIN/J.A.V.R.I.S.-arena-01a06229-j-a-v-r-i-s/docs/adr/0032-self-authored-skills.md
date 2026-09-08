# ADR-0032: Self-authored skills — a forge that writes *data*, is tested by the *kernel*, and never reaches `skills/` without the owner

- **Status:** **Accepted 2026-09-08 (owner decisions D14) — scheduled after C2; not yet implemented.**
  Owner answers: placement **after C2**; Tier B **yes, as follow-up ADR-0033 once Tier A ships**;
  ceiling **T0 by default, T1 behind `--tier 1`**, **3** repair attempts; authoring modes **AI with
  template fallback**. Proposed the same day, docs only. Nothing in `src/` changes with this ADR. Three throw-away spikes were run in the sandbox to
  ground the claims below; none of their code is committed.
- **Owner request (verbatim intent):** make JARVIS capable of *"creating its own skills via
  programming, through multiple tests"* — generate a skill, test it repeatedly, adopt it — and
  study `nazirlouis/Ada-SI` for how such a feature is built. Treat as sequence item **C12**.
- **Context:** JARVIS already owns the *safe half* of a skill forge and has for five ADRs:
  - **M9b verified skill packs** (ADR-0013; `planner/skills.py`): a `*.skill.json` is *data* —
    `id`, `description`, one anchored `match` regex, a `playbook` id from the catalog, fixed
    scalar `params`, 1..10 `evals`, `provenance{source, sha256}`. `validate_skill` checks the
    schema; `_dry_run_evals` builds a real plan for every eval through the referenced playbook;
    `install_skill` writes the pack **and a receipt** (sha256); `installed_skills` reports
    `ok | invalid | drift`; `match_skill` is consulted **only after** every static matcher has
    failed, tries `ok` packs in id order, and returns the playbook's own tier and params. A pack
    has **no capture groups**: it maps phrasings to a fixed playbook call and can never move user
    text into an argv. *Packs add vocabulary, not power.*
  - **M8d supervised growth** (ADR-0012; `planner/grow.py`): `draft_skill` validates a pack
    through the same machinery and parks it under `state_dir()/proposals/skills/` with a
    `.meta.json` (rationale, timestamp). Proposals are never read by any matcher. Promotion is
    a separate, consented act: `jarvis --yes skill install <file>` (evals re-run at install).
  - **The journal already collects the forge's raw material**: every request no matcher could
    map is stored by `record_unknown_request(text, reason, alternatives)` (`journal/sqlite.py`,
    table `unknown_requests`, chained kind `unknown`); `cli/app.py` fills `alternatives` from
    `rank_intents`/`nearest_intents`, i.e. the closest catalog playbooks; the briefing engine
    reads `recent_unknown_requests` today.
  - **Provider layer** (ADR-0014/0025): `Provider.complete(system, user, *, schema=…)` with
    schema-constrained JSON output treated as *untrusted input*, breaker, failover with
    disclosure (`served_by`), the `--no-ai` / `JARVIS_NO_AI=1` contract.
  - **Charter limits**: ADR-0012's never-bend list — *"no self-modification of code or policy …
    context never increases action authority"*; ADR-0013's explicit non-goals — *"free-form code
    execution as a planner output … any path where the model edits its own policy, skills, or
    charter bytes."* This ADR must add a forge **without** crossing either line.

  What is missing is exactly the *authoring loop*: nothing today can *propose* a pack; the
  owner writes JSON by hand. The forge is that loop — and the field study below says the only
  version of it that survives contact with the evidence is one where the model authors **data**
  and the **kernel** owns every test.

## 1. Field study (deep research, 2026-09-07/08; primary sources in §9)

### 1.1 Ada-SI — the reference "forge" and the counter-example

`nazirlouis/Ada-SI` (MIT, 120★, last commit Jul 2026) is three services — FastAPI chat `:8080`,
LiteLLM proxy `:4000`, tool runtime `:8090`. A skill is a **Python module** in
`chat/custom_tools/{name}.py` (+ `.test.py`, `.requirements.txt`, `.manifest.json`) exposing
`get_tool_schema()` (OpenAI function schema) and `run(**kwargs)`. The pipeline
(`chat/build_pipeline.py`) is the owner's "multiple tests" loop:
`generate_code → validate_code → sandbox_test → validate_ui → contract_test → preview_review →
ui_preview → pip_review → runtime_verify → install_tool`, `PHASE_MAX_RETRIES = 3`, and on a
failure the LLM is asked to `fix_runtime_failure` / `fix_test_code` / `fix_validation_errors`
and the phase re-runs. `tool_verify.py` creates a fresh venv per attempt under `chat/staging/`,
`pip install`s the model's requirements (300 s), runs the model's `test_run.py` (120 s), caps
logs at 8 KiB; `augment_requirements_for_missing_module` parses `No module named 'x'` and
**auto-adds `x` to requirements** (≤ 4 retries). `tools_engine.py` loads the schema via
in-process `exec(compile(...))`; `tool_runtime/runner.py` runs every tool in a **persistent
shared venv** by writing a temp runner script and `subprocess.run`-ing it. The README says it
plainly: not OS-level sandboxing, no auth, forged code runs with the user's permissions, API
keys via `os.environ`; the approval gates "reduce accidents, not a security sandbox."

What Ada-SI gets right and JARVIS keeps: a **plan gate before code** (owner sees intent first),
a **bounded retry loop with the failure text fed back**, **per-attempt clean state**, **human
gates at install and at every dependency**. What Ada-SI does that JARVIS must not: the model
authors the code **and** the test that judges it (LLM-as-oracle); the dependency list grows
itself from error strings (the exact "slopsquatting" path — §1.3); the artifact is executable
Python with the user's full authority; "sandbox" means a venv.

### 1.2 The academic lineage of tool-making — and why every one of them authors code

- **LATM** (Cai et al., arXiv 2305.17126): a strong model writes a Python function *and* unit
  tests from a few demonstrations, repairs on failure, then a cheaper model calls the tool.
- **ToolMaker** (arXiv 2502.11705, May 2025): repository → installable tool with dependency
  installation and closed-loop self-correction; ≈ 8 unit tests per task; 80 % of 15 tasks.
- **Tool-making for low-latency agents** (arXiv 2607.08010, Jul 2026): repeated SOP steps are
  compiled into validated, versioned tools **before deployment**, repaired against labeled cases
  — offline, gated tool-making, the closest stance to this ADR.
- **Voyager**-style skill libraries (and their descendants AutoSkill/ExpeL) store executable
  skills and retrieve them by description.

### 1.3 What the security evidence says (the numbers that decide the design)

- **Self-poisoning of skill libraries — EvoMal** (Wu et al., Queen's U., arXiv 2608.25776,
  26 Aug 2026): an agent that authors and stores its own skills will *copy* a planted malicious
  skill's structure ("banner") into a **newly authored** malicious skill. Agent self-poisoning
  rate (ASPR) across 6 models × 153 SWE-bench Verified tasks: **20.3–41.8 %**; libraries end up
  holding **4.9–9.0×** the planted count; task-family-tailored descriptions reach **86.7 %**;
  the worm persists after the seeds are removed (Qwen3 round-5 ASPR 68 %). Copies evade every
  defence that inspects attacker-submitted names/code/signatures. The authors' remedy and the
  one this ADR adopts: a **two-level library — a curator-signed retrievable level and an
  unretrievable quarantine for agent-authored entries** (co-r-e.com write-up). JARVIS already
  has that shape: receipt-pinned `skills/` (retrievable) vs `proposals/` (quarantine).
- **EvoSkill Injection / SARGE** (arXiv 2608.30429): malicious skill *generation* in
  AutoSkill/Voyager/ExpeL, ASR 43–55 %; Voyager's harmful-action rate 6.5 % → 32.5 %.
  **SkillJack** (arXiv 2608.03509): poisoned *experience* records get compiled into durable
  skills with no write access to the library at all — i.e. the forge's *input* (our
  `unknown_requests`, which anyone who can type at JARVIS can fill) is an attack surface too.
- **AI-written code is not trustworthy by default — Veracode 2026 GenAI Code Security Report**
  (press release 2026-07-28; > 100 models, no security prompting): average security pass rate
  **56 %** — ≈ 44 % of code-generation tasks introduce a known vulnerability — flat versus 55 %
  the year before; best model 68 %; XSS 15 % and log-injection 12 % pass rates. **Package
  hallucination** (USENIX Sec 2025, via CSA): 19.7 % of 2.23 M generated samples referenced a
  non-existent package, 43 % of them repeatably ("slopsquatting") — the failure Ada-SI's
  auto-requirements path walks straight into.
- **Instruction-file "skills" are no safer** — the Agent Skills open standard (agentskills.io,
  `SKILL.md` = YAML + Markdown the model *reads*): Snyk's Feb 2026 audit of 3,984 public skills
  found **36.82 %** with ≥ 1 security flaw and **13.4 %** critical. ADR-0013 already rejected
  this class (the ClawHub lesson). One thing worth borrowing from that ecosystem's testing
  advice: every skill needs **happy-path, near-miss and out-of-scope must-not-activate cases**.

### 1.4 Conclusion of the study

Every published forge that authors *executable* artifacts inherits three unsolved problems at
once — an oracle the model controls, an authority the artifact inherits, and a library that
poisons itself. JARVIS' existing pack format sidesteps all three *if* the forge is confined to
it: a pack cannot execute, cannot carry user text into argv, cannot raise a tier, and cannot be
retrieved until a receipt exists. The owner's request is therefore met by adding the **authoring
loop** to M9b + M8d, not by adding a code path.

## 2. Options considered

| # | Option | Artifact the model writes | Oracle | Verdict |
|---|---|---|---|---|
| A | Ada-SI-style Python skills (LLM code + LLM tests, venv, pip) | executable code + deps | model-written tests | **Rejected** — ADR-0013 non-goal; Veracode 44 % flaw rate; slopsquatting; venv ≠ sandbox; ASPR 20–42 % |
| B | Agent-Skills `SKILL.md` instruction files | prose the model re-reads | none | **Rejected** — ADR-0013 (ClawHub class); Snyk 36.8 % flawed |
| C | **Tier A — vocabulary packs**: the forge authors an M9b `*.skill.json` | data: regex + playbook id + evals | kernel: schema, real dry-run, negatives, ReDoS, tier, shadow | **Proposed (core)** |
| D | **Tier B — read-only command specs**: the forge authors a `ReadOnlySpec`-shaped JSON (allow-listed T0 binary, pinned flags, ≤ 1 validated slot) | data: argv template | kernel: `check_argv`, `clean_arg`, Landlock read-only behavioural probe, fixture digest | **Proposed as owner option** — separate ADR (0033) if accepted; needs the confinement helper |
| E | Model-authored *playbooks* (T1/T2 with undo, sudo) | data with authority | none adequate (no oracle for "undo is correct") | **Rejected for now** — no test can vouch for reversibility; revisit only after C5 + a feedback history |

## 3. Decision (proposed)

### D1 — The forge authors data, never code

`jarvis grow forge` produces exactly one of two artifact kinds, both plain JSON compiled through
kernel code that already exists: a **Tier A pack** (`SKILL_SCHEMA = 1`, unchanged key set plus
the additive optional `negatives` list from D2) or — if the owner accepts Tier B — a
**read-only spec** (`ReadOnlySpec` fields: `id`, `description`, `argv`, `patterns_bare`,
`patterns_arg`, `arg_kind`, `timeout_s`). No Python, no shell, no dependency list is ever part
of a forge output; a candidate containing any other key is discarded before validation, not
"cleaned". Consequence of the format: a Tier A artifact **cannot** execute, carry user text into
an argv, or set a tier — it inherits the referenced playbook's tier exactly as packs do today.

### D2 — The tests are the kernel's; the model never grades its own work

Every candidate runs the full suite below; every failure is returned to the model verbatim as
the next attempt's context (D3). The model *may* add cases; it can never remove or replace the
kernel's.

| # | Test | Oracle (existing code first) |
|---|---|---|
| T1 | Schema + invariants | `validate_skill` (unchanged; `negatives`, if present, must be 1..20 non-empty strings) |
| T2 | Positive evals build a real plan | `_dry_run_evals` (real matcher regex + real `playbook.build` with the pack's params; nothing executes) |
| T3 | Negatives must **not** fullmatch | kernel-synthesized set **always**: all `INTENT_HINTS` phrases (the catalog's own vocabulary), a kernel-owned destructive corpus in `planner/forge.py` (the M3 phrasings — *wipe the disk*, *delete everything*, *remove glibc*, … — live inside test functions today, so the forge ships its own list and a test asserts it is a superset of the M3 vectors), the request with shell metacharacter tails (`; rm -rf /`, `$(…)`, backticks, `|`), empty/whitespace; plus any model-authored negatives |
| T4 | No capture groups, no shadowing | `re.compile(match).groups == 0`; `match_intent(request) is None` for every eval (a pack may only cover what the catalog cannot) |
| T5 | Pathological-regex probe | the regex is run in a **forked child under a wall budget** (250 ms) over evals, negatives and synthetic near-misses at 50/100/200 chars; a timeout is a failure. Spike 3 showed `validate_skill` accepts `(a+)+` today (0.72 s at 24 chars) — the forge gates it; recommendation F4 adds the same gate to hand-written packs |
| T6 | Tier ceiling | target playbook tier ≤ the forge's ceiling (default **T0**; `--tier 1` opt-in; T2 always refused — **D14: accepted as proposed**) |
| T7 | Identity | `id` collides with no installed pack, proposal or catalog playbook id |
| T8 | Provenance is kernel-made | `provenance.source = "forge:<provider>/<model>"` or `"forge:template"`, `sha256` computed by the kernel over the canonical bytes — never taken from the model |

Tier B adds: B1 `argv[0]` is in the **fixed allow-list of binaries the catalog already runs at
T0 with at most one argument slot** (today: `cat date df dig dmesg du env file free head hostname
id ip journalctl last ls lsblk lscpu lspci lsusb md5sum ping ps ss stat tail uname uptime wc which
who` — the 30 distinct `inspect_cmds.SPECS` binaries plus `uname` from `sys.info`, derived at test
time, never typed twice; `find`/`grep` from the two-slot readers `fs.find`/`fs.search` are
deliberately **out**, a spec has one slot); B2 every fixed token matches a strict flag grammar
and `check_argv` passes on the rendered argv (with the slot filled by a hostile sample per
`arg_kind`, which `clean_arg` must refuse); B3 **behavioural read-only probe**: the rendered
argv is executed once against a temporary fixture tree inside a **Landlock domain that denies
every filesystem write right** (Spike 2: `du` succeeds, `rm`/`>` get `EACCES` on this kernel,
ABI 2), with the runner's timeout; exit 0, non-empty stdout, and an **unchanged fixture digest**
are required; B4 shadow check against every catalog matcher; B5 network-capable binaries
(`ping`, `dig`) are flagged `network: true` in the spec — Landlock ABI 2 cannot deny network
(ABI ≥ 4 can), so the owner sees it at install.

### D3 — A bounded repair loop, every attempt written down

`attempts ≤ 3` (**D14: 3 accepted**; Ada-SI's `PHASE_MAX_RETRIES` is also 3). Attempt *n+1* receives the
request, the catalog block, the previous candidate and the **exact test failures**. On the last
failure the forge stops with the transcript and exit code 2 — it never installs, never widens a
regex "to make the test pass", never lowers the ceiling. The transcript
(`<id>.forge.json` beside the proposal: request, source of the request, provider `served_by` or
`template`, per-attempt candidate sha256 + failures, final verdict, wall time) is what
`jarvis grow show <id>` prints. No journal schema change: the proposals directory is the record,
and it stays **outside** the integrity scope on purpose — quarantine holds no authority.

### D4 — Quarantine and promotion (the EvoMal two-level rule, already JARVIS' shape)

The forge writes **only** to `state_dir()/proposals/skills/` (Tier A, via the existing
`draft_skill`) or `proposals/specs/` (Tier B). `match_skill` reads `skills/`; nothing reads
`proposals/`. Promotion is the owner's act and reuses existing verbs unchanged:
`jarvis grow export <id>` → `jarvis --yes skill install <file>` (all tests re-run at install,
receipt written, `doctor --write-baseline` reminder). Tier B promotion would be a new
`jarvis spec install|list|remove` family with its own receipts and an **additive** integrity-scope
entry (`state_dir()/specs`) — specified in ADR-0033 if accepted. Removing a forged artifact is
`skill remove` / `grow prune` as today.

### D5 — Trigger: the owner, never a timer

`jarvis grow forge "<request>" [--playbook <id>] [--tier 1] [--attempts N] [--json]` and
`jarvis grow forge --from-unknowns [--limit N]` (drains `recent_unknown_requests`, one candidate
per distinct request, `alternatives` offered to the model as hints). There is no scheduled or
event-driven forging; the briefing may at most *suggest* — "4 requests this week had no
playbook; `jarvis grow forge --from-unknowns` can draft packs for review" — which is the M8
pattern (suggestions cite evidence). This keeps the anti-Ultron clause intact: the model never
edits `skills/`, `playbooks.py`, policy or charter bytes; the owner does, with a receipt.

### D6 — Two authoring modes; the deterministic one needs no model

- **Template mode** (`--no-ai`, `JARVIS_NO_AI=1`, or no provider reachable): with `--playbook`
  given, the forge builds the pack itself — `match` = the whitespace-collapsed, `re.escape`d
  request anchored `^…$` (optionally with `(?:please )?`/trailing-punctuation tolerance from a
  fixed template list), one eval (the request), the kernel negatives, `source: forge:template`.
  This is "teach JARVIS that *show me the disks* means `fs.disk_free`" in one command and
  already covers most `unknown_requests`.
- **AI mode**: `complete_with_failover(system, user, schema=FORGE_PACK_SCHEMA)` with the same
  breaker, failover and `served_by` disclosure as the planner; the system prompt is derived from
  the catalog like `build_system_prompt()` (ids, descriptions, tiers, the pack schema, the rules
  in D1/D2); the model proposes `match`, `evals`, `negatives`, `description`, `playbook`. The
  output is untrusted input: parsed, key-filtered, then run through D2 like any other candidate.
  Without `--playbook` the model picks the target; T6/T4 bound the damage of a wrong pick.

### D7 — Interfaces preserved (additive only)

CLI: new sub-command under the existing `grow` verb; `skill install|list|remove` and
`grow fact|skill|list|show|prune|export` unchanged. Pack schema: `SKILL_SCHEMA` stays 1;
`negatives` optional and ignored by 1.23 readers (unknown keys already tolerated). Journal: no
new table; the forge only *reads* `unknown_requests`. MCP: no new tool in this ADR (a
`jarvis_forge` tool would be a consent question of its own — recommended as a follow-up, not
scope). Integrity scope: unchanged for Tier A. Version on implementation: the next minor after C2
(**1.25.0** if C2 ships as 1.24.0).

### D8 — Non-goals (explicit, in the charter's words)

No Python/shell/`SKILL.md` skills; no pip or any dependency change by the forge; no model-only
oracle; no forged artifact above the ceiling; no autonomous or scheduled forging; no forge
output ever placed in `skills/`, `playbooks.py`, `policy/`, `charters/`; no remote skill
registry; no MCP exposure; no "sandbox" claim for anything but the Tier B *probe* (the installed
spec runs through the ordinary runner until C5 lands).

## 4. Failure modes (each degrades to today's behaviour)

| Situation | Behaviour |
|---|---|
| No provider / breaker open / `--no-ai` | Template mode when `--playbook` given; otherwise exit 2 with "no target playbook — pass `--playbook` or enable AI"; nothing written |
| Model returns non-JSON / extra keys / wrong schema | Attempt counted, failure text fed back; after N attempts exit 2 with transcript; nothing in `skills/` |
| Model targets a T2 playbook or an unknown id | T6/T1 fail — never "corrected" to a nearby id |
| Over-broad regex (`.*disk.*`) | T3 (INTENT_HINTS, M3 corpus, metachar tails) and T4 (`match_intent` must be None) fail |
| Catastrophic regex | T5 child times out → failure; the parent never runs the regex itself |
| Request itself is hostile (poisoned `unknown_requests`, SkillJack class) | The request is only ever a *phrase to match*; a pack cannot carry it into an argv; T3 metachar tails reject regexes built to absorb such tails; the owner reads the regex at install |
| Proposal tampered with after forging | Irrelevant to authority (quarantine); `skill install` re-runs every test and pins a fresh receipt |
| Forge interrupted mid-loop | Nothing partial: the proposal + transcript are written once, atomically, after the last test |
| Tier B: probe binary missing on this machine | B3 fails honestly ("`lsblk` not found") — no fallback binary |
| Tier B: Landlock unavailable (old kernel, ABI < 1) | Probe **refuses to run** ("no confinement; run on a Landlock kernel or install the spec by hand") — best-effort must fail closed for an explicit request (research §3.7 rule) |
| Tier B: command exits 0 but changes the fixture | Digest mismatch → failure; the spec is not read-only whatever its name says |

## 5. Verified vs. assumed (design phase, sandbox, 2026-09-08)

**Verified by real runs (spikes, not committed):**
- Spike 1 — a JSON-described spec compiled through the existing `ReadOnlySpec → make_readonly`
  path (no kernel edit) matched *"show the biggest files under /tmp"* (which `match_intent`
  does not), built `('du', '-ah', '--max-depth=1', '/tmp')` at T0, passed `check_argv`, matched
  **none** of the 57 `INTENT_HINTS` phrases, and rejected *"delete the biggest files in /tmp"*.
- Spike 2 — `ctypes` Landlock on this kernel (6.1.158, **ABI 2**): a child that handled all
  fourteen ABI-2 filesystem rights and allowed only `EXECUTE|READ_FILE|READ_DIR` beneath `/`
  ran `du -ah --max-depth=1 <fixture>` (exit 0, 3 lines); in the same domain `sh -c 'echo > f'`
  and `rm` both failed with `Permission denied` and the fixture was unchanged.
- Spike 3 — `validate_skill` returns `[]` for `match = "^(?:show )?(a+)+ the disk$"`; a
  near-miss of 24 chars takes 0.72 s (18 → 0.01 s, 22 → 0.18 s) — the ReDoS gate is needed.
- The kernel facts in Context (function names, tables, ordering of `match_skill` after
  `match_intent`, tolerance of unknown pack keys, `unknown_requests` producers/consumers) were
  read from the source, not recalled.

**Not verified, and cannot be here:** any live model producing a pack (no Ollama, no API key);
therefore the model's schema compliance, its typical attempt count, and whether a local model
shows EvoMal-style copying on this prompt are **unknown** — the implementation's tests will use
`FakeProvider` scripts (compliant, non-JSON, over-broad, T2-targeting, ReDoS, extra-key
replies) and the owner's first live run is the acceptance test. Landlock ABI ≥ 4 network rules
were not exercised (kernel too old here).

## 6. Owner decisions (asked and answered 2026-09-08 — TASKS.md D14)

- **Q-A · Placement.** Next (before C2), or after C2, or park. **Answer: after C2** — C2 (resumable
  task log) is implemented first; the forge follows as the next minor release after it.
- **Q-B · Tier B.** Accept as a follow-up ADR-0033 after Tier A ships / decline / decide later.
  Tier B is the only part that executes anything during testing and the only part that needs the
  Landlock helper (which would pull the confinement primitive of C5 forward). **Answer: follow-up
  ADR-0033 after Tier A ships.**
- **Q-C · Ceiling and budget.** Forged packs may target: T0 only (default) / T0 + T1 behind
  `--tier 1` / any tier the owner names. Repair attempts: 3 (default) or another number. **Answer:
  T0 default, T1 behind `--tier 1`; 3 attempts.** T2 stays refused whatever flags are passed.
- **Q-D · Authoring modes.** Both (AI with template fallback, default) / template only (no model
  ever writes a regex) / AI only. **Answer: both** (AI with template fallback).

## 7. Consequences

- The owner's loop exists — propose → test → repair → propose again → owner installs — with the
  model confined to the one artifact class the kernel can fully judge. Ada-SI's ergonomics, none
  of its authority.
- The catalog's *reach* grows without the catalog growing: new phrasings for existing
  playbooks (Tier A) and, if accepted, new read-only inspections over already-trusted binaries
  (Tier B). Neither adds an authority path; both are removable with one command.
- `unknown_requests` becomes useful beyond the briefing: the gap list turns into draft packs.
- What is deliberately not here: forged write-path capabilities, a self-updating catalog,
  the model touching its own tests. Those are the three things the evidence says not to build.

## 8. Implementation plan (on acceptance; sized for one commit series)

`src/jarvis/planner/forge.py` (candidate model, kernel negatives, T1–T8, repair loop, template
mode, transcript; ≈ 350 LOC) · `cli/app.py` `grow forge` sub-command (+ `grow show` prints the
transcript) · `planner/skills.py`: optional `negatives` in `validate_skill` + `install_skill`
re-check (additive) · `tests/test_forge.py` (FakeProvider scripts above, template mode, loop
bounds, transcript shape, quarantine-only writes, `--from-unknowns` from a seeded journal) ·
M3 corpus gains forge vectors (over-broad regex, T2 target, metachar tails) · docs
(CHANGELOG entry for that release, README "Growing vocabulary with the forge", PLAN row, this ADR
to Implemented, AGENT-EXPERIENCE). Tier B = ADR-0033 + `system/confine.py` (Landlock via `ctypes`,
re-exec helper rather than `preexec_fn`, which the `subprocess` docs mark unsafe with threads)
+ `planner/specs.py` + `spec` verbs.

## 9. Sources (fetched 2026-09-07/08 unless marked)

- `nazirlouis/Ada-SI` — `README.md`, `chat/build_pipeline.py`, `chat/tool_creator.py`,
  `chat/tool_verify.py`, `chat/tools_engine.py`, `chat/prompts_config.py`,
  `tool_runtime/runner.py` (github.com/nazirlouis/Ada-SI, raw files) `[fetched]`.
- H. Wu et al., "EvoMal: self-poisoning of self-evolving agents' skill libraries" — arXiv
  2608.25776 (abstract page) `[fetched]`; CO-R-E write-up "Skill-library self-poisoning"
  (co-r-e.com/method/skill-library-self-poisoning) `[fetched]`.
- "EvoSkill Injection / SARGE" — arXiv 2608.30429; "SkillJack" — arXiv 2608.03509 `[search
  snippets only]`.
- T. Cai et al., "Large Language Models as Tool Makers" — arXiv 2305.17126; "ToolMaker" — arXiv
  2502.11705; "Tool-making for low-latency agent systems" — arXiv 2607.08010 `[search snippets]`.
- Agent Skills specification — agentskills.io `[fetched]`; Snyk, "Audit of 3,984 public agent
  skills" (Feb 2026) `[search snippet]`.
- Veracode, "2026 GenAI Code Security Report" — press release via SD Times, 2026-07-28
  `[fetched]`; secondary coverage tech-insider.org (2026-08-06), matrixgard.com (2026-08-03);
  CSA on package hallucination (USENIX Security 2025 figures) `[search snippets]`.
- M. Salaün, "Landlock: unprivileged access control" — docs.kernel.org/userspace-api/landlock.html
  (Aug 2026) `[fetched: rules, ABI compatibility switch, `no_new_privs` requirement, network
  rules since ABI 4]`.
- Python `subprocess` documentation (args as a sequence, `shell=False`, `preexec_fn` caveat)
  `[fetched]`.
- In-repo: ADR-0012 (M8d, anti-Ultron clause), ADR-0013 (M9b, non-goals), ADR-0014/0025
  (provider contract, failover disclosure), `docs/RESEARCH-agent-construction-and-future-tech-2026.md`
  §3.7 (sandboxing), §6.2 (learning loops), candidate table (C5).
