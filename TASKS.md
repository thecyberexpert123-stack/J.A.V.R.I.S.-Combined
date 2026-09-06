# Task list — Deep Research II follow-through (opened 2026-09-06)

Owner instruction: *"continue … follow my guidelines … create a task list to make sure of all."*
This file is the single checklist for turning the eleven candidates in
[`docs/RESEARCH-agent-construction-and-future-tech-2026.md`](JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s/docs/RESEARCH-agent-construction-and-future-tech-2026.md)
into owner-gated, charter-compliant work. It is updated in the same change-set as the work it
tracks (guideline 4). Nothing here is done until its box is ticked **and** the verification column
says how it was verified.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked / needs owner ·
`[-]` dropped (reason recorded).

## 0. Ground rules that apply to every item

| Rule | How it is enforced in this sequence |
|---|---|
| Sign-off gates (charter Part C) | Every item begins with an **ADR draft**; no code for that item until the owner accepts the ADR. Items flagged *security-sensitive* additionally pause on their design choices (guideline 20). |
| Never merge (guideline 23) | All work on `arena/01a0717a-j-a-v-r-i-s-combined`; `main` untouched. Commits/pushes only as the owner instructs (§D records the policy). |
| Research before implementing (3) | Each item cites the research section it comes from; new facts needed during implementation are fetched and cited, never assumed. |
| No new dependency without justification (16) | Stdlib-only remains the default (ADR-0005). Any item that would need a binary or library stops at the ADR with the dependency case written out. |
| Preserve interfaces (17) | CLI verbs, MCP tool names/payloads, journal schema, and unit-file contents are interfaces. Additive changes only; any breaking change is flagged in the ADR and CHANGELOG. |
| Failure modes (18) | Each ADR carries a failure-mode table; each feature degrades to today's behaviour when its precondition is absent (no `NOTIFY_SOCKET`, no bus, no Landlock). |
| Verification honesty (21) | Each item's "Verified / Not verified / Limits" block below is filled from real runs. Sandbox limits (§C) are stated, not glossed. |
| Changelog + experience log (4) | Kernel `CHANGELOG.md` + `AGENT-EXPERIENCE.md` per item; root logs for cross-cutting notes; PLAN.md milestone row per shipped item. |
| Self-review before "done" (22) | The §E checklist is run per item and its outcome logged. |

## A. Housekeeping (no owner decision needed beyond commit policy)

- [x] **A1.** Research II document written, cross-checked against source (56 sources, all cited; provenance labels; VERIFIED-IN-REPO/ASSUMED split).
- [x] **A2.** Kernel `CHANGELOG.md`, `AGENT-EXPERIENCE.md`, `README.md` index row; root `CHANGELOG.md`/`AGENT-EXPERIENCE.md` updated.
- [x] **A3.** This task list created and linked from the root README.
- [x] **A4.** Commit + push authorized 2026-09-06 (§D5): one commit per item on `arena/01a0717a-j-a-v-r-i-s-combined` (`git log` there), never merged.

## B. Candidate items (order = proposed; final order recorded in §D)

Each block: origin → sub-tasks → acceptance → verification plan → sandbox limits. "Size" is an
estimate. Version numbers are assigned when an item starts (project convention: one minor bump
per shipped behaviour change; docs-only ships without a tag).

### B-C6 · `pass^k` reliability in the eval drivers — *pre-approved (D4); no behaviour change* (S) — `[x]` done 2026-09-06 (ADR-0027; committed per D5 — hash in §A4 log below)
Origin: research §9 (τ-bench `pass^k`; a 98% target is a `pass^k` target).
- [x] Inspect `evals/harness/m2_eval.py`, `m3_faults.py`, `m4_grounding.py`, `m5_gui.py`, `m1_eval.annotate`, `providers/breaker.py`, and how `ci.yml` calls them. **Finding:** the fixed `/tmp/jarvis-m2-eval-<id>` state dir let the ADR-0014 breaker accumulate the refusal cases' failures → the 4th local invocation within 300 s failed 6/9 with `BREAKER_OPEN` (reproduced). Precondition for any K ≥ 4; fixed in this item.
- [x] `--runs K` (default 1) on `m2_eval.py` and `m4_grounding.py`; per-case `passes/runs/runs_detail`, suite `runs` + `pass_hat` curve; existing fields unchanged (field-by-field diff against the pre-change driver). `m1`/`m3`/`m5` excluded with reasons (ADR-0027 D5).
- [x] `evals/harness/passk.py` (stdlib estimator `C(c,k)/C(n,k)`, shared `--runs` argument, rendering) + `tests/test_eval_passk.py` (9 tests: formula, `pass^1 at n=1 == pass rate`, monotone curve, input rejection, both drivers end-to-end incl. keep-on-fail state dirs and pinned `JARVIS_STATE_DIR`). The isolation test was shown to fail (3/5) with the fix reverted.
- [x] Docs: ADR-0027; kernel CHANGELOG (`Added` + `Fixed`), AGENT-EXPERIENCE entry, PLAN §3 sentence + R-II row, README index row. No `evals/results/README` exists (nothing to update there).
- Acceptance: CI invocations unchanged (verified by reading `ci.yml`; CI itself not runnable from here); `--runs 5` on the M2 catalog produces the `pass^k` table; no runtime code touched (`src/jarvis` diff is empty).
- **Verified (real runs, 2026-09-06):** M2 `--runs 1` console output identical to baseline; M2 `--runs 5` 9/9, `pass^1…5 = 1.0000`, 27 s, zero leftover temp dirs; M4 `--runs 1` console identical, `--runs 3` 10/10 / 0 unverifiable claims; forced-failure catalog keeps one 0700 state dir per failing run with the path printed; `--runs 0`/`abc` rejected with exit 2; `ruff check .`, `ruff format --check .` (184 files), `mypy src/jarvis` (78 files), `mypy --strict` on the new module + test, `python -m pytest`: **865 passed, 2 skipped**.
- **Not verified:** GitHub Actions execution of the unchanged invocations; any real-model (`llm-eval.yml`) run.
- **Limits:** on scripted/KB-only drivers `pass^k` measures determinism; model reliability needs the weekly Ollama lane (→ C6b). No version bump: harness/tests/docs only (RELEASING precedent).
- [ ] **C6b (follow-up, owner to schedule):** extend `pass^k` to the real-model lane — `tests/test_fault_injection_live.py` corpus repeated K times under `RUN_LIVE_LLM=1`, and `m4_grounding.py --runs K` on a host with Ollama (the two refusal cases then exercise `knowledge/ai_answer.py`). Needs a workflow edit + an Ollama host; cannot be executed or verified from this sandbox.

### B-C11 · Hash-chained task journal (evidence chain) — *pre-approved (D4); low risk* (S) — `[x]` done 2026-09-06 (ADR-0028; **1.21.0**; committed per D5)
Origin: research §3.4 (SAL evidence chain), §3.5 (ACS); precedent `context/store.py` M9c chain.
- [x] Inspected `journal/sqlite.py` (schema, every writer, no DELETEs), `context/store.py` M9c chain, `safety/integrity.py` + `_cmd_doctor`, all journal callers (`orchestrator.py`, `gui/service.py`, `brief/engine.py`, `mcp_server.py`), ADR-0008 undo revalidation. **Finding:** a literal M9c copy (digest over current rows) would be *healed* by the next legitimate write on a table written every task — deletions would go unreported. Design changed to an append-only `prev_hash`-linked event chain (ADR-0028 context).
- [x] ADR-0028 written (D1 event chain in-transaction; D2 concurrency by lock ordering; D3 verify matrix; D4 additive backfill under `BEGIN IMMEDIATE`; D5 `doctor` surface, no new verb; D6 limitation + anchoring left to owner).
- [x] Implemented: `journal_chain` + `journal_meta` tables (additive), `_append_event`/`_chain_row` linked inside each writer's transaction, `verify_chain()`; `jarvis doctor` text + `--json` + exit 1. `__version__` **not** bumped (belongs to the authorized commit/tag step).
- [x] Tests `tests/test_journal_chain.py` (+18): edit / delete / forge / tail-event delete / interior-event delete / event edit / head rewrite / wiped chain table; pre-chain migration (schema replica) + downgrade-write detection; no-op writes append nothing; read-API shape pinned; 3 concurrent writer processes; 4 simultaneous first-opens; doctor ok + tampered (text/JSON/exit).
- [x] Docs: README integrity section + index row; CHANGELOG block; AGENT-EXPERIENCE entry; PLAN R-II row.
- Acceptance: `jarvis doctor` covers the journal ✔; performance measured ✔ (below); old DB opens and reads identically ✔.
- **Verified (real runs, 2026-09-06):** full gate `ruff` / `ruff format --check` (186 files) / `mypy src/jarvis` (78 files) / `python -m pytest` **883 passed, 2 skipped**; M3 fault gate 35 vectors / **0 escapes**; M2 `--runs 2` 9/9. Live CLI on a scratch state dir: real `fs.disk_free` task → 3 events / 2 rows; hand-flipped status → `journal chain  : TAMPERED — task:… differs from its last attested write`, exit 1, `--json clean=false`; `jarvis tasks`/`status` unchanged. Mutation checks: D2 invariant broken on purpose → concurrency test fails with `UNIQUE constraint failed: journal_chain.seq` (race, 1 of 3 runs), restored → passes. Timing: 2 000-row legacy backfill 49 ms; 0.99 ms vs 0.79 ms per write; verify 2 600 events in 28 ms; 4 writer processes × 150 tasks → contiguous chain; 6 simultaneous first-opens → exactly one backfill.
- **Not verified:** GitHub Actions on the changed tree (a re-run of the full suite at the end of the turn showed 2 failures in `tests/test_knowledge_live.py` — `api.github.com` began answering **401** from the sandbox; those tests import nothing this item touched and passed in the 883-run minutes earlier; `-m "not live"` → 874 passed); behaviour on SQLite builds older than this sandbox's 3.40 (`ON CONFLICT … DO UPDATE` needs ≥ 3.24, which the M9c store already relies on).
- **Limits:** tamper-*evidence*, not prevention (ADR-0028 D6); edits made *before* the upgrade are unknowable and reported as `legacy`. Coverage check: `mark_undone` delegates to `finish_task`, so undo status changes are chained too (verified by reading, 2026-09-06).
- [ ] **C11b (owner option):** anchor `chain_head` off-machine or in a separate owner-written pin (e.g. `jarvis doctor --pin-journal`) so a consistent rewrite of the whole chain is also detectable. Not started: it makes `doctor` a writer or adds an external dependency — owner call.

### B-C3 · Doorway survival: `sd_notify` watchdog + `STATUS=` + per-unit hardening — *OWNER-Q* (S–M) — `[x]` **done 2026-09-06** (ADR-0029 accepted D7/D8; implemented; ships in 1.22.0 with C1)
Origin: research §4.2 (`sd_notify(3)`), §3.7 (systemd hardening); baseline measured 2026-09-06: doorway / brief / charter units all scored **9.6 UNSAFE** in `systemd-analyze security --offline` (9.8 in `--user` view).
- [x] Inspected `cli/serve.py` (`run_server`, `unit_content`, install/status), `brief/install.py`, `safety/charter.py::unit_documents`, `execution/runner.py` (`sudo -n`, `env = dict(os.environ)` → children inherit env), brief engine (no playbooks, no network; `notify-send` only), playbook `requires_root` by tier (T0: 0 of 38; T1: 3 of 10; T2: 6 of 10), GUI `bridge/resident.py` (health poll only), `socketserver.serve_forever` → `service_actions()` hook.
- [x] **Finding that reshaped the design:** in a *user* service manager every seccomp-backed directive implies `NoNewPrivileges=yes` and every mount-namespace directive needs a user namespace; both break `sudo -n` (`setpriv --no-new-privs sudo -n true` → "no new privileges flag is set"; `unshare -U sudo -n true` → "must be owned by uid 0 and have the setuid bit set"); `UMask=0077` is unioned by sudo. ⇒ units that may run T1/T2 cannot take score-moving directives.
- [x] ADR-0029: D1 stdlib notify client, D2 doorway `Type=notify` + `WatchdogSec=30` with **no hardening** (score stays 9.6, reason stated), D3 brief unit opt-in `--harden` profile (**9.6 → 2.0**), D4 charters unchanged, D5 tests, D6 non-goals, failure-modes table, owner-machine commands.
- [x] Owner decisions: D1+D2 **accepted** (§D7); D3 **opt-in `--harden`** (§D8); C3b/C3c kept as options.
- [x] Implemented: `src/jarvis/system/sdnotify.py`; `cli/serve.py` `DoorwayServer` (ping in `service_actions()`, `READY` after bind, token-free `STATUS`, `STOPPING` on shutdown; env consumed before any child can spawn); `unit_content()` D2 text; `brief/install.py` `HARDENING_DIRECTIVES` + `service_content(harden=, state=)` + `install_timer(harden=)` with refuse-before-write on unquotable state dirs; CLI `brief install --harden`.
- [x] Tests `tests/test_sdnotify.py` (+30): fake systemd (abstract `AF_UNIX` datagram), cadence with fake clock, PID mismatch, malformed values, env consumed (in-process **and** a real child process), live doorway conversation, hung request does not starve the ping, `STOPPING=1`, unit-text pins for both units (doorway must NOT contain any confinement directive), offline analyser re-measure (skips when absent).
- [x] Docs: README (brief `--harden`, residency paragraph), kernel CHANGELOG/AGENT-EXPERIENCE/PLAN, ADR status, root CHANGELOG/AGENT-EXPERIENCE.
- **Verified (2026-09-06):** ruff / `ruff format --check` (189 files) / `mypy src/jarvis` (79 files) clean; `python -m pytest -m "not live"` **904 passed**; new tests stable over 3 runs; **4 mutations** each caught (ping moved into the handler; env not consumed; full instead of half interval; `NoNewPrivileges` slipped into the doorway unit). Real CLI under a fake `NOTIFY_SOCKET` (`WATCHDOG_USEC=1000000`): `READY=1` 0.10 s after start, `WATCHDOG=1` at 0.25/0.75/1.25/1.75 s, `STATUS=serving; 1 request(s); last: GET /v1/health -> 200`, `STOPPING=1` on SIGTERM, exit 0. Offline analyser on the rendered units: brief plain 9.6 → `--harden` 2.0 (`--threshold=25` exit 0); doorway 9.6 unchanged (asserted).
- **Not verified:** a live user service manager — watchdog-triggered restart, `Type=notify` readiness gating of `systemctl --user enable --now`, one confined brief run under seccomp + userns. **Owner-machine commands** (ADR-0029 Consequences): `jarvis serve install && systemctl --user status jarvis-serve` · `kill -STOP $(systemctl --user show jarvis-serve -p MainPID --value); sleep 35; journalctl --user -u jarvis-serve -n 5` (expect "Watchdog timeout" → restart) · `jarvis brief install --on daily --harden && systemctl --user start jarvis-brief.service && journalctl --user -u jarvis-brief -n 30`.
- **Limits:** supervision, not confinement, for anything that may escalate; `--harden` stays opt-in until one verified real run (promotion criterion); watchdog kills a wedged doorway mid-step (handler threads are daemon threads — pre-existing behaviour on any stop, unchanged).
- [ ] **C3b (owner option):** confined profile for `tier_ceiling = 0` charters once the brief profile is proven on real hardware (T0 tools need wider syscall/address-family allowances).
- [ ] **C3c (owner option, architectural):** a second doorway mode `jarvis serve --max-tier 0` that refuses T1/T2 and can therefore take the full confinement profile.

### B-C1 · Owner-authored, narrowing-only argument policy — *OWNER-Q; security-sensitive* (M) — `[x]` **done 2026-09-06** (ADR-0030 accepted D9–D11; implemented; **1.22.0**)
Origin: research §3.3 (Progent monotonic confinement, CaMeL), §3.4 (AgentSpec: human-owned rules). Primary source re-fetched for the ADR: Progent v3 HTML §4.1–4.2 (forbid-before-allow; narrowing vs expansion).
- [x] Inspected `safety/tiers.py` (`check_argv` 133–175), the three call sites (`core/orchestrator.py` 224 / 345 / 536), `_undo_payload` (no playbook id, no params), `_rebuild_undo_steps`, `_revalidate_undo_step`, `planner/catalog_common.py::clean_arg`, `integrity.default_scope()`, `safety/charter.py` JSON conventions, `cli/mcp_server.py::_orchestrator`, params keys by running `match()` on the catalogue (`names`, `path`, `src`/`dst`, `unit`, `text`, `app`/`tokens`, `pid`, `name`, `arg`).
- [x] ADR-0030 drafted (D1 rules bind to **params**; only-refuse effects; D2 one enforcement point per site; D3 fail closed per named playbook, T0 continues; D4 `policy lint|show|explain` + `doctor` line + additive `jarvis_status` key; D5 tests; D6 non-goals; failure-mode table).
- [x] Owner decisions: **D-A = A3** integrity-scoped + lint hint (§D9); **D-B = B2** (plans list every refusing part) + **U3 + U1** (undo artefacts carry `origins`; legacy skip) (§D10); **D-C = ship empty**, example via `jarvis policy example` (§D11); "do all".
- [x] Implemented: `src/jarvis/safety/argpolicy.py` (`Rule`, `Policy`, `parse_policy`, `load_policy`, `PolicyCache`, `EXAMPLE_POLICY`); `core/orchestrator.py` (policy check at the three sites; `_check_undo_origins`; `_undo_payload(plan, origins)` additive key, passed at both `store_undo` sites); `safety/integrity.py` (`state_dir()/policy` in scope); `cli/app.py` (`_cmd_policy`, argparse group, `doctor` line + JSON key, `status` line + key, `_argument_policy_view`); `cli/mcp_server.py` (`jarvis_status` additive key). Version 1.21.0 → **1.22.0** (pyproject, `__init__`, spec + changelog entry, PKGBUILD, READMEs, CHANGELOG `[1.22.0]`).
- [x] Tests `tests/test_argpolicy.py` (+40) — see kernel CHANGELOG for the list; existing suite is the "absent = identical" oracle.
- [x] Docs: kernel README (new "Argument policy" section, index row), CHANGELOG `[1.22.0]`, AGENT-EXPERIENCE, PLAN row, ADR status; root README version, CHANGELOG, AGENT-EXPERIENCE (HUD seam note).
- **Verified (2026-09-06):** ruff / `ruff format --check` / `mypy src/jarvis` (80 files) clean; `python -m pytest -m "not live"` **941 passed**; new tests stable over repeated runs; **6 mutations** each caught (`re.match` for `re.search`; `realpath` dropped; allow-match terminating evaluation; broken rule failing open; undo origins never checked; B1 instead of B2). **M3 fault gate 0 escapes** in three configurations: no policy (35 vectors), permissive policy naming all 20 T1/T2 playbooks (35 vectors), deny-all policy (34 vectors, 0 escapes; the driver's exit is 1 there only because one *test* expects `install htop --dry-run` to reach dry-run and the deny-all file refuses it first — identical to how validator refusals pre-empt dry-run today, e.g. `delete the file /etc/shadow`). `jarvis policy lint` on the example: `ok: 3 rule(s) bind to 6 playbook(s)`; `jarvis policy explain "uninstall grub"` → `REFUSED — … rule 'no-kernel-removal' … boot- and login-critical`; import cycle `mcp_server` ↔ `app` checked (lazy import inside `_tool_status`).
- **Not verified:** nothing outstanding (no sandbox limits for this item). Real-world rule authoring ergonomics are the owner's to judge — `jarvis policy explain` exists for exactly that.
- **Limits:** rules see *params*, not argv — a rule cannot express "no `-y`" (by design: argv is kernel-owned); Python `re` has no timeout, so lint rejects nested quantifiers and > 200-char patterns instead; `"*"` binds by key name only (a playbook that names its path param differently is not covered — lint's warning shows what each playbook produces); the deny-all + dry-run interaction above.
- [ ] **C1b (owner option, future ADR):** LLM-*proposed* narrowings (Progent's headline) behind the same only-refuse check — the planner never sees tool output today, so the injection vector this defends against is absent; not proposed now.
- [ ] **C1c (owner option):** `jarvis policy lint --diff OLD NEW` reporting whether an edit is a narrowing or an expansion (textual, no SMT) — cheap once the owner has more than a handful of rules.

### B-C4 · Environment signals as briefing inputs (propose-only) — *OWNER-Q* (M)
Origin: research §5 (logind `PrepareForSleep`/`PrepareForShutdown`, session lock, NetworkManager/UPower, inotify, idle), §5.3 (Horvitz threshold), §5.4 signal table.
- [ ] Inspect `brief/engine.py compose()/decide()/deliver`, `BriefLedger`, ADR-0021 deliver rules, ADR-0018 doorway loop, `voice/` fixed-argv pattern.
- [ ] Fetch-and-cite the exact UPower / NetworkManager interface names (research §11 lists them as unverified) before the ADR.
- [ ] ADR draft: (D1) which signals (owner prunes the §5.4 table); (D2) **poll-at-briefing-time only** (`busctl get-property` fixed argv, works in the oneshot) vs an opt-in **listener in the doorway** (`busctl monitor`/`dbus-monitor` fixed argv, long-lived); (D3) interruption-cost inputs to `decide()` (idle, lock, sleep-imminent suppress); (D4) wire shape to the HUD (the audit showed the seam is where defects hide).
- [ ] Owner accepts → implement behind the existing opt-in; every signal is a *line in the briefing*, never a trigger; tests with captured `busctl` output fixtures.
- Acceptance: with no bus present the briefing is byte-identical to today; with fixtures, items and suppressions appear as specified; ADR-0017 D3 intact (no execution path added).
- Verification plan: fixture tests + full gate; **live signal capture on the owner's machine** (commands in the ADR: `busctl --system monitor org.freedesktop.login1`, etc.).
- Sandbox limits: no system/session bus, no `gdbus`/`dbus-monitor`, no `notify-send` → live sensing cannot be verified here.

### B-C2 · Resumable task log + idempotency flags (offer resume/undo after a crash) — *OWNER-Q; touches the sole execution path* (M–L)
Origin: research §2.3 (Managed Agents session log), §4.3.
- [ ] First: **measure** — query the journal schema for interrupted/failed multi-step tasks to establish whether the problem occurs (data-driven go/no-go, recorded in the ADR).
- [ ] ADR draft: per-playbook `idempotent` flag; per-step `started/finished` events; on next invocation, an interrupted task is *reported* with the options resume (idempotent steps only, otherwise ask) / undo / dismiss — never auto-resumed; model-visible state (if any) machine-owned JSON.
- [ ] Owner accepts → implement; tests: crash between steps (fake runner raising), resume path, non-idempotent step asks, undo path unchanged.
- Acceptance: existing 856 tests unchanged in outcome; kill-switch semantics (exit 130) unchanged.
- Verification plan: unit + fault suite + full gate.
- Sandbox limits: none.

### B-C7 · MCP `2026-07-28` migration plan — *OWNER-Q; two-repo* (S plan / M do)
Origin: research §8.1. Kernel echoes any date-shaped `protocolVersion` (fallback `2024-11-05`); HUD pins `2025-03-26`; neither uses Roots/Sampling/Logging.
- [ ] Fetch and cite the **specification text** (not the blog) for the stdio transport under the stateless core; record what actually changes for `initialize`/`notifications/initialized`.
- [ ] Write the plan as an ADR (kernel) + a linked note in the HUD docs: negotiate both, keep fallback, deprecation dates.
- [ ] Owner decides whether to execute; if yes, implement in kernel then HUD, with live handshake capture as in the audit.
- Verification plan: live `jarvis mcp serve` handshake capture (works in sandbox); HUD unit + QML gates with GL stubs.
- Sandbox limits: none for stdio.

### B-C8 · `SKILL.md` import/export for app packs — *OWNER-Q* (M)
Origin: research §8.2; tiers remain the enforcement regardless of `allowed-tools`.
- [ ] Inspect ADR-0026 pack loader (`gui/appskill.py`), receipts (`planner/skills.py`).
- [ ] ADR draft: mapping table pack ⇄ `SKILL.md` frontmatter; on import the receipt and tier ceiling are applied, `allowed-tools` is advisory only and is *checked against* the pack's declared actions.
- [ ] Owner accepts → implement + round-trip tests.
- Sandbox limits: none.

### B-C10 + B-C11 bundle option · Release provenance — *OWNER-Q* (S)
Origin: research §3.6; `release.yml` has no checksum manifest and no PyPI step.
- [ ] ADR draft (may be bundled with C11 as a "provenance" ADR): `SHA256SUMS` generated in `release.yml` and attached to the draft release; Trusted Publishing + PEP 740 attestations documented as the path if an index is ever used.
- [ ] Owner accepts → implement the workflow step; verify with a `workflow_dispatch` run **only if the owner permits a push**.
- Sandbox limits: cannot run GitHub Actions here; the step is testable locally with `sha256sum -c`.

### B-C9 · Owner-run offline prompt optimization (GEPA-style) — *OWNER-Q* (M)
Origin: research §6.2; ADR-0013 non-goal preserved (runtime never self-edits).
- [ ] ADR draft only at first: inputs (eval catalog + injection corpus), loop (owner-run script, local model), output (a *candidate* prompt file + diff + eval report; never applied automatically), acceptance rule (must not regress the injection corpus or `pass^k`).
- [ ] Owner decides whether to build the script.
- Sandbox limits: no Ollama → the script cannot be exercised here beyond dry-run.

### B-C5 · Sandboxing the hands (Landlock via `ctypes` vs bubblewrap) — *OWNER-Q; dependency decision* (L)
Origin: research §3.7; sandbox check 2026-09-06: Landlock ABI 2 present on kernel 6.1; `bwrap` absent.
- [ ] ADR draft comparing: (a) `ctypes` Landlock self-restriction around T0 read-only steps (no dependency; ABI-gated best-effort; **explicit requests fail closed**), (b) `bwrap` (external binary, new dependency), (c) defer. Include what each does *not* protect against.
- [ ] Owner decides; implement only if (a) or (b) is chosen.
- Sandbox limits: Landlock (a) is testable here (ABI 2 → filesystem rules only); (b) is not.

## C. Verification matrix (sandbox vs owner machine)

| Capability | Sandbox (this session) | Owner's machine |
|---|---|---|
| Unit/type/lint gates, M2/M3/M4 evals (stub LLM) | Yes | Yes |
| Live LLM lanes (`RUN_LIVE_LLM`, `pass^k` with a real model) | **No** (no Ollama) | Yes |
| `systemd-analyze security --offline` on unit text | Yes (systemd 252) | Yes |
| Watchdog restart, `systemctl --user status` STATUS line | **No** (no user manager) | Yes |
| `sd_notify` protocol bytes (READY/WATCHDOG/STATUS/STOPPING) | Yes — fake systemd on an abstract `AF_UNIX` datagram socket, real CLI process (C3) | Yes |
| D-Bus signals (logind/NM/UPower), `notify-send` | **No** (no bus, binaries absent) | Yes |
| MCP stdio handshake capture | Yes | Yes |
| Landlock self-restriction | Yes (ABI 2, fs rules) | Depends on kernel |
| GitHub Actions runs | **No** (api.github.com unreachable) | Yes |

## D. Decision log (owner answers; filled as they arrive)

| # | Question | Answer | Date |
|---|---|---|---|
| D1 | Scope of "continue" | **Full sequence, gated per ADR** (draft ADR → owner acceptance → implement + test + docs → next). | 2026-09-06 |
| D2 | Execution order | **Proposed order accepted:** C6 → C11 → C3 → C1 → C4 → C2 → C7 → C8 → C10 → C9 → C5. | 2026-09-06 |
| D3 | Commit/push policy | Owner's words: *"No merge, and all, that is what I wanted to say."* Recorded as: **never merge** (guideline 23 reaffirmed). Whether each finished item may be committed + pushed to the arena branch was not stated explicitly; to be confirmed with the owner when the first item is ready, not assumed. | 2026-09-06 |
| D4 | Per-item gating | **Pre-approve low-risk, pause on security:** C6, C11, C7-plan, C10 may go ADR → code without a pause; C1, C2, C3, C4, C5, C8, C9 pause at the ADR for acceptance. | 2026-09-06 |
| D5 | Commit/push (asked again with C6 + C11 ready) | Owner: *"Do the first option, BUT JUST DON'T MERGE."* = **commit + push now, one commit per item, to `arena/01a0717a-j-a-v-r-i-s-combined` only; never merge.** A4 unblocked. | 2026-09-06 |
| D6 | Kernel version | **Bump 1.20.0 → 1.21.0 now** (C11 is the first runtime change); PKGBUILD/spec synced; `pip install -e .` re-run so `test_package` sees the dist version. | 2026-09-06 |
| D7 | ADR-0029 D1+D2 (doorway watchdog, no hardening) | **Accepted — implement now.** Live watchdog restart still to be observed on the owner's machine (commands in the ADR). | 2026-09-06 |
| D8 | ADR-0029 D3 (confined brief unit) | **Opt-in `--harden`** (default unit unchanged; promotion to default-on after one verified real run). C3b/C3c stay recorded as owner options. | 2026-09-06 |
| D9 | ADR-0030 D-A storage | **A3** — integrity-scoped + `jarvis policy lint` re-baseline hint. | 2026-09-06 |
| D10 | ADR-0030 D-B `plan` / `undo` | **B2** (list every refusing part) + **U3 + U1** ("do all": undo artefacts carry `origins` and are policy-checked; legacy artefacts skip). | 2026-09-06 |
| D11 | ADR-0030 D-C + go-ahead | **Ship empty**, example via `jarvis policy example`; implement now, commit + push, no merge ("Do all"). | 2026-09-06 |

## E. Definition of done — per item (guideline 22 self-review)

- [ ] Inspected before modifying; diff limited to the item; every change justified in the ADR or CHANGELOG.
- [ ] No new dependency; interfaces preserved or the break flagged.
- [ ] Failure modes listed and each degrades to today's behaviour.
- [ ] Tests added for the new behaviour **and** the absent-precondition path; full gate green (ruff, ruff format, mypy strict, pytest; M2/M3/M4 where relevant).
- [ ] CHANGELOG + AGENT-EXPERIENCE + PLAN row + README (if user-visible) updated in the same change-set.
- [ ] "Verified / Not verified / Limits" written from actual runs; sandbox limits named.
- [ ] Nothing merged; `main` untouched; commits/pushes per §D3 only.

§E outcomes: **C6** all seven ✔ (2026-09-06) · **C11** all seven ✔ (2026-09-06) · **C1** all seven ✔ (2026-09-06; absent file = identical proven by the pre-existing suite; interfaces additive: new verbs, new JSON keys, undo artefact gains `origins`) · **C3** all seven ✔ (2026-09-06; absent-precondition path = no `NOTIFY_SOCKET` → inert, tested; interfaces additive: unit text gained lines, `service_content`/`install_timer` gained keyword-only parameters, `build_server` gained an optional 4th argument).

## F. Recommendations recorded on the way (not in scope; guideline 15)

| # | Found while | Recommendation |
|---|---|---|
| F1 | C6 full gate | Bare `pytest` (venv entry point) fails `tests/test_intent_model.py::test_vocabulary_covers_the_whole_catalog` with `ModuleNotFoundError: training`; only `python -m pytest` puts the repo root on `sys.path`. CI's `unit_gate.py` uses `sys.executable -m pytest`, so the gate is unaffected. Consider `[tool.pytest.ini_options] pythonpath = ["."]` so both spellings agree. Pre-existing; reproduced with the C6 files stashed. |

