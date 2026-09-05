# JARVIS — Master Project Plan

> **JARVIS** — *"Just A Rather Very Intelligent System."* Canonical display form: `JARVIS` (owner ruling, 2026-09-02). Python package and CLI: `jarvis`. The GitHub repository keeps its original name (`J.A.V.R.I.S.`); renaming it is an owner decision and out of the agent's authority.

| | |
|---|---|
| **Status** | `ACCEPTED — baseline` (owner delegated remaining decisions to engineer-of-record, 2026-09-02; resolutions in §13, ADR-0001…0004; maintained through ADR-0024, 2026-09-04 — later amendments are dated annotations, history preserved) |
| **Date** | 2026-09-02 |
| **Governance** | Single source of truth for scope & architecture. Binding charter: `docs/GOVERNANCE.md`. **The owner merge policy is absolute: the agent never merges anything.** All work lives on the session branch. |
| **Evidence base** | `docs/RESEARCH.md` (all decisions trace to research items R1–R5); 2026 deep-research corpus: `docs/RESEARCH-jarvis-agent-linux-2026.md` (45 sources; produced the landed R1–R5 roadmap) |

---

## 1. Mission & Scope

**Mission.** JARVIS is a production Linux automation agent that plans, executes, and *verifies*
real tasks on the user's machine — across distributions — without destabilizing the system and
without the user having to script anything. It is not a chatbot with shell access; it is an
**operational agent with a safety kernel**.

**In scope (v1.x)**
1. Natural-language task execution on the local Linux machine (packages, services, files, config, networking, cron/timers, user environment).
2. Distro abstraction: Debian/Ubuntu, Fedora, Arch, openSUSE, Alpine + Flatpak/Snap at v1; adapter interface open for the rest.
3. Deterministic **task engine** (verified playbooks, no LLM needed) + **LLM planner** (local models and/or APIs) behind one router.
4. Grounded knowledge: local system introspection, man pages, package metadata, versioned knowledge base, optional online official-docs fetch with attribution.
5. GUI automation (X11 + Wayland) via layered backends (AT-SPI → compositor DBus → uinput → vision fallback).
6. Full audit trail: every action journaled with plan, approval, result, and undo path.

**Out of scope (explicitly, for v1.x)**
- Multi-machine/fleet orchestration; Windows/macOS; home-automation integrations; unattended full-autonomy mode on system-level changes.
- *Dated scope amendments (2026-09-04, owner-directed roadmap):* **voice I/O** entered scope as
  a push-to-talk front-end through the same kernel (ADR-0019, v1.13.0; ambient wake-word stays
  parked per the ADR-0005 exception), and a **purpose-built tiny intent classifier with an
  in-repo gated trainer** entered scope (ADR-0015/0023, v1.10.0/v1.17.0) — general model
  training/fine-tuning remains out of scope.

**Anti-goals** (what this project will never do)
- Blindly execute model output; pipe anything into a privileged shell unread (RESEARCH R2); claim success without post-condition verification; ship placeholder/unfinished modules (owner guideline #1).

---

## 2. Requirements (owner's 11 points → engineering requirements)

| # | Owner point | Requirement |
|---|---|---|
| 1 | Any task, any distro | FR-1 Distro abstraction layer (identity, package, service, firewall, paths adapters). Tier-1: Ubuntu/Debian, Fedora, Arch, openSUSE, Alpine |
| 2 | Does not blindly do tasks | FR-2 Action classification + tiered approval (§4.3); refuse-or-ask on low confidence |
| 3 | 98% success rate | NFR-1 Success-rate engineering — precisely defined, measured, gated (§3) |
| 4 | Never destabilize the PC | NFR-2 Safety kernel: backups, dry-run, journal, undo, blocklists (§4.3) |
| 5 | Deep, current knowledge | FR-3 Layered knowledge system (§4.4) with versioned KB + live local grounding |
| 6 | Prevent hallucination | NFR-3 Grounding pipeline: cite-or-abstain, schema-strict tools, post-condition checks (§4.4) |
| 7 | Nothing unstable/misconfigured | NFR-4 Preflight simulation + atomic config edits + snapshot/restore integration (§4.3) |
| 8 | Right tool per distro is hard | FR-4 Capability registry: agent discovers what exists on THIS machine before choosing tools |
| 9 | API + local models + basic-task engine | FR-5 Provider abstraction + rule engine + complexity/sensitivity router (§4.5) |
| 10 | Deep integration, simple setup | FR-6 One-command install, zero-config first run, systemd user service optional; root only when a task requires it, per-action |
| 11 | GUI control path | FR-7 Layered GUI backends with consent-based setup wizard (§4.6) |

---

## 3. Reality Check: Success-Rate Engineering (the "98%" question)

RESEARCH R1 is unambiguous: state-of-the-art computer-use agents score **63.5–76%** on OSWorld and
**~20%** on long-horizon OSWorld 2.0. Promising 98% open-world success would be dishonest. We will
not do that. Instead we make 98% a **measured, scoped, auditable engineering target**:

**Definition (proposed for owner confirmation):**
> **S ≥ 98% =** on the versioned **Tier-1 Task Catalog** (curated, well-specified tasks the agent
> officially supports), measured by automated execution-based evaluation in disposable containers/VMs,
> where a task counts as success only if **post-condition verification passes**. Outside the catalog,
> the agent operates in *explorer mode*: plan → confirm → execute → verify, and must **decline or
> escalate** when confidence or verification fails. Catalog + eval results are versioned and published
> in-repo (`evals/results/`) — the claim is always auditable.

This matches the owner's own rule #2 (*"does not blindly do any task"*) and converts point 3 from a
marketing number into a quality gate: **the catalog grows only when its tasks hold ≥98% in CI.**

> **ADOPTED 2026-09-02** via [ADR-0001](adr/0001-scoped-success-metric.md) (authority delegated by owner).

---

## 4. Architecture Overview

### 4.1 Pipeline (every task, no exceptions)

```
 User intent
     │
     ▼
 ┌─────────┐   ┌─────────┐   ┌────────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐
 │  SENSE  │──▶│  GROUND │──▶│  PLAN  │──▶│ APPROVE  │──▶│ EXECUTE  │──▶│ VERIFY  │
 │ inspect │   │ facts & │   │ steps, │   │ safety   │   │ guarded, │   │ post-   │
 │ machine │   │ tools   │   │ costs  │   │ tier gate│   │ stepwise │   │ checks  │
 └─────────┘   └─────────┘   └────────┘   └──────────┘   └──────────┘   └────┬────┘
     ▲        ┌──────────────────────────────────────────────────────────────┤
     │        ▼                                                              │
 ┌───┴─────────────┐        failure → diagnose → replan (bounded retries)     │
 │   JOURNAL /     │◀── every stage recorded: plan, diffs, output, undo ──────┘
 │   AUDIT (SQLite)│
 └─────────────────┘
```

- **SENSE** — machine fingerprint: distro (`/etc/os-release`), init system, session type, available tools, permissions, hardware.
- **GROUND** — resolve intent against *this machine's* reality (capability registry, package metadata, man pages, KB). Hallucination dies here or not at all.
- **PLAN** — rule engine first (playbook match → deterministic, no LLM); LLM planner otherwise; plan = typed step list (strict Pydantic schemas), each step tagged with a safety tier.
- **APPROVE** — §4.3 tier gate; user-visible plan with diffs; config-controlled autonomy per tier.
- **EXECUTE** — guarded shell (timeouts, output caps, sandbox options), one step at a time, journaling everything.
- **VERIFY** — post-conditions per step + per task; failure → bounded diagnosis/replan or clean rollback.
- **LEARN** — outcomes feed the journal and eval harness; recurring confirmed plans become candidate playbooks (human-reviewed).

### 4.2 Module boundaries (planned `src/jarvis/`)

| Module | Owns | Must NOT |
|---|---|---|
| `core` | Orchestrator, state machine, task lifecycle | touch hardware/LLM directly |
| `system` | Distro/capability adapters (pkg, svc, fw, paths) | know about LLMs |
| `execution` | Guarded shell, validators, sandboxes, atomic file edits | decide *whether* to act |
| `safety` | Tier classification, blocklists, backups, snapshots, undo | execute anything |
| `planner` | Rule engine (playbooks) + LLM planner, step schemas | execute anything |
| `knowledge` | Capability registry, KB store, man/doc grounding, fetch cache | guess — cite or abstain |
| `providers` | LLM providers (local: Ollama/llama.cpp; API: OpenAI/Anthropic/Google/OpenRouter) | contain task logic |
| `gui` | AT-SPI, compositor backends, uinput, vision fallback | bypass tier approval |
| `journal` | SQLite audit log, undo artifacts | be optional (it isn't) |
| `cli` | Typer CLI + Textual TUI chat + daemon IPC | contain business logic |
| `evals` | Task catalog + harness + results | run on user machines |

### 4.3 Safety kernel (owner points 2, 4, 7)

**Action tiers** (classifier = static rules first, LLM reviewer second, both must agree):

| Tier | Example | Default policy |
|---|---|---|
| T0 read-only | `systemctl status`, `df`, read config | auto-run, journaled |
| T1 reversible, user-scope | write file (backup kept), install user package | auto-run w/ backup + undo |
| T2 system-level | `sudo` actions, service enable, config under `/etc` | **explicit user approval** + dry-run + config backup |
| T3 destructive/irreversible | disk ops, `rm -rf` outside workspace, auth changes, `curl \| sh` | **refused by default**; require typed interactive confirmation, never in daemon mode |

**Mechanisms** (all RESEARCH-R2-backed):
- Preflight: `bash -n` syntax check → shell-lint → static blocklist regexes (fork bombs, `mkfs`, `dd` to devices, recursive permission/ownership changes on system paths, …) → LLM safety review → dry-run where the tool supports it.
- Backups before every T1+ file edit (atomic temp-write + rename, original archived in journal).
- Optional system snapshots when available: snapper/timeshift (btrfs/LVM) detection; if absent, targeted backups only, and the agent says so.
- Guarded execution: per-step timeouts, output caps, no interactive prompts passed through silently, sudo per-command with visible escalation, never a root daemon.
- Undo: every T1/T2 step ships an undo script generated at plan time and tested where feasible.

### 4.4 Knowledge & anti-hallucination (points 3, 5, 6)

Layers, checked in order; the agent must cite which layer grounded each fact, else abstain:
1. **Live system introspection** — the only layer that cannot lie about *this* machine.
2. **Versioned built-in KB** — distro matrix, pitfalls, playbook prerequisites; shipped with the package, updated in releases, sourced from official docs (attribution in `knowledge/sources/`).
3. **Local docs** — man pages, `/usr/share/doc`, package manager metadata.
4. **Online official docs** (opt-in) — Arch Wiki, distro docs, upstream READMEs; fetched, cached, URL-attributed.

Plus: strict-schema tool calls; post-condition verification; bounded self-correction loop (R1: the verification loop is *the* differentiator of top agents).

### 4.5 Model strategy (point 9)

- **Engine (no LLM):** curated playbooks cover the high-frequency basics with near-deterministic reliability.
- **Local models** (Ollama/llama.cpp): privacy mode, offline, no cost — default for planning when installed.
- **API models:** highest capability for hard planning/vision GUI grounding; user brings keys; per-task router picks by complexity, sensitivity (T2/T3 tasks prefer local models or the strongest available review), and availability.
- Router is config-driven and swappable; provider interface is thin and tested with fakes (no network in unit tests).

### 4.6 GUI control (point 11) — reliability ladder

1. **Prefer non-GUI** equivalents when the outcome allows (the terminal path is the reliable path).
2. **AT-SPI 2** accessibility tree (X11 + Wayland): read UIs, activate widgets — structured, no pixel guessing.
3. **Compositor backends:** GNOME (DBus introspect/extension), KDE (KWin scripting), Hyprland (`hyprctl`), i3 (`i3-msg`), X11 generic (wmctrl/xdotool) — pattern proven by `agent-sh/computer-use-linux`.
4. **uinput input injection** (`ydotool` + `ydotoold`) for Wayland sessions — enabled by an explicit, consent-gated setup wizard (it requires uinput permissions; the wizard explains the security trade-off).
5. **Vision fallback:** screenshot → multimodal model → coordinate action, gated behind approval; used only when 2–4 cannot.

---

## 5. Tech Stack & Decisions

| Choice | Decision | Why (justification) |
|---|---|---|
| Language | **Python ≥3.10** | Only language with first-class AI-provider ecosystem + strong systems glue; present on all target distros (we vendor a portable runner for old ones) |
| Packaging | **pyproject.toml (PEP 621), src/ layout, uv for dev** | Modern standard; src/ layout prevents import accidents; reproducible dev envs |
| CLI/TUI | **M1: stdlib argparse (ADR-0005); Typer + Rich + Textual enter at M2 with the TUI chat** | Typed, composable; deps enter when their UX value exists |
| Schemas | **Pydantic v2** | Strict typed plans/steps → whole classes of model-syntax hallucination impossible at parse time |
| Storage | **SQLite** (journal, KB index) | Zero-config, ubiquitous, transactional |
| LLM access | Provider SDKs behind our own thin `Provider` interface | Swap local/API freely; unit-test with fakes |
| Shell validation | `bash -n`, **ShellCheck** (optional dep), internal static analyzer | R2 pipeline |
| GUI | python `atspi`/`pygi` via AT-SPI 2, DBus (gio), `ydotool` subprocess, screenshots via compositor portals | R3 ladder |
| Tests | **pytest** + distro-container matrix (Podman/Docker) + QEMU eval harness (M3+) | Adapters are *certified*, not assumed |
| Quality gates | **ruff** (lint+format), **mypy** (strict on `core/safety/execution`), pre-commit, **pip-audit**, CI on GitHub Actions | Owner guidelines 5–6, 15 |
| Docs | Markdown in-repo; ADRs for every significant decision | Auditability (owner guidelines 8, 10) |

Each dependency will get a justification note (guideline 16) in its ADR before entering `pyproject.toml`.

---

## 6. Proposed Repository Structure

```
J.A.V.R.I.S./
├── README.md                     # mission, quickstart, honest capability statement
├── CHANGELOG.md                  # incremental, detailed (owner guideline 4)
├── AGENT-EXPERIENCE.md           # development experiences/challenges log
├── LICENSE
├── pyproject.toml
├── .gitignore  ·  .pre-commit-config.yaml
├── docs/
│   ├── PLAN.md                   # this file
│   ├── RESEARCH.md               # evidence base
│   ├── GOVERNANCE.md             # binding 22-directive charter + standing orders
│   └── adr/                      # architecture decision records (ADR-0001…)
├── src/jarvis/
│   ├── core/ · system/ · execution/ · safety/ · planner/
│   ├── knowledge/ · providers/ · gui/ · journal/ · cli/ · config/
│   └── py.typed
├── knowledge/                    # versioned KB sources + distro matrix (data, attributed)
├── evals/
│   ├── catalog/                  # Tier-1 task definitions (versioned, execution-checked)
│   ├── harness/                  # container/VM runners
│   └── results/                  # published, auditable eval runs
├── tests/
│   ├── unit/ · integration/
└── .github/workflows/ci.yml      # lint · types · tests · distro matrix · eval smoke
```

---

## 7. Milestones, Deliverables, Acceptance Criteria

| M | Deliverable | Acceptance criteria (gate to next M) |
|---|---|---|
| **M0** Governance & skeleton | Plan/research/governance docs, CHANGELOG, AGENT-EXPERIENCE, ADR-0001/2, repo skeleton, CI wired, toolchain configs | Owner signs off plan; CI green on skeleton; **no unfinished files anywhere** |
| **M1** Kernel (no LLM) — **COMPLETE 2026-09-02** | SENSE + adapters + guarded execution + journal + tiers + 10 playbooks + CLI, 0 runtime deps (ADR-0005), safety policy (ADR-0006) | **Met & observed:** execution-eval 70/70 across debian:12/ubuntu:24.04/fedora/arch/alpine (run 33637847042); undo artifacts on every T1+ action (catalog-verified); kill-switch unit-tested (SIGTERM→interrupted, exit 130); 193 unit + 4 live tests; lint/types clean |
| **M2** LLM planner & router — **COMPLETE 2026-09-02** (ADR-0007) | Providers (Ollama + OpenAI-compatible, stdlib), strict-JSON planner behind M1 matchers, `run_plan` composite execution/undo, `ask`+`chat` REPL | **Met & observed:** planner eval 9/9 in CI (100% schema-validity over eval set incl. injection refusals); T2 approval default enforced (tests + tier gate); all provider branches fake-tested; 231 unit + 4 live tests; gates clean. Textual TUI deliberately deferred (ADR-0007) |
| **M3** Safety hardening — **COMPLETE 2026-09-02** (ADR-0008) | Snapshot preflight (honest degradation, journaled), file.append with real backup/undo, blocklist suite expansion, dynamic tier elevation, fault gate in CI, REPORT-m3.md published | **Met & observed:** fault suite 35 vectors / 0 escapes (incl. a real tee→/etc/shadow gap found & fixed); rollback byte-identical restore proven on real files; first consolidated eval report committed |
| **M4** Knowledge system — **COMPLETE 2026-09-02** (ADR-0009) | Cited KB v1 (12 facts; torvalds/linux kernel-doc citations), local verifiers, cite-or-abstain `jarvis explain`/`facts`, allowlisted online verification (GitHub Contents API) | **Met & observed:** grounding eval 12/12 with **0 unverifiable claims** (incl. live torvalds/linux upstream checks); uncited facts structurally impossible (store refuses them); gates clean |
| **M5** GUI control — **COMPLETE 2026-09-02** (ADR-0010; Wayland-session wizard verification open — see REPORT-m5 §4) | Capability matrix + consent-gated injection; backends: X11 (wmctrl/xdotool/scrot), i3/sway IPC, Hyprland, KDE, GNOME; AT-SPI optional; ydotool wizard; vision via local Ollama (abstains) | **X11 lane met & observed:** 15-task catalog on Xvfb+i3 through the real CLI in CI, gate ≥98% ⇒ 15/15; headless subset 4/4. **Wayland sessions: not verifiable in project infra — honestly documented** |
| **M6** Production hardening & packaging — **COMPLETE 2026-09-02** (ADR-0011) | wheel+sdist `jarvis-agent` (pipx path), .deb (dpkg-verified), .rpm + AUR PKGBUILD (distro-container verified), INSTALL.md + RELEASING.md, telemetry **none** (owner-reserved), v1.0.0 on branch + PR opened (never merged by agent) | **Met & observed:** packaging matrix green on all 5 Tier-1 distros (native artifacts, KB smoke); full CI matrix green; CHANGELOG complete 0.0.1→1.0.0; P0/P1: none open (KB-path P1 found & fixed this milestone) |
| **M7** Real-machine readiness — **COMPLETE 2026-09-02** | GUI focus TOCTOU guard; `safety-check` self-test battery (sentinel runner); `do --preview` + blast radius; auto-rollback (`--auto-rollback`); cautious mode (`cautious`/`--cautious-ok`); live-LLM injection corpus + weekly real-model CI lane; SAFE-TESTING.md ladder | **Met & observed:** battery 7/7 (execution-blocked sentinel); cautious gate live-verified; auto-rollback byte-identical restore; all gates green (352+1 tests) |
| **M8** Adaptive initiative (ADR-0012) — **M8a COMPLETE 2026-09-03**; M8b context store, M8c charters, M8d growth loop planned | M8a: evidence-backed `jarvis suggest` (undo-orphans, stale index, cited pitfalls) + feedback ledger + `context show`; engine is read-only by construction | **M8a met & observed:** suggestions cite journal/KB evidence; suppression works; nothing executes without the user's own command; M8b–M8d remain open by design |
| **M9** Architecture evolution (ADR-0013) — **COMPLETE & SHIPPED: M9a MCP server (1.3.0) · M9c integrity (1.4.0) · M9d charters (1.5.0) · M9e API-first GUI + M9b skill packs (1.6.0)** |
| **M8b/M8d** Adaptive initiative completion (ADR-0012) — **COMPLETE & SHIPPED in 1.7.0**: context store (preferences, house rules, routines, consent-gated forget — all inside the M9c tamper evidence) + supervised growth loop (drafts validated by the real KB/skill stores; promotion owner-only) |
| **Front-end contract** (owner-directed 2026-09-03) — **SHIPPED in 1.8.0**: `jarvis mcp describe` publishes `javris-frontend/1` (transport, tools + consent semantics, state mapping onto J.A.V.R.I.S.-GUI's AssistantState); conformance-tested against the live server; `docs/integration/JAVRIS-GUI.md` is the wiring document. The GUI's QProcess client lives in the GUI repo against this contract | M9a MCP server (stdlib JSON-RPC/stdio; kernel tools only) · M9c memory/config integrity (drift baseline, `doctor`, write-time scanning) · M9b verified skill packs (declarative, eval-gated, provenance — never runtime-LLM-read) · M9d charters (circuit-broken standing orders) · M9e API-first GUI actions | Design accepted into PLAN; acceptance per phase defined in ADR-0013; invariant: new capability enters through the kernel or not at all |
| **M10** AI failure semantics (ADR-0014, owner-directed 2026-09-04) — **SHIPPED in 1.9.0**: what the agent does when the AI fails, how unknown situations are processed, how it runs with no AI at all, and a proper (validated, breaker-tracked, grounded) AI integration | Persisted per-provider circuit breaker (closed/open/half-open, `.state` outside integrity scope); typed failure taxonomy in outcomes + `status`; schema-constrained planner wire + unchanged strict validation; grounded AI answers on KB misses (cite-only-from-evidence, structural abstention); unknown requests → nearest intents + journal record + teaching hint; `--no-ai`/`JARVIS_NO_AI=1` operator kill switch; `doctor` AI state informational-only | Research: `docs/RESEARCH-ai-resilience-2026.md`; acceptance: AI-less suite green end to end; breaker prevents retry storms across processes; model still never executes, consents, or widens authority (kernel remains the only door) |
| **M11** Learned intent recall (ADR-0015, owner-directed 2026-09-04) — **SHIPPED in 1.10.0**: a purpose-built neural classifier (proposals-only recall widener after engine-miss + planner-decline; never a fallback executor) | Tiny MLP (256-dim hashed n-grams → 48 ReLU → softmax over 12 playbook families + `unknown`); ~13K params as package data; stdlib inference; seeded gated trainer in-repo (gates on rounded shipped weights); suggestion = extractor + real-matcher-revalidated text the user types; `--no-ai` honored; MCP untouched | Research: `docs/RESEARCH-tiny-intent-models-2026.md`; acceptance: hand-written eval sets independent of the training generator (top-1 ≥ 0.9, top-3 = 1.0, OOD abstain ≥ 0.85), every suggestion engine-legal, AI-less suite green; limitations documented (synthetic corpus distribution, English-only) |

| **R-series** (2026 deep research → owner-directed "continue" sequence) — **COMPLETE v1.12.0–v1.18.0**: hybrid residency (ADR-0018, 1.12.0) · voice front-end (ADR-0019, 1.13.0) · owner-taught file memory (ADR-0020, 1.14.0) · scheduled propose-only briefings (ADR-0021, 1.15.0) · guarded desktop awareness, read-only AT-SPI tier (ADR-0022, 1.16.0) · full-vocabulary intent retrain (ADR-0023, 1.17.0) · synthesis-over-sources digest `sys.digest` (ADR-0024, 1.18.0) | Catalog 12 → 57 playbooks; suite 794 passed + 2 honest skips; 22 draft releases queued for owner review | Research: `docs/RESEARCH-jarvis-agent-linux-2026.md`; acceptance per ADR-0018…0024; guideline-compliance table in each milestone report; **nothing merged, `main` untouched** |

---

## 8. Risk Register & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Open-world success expectations exceed technology reality (R1) | High | Trust loss | §3 scoped-metric contract; publish eval results; agent declines what it cannot verify |
| Wayland fragmentation breaks GUI features on some compositors (R3) | High | Medium | Reliability ladder + per-compositor backends + honest capability matrix shown to user at setup |
| Model produces a destructive command that passes review | Medium | **Critical** | Dual reviewer (static+LLM), tier gate, dry-run, sandbox rehearsal for T2/T3, snapshots, undo — defense in depth; T3 refused by default |
| Sudo misuse / privilege creep | Medium | Critical | Per-command visible sudo, no root daemon, sudoers untouched, T2 approval default-on |
| Distro long tail (Gentoo/Nix/Void…) | High | Medium | Adapter interface public; Tier-1 certified, others "best-effort, clearly labeled"; community PRs (owner merges) |
| API keys/cost/privacy concerns | Medium | Medium | Local-first default, keys via env/config, no telemetry without explicit opt-in |
| Agent destabilizes user session (GUI) | Low | Medium | Input-injection off until wizard consent; GUI actions are T1 minimum; screenshots are read-only |
| Scope creep into everything-agent | Medium | Schedule | §1 explicit out-of-scope list; changes require plan amendment + owner approval |

---

## 9. Changelog & Experience Workflow (owner guideline 4)

- **CHANGELOG.md** — Keep-a-Changelog format; every change-set gets an entry (Added/Changed/Fixed/Safety/evals) with rationale links to ADRs. Written in the same commit-set as the change, never retroactively.
- **AGENT-EXPERIENCE.md** — running log after each milestone: what was hard, what surprised us, what we'd do differently, evidence encountered (with sources). Includes honest incident records (e.g., documentation defects and their repair).
- **ADR discipline** — any decision that is expensive to reverse (deps, safety model, protocol, storage) requires `docs/adr/NNNN-*.md` with context/options/decision/consequences.

## 10. Working Agreement

- **Binding charter:** [`docs/GOVERNANCE.md`](GOVERNANCE.md) — the owner's 22 engineering directives (including: never fabricate, inspect before modifying, minimal justified changes, security-first, dependency discipline, failure awareness, no scope creep, human authority, verification honesty, continuous self-review) plus standing orders. It supersedes convenience everywhere.
- All work on session branch `arena/01a06229-j-a-v-r-i-s`; **the agent never merges anything** (owner standing order) — PRs are opened for owner review only.
- Quality gates (§5) must pass before any commit is offered; no placeholder/hypothetical code ever lands (guideline 1).
- Owner confirmation required: at plan sign-off, at each milestone acceptance gate, and for any scope change (guideline 20).
- Milestone completion reports include a mandatory **"Verified / Not verified / Limitations"** section (guideline 21).

---

## 11. Minimal End-to-End Starter Outline (M1 first slice — *described, not yet implemented*)

Vertical slice to prove the pipeline with zero LLM dependency:

1. `jarvis status` — SENSE: prints machine fingerprint (distro, init, session, package backend) from adapters. *Accept: correct on all Tier-1 containers.*
2. `jarvis do "install htop"` — GROUND: capability registry resolves package name against the real repos; PLAN: matches `pkg.install` playbook; APPROVE: T1 gate (backup + undo prepared); EXECUTE: guarded shell via detected backend (apt/dnf/pacman/zypper/apk); VERIFY: `command -v htop` + package-db check; JOURNAL: full record + undo.
3. `jarvis undo <task-id>` — replays the undo artifact.

This slice forces every module boundary (§4.2) to exist and be tested before any LLM enters the codebase — the correct production order.

---

## 12. References

Primary evidence: `docs/RESEARCH.md`. ADRs: `docs/adr/`. Benchmark sources: OSWorld leaderboard (codesota.com), OSAgent result (theagi.company), OSWorld 2.0 (arXiv:2606.29537), Wayland/input findings (linuxvox.com, r/linux, github.com/agent-sh/computer-use-linux), copilot-safety practice (linuxbash.sh, devopsaitoolkit.com).

---

## 13. Decisions Requiring Owner Sign-off (blocking M0 acceptance)

1. ~~**Name ruling**~~ — **RESOLVED (2026-09-02):** canonical name **JARVIS** — *"Just A Rather Very Intelligent System"*; display form `JARVIS`; Python package & CLI `jarvis`; GitHub repo name unchanged (renaming is an owner decision).
2. ~~**98% metric**~~ — **RESOLVED (2026-09-02, owner-delegated):** scoped catalog definition adopted → [ADR-0001](adr/0001-scoped-success-metric.md).
3. ~~**v1 interaction surface**~~ — **RESOLVED (2026-09-02, owner-delegated):** CLI-first + TUI chat → [ADR-0002](adr/0002-cli-first-surface.md).
4. ~~**Model posture**~~ — **RESOLVED (2026-09-02, owner-delegated):** hybrid router, local-first default → [ADR-0003](adr/0003-hybrid-router-local-first.md).
5. ~~**M0 commit authorization**~~ — **RESOLVED (2026-09-02):** owner delegated; M0 (docs + skeleton + CI) committed to the session working branch. No merges, ever (standing order).
6. **LICENSE selection** — **OPEN (owner decision, legal authority):** recommend MIT or Apache-2.0. `pyproject.toml` intentionally omits the license field until ruled; no placeholder license text is shipped.
