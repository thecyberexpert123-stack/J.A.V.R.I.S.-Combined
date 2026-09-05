# JARVIS

> **J**ust **A** **R**ather **V**ery **I**ntelligent **S**ystem — an AI automation agent for Linux.
> Plans, executes, and **verifies** real tasks on any Tier-1 distribution — with a safety kernel,
> an audit journal, and no blind execution. Ever.
>
> *(Repository keeps its original name `J.A.V.R.I.S.`; the canonical project name is JARVIS per owner ruling, 2026-09-02.)*

**Status: `v1.20.0` — M0–M11 complete + the 2026 deep-research roadmap fully landed
(voice ADR-0019 · memory ADR-0020 · briefings ADR-0021 · guarded desktop awareness ADR-0022 ·
intent retrain ADR-0023 · synthesis digest ADR-0024) + the hybrid AI upgrade (ADR-0025) + the
unknown-app answer (ADR-0026)**: deterministic engine + a dual-path (local/API) LLM planner
with derived full-catalog vocabulary, disclosed failover, and breaker-tracked failure
semantics + a proposals-only neural intent classifier + safety kernel + cited knowledge + MCP
surface + verified skill packs + charters + integrity doctor + GUI control + **58
deterministic playbooks** + guarded AT-SPI actions inside unknown apps + **owner-taught app
packs** (`jarvis app-skill wizard`) + an opt-in loopback doorway + push-to-talk voice with
sentence-boundary speech + plain-file memory + propose-only briefings + a fail-closed
read-only AT-SPI tier, packaged (wheel/deb/rpm/AUR) and install-verified on all Tier-1
distros in CI. Review candidates `v1.0.0-rc1` … `v1.20.0-rc1` await the owner's release
decisions. Reports: `evals/results/`. See `INSTALL.md`.**
Plan accepted 2026-09-02; open decisions recorded in [`docs/PLAN.md` §13](docs/PLAN.md).

| | |
|---|---|
| Plan & architecture | [`docs/PLAN.md`](docs/PLAN.md) |
| Research & evidence | [`docs/RESEARCH.md`](docs/RESEARCH.md) |
| 2026 deep research & roadmap | [`docs/RESEARCH-jarvis-agent-linux-2026.md`](docs/RESEARCH-jarvis-agent-linux-2026.md) |
| Change log | [`CHANGELOG.md`](CHANGELOG.md) |
| Development experience log | [`AGENT-EXPERIENCE.md`](AGENT-EXPERIENCE.md) |

## What it will do

- Automate Linux tasks from natural language: packages, services, files, configuration, networking, scheduled jobs, and desktop (GUI) operations.
- Run on Tier-1 distributions (Ubuntu/Debian, Fedora, Arch, openSUSE, Alpine) through a distro-abstraction layer; more via community adapters.
- Use a deterministic playbook engine for common tasks and local/API LLMs for open-ended planning — routed per task by complexity and sensitivity.
- Never act blindly: every action is classified by safety tier, verified against the real machine before execution, gated by approval policy, checked after execution, and fully journaled with an undo path.

## Honest capability statement

Open-world task success at "98%" is not promised by anyone honestly — the best published
computer-use agents reach ~63–76% on the OSWorld benchmark. This project's contract is different and
verifiable: **≥98% execution-verified success on its published, versioned task catalog**, with
graceful refusal or escalation outside it, and all evaluation results auditable in the open.
Details: [`docs/PLAN.md` §3](docs/PLAN.md).

## Quick start (from a checkout)

```bash
pip install .                      # zero runtime dependencies
jarvis status                      # what JARVIS sees on this machine
jarvis do --dry-run "install htop" # deterministic engine: exact plan, nothing run
jarvis do "install htop"           # execute with journal + undo artifact
jarvis undo <task-id>              # reverse a task (see: jarvis tasks)
jarvis ask "set up monitoring"     # engine first; LLM planner for the rest
jarvis chat                        # interactive REPL
jarvis explain "what is ostype"    # cited answer + on-machine verification
jarvis facts                       # browse the knowledge base (12 cited facts)
jarvis safety-check                # prove the guards are alive on THIS machine
jarvis do --preview "upgrade the system"   # plan + blast radius, nothing runs
jarvis cautious on                 # early-days guard for a fresh machine
jarvis suggest                     # evidence-backed suggestions (read-only; nothing runs)
jarvis system digest              # cited, computed health digest (no LLM; ADR-0024)
```

> **Before a machine you care about:** read [`docs/SAFE-TESTING.md`](docs/SAFE-TESTING.md) —
> the honest risk map and a 4-rung ladder for building trust.

Knowledge answers are **cite-or-abstain**: every answer names its sources
(kernel docs in [`torvalds/linux`](https://github.com/torvalds/linux), man pages,
distro docs) and whether the fact was verified *on this machine*; anything
outside the knowledge base is refused, never guessed (ADR-0009). With
`JARVIS_ONLINE_DOCS=1`, JARVIS additionally verifies its kernel-doc citations
against `torvalds/linux` master on demand (CI does this on every push).

GUI control is a **capability matrix**, not a promise: `jarvis gui status` reports
exactly what this desktop supports (X11 · i3/sway · Hyprland · KDE · GNOME; AT-SPI
when present). Keystroke injection always shows you the focused window it will type
into and asks for consent — and typed text is never written to the journal.
`jarvis gui wizard` checks ydotool readiness on Wayland with distro-specific fixes.

Planning backends (ADR-0003, ADR-0025): local **Ollama** is auto-detected
(`OLLAMA_HOST`, `JARVIS_LOCAL_MODEL`); an **OpenAI-compatible** endpoint is
opt-in (`JARVIS_OPENAI_API_KEY`, `JARVIS_OPENAI_BASE_URL`,
`JARVIS_OPENAI_MODEL`); `JARVIS_REMOTE_LLM=0` disables the remote path. Both
paths are reliable: if the local backend is down or its breaker has opened, a
configured remote is tried (**failover is never silent** — every answer
discloses its backend: `[jarvis] served by <mode> (<model>)`, plus
`jarvis ai status` for both paths' liveness, models, and breakers). The
planner's vocabulary is **derived from the live catalog** — one engine-legal
example phrase per playbook, pinned by tests — so the model can propose any
of the 57 playbooks and can never be taught a phrasing the engine would
refuse. Chat feeds recent turns and owner memory to the planner as delimited
BACKGROUND CONTEXT — reference only, never instructions. The LLM never issues
commands — it proposes intents that must pass the same validators as the
deterministic engine (ADR-0007).

**Model guidance (researched, not coupled — ADR-0025 D5):** the local SLM tier
is agentic now; good defaults are Llama 3.1 8B-class (≈89% tool-calling
accuracy), Llama 3.2 3B on small machines, or a Qwen 3.5-class 9B if you have
8 GB VRAM. Ollama wins on ergonomics; llama.cpp on footprint. Set
`JARVIS_LOCAL_MODEL=<name>` after `ollama pull <name>`; remote models via
`JARVIS_OPENAI_MODEL`.

**AI failure semantics (ADR-0014):** the AI path is optional, breaker-tracked,
and honest. A persistently failing model trips a per-provider circuit breaker
(`status` shows it; `state_dir/ai/breaker.state`), failures are classified
(`unreachable/timeout/http/malformed/key-missing/breaker-open`), planner
output is schema-constrained *and* strictly validated, `explain` falls back
from KB cite-or-abstain to a grounded AI answer only when citations resolve
to real KB facts, unknown requests return nearest-known intents plus a
journal record for owner review, and `--no-ai` (or `JARVIS_NO_AI=1`) disables
every model path in one switch — the agent remains fully usable without any
AI.

**Learned intent recall (ADR-0015, ADR-0023):** a tiny purpose-built neural
network (shipped weights, stdlib inference) ranks the playbook vocabulary for
loosely-phrased requests when the engine and the LLM planner have both
declined. The vocabulary is **derived from the live catalog** — the trainer
labels are `sorted(PLAYBOOKS ids) + unknown`, so all 57 playbooks are rankable
and a test makes staleness loud. It is proposals-only by construction:
reconstruction extractors stay limited to the vetted families (paths are never
reconstructed), suggestions must re-pass the real matchers and are printed for
you to type (`jarvis do …`), never executed; `--no-ai` switches it off.
Retrain any time: `python training/train_intent.py` (gated, deterministic,
byte-reproducible).

## Playbook breadth (ADR-0016)

`jarvis playbooks` lists **57 deterministic playbooks** (was 12). Breadth follows one rule: every
new command enters through a **guarded family** — a pinned binary, a fixed flag prefix, and
argument slots validated at match time (a user flag such as `-rf` is a refusal that makes the
intent unmatchable, never a sanitize; shell metacharacters are banned outright). Families:

- **Read-only inspection (T0):** `fs.list/read/head/tail/count/stat/file_type/which/disk_usage/find/search/disk_free`,
  `sys.memory/processes/uptime/date/hostname/cpus/pci/usb/blocks/sockets/network/routes/journal/kernel_log/users/login_history/env/identity/checksum`,
  `net.ping` (bounded: 4 packets, 4 s), `net.dns`, plus the synthesis playbook `sys.digest` (below).
- **File management (T1, root-gated where policy demands):** `fs.mkdir/touch/copy/move/remove/link`
  — protected paths refused, undo planned before execution, deletion disclosed as irreversible.
- **Process & service control (T2):** `svc.stop/restart/disable` (systemd-gated),
  `proc.kill` (numeric pid), `proc.kill_name` (exact name, no patterns).

Some things are **deliberately absent** and documented as such in ADR-0016: `dd`, `mkfs`,
partition editors, `shutdown`/`reboot`, downloads-and-pipes (`curl | sh`), stream editing
(`sed -i`), and permission changes (`chmod`/`chown`) have no playbook at all — they are
unmatchable by design, and tests prove it. `jarvis playbooks` shows the full catalog with tiers.

Outside those families sits one deliberate addition, `sys.digest` (ADR-0024):
`system digest` / `health check` / `analyze my system` runs three existing read-only sources
(`df -h`, `free -h`, `uptime`) and **computes** a cited health digest with disclosed
thresholds — no LLM in the path, and an unreadable source is disclosed, never guessed.

## Voice (ADR-0019)

Push-to-talk, same kernel, zero new dependencies:

```bash
jarvis voice doctor          # what can this machine do right now (honest)
jarvis voice ask             # record (arecord) -> whisper STT -> the safety kernel -> piper TTS
jarvis voice ask --wav x.wav # transcribe a file instead of recording
jarvis voice say "all done"  # speak a short text
```

Replies are spoken **sentence-by-sentence** (ADR-0025 D4): playback of the
first sentence starts after one sentence's synthesis, not the whole reply's —
the latency lives in TTS, and pipelining is where the research says the win
is.

Voice is **presentation, never authority**: a spoken request follows the identical
match → plan → approve → execute → verify path; **T2 is not voice-consentable** — the spoken
refusal tells you to type it with `--yes`. Requires standard binaries (`whisper-cli`-class STT
with `$JARVIS_STT_MODEL`, `piper` with `$JARVIS_TTS_MODEL`, `arecord`, a player); `doctor`
reports exactly what is missing. Hands-free wake word is parked by design (ADR-0019 D3).

## Memory (ADR-0020)

Plain files you teach, the planner may read, anyone can purge:

```bash
jarvis memory remember "deploy user is admin on the ops box"
jarvis memory list                  # newest first, with provenance
jarvis memory show <id> / forget <id> / forget --all
```

Writes are hygiene-checked and **prompt-injection-scanned** (instruction-like text is refused,
never stored); the LLM planner sees the newest ≤10 entries as a delimited *background context*
block in its system prompt — never as instructions, never a bypass: every proposed step still
re-validates through the real playbooks. No database, no embeddings; one file per memory under
the state dir. Agent-initiated capture is parked (ADR-0020 D2).

## Scheduled briefings (ADR-0021)

Level-2 proactivity, propose-only — the agent may knock, never act on its own:

```bash
jarvis brief                  # compose + decide + deliver (prints "nothing to report" or the briefing)
jarvis brief status           # runs, notified, silenced, silence rate, feedback counts
jarvis brief accept|dismiss <id>   # feedback recorded (policy learning parked)
jarvis brief install [--on daily|weekly]   # opt-in systemd --user timer
jarvis brief uninstall
```

Briefings are **computed from local state only** (journal failures, evidence-backed
suggestions, unmapped requests, disk pressure via `statvfs` — zero subprocesses) and never
execute commands. The v1 policy is deterministic and inspectable; silence is a first-class,
ledgered outcome with a reason. `--quiet` (timer mode) delivers via `briefings/latest.md` and
an optional desktop notification.

## Guarded desktop awareness (ADR-0022)

The read-only tier of the AT-SPI family — JARVIS can see the desktop's published
accessibility tree, inside fail-closed walls:

```bash
jarvis desktop read     # guarded outline; blocked apps / password fields / sensitive names
jarvis desktop status   # availability + content-free audit totals
```

Three walls, in order: blocked applications (password managers, keyrings, polkit/askpass,
terminals) are never read at all; `password text` roles are withheld **before their name is
read**; sensitive names are redacted before display. Every read is audited content-free
(counts only — titles are never persisted), and the GUI service inherits the same walls:
a blocked app cannot be listed, focused, or typed into. On-demand only — no scheduled or
ambient reads; input injection stays parked for its own ADR.

## Unknown apps & owner-taught packs (ADR-0026)

When JARVIS must control an application no playbook knows, it climbs a fixed ladder —
launch the app → guarded AT-SPI read → invoke the app's **own published actions**
(`queryAction`/`doAction`) → write text through EditableText → synthetic keys last — and
honestly reports which rung the app supports. Blocked applications and password fields are
walled before any read, at plan time and again at execution time. Vision, synthetic clicks,
and portal input are never used (each parked behind its own future ADR).

Teaching JARVIS a new app is data, not code — a ≤20-line JSON pack, compiled through the
kernel:

```json
{
  "schema": "app-skill/1",
  "id": "gedit-save",
  "description": "type into gedit, save via keyboard, click Save",
  "app": { "launch": ["gedit", "/home/owner/notes.txt"] },
  "steps": [
    { "type":   { "app": "gedit", "role": "text", "name": "Find", "text": "hello" } },
    { "key":    "ctrl-s" },
    { "action": { "app": "gedit", "role": "push button", "name": "Save", "action": "click" } }
  ],
  "phrases": ["save my gedit file"]
}
```

```bash
jarvis app-skill wizard --file gedit-save.json  # validate-by-construction + sha256 receipt
jarvis app-skill list | show <id> | remove <id>
jarvis do "save my gedit file"                  # one consented T2 task, plan displayed
```

No field can carry a command: launch arguments reject shell metacharacters, every value is
length-bounded, and packs install with a sha256 receipt — any later drift makes the pack
invisible (fail-closed), never half-run.

## Hybrid residency (ADR-0018)

By default **nothing runs unless you run it**. If you want front-ends (the GUI, scripts) to
reach JARVIS any time after login without starting it yourself, opt in:

```bash
jarvis serve install [--with-gui]   # systemd --user unit (+ GUI autostart if installed)
jarvis serve                        # or run the doorway in the foreground
jarvis serve status / uninstall     # inspect / return to pure on-demand
```

The doorway is **loopback-only and token-authenticated** (token `0600` in the state dir, never
logged). It serves exactly the six MCP tools with **identical consent semantics**: T2 still
needs a per-call `allow: true`, T3 is always refused, there is no persistent yes and no
exec passthrough — a doorway, never an actor. Packaging never enables it; `uninstall` removes
every trace.

## MCP surface (ADR-0013 M9a)

`jarvis mcp serve` speaks the Model Context Protocol — newline-delimited JSON-RPC 2.0 on stdio, stdlib-only (no SDK). An MCP client is just another front-end to the same kernel:

- tools: `jarvis_status`, `jarvis_facts`, `jarvis_explain`, `jarvis_suggest`, `jarvis_preview`, `jarvis_do`
- resources: `kb://facts`, `journal://tasks`
- consent is unchanged: T2 actions need an explicit per-call `"allow": true`; T3 is refused; there is no free-form-exec passthrough tool

Smoke test:

```console
$ printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26"}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n' | jarvis mcp serve
```

## Integrity (ADR-0013 M9c)

Policy-relevant state — KB files, playbooks registry, safety kernel, execution and ingress code, cautious flag — is hashed into a machine-local baseline:

```console
$ jarvis doctor --write-baseline   # once, after reviewing the state
$ jarvis doctor                    # verify: 0 clean · 1 drift · 2 no baseline
$ jarvis doctor --canaries         # trace suggestion-canary leak paths
```

`jarvis status` shows a live integrity line. Stored feedback is write-time-scanned for injection patterns and hash-chained; `jarvis doctor` reports tampering with it. Honest limitation: a tripwire against invisible, gradual modification — not a cryptographic anchor.

## Charters (ADR-0013 M9d)

Recurring automation as a circuit-broken contract — one pre-authorized request, played through the same kernel on a schedule:

```console
$ jarvis --yes charter install nightly-cache \
    --request "update the package cache" \
    --playbook pkg.cache.refresh --tier-ceiling 1 \
    --monthly-runs 30 --on-calendar daily
$ jarvis charter run nightly-cache      # one firing (what the timer executes)
$ jarvis charter list / pause / resume / revoke
```

Breakers: failure **pauses** the charter; monthly run budget and per-run step caps; hard tier ceiling (T3 never charterable); systemd `TimeoutStartSec` wall-clock bound; semantic drift (a request that stops matching its allowlist) pauses instead of improvising; contract bytes are inside the `jarvis doctor` integrity scope. Without a systemd user session, scheduling degrades honestly to manual `charter run` invocations.

## Skill packs (ADR-0013 M9b)

A skill pack adds new phrasings for an **existing** playbook — never new commands, never model-read instructions:

```json
{
  "schema": 1,
  "id": "refresh-all",
  "description": "colloquial phrasings for refreshing the package index",
  "match": "^(?:refresh|sync)\s+(?:everything|all)$",
  "playbook": "pkg.cache.refresh",
  "params": {},
  "evals": [{"request": "refresh everything"}],
  "provenance": {"source": "owner", "sha256": "<hex>"}
}
```

```console
$ jarvis --yes skill install refresh-all.skill.json   # evals run as real dry-runs
$ jarvis do --dry-run "refresh everything"            # plans through the kernel
```

Packs are receipt-pinned (sha256) and live inside the `jarvis doctor` integrity scope; drifted packs are skipped fail-closed. GUI actions disclose their route (`api` / `wm` / `injection`) in `jarvis gui status`; `type_text` prefers the AT-SPI EditableText API over synthetic keystrokes (ADR-0013 M9e).

## Context & growth (ADR-0012 M8b/M8d)

```console
$ jarvis context prefer suppress.undo 1        # tune suggestions, never authority
$ jarvis context rule never touch docker       # house rules suppress matching suggestions
$ jarvis context routines                      # journal-inferred patterns (never persisted)
$ jarvis context forget                        # delete everything (consent-gated)
$ jarvis grow fact --id t.f --topic t --claim "..." --pattern q \
    --sources '[{"kind":"docs","ref":"..."}]'  # drafts validated by the real KB store
$ jarvis grow export t.f --out out/            # artifact + owner commands (owner merges)
```

Context is local, inspectable (`context show`), deletable, and tamper-evident (`jarvis doctor` verifies its hash chains). Growth proposals are inert data; the kernel, policy, and shipped knowledge stay outside JARVIS's write scope — promotion runs through owner-reviewed PRs and consented installs only.

## Front-ends (J.A.V.R.I.S.-GUI)

Native HUD front-end (owner's [J.A.V.R.I.S.-GUI](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.-GUI) project) wires to this kernel over the MCP stdio surface:

```console
$ jarvis mcp describe    # machine-readable front-end contract (javris-frontend/1)
```

A front-end is another untrusted-ingress surface: it renders, it never widens authority — T2 actions need the owner's explicit per-call consent in the UI; `docs/integration/JAVRIS-GUI.md` is the wiring contract, and CI asserts the published contract against live server behavior.

## Status of this repository

Production implementation, in active owner-directed development on the session branch:
M0–M11 complete through v1.11.0; then the 2026 deep research (45 sources) produced a
charter-compliant roadmap whose items are now all landed — voice (v1.13.0), file memory
(v1.14.0), scheduled briefings (v1.15.0), guarded desktop awareness (v1.16.0), full-vocabulary
intent retrain (v1.17.0), synthesis digest (v1.18.0), the hybrid AI upgrade (v1.19.0), and
the unknown-app answer with owner-taught app packs (v1.20.0). Milestone history and
acceptance criteria: [`docs/PLAN.md` §7](docs/PLAN.md). Review candidates `v1.0.0-rc1` …
`v1.20.0-rc1` (24 drafts) await the owner's publishing decisions; nothing is merged and
`main` is untouched — the owner merge policy is absolute.
