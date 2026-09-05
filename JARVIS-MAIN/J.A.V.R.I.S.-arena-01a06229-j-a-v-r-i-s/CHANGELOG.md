# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning targets [SemVer](https://semver.org/).

> Merge policy: the development agent **never merges** anything into `main`. All entries below land on the session working branch and reach `main` only through owner-approved merges.

## Errata — 2026-09-03

Suite-count claims were re-verified by replaying each milestone's exact commit in an
isolated worktree (era-correct package metadata, `RUN_LIVE=1`, no local LLM; skip
identities confirmed via `-rs`). Originals preserved here for transparency; numbers
below each entry were corrected in place.

- **0.2.0 / 0.3.0:** the quoted "unit" totals (193 / 231) already included the 4 opt-in
  live tests; true split is 189+4 / 227+4 (verified by `--collect-only` sums at
  `4178777` / `7720176`). Totals were right; the split labels double-counted.
- **0.4.0:** "297 unit + 6 live" → observed at `d2e40f4`: **301 collected = 294 unit +
  7 live-marked (live: 6 pass + 1 skip)**.
- **0.5.0:** "+38 tests / 339 passed + 1 honest skip; live 5 pass + 1 skip" → observed
  at `6d53a63`: **+40 tests; 340 passed + 1 skip (341 collected); live-marked set is 10
  (9 pass + 1 skip)**. The "live 5" phrasing was stale from the 0.4.0 era.
- **1.1.0:** "+18 tests / 352 passed + 1 honest skip" → observed at `a08ba8f`: **+17
  tests; 356 passed + 2 skipped** (both model-availability skips: `live_llm` gate and
  the Ollama smoke test).
- Verified exact, no change: 1.0.0 gates (REPORT-m6 §8: 340 passed + 1 skip at
  `1f9f430`), 1.2.0 (370 passed + 2 skips at `2c64904`), 1.2.1 (372 passed + 2 skips).
- `evals/results/REPORT-m6.md` §4 cited packaging run `33653104688` — a transcription
  slip (HTTP 404). Actual run at `1f9f430`: **33653349705** (build + 5/5 distro jobs
  success), CI run `33653349731` also green. Corrected in place.

## [Unreleased]

### Added
- **Documentation sweep** (owner-directed, docs-only — ships without a tag per the docs-only
  convention): README repaired (a pre-existing mid-sentence paragraph split around the
  cite-or-abstain/GUI text; the stale "Planning phase (M0)" closer replaced with the real
  status; the F6 digest paragraph that had silently failed to land in 1.18.0 is actually
  present now); `AGENT-EXPERIENCE.md` brought current through v1.18.0; `docs/PLAN.md` amended
  with dated annotations only (voice/classifier scope amendments; the R-series milestone row);
  `docs/RELEASING.md` records the docs-only-no-tag convention and the 22-draft review queue.
  No code changes.
- **Deep research** (`docs/RESEARCH-jarvis-agent-linux-2026.md`, owner-directed): how to build a
  JARVIS-class agent for Linux. Decomposes the MCU target into 12 film-evidenced capabilities,
  surveys the 2026 state of the art per subsystem (memory; planning/tool use; Linux computer use
  via AT-SPI; proactivity taxonomy; agent security — injection unsolved, containment durable;
  local inference and the voice stack), benchmarks the gap against v1.12.0, and proposes a
  charter-compliant roadmap (voice front-end, provenance-tagged file memory, Level-2
  propose-only proactivity, AT-SPI guarded family) with deliberate divergences documented.
  45 sources, tier-labeled. Docs-only.
- **ADR-0017 — Dragon Fly AI (DFA) alignment** (`docs/adr/0017-dfa-alignment.md`): the owner's
  self-derived agent architecture, assessed layer-by-layer against the source at `1b5d8eb`.
  Verdict: JARVIS already implements DFA's four layers (reasoning → `providers/`, capabilities →
  playbooks, control → approval/tier pipeline, action → argv-only execution), so DFA is adopted
  as the descriptive frame and contributor vocabulary — no code change. One delta adopted as an
  owner-gated v1.12.0 proposal (per-playbook capability manifests); one delta deliberately
  diverged and documented (DFA's autonomous observe-iterate loop contradicts the "no blind
  execution" charter; JARVIS requires a human per request). Docs-only; no behavior change.

## [1.20.0] - 2026-09-05 — the unknown-app answer: guarded AT-SPI actions + owner-taught app packs (ADR-0026)

Owner-directed deep-research milestone: *"When JARVIS will try to control and use another APP,
which the playbook does not know — how will it do it, and how will I easily do it / set that up
later?"* Two deliverables, both landed: (a) a rung-ladder the engine walks **inside any
accessible application it has never been taught**, and (b) a data-only teaching workflow —
`app-skill/1` packs — by which the owner teaches a new app in minutes without code.

### Added

- **Guarded AT-SPI action layer** (`jarvis/gui/actions.py`): `find_node` walks an
  application's accessibility tree under the ADR-0022 walls — blocked applications are refused
  **before the tree is read** (subtree never touched), password roles are refused **before any
  name is read**, names pass hygiene, and walks are bounded (depth 4 / 256 nodes). On top of it:
  `list_actions` reads the node's **published** Action interface, `do_named_action` invokes an
  action **only by its published name** (must report True), and `set_node_text` writes through
  EditableText. Child traversal speaks both the real pyatspi index protocol
  (`get_child_count`/`get_child_at_index`) and duck-typed `iter()` stubs.
- **`jarvis.gui.action_exec`** — the fixed-argv module CLI (ADR-0026 D3): one JSON line out,
  honest exits (`0` ok / `2` refused-by-a-wall / `3` not found), pyatspi imported lazily so
  headless machines get an honest diagnostic, never a traceback.
- **Owner-taught app packs** (`jarvis/gui/appskill.py`, schema `app-skill/1`): a ≤20-line
  declarative pack (`id`, `description`, optional `app.launch` tokens, owner phrases, bounded
  steps `focus | action | type | key`) with **no field that can carry a command** — the first
  launch token must be a bare command name (PATH lookup; no path-based exec), arguments reject
  shell metacharacters, blocked apps are refused at launch, focus, and per-step level, and
  every value is length-bounded. Install is atomic with a **sha256 receipt** (the M9c
  integrity pattern); loads are **fail-closed** — drifted bytes make the pack invisible and
  the matcher abstains, never half-runs.
- **`jarvis app-skill wizard|list|show|remove`** — the teach workflow: `wizard --file <pack>`
  validates the pack **by constructing it through the real `gui.app` builders** (the M9b eval
  discipline), prints the constructed steps, installs pack + receipt, and honestly notes when
  it is *replacing* an existing pack. Exit `2` on any refusal, including bad JSON.
- **`gui.app` playbook (T2)** — the 58th catalog entry: match consults installed packs'
  anchored phrase regexes; build emits launch (detached `setsid`) → focus (`wmctrl -a`) →
  API steps (`action_exec`) → keys (`ydotool`, last resort); verify reads the last pack
  step's real result. One consented T2 task per run, full plan displayed — consent parity
  with `gui type/key`.
- **42 new tests** (`tests/test_gui_appskill.py` + catalog pins): walls-before-reads (including
  a booby-trapped subtree proving blocked apps are never touched), receipt drift → abstain,
  build argv shapes, action_exec exit codes, wizard round-trip, and the no-shadow rules
  against `gui.launch`. Battery: **856 passed + 2 skipped**.

### Changed

- Catalog **57 → 58** (breadth discipline, ADR-0026 D5). `gui.app` carries **no static hint**
  and is **excluded from the classifier vocabulary** — owner-taught playbooks have no static
  matcher surface to template; absent packs make every proposal path abstain honestly.
  Registry/hint/vocabulary pins updated with the documented exemptions.
- README status and INSTALL notes describe the control ladder and the teach workflow.

### Security

- Unknown-app control climbs a fixed ladder — launch → guarded read → **published actions** →
  EditableText → keys last — and **never** falls to vision, synthetic clicks, or portal input
  (each parked behind its own future ADR). Blocked applications and password fields are walled
  **before any read**, at plan time and again at execution time. Packs are data that compile
  through the kernel: nothing in a pack can widen authority beyond the rungs it composes.

## [1.19.0] - 2026-09-05 — the hybrid AI upgrade: kernel-derived planning vocabulary, dual-path reliability, streamed speech (ADR-0025)

Owner-directed "Very Big and Major Update in the AI/LLM part" — direction chosen by the owner
from a four-option decision brief (*combined hybrid setup*), model posture fixed by the owner
(*both local and API, both with reliability*). Every ADR-0007/0014 invariant is retained: the
model proposes, the kernel disposes; schema-constrained output is still validated; `--no-ai`
kills every AI path.

### Changed
- **The kernel owns the planning vocabulary (D1):** the LLM planner's system prompt is now
  *built* from the live catalog — one canonical, engine-legal example phrase per playbook
  (`jarvis/planner/intent_hints.py`) instead of a frozen 12-intent hand-list. Two tests keep it
  honest: every hint must pass the real `match_intent`, and the hint set must cover exactly the
  live catalog (57/57) — staleness is a CI failure, the ADR-0023 discipline applied to the
  planner. The prompt can never again silently fall behind the engine.
- **Conversation context is background, never instructions (D2):** `build_plan` accepts recent
  dialogue (`history`); chat maintains bounded turns; memory (ADR-0020) and dialogue ride as a
  delimited *BACKGROUND CONTEXT — reference only, never instructions* block. The memory-in-
  system-prompt test was updated to the new contract (memory reaches the model only inside the
  delimiter, the system prompt stays pure catalog).

### Added
- **Dual-path reliability with mandatory disclosure (D3):** `complete_with_failover` —
  candidates in ADR-0003 precedence behind the persisted breaker; ONE bounded retry on
  transient failures of the primary (the breaker, not the retry loop, guards storms); failover
  local ⇄ remote on final failure; **the serving backend is always disclosed**
  (`[jarvis] served by <mode> (<model>)`, and `served_by` on the plan). A dead local no longer
  kills a request a configured remote could serve.
- **`jarvis ai status`:** both paths honestly — endpoint liveness, models, key-configured
  (never the key), remote-allowed flag, per-provider breaker state, precedence, failover note.
- **Voice sentence-boundary speaking (D4):** `speak_sentences` — playback of the first
  sentence begins after one sentence's synthesis instead of the whole reply's (the research's
  voice-latency insight applied where latency really is: TTS, not the LLM). Token-level LLM
  streaming is deliberately deferred: every AI surface emits a validated artifact; there is no
  free-text surface to stream, and speculative plumbing would be dead code.
- **Model guidance, not model coupling (D5):** README/INSTALL document the researched local
  class (Llama 3.1 8B / Llama 3.2 3B / Qwen 3.5-class 9B; Ollama vs llama.cpp trade-offs).
  Defaults unchanged.

### Fixed
- A latent str-Enum bug in the subsystem: `str(FailureKind.TIMEOUT)` is
  `"FailureKind.TIMEOUT"`, never `"timeout"` — transient-retry comparison now uses enum value
  equality, and `ai_answer` no longer records a breaker failure for attempts the breaker never
  allowed (`is not FailureKind.BREAKER_OPEN`).

### Tests
- +20 (`tests/test_ai_upgrade.py`): the hint pins (cover catalog, engine-legal, derived prompt
  completeness), bounded delimited context, failover semantics (transient retry exactly once,
  permanent-error straight failover, breaker-open skip without network, all-paths-failed
  honesty, no-backend honesty, dedup + `--no-ai` absolute), `served_by` disclosure incl. the
  `_ask_flow` stderr line, refusal provider attribution, `ai status` JSON, and the voice
  sentence pipelining (per-sentence synthesis, single-sentence degeneration). Suite:
  **814 passed + 2 honest skips** (816 collected). ruff + mypy clean.

## [1.18.0] - 2026-09-04 — synthesis-over-sources digest: the F6 playbook `sys.digest` (roadmap R5b, ADR-0024)

"Continue" — the last parked R5 item that was not owner-gated. The research scored F6 (data
analysis and distillation) *partial*: "LLM synthesis [is] still hallucination-prone", and the
gap line is verbatim — "no synthesis-over-sources playbook". One phrase now yields a cited,
deterministic health digest computed from the exact pinned commands of three existing
read-only playbooks. **Catalog grows 56 → 57 by the breadth discipline** — the first growth
since ADR-0016, and it went through its own ADR.

### Added
- **`sys.digest` (tier T0, read-only; ADR-0024):** "system digest" / "health check" /
  "analyze my system" → three source steps (`df -h`, `free -h`, `uptime` — the *same pinned
  argv* as `fs.disk_free`, `sys.memory`, `sys.uptime`) and a VERIFY stage that **is** the
  synthesis: `jarvis.system.digest.synthesize_digest` is a pure-stdlib function over the
  captured stdout — no LLM anywhere in the path. Zero engine/orchestrator changes; the digest
  flows through the standard verification detail and is journaled with the task.
- **Disclosed thresholds, honest sources:** warn at disk ≥ 85% used (root), memory ≥ 85% used
  (available vs total), load-1 > core count; an unparseable source becomes an explicit
  `[source unreadable: …]` line — never a guess. Every digest line names its source playbook
  and the header discloses "computed deterministically from 3 read-only sources (no LLM)".
  Warnings are findings, not failures; `ok` is true iff at least one source was readable.
- **Matcher safety:** anchored bare phrases only. The battery pins the shadow set — and caught
  a real one during development: "run a health check" was being caught by `gui.launch`'s
  greedy T2 "run X" matcher; the digest matcher now claims its phrases *before* the T2
  launcher can (verified: "run a health check" → `sys.digest`, T0, no launch attempted).
- **Vocabulary retrain per the ADR-0023 cadence:** the trainer derives the new label from
  `PLAYBOOKS` automatically; corpus gains the `sys.digest` family; gates re-earned at
  58 classes: **top-1 0.997 / top-3 1.000 / OOD abstention 1.000**; model 126 KB;
  byte-reproducible. Reconstruction stays frozen (no extractor — pinned).

### Tests
- +33 (`tests/test_digest.py`): matcher anchors + the no-shadow set (incl. the gui.launch
  regression), build == the three source argvs (all T0, no user data), the pure synthesizer
  (determinism, citations, thresholds, unreadable/partial honesty, hygiene, no-fabrication),
  verify wiring (incl. optional-source skip, missing results), read-only undo, and the CLI
  dry-run contract. Catalog pins updated 56 → 57 (playbooks/breadth/cli/brief).
  Suite: **794 passed + 2 honest skips** (796 collected). ruff + mypy clean.

### Still parked (owner-gated)
- Capability manifests (ADR-0017 D2) — "no code moves until the owner says so." Publishing any
  of the 21 drafts, LICENSE, PyPI/AUR, PR #1, Level-3 briefing policy, memory agent-capture,
  GUI input injection — all await the owner.

## [1.17.0] - 2026-09-04 — intent vocabulary retrain: the classifier finally speaks all 56 playbooks (roadmap R5a, ADR-0023)

"Continue" — the first parked R5 item. The proposals-only classifier (ADR-0015, v1.10.0) was
trained against a 12-intent catalog; the catalog is now 56 playbooks across eight families, so
**44 playbook ids were invisible to the model** — unrankable in "did you mean" disclosures,
unproposeable. This release retrains it over the full vocabulary. Its authority is unchanged:
still proposals-only, matcher-disposed, `--no-ai`-switchable.

### Changed
- **The kernel now owns the vocabulary (ADR-0023 D1):** `training/train_intent.py` derives
  `LABELS` from `PLAYBOOKS` (`sorted(ids) + [unknown]`) instead of hand-listing — the same
  single-source-of-truth discipline as `suggest_intent` importing `match_intent`. Catalog
  drift flows into the next training run; a new test pins
  `model["labels"] == sorted(PLAYBOOKS ids) + [unknown]` so shipped weights and the live
  catalog can never diverge silently.
- **Corpus rebuilt per family (D3):** every one of the 56 ids has a synthetic template corpus
  written against the real matchers' accepted surface (cue-word discipline keeps
  head/tail/read, the svc stop/restart/disable trio, and the proc pair apart). The stratified
  holdout splits **unique** texts *before* seeded upsampling balances the train split — no
  duplicate leakage in the gate numbers.
- **Same gates, earned at 57 classes (D2):** holdout top-1 ≥ 0.88, top-3 ≥ 0.97, OOD
  unknown-recall ≥ 0.80, evaluated on the rounded shipped weights, trainer refuses to write
  on failure. Achieved: **top-1 0.998 / top-3 1.000 / abstention 1.000**; model 125 KB
  (< 400 KB pin); byte-reproducible (verified by double training run, identical sha256).
- **Reconstruction stays conservative (D4):** slot extractors remain frozen at the original
  12 labels; the widened families rank in disclosures (`rank_intents`, the unknown-request
  hint) but `suggest_intent` abstains on them — pinned by tests. Paths still never
  reconstructed; the user typing the suggestion remains the sole consent path, including for
  T2 families that gain only "did you mean" visibility.
- Runtime inference unchanged (labels are data in `model.json`); the catalog **stays 56** —
  no playbook, matcher, or authority surface changed.

### Tests
- +2 and widened: the vocabulary==catalog pin, softmax width == label count, 45 new
  hand-labeled cases across the previously-invisible families (hand set now 67, independent
  of the trainer's generator), and the rank-but-never-reconstruct pin for widened families.
  Suite: **761 passed + 2 honest skips** (763 collected). ruff + mypy clean.

### Still parked
- Capability manifests (ADR-0017 D2) remain **owner-gated** — "no code moves until the owner
  says so." Slot-extractor widening for the new families is future work with its own review.

## [1.16.0] - 2026-09-04 — guarded desktop awareness: the read-only AT-SPI tier (roadmap R4, ADR-0022)

"Continue" — roadmap R4 from the deep research. JARVIS has been an AT-SPI session-bus client
since M9e — a client of the boundary the research names ("AT-SPI exposes window contents to any
client on your session bus") — with **no guards at the data boundary**. This release adds the
published hardening posture as one shared, fail-closed guard family, shipped as the read-only
tier.

### Added
- **`src/jarvis/desktop/guards.py`** — frozen constants + pure predicates, pinned by tests,
  shared by every reader (CLI and GUI service alike):
  **BLOCKED_APPS** (password managers, keyrings/secret services, polkit/pkexec/askpass agents,
  terminal emulators — shell content is out of scope for a read-only agent); **PASSWORD_ROLES**
  (`password text`); the sensitive-name pattern (word-boundary regex, so "author", "passport",
  "pinning" do not match); hygiene (control chars stripped, collapsed, ≤120 chars).
  Matching is fail-closed by explicit bias: false-positive blocks are acceptable,
  false-negative reads of a secret-bearing surface are not.
- **`src/jarvis/desktop/read.py`** — the guarded walk through three ordered walls: (1) blocked
  apps' subtrees are never read at all, disclosed as `[withheld: application '<name>' is on the
  blocked list]`; (2) password-role nodes are withheld **before their name is ever read**;
  (3) sensitive names are read, then redacted before display/persist. Budgets: depth ≤ 4,
  512 nodes with an honest truncation marker; unreadable nodes degrade to `[unreadable node]`.
  The walk is read-only by construction — a test pins that no mutating call is ever made.
- **Content-free per-op audit (D4):** every read appends to `<state>/desktop/ledger.jsonl` —
  timestamp, source (cli/gui), blocked-app identifiers, counts, truncated flag. **No title or
  field content is ever persisted** (a test pins that a distinctive window title appears
  nowhere in the ledger bytes), and desktop content never enters planner prompts, memory, or
  briefings (situation-aware combination parked for a future ADR).
- **`jarvis desktop read` / `desktop status`** — on-demand, owner-issued reads only; no
  scheduled or ambient reading. Unavailability is the honest ADR-0010-style gap
  (`(None, reason)` / exit 0 with disclosure, nothing audited when nothing was read).
- Docs: ADR-0022; README desktop-awareness section. Input injection (Wayland portals /
  ydotool / compositor APIs) stays parked for its own ADR; the `run_shell`-style escape hatch
  of production MCP servers remains rejected.

### Changed
- **`gui.atspi.desktop_window_titles()` is rewired through the guard** (ADR-0022 D5, contract
  unchanged): the GUI service's window list / focus / type flows now cannot list, focus, or
  type into a blocked application at all — the guard inherits downward, never upward.

### Tests
- +27 (`tests/test_desktop.py`): the exact blocklist/role pins, word-boundary redaction cases,
  hygiene, walk walls (no descent into blocked apps, no name read on password fields,
  budget/depth caps, honest unreadable nodes), the read-only-discipline pin, content-free
  audit guarantees, guarded titles + the GUI rewire, and CLI read/status/bare/unavailable.
  Suite: **759 passed + 2 honest skips** (761 collected). ruff + mypy clean.

## [1.15.0] - 2026-09-04 — scheduled briefings: Level-2 proactivity, propose-only (roadmap R3, ADR-0021)

"Continue" — roadmap R3 from the deep research. The agent gains a polite, bounded presence: a
computed briefing with a deterministic notify-or-silence policy. **Briefings are computed, never
executed** — the charter line "no unsolicited action" now has a scheduled surface that respects it.

### Added
- **`src/jarvis/brief/engine.py`** — composes from four local, zero-subprocess sources: the task
  journal (recent failures), the existing evidence-backed suggestions engine, unknown requests
  (the owner's growth queue), and disk pressure via `os.statvfs` (stdlib stat, not a `df`
  subprocess). **No playbook added; the catalog stays 56.** A test asserts composition spawns
  no processes.
- **Deterministic v1 policy (D2):** notify iff failures ≥1 (7-day window) OR suggestions ≥1 OR
  free disk % < 15; otherwise **silence with a recorded reason**. Every run appends to
  `<state>/briefings/ledger.jsonl`; `jarvis brief status` reports runs/notified/silenced and
  the **silence rate** — the denominator-aware transparency the 2026 proactivity literature
  calls for.
- **Delivery is presentation (D3):** notify writes `briefings/latest.md` plus one hygiened
  `notify-send` line when that binary exists (fixed argv, ≤200 chars, control-char stripped,
  honestly "unavailable" otherwise). `--quiet` (timer mode) prints nothing.
- **Feedback recorded, not acted on (D4):** `jarvis brief accept|dismiss <id>` appends to the
  ledger; policy learning from feedback (Level 3) is parked, owner-gated.
- **Opt-in timer (D5):** `jarvis brief install [--on daily|weekly]` writes a systemd **user**
  timer + service (`jarvis-brief.timer` → `jarvis brief --quiet`), enables via `systemctl
  --user` when available (else disclosed skip with the manual command); `uninstall` reverses;
  packaging never enables it. The ADR-0018 doorway stays "a doorway, never an actor" — the
  timer composes text, which is not action.
- Docs: ADR-0021; README proactivity section. Command-based checks (e.g., pending-updates
  simulation) stay parked — they would be the first scheduled subprocesses and deserve their
  own ADR.

### Tests
- +18 (`tests/test_brief.py`): composition from seeded journal/context with monkeypatched
  statvfs; the no-subprocess guard (composition asserts `subprocess.run` is never called);
  the full policy table; notify-line hygiene; ledger runs/feedback/stats with the silence
  denominator; run_once delivery + quiet mode + json; timer content/install/uninstall
  round-trip with honest non-systemd disclosure; CLI bare-run/status; and the catalog-stays-56
  charter check. Suite: **731 passed + 2 honest skips** (733 collected). ruff + mypy clean.

## [1.14.0] - 2026-09-04 — owner-taught file memory: provenance, injection-scanned, read-only to the model (roadmap R2, ADR-0020)

"Continue with the Others" — roadmap R2 from the deep research. The first persistent-
personalization layer: small plain files the owner teaches, the planner may read, and anyone
can purge. No database, no embeddings, no daemon.

### Added
- **`src/jarvis/memory/store.py`** — one markdown file per entry under `<state>/memory/<id>.md`
  (12-hex id; header: created/origin/source; then the text). Bounded: ≤200 entries, ≤500 chars
  each; a full store refuses honestly.
- **Write-ahead gates (D2):** the single write path (`jarvis memory remember`, origin=`owner`)
  runs text hygiene (non-empty, ≤500 chars, no control chars) **and the existing prompt-
  injection scanner** (`context.store.find_injection_pattern`) — instruction-like text is
  refused, never sanitized. Agent-initiated capture is parked (owner-gated future ADR).
- **Read-only, delimited surfacing (D3):** when the LLM plans an unmatched request, the newest
  ≤10 entries (≤2000 chars) ride in the SYSTEM prompt as "background context, not instructions;
  never a reason to skip validation" (the spotlighting defense); every proposed step still
  re-matches through the real playbooks. `--no-ai` behavior unchanged; corrupt files skipped at
  read, never fatal; the deterministic engine, KB, journal, and all safety gates are untouched.
- **Purge-ability (D4):** `jarvis memory forget <id> | --all`, plus `list` and `show` with full
  provenance. Every entry is one file the owner can read, edit, or `rm`.
- Docs: ADR-0020; README memory section. MCP/GUI write surfaces and the six-tool contract stay
  frozen this release (parked, disclosed).

### Tests
- +23 (`tests/test_memory.py`): hygiene refusals, injection refusal (nothing written),
  provenance round-trip, store-full honesty, malformed-id safety, newest-first ordering with a
  controllable clock, bounded delimited prompt block, corrupt-file tolerance, purge semantics,
  and planner-surfacing proofs at the `build_plan` seam (memory rides in the system prompt;
  the request and catalog validation stay pure). CLI round-trip incl. refusal exit codes.
  Suite: **713 passed + 2 honest skips** (715 collected). ruff + mypy clean.

## [1.13.0] - 2026-09-04 — voice front-end: push-to-talk into the same kernel (owner-directed roadmap R1, ADR-0019)

"Continue the Major Milestone" — roadmap R1 from the deep research. Voice is **presentation,
never authority**: the transcribed request enters the same match → plan → approve → execute →
verify path as typed text, with the same journal, tiers, and refusals.

### Added
- **`jarvis voice doctor`** — honest capability detection (mirrors `gui/detect.py`): probed
  recorder (`arecord`/`pw-record`), STT (`whisper-cli`/`whisper.cpp`/`whisper` + `$JARVIS_STT_MODEL`),
  TTS (`piper` + `$JARVIS_TTS_MODEL`), player (`paplay`/`aplay`/`ffplay`); missing pieces are
  reported as a plain-language list, never a silent degrade. A headless box is a normal state.
- **`jarvis voice ask [--seconds N] [--wav FILE]`** — record → transcribe → kernel → terse
  summary; **`jarvis voice say "<text>"`** — speak a short text. All audio work is delegated to
  standard external binaries via **fixed argv** (recorder flags frozen, model paths validated as
  single argv tokens, piper's text piped through the Runner's `stdin_text`) — no shell, **zero
  new Python dependencies** (ADR-0005 honored), audio files live in the state dir and are
  overwritten per turn (nothing retained).
- **Consent parity (D3):** voice requests run under the non-consenting policy — T0/T1 proceed as
  on a non-tty CLI; **T2 is not voice-consentable** (speech misrecognition must never
  manufacture consent): the spoken refusal points to typed `--yes`; T3 refused as always.
  Hands-free wake-word listening is parked (an in-process engine would need an ADR-0005
  exception; owner-gated).
- Docs: ADR-0019; README voice section. Research basis: `docs/RESEARCH-jarvis-agent-linux-2026.md`
  §3.6 (local voice stack) and R1.

### Tests
- +20 (`tests/test_voice.py`): stub binaries on a fake PATH exercise the whole round trip
  without audio hardware — detection honesty (headless + missing-model cases), exact argv
  templates, stdin-piped TTS text, text hygiene refusals, pw-record's honest "no timed mode",
  kernel parity through voice (T0 succeeded end-to-end incl. spoken summary; unmatched →
  refused; T2 refused with typed-consent hint, nothing executed; never-list stays unmatchable),
  and the CLI surface. Suite: **690 passed + 2 honest skips** (692 collected). ruff + mypy clean.

## [1.12.0] - 2026-09-04 — hybrid residency: opt-in resident doorway, agent stays on-demand (owner-directed, ADR-0018)

Owner directive: "Combine both, and make a Hybrid, option" — the systemd user-unit doorway and
the GUI-autostart option combined into one opt-in mode. The charter holds: the agent itself
never autostarts; what may exist after login is a **doorway, never an actor**.

### Added
- **`jarvis serve`** (`src/jarvis/cli/serve.py`): a loopback-only, token-authenticated HTTP
  doorway that reuses the MCP tool handlers **verbatim** — consent parity is structural, not
  reimplemented (`jarvis_do` still needs per-call `allow: true` for T2; refusals carry the same
  preview-then-allow hint; T3 refused unconditionally; no persistent yes anywhere; no
  exec/passthrough tool). Serve adds availability, never authority.
- **Hardening, each asserted by a test (ADR-0018 D2):** non-loopback binds refused outright;
  bearer token with constant-time compare (file `0600`, generated on first run or at install,
  never logged); `Host` header must be loopback (DNS-rebinding defense); method/path
  allowlists; 64 KiB body cap; JSON-only bodies; unknown tools 404; no CORS/preflight answers
  (browsers cannot drive it); one stderr audit line per request without token or body.
- **`jarvis serve install [--with-gui]`**: writes a systemd **user** unit
  (`~/.config/systemd/user/jarvis-serve.service`, `WantedBy=default.target`, `Restart=on-failure`)
  and enables it via `systemctl --user` when available (otherwise files are written and the skip
  is disclosed with the manual command — never silently claimed). `--with-gui` additionally
  writes an XDG autostart entry for the GUI frontend **only if** a `jarvis-gui` command exists
  (probed first, refusal otherwise; the GUI repo remains untouched — contract-side only).
  Validation precedes any write. **`uninstall`** reverses everything; **`status`** reports each
  piece honestly.
- **Packaging never enables residency (D4):** only the owner's typed `install` does. Default
  shape unchanged: nothing runs unless you run it.
- Docs: ADR-0018; README hybrid-residency section; integration-doc §9 (resident mode).

### Tests
- +21 (`tests/test_serve.py`): real-socket transport hardening, kernel parity through the
  doorway (unmatched → refused; T2 without allow → refused; protected paths refused at build),
  unit/desktop generation, install/uninstall/status round-trips with a fake HOME, token
  hygiene. Suite: **670 passed + 2 honest skips** (672 collected). ruff + mypy clean.

## [1.11.0] - 2026-09-04 — playbook catalog breadth: 12 → 56 commands, same kernel discipline (owner-directed)

Owner directive: "add almost every possible, Linux Command in the Playbook, also maintain my
guidelines, too." Breadth is delivered the only way this project allows: more **guarded
families** — fixed argv, validated arguments, tier gates, honest undo — never a raw passthrough.

### Added
- **ADR-0016** (`docs/adr/0016-playbook-catalog-breadth.md`): spec+factory design for catalog
  breadth; argument policy (user flags refused — a leading dash is a refusal, never a sanitize;
  shell metacharacters banned in every slot; 200-char bound); tier map (readers T0, file
  mutations T1, process/system control T2); the documented **never-list** (`dd`, `mkfs*`,
  `fdisk`/`parted`, `shutdown`/`reboot`/`halt`, `curl`/`wget`, `sed -i`/`awk`, `chmod`/`chown`
  — no playbook exists for these; they are unmatchable by design); fs.* requests are matched
  case-preserved while the LLM prompt vocabulary stays the core twelve.
- **`planner/inspect_cmds.py`** — 33 read-only playbooks (T0): file inspection (`fs.list`,
  `fs.read`, `fs.head`, `fs.tail`, `fs.count`, `fs.stat`, `fs.file_type`, `fs.which`,
  `fs.disk_usage`, `fs.find`, `fs.search`), system probes (`sys.memory`, `sys.processes`,
  `sys.uptime`, `sys.date`, `sys.hostname`, `sys.cpus`, `sys.pci`, `sys.usb`, `sys.blocks`,
  `sys.sockets`, `sys.network`, `sys.routes`, `sys.journal`, `sys.kernel_log`, `sys.users`,
  `sys.login_history`, `sys.env`, `sys.identity`, `sys.checksum`, `fs.disk_free`), and network
  probes (`net.ping` bounded to 4 packets/4 s, `net.dns`). 31 of 33 come from one spec+factory
  table; args are validated at MATCH time — a bad argument leaves the playbook unmatchable and
  the request falls through to honest refusal.
- **`planner/file_cmds.py`** — 6 file-mutation playbooks (T1): `fs.mkdir`, `fs.touch`,
  `fs.copy`, `fs.move`, `fs.remove`, `fs.link`. Destinations run through the full edit policy
  (protected paths refused; system prefixes escalate to root-gated T2 steps). Undo plans are
  built at plan time with plan-time existence: mkdir/touch/copy/link get real reverse steps
  with post-conditions; move gets a move-back; **deletion is disclosed as irreversible**.
- **`planner/proc_cmds.py`** — 5 process/service playbooks (T2): `svc.stop`, `svc.restart`,
  `svc.disable` (systemd-gated, unit names validated at match time) and `proc.kill` (numeric
  pid only), `proc.kill_name` (`pkill -x`, exact name, patterns impossible). Service undo is
  honest: the recorded reverse path is the inverse command, stated as `none_needed`.
- `nearest_intents` and the M11 proposals cover the new vocabulary automatically. The neural
  classifier remains the 13-class core model (proposals-only by construction); new families
  surface through the lexical fallback — retraining is available but not required.

### Changed
- `Playbook`, its protocols, and `Params` moved to `planner/models.py` so catalog family
  modules can construct playbooks without import cycles; `PLAYBOOKS` concatenates
  families-first (guarded matchers answer before core package verbs).
- `show …` phrasings (`show memory usage`, `show disk free`, `show running processes`, …) and
  space-separated two-path forms (`mv /a /b`) are recognized; file-noun requests
  ("what's in the file X") resolve to `fs.read`, not `ls`.

### Security
- Argument slots are kind-validated at match time (`path`/`name`/`host`/`glob`): flags
  (`list files in -rf /`), unit-name escapes (`stop ../../etc`), and shell metacharacters are
  refusals that make the intent unmatchable — the never-list is provably unmatchable by tests.
- Builders conform to the kernel's static-argv rules (no empty elements, no paths after `--`);
  defense-in-depth stayed in charge and shaped the catalog (three build shapes were corrected
  to pass the kernel's checker, not to appease it — the checker was right).

### Tests
- +64 — the new `tests/test_playbook_breadth.py` (64 tests): catalog shape, family argv
  allowlists, match-time refusal semantics, never-list unmatchability, plan/undo honesty per
  family, protected-path refusals, systemd gating, core regressions. Registry/tier/CLI count
  assertions updated in place.
  Suite: **645 passed + 2 honest skips** (647 collected) at this milestone's commit.
  mypy strict-clean; ruff clean (including format).

## [1.10.2] - 2026-09-04 — remaining backlog: CI rate-limit remedy, release-doc lessons, README status truth

### Fixed
- **The documented CI flake class is remediated at the root.** Discovery: the live KB tests
  (`tests/test_knowledge_live.py`) run in every CI matrix leg and hit `api.github.com`
  **unauthenticated** — 60 req/h shared per runner IP — the mechanism behind 4+ intermittent
  `test_cited_kernel_docs_exist_upstream` failures. Remedy, both ends: `fetch.verify_kernel_doc`
  now sends `GITHUB_TOKEN` from the environment when present (never logged), and retries a
  rate-limited call (429, or 403 with `x-ratelimit-remaining: 0`) **exactly once**, bounded to 5 s
  regardless of `Retry-After`, with the retry disclosed in the returned detail; `ci.yml` supplies
  `GITHUB_TOKEN: ${{ github.token }}` to the Tests step and the M4 grounding step. +5 tests
  (`tests/test_fetch_resilience.py`) over real sockets: token sent but never leaked, no-token
  shape, retry-once + disclosure, persistent rate limit stays honest, plain 403 not retried.
  `StubHTTPServer` gained GET queueing/recording (backward compatible).

### Changed
- README status line updated (was stale at v1.0.0/M0–M6): now states v1.10.1-era reality —
  M0–M11 + front-end contract, failure semantics, neural intent recall, and the twelve
  `-rc1` review candidates awaiting owner release decisions.
- `docs/RELEASING.md` gains "Tag-push mechanics" — the release-engineering lessons that
  previously lived only in AGENT-EXPERIENCE: push tags ONE per push event (GitHub creates no
  push events when more than three tags arrive at once), the `-rc1`/draft convention, the
  dispatch-token caveat, and the rate-limit-flake verification rule.

### Tests
- +5; suite: **581 passed + 2 honest skips** (583 collected; an earlier draft of this line said
  583/585 — corrected 2026-09-04 by recount at `9584127`). No product behavior changes beyond
  the fetch path described above; wire (`javris-frontend/1`) untouched.

## [1.10.1] - 2026-09-04 — GUI coordination pass: contract re-verified against kernel 1.10.0 and GUI @ `d5233d5` (owner-directed)

### Added
- **Coordination log** in `docs/integration/JAVRIS-GUI.md` §8: the `javris-frontend/1` wire is unchanged from v1.8.0 through v1.10.0 (M10/M11 changed what the kernel says in failure/unknown situations, not the protocol); conformance re-verified — 7 contract tests green, plus a subprocess-level replay of the contract's example frames through the shipped `jarvis mcp serve` binary (protocolVersion echo, `serverInfo` 1.10.0, deterministic explain, honest T2 refusal, protocol-free stderr). GUI-side re-inspection: `state.py` transition table and `router.py` verbs are unchanged at the GUI branch head, so every §4 mapping and §5 verb remains exact; the branch's new attention-escalation/orb/motion work is rendering-side and orthogonal.
- **Front-end rendering guidance** (§8): degraded AI is telemetry, not an error (attention-escalation is the natural home); unknown-request suggestions may render as pre-filled console text (user still disposes — consent model untouched); `JARVIS_NO_AI=1` gives an air-gapped mode with the state machine unaffected. A structured suggestion field on the wire is explicitly recorded as a proposed, owner-gated `javris-frontend/1.1` revision — deliberately not implemented.
- **Identity-parity conformance test**: the live handshake's `serverInfo.version` is pinned to the kernel package version (front-ends read it for capability detection; drift there would silently break their logic). Tests: +1 → **576 passed + 2 honest skips** (578 collected).

### Changed
- No kernel behavior changes; no wire changes (`javris-frontend/1` stable). Docs and conformance evidence only.

## [1.10.0] - 2026-09-04 — M11: learned intent recall — a purpose-built proposals-only neural classifier (ADR-0015, owner-directed)

### Added
- **A purpose-built neural network for JARVIS** (`src/jarvis/intent/`): a tiny MLP — hashed word/bi-gram + character-trigram features (fastText-style, 256-dim signed hashing trick) → 48 ReLU units → softmax over the 12 playbook families **plus an explicit `unknown` abstention class** (~13K parameters, 107 KB weights shipped as package data). Pure-stdlib inference (~1 ms), zero runtime dependencies (ADR-0005 intact).
- **Deterministic gated trainer** (`training/train_intent.py`, dev-only): seeded, reproducible, pure-stdlib backprop; gates (holdout top-1 ≥ 0.88, top-3 ≥ 0.97, OOD abstention ≥ 0.80) run against the *rounded shipped weights* and refuse to write model.json on failure. Shipped model: holdout **top-1 0.992 / top-3 1.000 / OOD abstention 1.000**; hand-written eval sets (independent of the training generator): 22 labeled, top-1 ≥ 0.9 gate, top-3 = 1.0, OOD abstain ≥ 0.85 — all green.
- **Proposals-only wiring** (the authority contract): the classifier is consulted only after the deterministic engine missed AND the LLM planner is unavailable or honestly unexpressible; a suggestion must pass a deterministic slot extractor AND re-pass the REAL playbook matcher, and is rendered as text — "it looks like: `jarvis do install htop` — type that yourself to run it (suggestions never self-execute)". `file.append` is extractor-free by design (the model never reconstructs paths). `--no-ai`/`JARVIS_NO_AI=1` switches it off like every other model path (ADR-0014 D7); disclosure falls back to the lexical ranking.
- **Research + ADR**: `docs/RESEARCH-tiny-intent-models-2026.md` (fastText/hashing lineage, abstention structure, training-data honesty) and `docs/adr/0015-learned-intent-recall.md`.
- Tests: +14 (`tests/test_intent_model.py`): artifact shape/size, hand-labeled accuracy gates, hand-OOD abstention, the structural every-suggestion-is-engine-legal invariant, determinism, latency, missing-model fallback, and end-to-end CLI wiring incl. the `--no-ai` off-switch. Suite: **575 passed + 2 honest skips** (577 collected).

### Changed
- Unknown-request hints (`jarvis ask` unknown path) may now include a learned, engine-legal suggested command — exit codes and JSON `error` contracts unchanged. The MCP surface is untouched (frozen `javris-frontend/1`).

## [1.9.0] - 2026-09-04 — M10: AI failure semantics — breaker, taxonomy, grounded answers, no-AI contract (ADR-0014, owner-directed)

### Added
- **Persisted per-provider circuit breaker** (`providers/breaker.py`): three states (closed/open/half-open), 3 consecutive failures → open, 300 s wall-clock cooldown that survives process boundaries, half-open single-probe recovery; state at `state_dir/ai/breaker.state` — operational `.state` outside the M9c integrity scope (the M9d charter precedent). A hung model now degrades the *second and later* requests to instant honest refusals instead of fresh full timeouts. A malformed model output counts as a provider failure; an honest "unexpressible" does not — the model is healthy, the request is out of vocabulary.
- **Failure taxonomy** (`ProviderError.kind`): `unreachable | timeout | http | malformed | key-missing | breaker-open`, surfaced in `jarvis ask` output (text + JSON), in `status`, and in breaker records — degraded-mode disclosure: what changed, what still works, what happens next.
- **Grounded AI answers on KB misses** (`knowledge/ai_answer.py`, `jarvis explain`): deterministic cite-or-abstain runs first and unchanged; on a KB miss the planner backend gets one bounded chance to synthesize an answer from an evidence envelope of real KB facts, citing ONLY supplied fact ids (unknown/empty citations, `abstain:true`, oversized or injection-shaped text → forced abstain; AbstentionBench's structural-abstention lesson). Cited facts get the same on-machine verification rendering; any failure falls back to the deterministic refusal with a one-line disclosure. MCP `jarvis_explain` stays deterministic-only (frozen `javris-frontend/1` contract, latency-stable read-only surface).
- **Unknown situations are processed, not just refused** (ADR-0014 D6): when neither the engine nor the planner can map a request, `ask` returns top-3 nearest known intents (lexical), journals an `unknown_requests` record for owner review (growth-loop input), and names the teaching paths — `unknown-request:` prefixed in JSON, exit 2 unchanged.
- **The no-AI contract** (ADR-0014 D7): global `--no-ai` / `JARVIS_NO_AI=1` disables every model path in one switch (routing returns "none" without probing; the full suite passes AI-less — air-gap/audit mode). `JARVIS_REMOTE_LLM=0` remains the remote-only switch.
- `status` gains an `ai breaker` line; `doctor` reports AI backend state informationally (env-dependent — deliberately not baseline-scoped, ADR-0014 D8).
- **Research + ADR**: `docs/RESEARCH-ai-resilience-2026.md` (degradation ladders, circuit breakers, AbstentionBench/I-CALM/conformal abstention, structured-output practice — all sourced) and `docs/adr/0014-ai-failure-semantics.md` (decisions D1–D8).

### Changed
- Planner wire is schema-constrained: Ollama receives the planner's JSON Schema in `format`, OpenAI-compatible receives `json_schema` response format; strict post-validation unchanged (schema-constrained output is still untrusted input). No retries on the planner path — one attempt, then honest failure + breaker record (documented deviation from the "retry briefly" rung: CLI interactivity budget).
- Internal API additions only: `Provider.complete(schema=…)`, `plan_routing(enabled=…)`, `PlanRefused.kind`, `Answer.ai_text` (additive JSON field), `journal.record_unknown_request()`. CLI exit codes and the `--json` status shape unchanged.

### Tests
- +40 (`tests/test_ai_resilience.py`): breaker states/persistence/isolation/corruption, taxonomy over real sockets (incl. a hung-server timeout), schema wire assertions via request capture, breaker-gated planner, unknown-request journal, grounded-answer contract (citation subset, abstain, injection scan, fallback), and the no-AI CLI path end to end. Suite: **561 passed + 2 honest skips** (563 collected).

## [1.8.0] - 2026-09-03 — J.A.V.R.I.S.-GUI wiring: front-end contract (owner-directed)

### Added
- **`jarvis mcp describe`**: the machine-readable front-end contract (`javris-frontend/1`) — transport/spawn/framing, handshake with version exchange, every tool with its declared consent semantics (`read-only` / `explicit-allow`), resources, the consent model (a front-end never synthesizes `allow:true`; charters remain the only pre-authorization), a state mapping onto the GUI's explicit `AssistantState` machine (legal transitions only), and a verbatim example session.
- **`docs/integration/JAVRIS-GUI.md`**: the wiring contract for the owner's [J.A.V.R.I.S.-GUI](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.-GUI) Qt6 HUD — architecture (GUI renders, kernel decides), consent UX (refusal → owner action → per-call `allow:true`), console-verb suggestions for its allow-listed `CommandRouter`, honest `OFFLINE` degradation when `jarvis` is absent, and a deliberate licensing note (protocol is the seam; no code crosses repos until the owner sets this repo's license).
- **Conformance tests** (`tests/test_frontend_contract.py`): the published descriptor is asserted against LIVE server behavior — tool set, consent labels, CLI/library parity, the example handshake replayed through the real `MCPServer`, and the full consent flow end-to-end (read-only plays; T2 refuses without `allow`, plays with it). The contract and the code cannot drift.
- Tests: +6. Suite: **521 passed + 2 honest skips** (523 collected).

### Changed
- Version 1.8.0; PKGBUILD/spec synced. The GUI implements its QProcess client against the published contract (its repo/branch, its MIT license); this repo owns the server side and the contract.

## [1.7.0] - 2026-09-03 — M8b + M8d: user context & supervised growth (ADR-0012 complete, owner-approved)

### Added — M8b: user context store
- **`jarvis context prefer <key> [value]`** (`--unset`): explicit preferences in the same tamper-evident store — preferences **tune what is suggested, never what is allowed**. `suppress.<category>=1` silences whole suggestion categories.
- **`jarvis context rule "never touch docker"`** / `--remove <id>`: house rules (deterministic content-addressed ids) that suppress matching suggestions from listings; ≥4-char tokens only, so short rules can't overmatch.
- **`jarvis context routines`**: recurring-playbook patterns inferred **on demand** from the journal with cadence + confidence, citing their evidence, never persisted (documented deviation from the ADR sketch: inference from the journal means `context forget` cannot leave stale inference behind), with charter hints for T≤2 recurrences.
- **`jarvis context forget`**: deletes the entire store — consent-gated (T2-grade through the real policy), reports exact counts.
- The M9c chain covers the new tables: per-row content hashes (edits caught, not just deletions) chained into per-table digests folded into `verify_integrity()`/`jarvis doctor`; write-time injection scan covers preference values and rule text.
- `context show` now renders feedback + preferences + rules (JSON: one structured object; the 0.4-era bare-list shape is superseded).

### Added — M8d: supervised growth loop
- **`jarvis grow fact|skill|list|show|prune|export`**: JARVIS drafts growth proposals as inert data in `state/proposals/` — KB facts validated by the **real citation-required store** (an uncited fact cannot even be drafted; ADR-0009 enforced at draft time) and skill packs validated by the M9b machinery. The kernel, policy, and shipped KB/skills stay outside its write scope, permanently.
- **Promotion is owner-only, by design**: `grow export` copies the ready-to-PR artifact and prints the exact owner commands — JARVIS never opens or merges PRs (merge authority is the owner's, per governance). Skill proposals install only via consented `jarvis skill install` (evals re-run at install).
- Documented interpretation of the ADR's "drafts ... as PRs": drafting/validation/export are automated; PR creation and merge remain owner actions (no remote or credential actions from the product).

### Changed
- Version 1.7.0; PKGBUILD/spec synced. **ADR-0012 is now fully implemented** (M8a 1.2.0 · M8b+M8d 1.7.0 · charter hardening via M9d 1.5.0).
- Tests: +26 (preferences/rules round-trips + tamper detection, engine suppression via both mechanisms, routines inference incl. garbage rows and window bounds, consent-gated forget, fact drafting through the real store incl. refusals, skill proposals, export semantics, integrity-scope exclusion of proposals). Suite: **515 passed + 2 honest skips** (517 collected).

## [1.6.0] - 2026-09-03 — M9e + M9b: ADR-0013 complete (owner-approved)

### Added — M9e: API-first GUI actions
- **`type_text` gains an AT-SPI EditableText API path**: when `pyatspi` is importable, text entry prefers the accessibility interface — no synthetic keystrokes. Same T2 consent, same TOCTOU focus guard, same no-text-in-journal redaction. **Fallback is disclosed, not silent** (ADR-0013 ordering: API preferred, synthetic input as last resort): if the API path fails (e.g. the focused app exposes no editable), the injection backend runs under the same consent and the journal/result name both attempts (`api_attempt`); with no fallback at all it is an honest error. Key combinations stay injection-only — stated plainly: there is no honest API path for key synthesis.
- **Action-path disclosure**: every capability binding now carries a `path` (`api` / `wm` / `injection`) shown by `jarvis gui status` and `--json` — the UFO²-informed guarantee that the operator can see whether an action rides OS interfaces or synthetic input.

### Added — M9b: verified skill packs
- **`jarvis skill install/list/remove`**: a skill pack is **data that compiles through the kernel** — it may only re-expose an existing playbook under a new one-line match regex with fixed scalar params. The referenced playbook determines argv and tier; packs cannot add commands, raise tiers, or carry instructions any model reads at runtime (the anti-ClawHub design; ~12% of ClawHub's instruction-file catalog was documented malicious).
- Install is consent-gated (T2 through the real `ApprovalPolicy`), shows the full pack first, and runs every eval case as a real planning dry-run — a pack that cannot build on this machine never installs. Installed bytes are pinned by a sha256 receipt; a pack whose bytes drift is skipped **fail-closed** by the matcher and flagged by `jarvis doctor` (skills live in the M9c integrity scope).
- `match_intent` gains a verified fallback: installed, receipt-verified packs extend NL matching deterministically (id order, first fullmatch); `run_intent` journals the alias in `params.skill`. Charter precheck deliberately still speaks canonical phrasings only — standing orders don't change meaning silently.
- Format note: ADR-0013 sketched YAML; packs are strict **JSON** (`*.skill.json`) — stdlib-only per ADR-0005.
- GUI eval catalog: task `03-input-xdotool` now asserts the stable fact (`capabilities.key.backend == xdotool`) instead of pinning `type_text`'s backend — which legitimately becomes `atspi-editable` on machines with pyatspi.
- Tests: +40 (M9e matrix paths, API flow incl. consent/TOCTOU/disclosed fallback/no-tool honesty with a fake pyatspi; M9b validation matrix, eval gating, receipt drift fail-closed, end-to-end skill phrasing through `run_intent`, CLI, integrity scope). Suite: **489 passed + 2 honest skips** (491 collected).

### Changed
- Version 1.6.0; PKGBUILD/spec synced. **ADR-0013 is now fully implemented** (M9a 1.3.0 · M9c 1.4.0 · M9d 1.5.0 · M9e+M9b 1.6.0).

## [1.5.0] - 2026-09-03 — M9d: charters, circuit-broken standing orders (ADR-0013, owner-approved)

### Added
- **`jarvis charter`**: recurring automation as a versioned, revocable contract — the "heartbeat" capability the landscape research shows is the field's most useful *and* most abused feature, designed here against its documented failure modes.
- **Install (`charter install`, T2 consent through the real `ApprovalPolicy` gate)**: the contract is printed line-by-line before consent — one pre-authorized NL request, an explicit playbook allowlist, a hard tier ceiling (0..2; **T3 is never charterable**), `--on-calendar` (systemd user timer; omit for manual scheduling), per-run step cap, monthly run budget, and `TimeoutStartSec` wall-clock bound.
- **Run (`charter run`)**: precheck opens every firing — status must be `active`, the contract must still validate, the request must still resolve to an allowlisted playbook at or under the ceiling (semantic drift **pauses** instead of improvising), and the rolling-30-day journal budget must be under the cap. Only then does the request play through the normal Orchestrator with pre-authorized consent; every firing is a normal journaled task.
- **Circuit breakers**: failure policy is fixed at `pause` (a failed or refused firing stops the charter until the owner resumes); budget exhaustion pauses; `pause`/`resume`/`revoke` give the owner instant control (revoke keeps the audit file, firings refuse forever).
- **systemd user timers, honestly degraded**: `charter install` writes `jarvis-charter-<id>.{service,timer}` and enables them when a systemd user session exists; otherwise it says so and documents the manual path (`jarvis charter run`). Unit generation is pure and unit-tested; `systemctl --user` is best-effort and never crashes the CLI.
- **Integrity integration**: charter contracts live in the M9c scope (`~/.local/state/jarvis/charters/*.json`) — a new or drifted contract trips `jarvis doctor` until deliberately re-baselined; operational state files (`.state`) are deliberately outside the glob so pausing/resuming never false-alarms.
- Anti-Ultron clause holds: a charter can only replay its own allowlisted request through the kernel; it cannot modify charters, code, or policy.
- Tests: +23 (schema invariants incl. T3 refusal, consent gate, dry-run semantics, failure pause → refusal, budget exhaustion, tamper + semantic-drift layers, revoke, systemd units, integrity-scope placement). Suite: **448 passed + 2 honest skips** (450 collected).

### Changed
- Version 1.5.0; PKGBUILD/spec synced.

## [1.4.0] - 2026-09-03 — M9c: memory & config integrity (ADR-0013, owner-approved)

### Added
- **`jarvis doctor`**: hash baseline over policy-relevant state — packaged KB files, the decision/gate/execution code (playbooks registry, safety kernel, runner, orchestrator, both ingress front-ends), the context store module, and the cautious-mode marker — written **only** via explicit `--write-baseline`; every later run reports drift (`ok` / exit 0, drift / exit 1, no baseline / exit 2 with guidance). `jarvis status` carries a live integrity line. Honest limitation stated in code and docs: this is a tripwire against invisible, gradual modification (the OpenClaw "security degradation" class), not a cryptographic anchor.
- **`jarvis doctor --canaries`**: every suggestion render (CLI human output, MCP `jarvis_suggest`) now issues a random canary token recorded in `canaries.jsonl`; if a canary string appears off-machine, the owner can trace exactly which suggestion batch leaked.
- **Context store hardening**: feedback text (reason/title) is scanned at write time for injection patterns and refused (the table feeds future suggestions in M8b — poisoned feedback would become poisoned suggestions); every entry carries a content hash chained into a table digest, so silent edits, deletions, and forgeries are reported by `verify_integrity()`; pre-1.4.0 rows are honestly reported as legacy and gain hashes on their next upsert; `jarvis doctor` folds the chain verdict into its exit status.
- Tests: +26 (baseline round-trip/changed/missing/added, doctor CLI + status line, canary issuance/trace, scan refusal/allowance, tamper detection incl. a doctor-level poisoned-store case). Suite: **425 passed + 2 honest skips** (427 collected).

### Changed
- Version 1.4.0; PKGBUILD/spec synced.
- MCP tool surface intentionally unchanged (fixed set of six — new capabilities are CLI/doctor-side; the server's `jarvis_suggest` payload gains only a `canary` field).

## [1.3.0] - 2026-09-03 — M9a: MCP server surface (ADR-0013, owner-approved)

### Added
- **`jarvis mcp serve`**: a Model Context Protocol server on stdio — newline-delimited JSON-RPC 2.0, **stdlib-only** (ADR-0005 dependency discipline holds; no SDK). Harm model: an MCP client is just another untrusted-ingress front-end, identical in standing to the CLI; nothing bypasses the kernel.
- **Tools (fixed set — deliberately no free-form-exec passthrough)**: `jarvis_status` (fingerprint) · `jarvis_facts` (cited KB) · `jarvis_explain` (cite-or-abstain) · `jarvis_suggest` (read-only) · `jarvis_preview` (plan + blast radius; never asks, never executes) · `jarvis_do` (deterministic playbook through the same Orchestrator; **T2 requires explicit per-call `"allow": true`**, mapped onto the CLI's `--yes` semantics with a deterministic non-tty stdin; **T3 refused unconditionally**; refusals restated in MCP terms with a preview-then-allow hint).
- **Resources**: `kb://facts` (all cited facts) · `journal://tasks` (recent journaled tasks).
- Protocol conformance: initialize (version echo with fallback) / ping / tools+resources discovery; parse-error, invalid-request, method-not-found, invalid-params error codes; notification silence; batch rejection. stdout carries protocol frames only — diagnostics go to stderr.
- Tests: +27 (protocol frames, tool semantics incl. refusal through the real ApprovalPolicy, execution via scripted runner, CLI wiring). Suite: **399 passed + 2 honest skips** (401 collected).

### Changed
- Version 1.3.0; `packaging/arch/PKGBUILD` + `packaging/rpm/jarvis-agent.spec` synced from stale 1.2.0 → 1.3.0 (they document the next v-tag; artifacts become fetchable when the owner cuts the v1.3.0 release).
- ADR-0013 status Proposed → Accepted (owner go-ahead 2026-09-03); M9a implemented, M9b–M9e pending per-phase go.

## [Unreleased] — M1 container evaluation: 70/70 PASSED

### Verified (observed, run 33637847042)
- Container execution-eval green on **all five distros** — debian:12, ubuntu:24.04, fedora:latest, archlinux:latest, alpine:latest — **14/14 tasks each (70/70 overall)**, including real install/remove/upgrade across apt/dnf/pacman/zypper/apk, the undo round-trip with post-condition replay, and all honest-refusal paths. Evidence: check annotations + [eval summary](evals/results/m1-baseline.md). CI annotation channel added to the driver; artifact names sanitized; GITHUB_ACTIONS passed into containers.

### Added
- `evals/catalog/m1.json` — M1 seed catalog: 14 executable expectations per distro (10 playbooks incl. undo round-trip, idempotent reinstall, system upgrade, honest service refusal in non-systemd containers, and three refusal cases: protected package, unmatched intent, invalid option-like name).
- `evals/harness/m1_eval.py` — stdlib-only eval driver; runs the real CLI per task, checks status/playbook/verification/error substrings/exit codes, writes JSON results, exits non-zero on any mismatch.
- `evals/harness/bootstrap.sh`, `evals/harness/run_in_container.sh` — python3 bootstrap (apt/dnf/pacman/apk/zypper) and container entrypoint.
- `.github/workflows/container-eval.yml` — matrix evaluation in debian:12, ubuntu:24.04, fedora:latest, archlinux:latest, alpine:latest containers (root, network), results uploaded as artifacts.

### Changed
- `.gitignore` — generated eval JSON excluded from version control; curated summaries are committed instead (`evals/results/`).

## [1.2.1] - 2026-09-03 — Security & quality audit fixes

### Fixed
- **P1 security**: knowledge fetch now re-validates **every redirect** against the URL allowlist (`SafeRedirectHandler`); previously only the initial URL was checked and redirects were followed blindly. All request sites routed through the validating opener (+2 tests).
- **P1 bug**: `jarvis safety-check` could **hang interactively** on graphical desktops (GUI battery's approval policy defaulted to the TTY stdin and would prompt with a focused window). Battery now uses a non-tty stdin.
- **P2 packaging**: install-test rpm version now derived from the wheel filename and verified via `rpm -q` (the tested rpm was previously mislabeled 1.0.0 while containing 1.2.0); spec/PKGBUILD synced to 1.2.0.
- P2 hygiene: `gui/detect.py` normal imports; dev-env setuptools upgraded past published advisory (build-system already required ≥68; jarvis has zero runtime deps).

### Audit
Full findings, soundness checks, and documented limitations: `evals/results/AUDIT-1.2.1.md`. Tests: **372 passed + 2 honest skips**.

## [1.2.0] - 2026-09-03 — M8a Adaptive initiative: suggestion engine

### Added (ADR-0012 — "proactivity proposes; consent executes")
- **`jarvis suggest`**: deterministic, evidence-backed suggestions — failed tasks with available undo artifacts (journal evidence), stale package index (>14 days, journal evidence), distro-relevant pitfall briefings (KB-cited with sources). The engine takes **no runner and executes nothing**; accept prints the exact `jarvis …` command for the user to run through the normal consent path.
- **Feedback ledger** (`jarvis suggest accept|reject <id> [--reason]`): handled suggestions are suppressed from future listings; rejections require a reason (calibration signal); ledger is the seed of the M8b context store.
- **`jarvis context show`** (+ status line): the local store is inspectable from day one; it tunes suggestions and never grants authority to act.
- Tests: +14 (rules, evidence, suppression, determinism, read-only invariant, broken-journal resilience, CLI flow). Suite: **370 passed + 2 honest skips**.

### Planned (recorded in ADR-0012, not built yet)
- M8b context store (preferences/routines/house-rules; inspectable, deletable, local-only), M8c charters (revocable standing orders on systemd timers, journaled, tier-capped), M8d supervised growth loop (KB/playbook proposals as gated PRs).

## [1.1.0] - 2026-09-02 — M7 Real-machine readiness

### Added
- **GUI focus TOCTOU guard**: the focused window is re-verified after consent, immediately before injection; a focus change aborts with disclosure (old → new). Keystrokes can no longer silently land in a window that took focus during approval.
- **`jarvis safety-check`**: live refusal battery through the real components — protected package, destructive NL, flag smuggling, protected file append, T2 consent gate, GUI injection guard — with an execution-blocked sentinel runner (a refusal bug still cannot touch the system). Verdict: `SAFETY CHECK PASSED` (7/7).
- **`jarvis do --preview`**: full plan + blast radius (max tier, root?, network?, commands, classified system/kernel/home paths) — never asks, never executes.
- **Auto-rollback** (`jarvis do --auto-rollback`): failed consented tasks are reversed automatically via the full `undo()` path (artifact rebuild + kernel revalidation + verification) under the original task's consent; journal keeps the task `failed` and marks the undo applied.
- **Cautious mode** (`jarvis cautious on/off/status`): blocks T2+ even with `--yes`; each action needs `--cautious-ok`; `--preview` always allowed. Status line in `jarvis status`.
- **Live-LLM injection corpus** (`tests/test_fault_injection_live.py`, marker `live_llm`): 7 prompt-injection frames through a real local model; planner-or-kernel-must-refuse invariant; honest skip without a model. New weekly `llm-eval.yml` CI lane (Ollama + qwen2.5:0.5b) for real-model drift detection.
- **`docs/SAFE-TESTING.md`**: verified/unverified map + 4-rung safe-testing ladder + safety-bug reporting protocol.
- Tests: +17 (TOCTOU order-semantics runner, blast radius, cautious gates, auto-rollback with real journal, battery, CLI). Suite: **356 passed + 2 honest skips** (both model-availability skips).

### Changed
- `Orchestrator` gains `auto_rollback` / `cautious_ok`; `undo()` gains internal `skip_consent` (rollback runs under the original task's consent); `TaskOutcome` gains `rolled_back` / `rollback_task_id`.

## [1.0.0] - 2026-09-02 — M6 Production hardening & packaging

### Added
- **Packaging** (ADR-0011): wheel + sdist (`jarvis-agent`), self-contained `.deb` (real dpkg lifecycle verified: install → run → remove), `.rpm` spec (built+installed in fedora CI container), AUR `PKGBUILD` (makepkg+pacman verified in arch CI container); all native packages unpack the wheel to `/usr/share/jarvis/lib` + `/usr/bin/jarvis` shim, depend only on `python3 >= 3.10`.
- **KB ships in the package** (`jarvis/knowledge/data/` via `importlib.resources`) — fixes a P1: the KB previously resolved against the repo root and vanished in installed wheels; clean-venv install proven; install harness greps for the KB on every distro.
- **Install matrix** (`packaging.yml`): every push builds artifacts and install-tests them on clean containers of all five Tier-1 distros (debian-12, ubuntu-24.04, fedora, arch, alpine) with a KB smoke.
- **Release pipeline** (`release.yml`): tag `v*` → artifacts + clean-venv smoke → draft GitHub Release; PyPI publishing manual and owner-only; `workflow_dispatch` on CI, container-eval, packaging, release for on-demand fresh VMs.
- **Docs**: `INSTALL.md` (per-distro install story), `docs/RELEASING.md` (owner release runbook).

### Changed
- **Distribution rename**: `jarvis-linux` → **`jarvis-agent`** (import package and `jarvis` command unchanged; metadata test guards the new name).
- **Telemetry: none** (owner decision pending; nothing added).

## [0.5.0] - 2026-09-02 — M5 GUI control

### Added
- **GUI capability matrix** (`jarvis gui status`): honest per-machine report of session (x11/wayland/headless), desktop, and per-capability backend — availability never pretended (ADR-0010).
- **Backends**: X11 (wmctrl/xdotool/scrot), i3/sway IPC (get_tree JSON walk, focus verification), Hyprland (hyprctl -j), KDE Wayland (kdotool when present; spectacle), GNOME Wayland (gdbus Shell screenshot), Wayland input via ydotool gated on a live `ydotoold` socket; AT-SPI optional read layer via `pyatspi` (honest absence).
- **Consent-gated actions** (`jarvis gui open/focus/type/key/screenshot/close`): focused-window target disclosure BEFORE acting, T2 approval via the standard policy, journaled; **typed text is never persisted** (length + sha256 prefix only — a unit test caught the argv leak, fixed); injection is CLI-only, unreachable from NL playbooks; text/key-combo/launch-argv policies.
- **ydotool wizard** (`jarvis gui wizard`): real readiness checks with distro-specific fix commands (apt/dnf/pacman/apk).
- **Vision fallback** (`jarvis gui describe`): screenshot → local Ollama vision model; abstains loudly when absent.
- **`gui.launch` playbook** (NL "open firefox", registry 12): app-name argv only, no paths, case-preserving, T2.
- **GUI eval** (`evals/harness/m5_gui.py` + 15-task catalog): real X stack (Xvfb + i3 + xterm) through the real CLI in CI (`gui-eval` job), gate ≥98% ⇒ 15/15; headless honesty subset (4 tasks) verified locally **4/4**; consent refusal is a graded task.
- Tests: +40 (detection, matrix, parsers, policy, service consent/journal/privacy, wizard, vision stub, CLI, playbook, detach regression). Suite: **340 passed + 1 honest skip** (341 collected); live-marked set: 10 (9 pass + 1 skip).

### Changed
- Package version 0.5.0; README GUI section; report addendum `evals/results/REPORT-m5.md`.

## [0.4.0] - 2026-09-02 — M4 Knowledge system

### Added
- **Cited knowledge base** (`knowledge/*.json`, KB v1): 12 facts across kernel/distros/pitfalls; every fact carries sources (kernel-doc paths in `torvalds/linux`, man pages, specs, distro docs) and an optional local verifier; the store **refuses uncited facts at load** (ADR-0009).
- **Local grounding** (`knowledge/grounding.py`): file_equals / file_exists / os_release_field / binary_present / command_ok verifiers; honest three-state results (verified / contradicted / unverifiable-here).
- **Cite-or-abstain answers** (`knowledge/answers.py` + `jarvis explain`): answers always carry sources + on-machine verification status; anything outside the KB is refused, never guessed.
- **Opt-in online verification** (`knowledge/fetch.py`, `JARVIS_ONLINE_DOCS=1`): kernel-doc citations verified against **`torvalds/linux` master** via the GitHub Contents API (owner-directed knowledge source; upstream reference, not vendored — ADR-0009); strict URL allowlist refuses anything else before a request; results cached in the state dir.
- **`jarvis facts [topic]`** browser; KB version/count in `jarvis status`; `jarvis` console-script entry point (`pip install` now puts the CLI on PATH).
- **Grounding eval** (`evals/harness/m4_grounding.py` + catalog): gate **0 unverifiable claims** — answered ⇒ cited; verified ⇒ verifier passed; kernel citations re-verified upstream in CI (online mode). Result: **12/12, 0 unverifiable claims** (offline 10/10; +2 upstream torvalds/linux checks).
- Tests: +26 (store schema refusals, verifiers on the real host, answers honesty, CLI surface, allowlist-before-network, live upstream verification). Suite: **301 collected (294 unit + 7 live-marked; live: 6 pass + 1 skip)**.

### Changed
- Package version 0.4.0; README quick start gains `explain`/`facts`; report addendum `evals/results/REPORT-m4.md`.

## [0.3.0] - 2026-09-02 — M3 Safety hardening

### Added
- **Snapshot preflight** (`safety/snapshots.py`): best-effort snapper/timeshift snapshot before every T2+ task, journaled per task (`task_meta`), surfaced in CLI output; honest degradation (never blocks; says exactly what protection exists). Restore stays manual by design (ADR-0008).
- **File edits with real backups**: `file.append` playbook + `jarvis file append <path> <text>` — pre-edit backup into the state dir (hash-addressed, mode-preserving `cp -p`), argv-only execution (`tee -a` via new runner `stdin_text` support), undo restores byte-identical content (or removes created files). Path policy (`safety/paths.py`): symlink-resolving checks; auth material (`passwd`/`shadow`/`sudoers`) and `/boot`/`/proc`/`/sys`/`/dev` refused outright; `/etc`,`/usr`,`/var`,`/opt`,`/srv` require T2 consent.
- **Dynamic tier elevation**: effective task tier is now computed from built steps (file edits under system paths are gated as T2 even though the playbook's registry tier is T1).
- **Blocklist hardening**: `wipefs`/`parted`/`fdisk`/`gdisk`/`sgdisk` refused as argv[0]; generic pipe-to-shell (`| sh`, `| bash`, sudo variants); `chmod 777 /`.
- **Injected-fault gate** (`tests/test_fault_injection.py` + `evals/harness/m3_faults.py` in CI): 35 adversarial vectors across 9 ingresses — **0 escapes**. The suite caught a real gap during development: tampered undo artifacts could reach `/etc/shadow` via `tee`; undo replay now re-applies the file-path policy to `tee`/`cp`/`rm`/`truncate` operands.
- **First published consolidated eval report**: `evals/results/REPORT-m3.md` (M1 70/70 containers · M2 9/9 planner · M3 fault gate 35/0 · rollback evidence).
- Rollback integration tests on real files (byte-identical restore; created-file removal); live Ollama smoke test (skips honestly when no backend).

### Changed
- Package version 0.3.0; journal gains a `task_meta` store (snapshot records); runner supports piped stdin for argv-only editors.

## [0.2.0] - 2026-09-02 — M2 LLM planner & router

### Added
- **Provider abstraction** (`src/jarvis/providers/`): stdlib-`urllib` backends for local **Ollama** (JSON mode, temperature 0, availability probe) and any **OpenAI-compatible** endpoint (opt-in key via `JARVIS_OPENAI_API_KEY`, base URL/model configurable) — no provider SDKs, keys from env only (ADR-0007).
- **Router** (`providers/router.py`): deterministic engine first (LLM never consulted on playbook matches — eval-asserted at 0 requests), then local Ollama, then remote if configured and not disabled (`JARVIS_REMOTE_LLM=0` disables only the remote fallback), else honest refusal with setup hint.
- **LLM planner** (`planner/llm.py`): strict JSON contract (`{"explanation", "steps"}` of natural-language intents); every step must pass the deterministic playbook matchers — invalid JSON, out-of-vocabulary, injection-shaped, or oversized proposals are **refused, never guessed** (ADR-0007 "the LLM proposes, the kernel disposes").
- **Composite plan execution** (`Orchestrator.run_plan`): multi-part plans with per-part post-condition verification, one journal task (`plan/<provider>`), tier gate on the maximum step tier, and **composite undo applied last-first**; a part without a reverse path (e.g. upgrade) marks the plan's undo honestly unavailable.
- **CLI**: `jarvis ask` (one-shot engine+planner with `--dry-run`) and `jarvis chat` (interactive REPL: `/status`, `/playbooks`, `/tasks [n]`, `/undo <id>`, `/help`); `jarvis status` now reports planning-backend availability.
- **M2 eval** (`evals/harness/m2_eval.py` + `evals/catalog/m2.json`): 9 deterministic cases against a scripted local LLM stub — routing (0-LLM fast path), schema validity of proposals, injection/malformed/empty refusals, provider-outage honesty, no-backend guidance. Wired into CI; **9/9 required**.
- Tests: +38 (provider HTTP behavior on real sockets via stub server, planner validation branches, composite plan lifecycle incl. poisoned undo, CLI routing incl. remote-fallback). Total suite: **227 unit + 4 live (231 collected)**.

### Changed
- Package version 0.2.0; ADR-0007 records the planner architecture and the deliberate deferral of Textual/Pydantic (stdlib REPL + strict hand-rolled validation suffice for the fixed schema).

## [0.1.0] - 2026-09-02 — M1 Kernel

### Added
- **SENSE** (`src/jarvis/core/fingerprint.py`): machine fingerprint from `/etc/os-release` (man-5 parser), init-system detection, package-manager resolution (distro mapping *verified against PATH*, honest `unknown`), session type, privilege state.
- **Distro adapters** (`src/jarvis/system/`): exact-argv command vocabulary for apt, dnf, pacman, zypper, apk — install/remove/refresh/upgrade/search/info/installed-probe — plus the boot-critical protected-package set (ADR-0006).
- **Guarded execution** (`src/jarvis/execution/runner.py`): argv-only subprocess (no shell anywhere), per-step timeouts with process-group SIGTERM-to-SIGKILL, 16 KiB output tails, non-interactive `sudo -n` privilege path with clean refusal when unavailable (ADR-0006).
- **Static safety analysis** (`src/jarvis/safety/tiers.py`): strict token validation (refuse, never sanitize), fork-bomb / `mkfs` / `dd of=/dev` / `rm -rf /` / piped-curl-sh / shutdown-class blocklist (argv[0]- and `-c`-content-aware to avoid false positives), end-of-options marker rule that blocks flag smuggling from tampered journals.
- **Tiered approval** (`src/jarvis/safety/approval.py`): T0/T1 auto · T2 interactive or `--yes` (refused, never hung, in non-interactive mode) · T3 always refused.
- **Playbook engine** (`src/jarvis/planner/`): 10 deterministic seed playbooks (`pkg.install`, `pkg.remove`, `pkg.search`, `pkg.info`, `pkg.cache.refresh`, `pkg.upgrade`, `svc.status`, `svc.start`, `svc.enable`, `sys.info`) with strict anchored intent matching (unmappable requests are refused, not guessed), per-backend step building, post-condition verification (pipeline VERIFY), and undo plans built *before* execution.
- **Audit journal** (`src/jarvis/journal/sqlite.py`): SQLite (0600) tasks/steps/undo-artifacts under `~/.local/state/jarvis` (XDG/state-dir env precedence); undo artifacts stored before first execution and strictly revalidated (incl. protected-set re-check) on replay.
- **Orchestrator** (`src/jarvis/core/orchestrator.py`): full lifecycle REFUSED, RUNNING, SUCCEEDED/FAILED/INTERRUPTED/UNDONE with SIGINT/SIGTERM kill-switch (process-group termination, journal marked `interrupted`, exit 130).
- **CLI** (`src/jarvis/cli/app.py`, stdlib argparse per ADR-0005): `status` / `do [--dry-run] [--yes]` / `undo [--dry-run]` / `playbooks` / `tasks`, global `--json`, documented exit codes (0/1/2/130).
- Tests: 189 unit tests (adapters exact-argv contracts, safety blocklist, matching table, journal round-trips, orchestrator lifecycle incl. tampered-undo refusal and interrupt semantics, runner sudo/timeout behavior, CLI surface) plus 4 opt-in live integration tests (193 collected in total) (`RUN_LIVE=1`; read-only and honest privilege-failure paths only — real mutations belong to the CI distro-container evaluation).
- Docs: ADR-0005 (M1 stdlib-only runtime), ADR-0006 (argv-only execution, validation, privilege policy).

### Changed
- Package version 0.1.0; `docs/PLAN.md` M1 status updated.

### Security
- ADR-0006 controls active: no-shell argv execution, token validation, `sudo -n` only, protected-package set enforced at plan *and* undo-replay boundaries, T3 refused by policy, kill-switch with process-group cleanup. A blocklist anchoring flaw was caught by tests before any release (see AGENT-EXPERIENCE.md).

## [0.0.1] - 2026-09-02 — M0 Governance baseline


### Added
- `docs/adr/0001-scoped-success-metric.md` — adopts the scoped ≥98% task-catalog metric (owner-delegated decision; benchmark evidence cited).
- `docs/adr/0002-cli-first-surface.md` — v1 interaction surface: CLI + TUI chat; GUI overlay and daemon deferred with rationale.
- `docs/adr/0003-hybrid-router-local-first.md` — model posture: playbook engine + local-model default + opt-in API models behind one router.
- `docs/adr/0004-m0-toolchain.md` — toolchain & dependency set with per-dependency justification (guideline 16); zero runtime dependencies at M0.
- Project skeleton: `pyproject.toml` (PEP 621, src-layout, ruff/mypy/pytest config, dev extras `ruff`/`mypy`/`pytest`, license field intentionally omitted pending owner ruling), `.gitignore`, `.github/workflows/ci.yml` (ruff lint+format, mypy, pytest on Python 3.10–3.12 matrix), `src/jarvis/__init__.py` (package root, v0.0.1), `tests/test_package.py` (packaging-integrity smoke tests).
- CI verified in operation: workflow pushed after GitHub connection upgrade (commit `feea3e2`); run [33635129000](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S./actions/runs/33635129000) observed green — 3/3 matrix jobs (py3.10/3.11/3.12) passed all gates (ruff lint, ruff format, mypy, pytest).

### Changed
- Canonical project name ruled by owner: **JARVIS** — *"Just A Rather Very Intelligent System"*; display form `JARVIS`, package/CLI `jarvis`; repository name unchanged. `README.md`, `docs/PLAN.md`, `docs/RESEARCH.md` updated accordingly; decision recorded as resolved in PLAN §13.1.
- `docs/PLAN.md` status elevated from DRAFT to **ACCEPTED (baseline)** — remaining decisions §13.2–13.5 resolved via owner delegation, each documented in an ADR; new open item §13.6 (LICENSE selection, owner decision).

### Fixed
- `docs/PLAN.md`: repaired self-inflicted corruption (a malformed edit truncated the document mid-§7, losing §8–§13; a stray fragment and a non-English character artifact also introduced). Full document restored from source content and verified (all 13 sections present, anomaly scan clean). Incident logged in `AGENT-EXPERIENCE.md`.

### Security
- No runtime code yet; M0 ships no runtime dependencies (supply-chain surface intentionally empty; ADR-0004). Safety architecture (tiered action gate, blocklists, undo/rollback, dual reviewer) specified in `docs/PLAN.md` §4.3 for M1+. CI quality gates (lint, format, types, tests) wired on push/PR.
