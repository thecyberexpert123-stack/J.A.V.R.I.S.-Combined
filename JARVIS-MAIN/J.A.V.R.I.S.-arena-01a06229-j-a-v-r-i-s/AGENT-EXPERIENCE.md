# Agent Experience Log

Running record of experiences, challenges, and learning moments during development (owner guideline #4).
One entry per milestone or significant event; newest at the bottom. Written honestly — this is a working log, not marketing.

---

## 2026-09-02 · Engagement start & governance phase

- **Repository found effectively empty.** `main` @ `6e452fd` ("Initial commit") contained a single `README.md` whose entire content was the title `# J.A.V.R.I.S.`. Everything — mission, scope, architecture — had to be established from the owner's brief. Lesson reinforced: on greenfield repos, requirements elicitation *is* the first engineering task.
- **Early misstep, corrected:** in the very first turn I began tool-assisted reconnaissance immediately upon receiving the engagement. The owner stopped me and made two things explicit: (1) no action without instruction, (2) **never merge anything, ever**. Both are now standing directives, recorded in `docs/PLAN.md` §10. Learning: in a governed engagement, even read-only exploration should follow the owner's sequencing, not the agent's enthusiasm.
- **Name discrepancy noticed:** repository is named `J.A.V.R.I.S.` while the owner's brief consistently says `J.A.R.V.I.S`. Flagged for owner ruling rather than silently picking one — it affects the README, CLI name, and Python package name. (See PLAN §13.1.)
- **The hardest conversation — the 98% target.** The owner requires a 98% success rate. Current evidence says state-of-the-art computer-use agents score ~63.5–76% on OSWorld and ~20% on long-horizon OSWorld 2.0 (see `docs/RESEARCH.md` R1). Blindly promising 98% would violate the owner's own anti-vibe-coding directive. Resolution drafted: scope the metric to a versioned, execution-verified task catalog and publish all eval results so the number is auditable — and *refuse or escalate* outside the catalog, which aligns exactly with the owner's rule "does not blindly do any task." Awaiting owner confirmation of that definition (PLAN §13.2).
- **Wayland reality check.** Research confirmed that the single hardest technical constraint for point 11 (GUI control) is not code volume but the Wayland security model: global input injection is intentionally blocked; xdotool/pyautogui-class tools fail natively; Fedora 43+ ships no X11 session at all. The reliable paths are AT-SPI 2 for reading UIs, per-compositor DBus backends, and uinput (`ydotool`) for input — the last requiring explicit user consent via a setup wizard. Design consequence captured in PLAN §4.6.
- **Working method adopted:** research dossier → plan with acceptance criteria per milestone → owner sign-off gates at M0 and every milestone → only then implementation. No code exists yet, by design.

---

## 2026-09-02 · Charter expansion (guidelines 11–22), name ruling, and a self-inflicted documentation defect

- **Owner issued engineering directives 11–22** (never fabricate; inspect before modifying; preserve existing work; minimal and justified changes; security-first; dependency discipline; compatibility; failure awareness; no scope creep; human authority; verification honesty; continuous self-review). Recorded verbatim-faithful in `docs/GOVERNANCE.md` with an operationalization mapping (Part D) so each directive has a concrete project control rather than a slogan.
- **Name ruling received:** canonical name **JARVIS** — *"Just A Rather Very Intelligent System"* — resolving PLAN §13.1. Remaining open decisions: 98% metric definition, v1 interaction surface, model posture, M0 commit authorization.
- **Incident (honest record):** while updating `docs/PLAN.md` for the name ruling, I issued a malformed edit (mismatched search/replace parameters). The fuzzy matcher corrupted the anti-goals bullet; my first repair restored the bullet but left a dangling fragment; on close inspection the document turned out to be **truncated mid-§7** — sections 8–13 were gone. Root cause: stacking edits on a file without verifying between operations. Repair: full rewrite from the known source content with all intended updates folded in, followed by structured verification (section header scan, tail check, anomaly grep, line count). Lesson institutionalized: **after every edit batch on a governed document, verify structure — never assume an edit applied cleanly.** This is directive #12 and #22 operating on my own work, and it cost far less here than it would have in code.
- **Verification-honesty note:** all repo changes this session are documentation only; no code, no commits, no pushes. Working tree holds: modified `README.md`, new `docs/PLAN.md`, `docs/RESEARCH.md`, `docs/GOVERNANCE.md`, `CHANGELOG.md`, `AGENT-EXPERIENCE.md`.

---

## 2026-09-02 · M0 executed: decisions delegated by owner, baseline committed

- **Owner delegated the four open decisions** ("leaving this to you to decide which should be made and is better at this moment"). Interpretation recorded up front: this covers the 98% metric, v1 surface, model posture, and M0 commit authorization; the never-merge standing order was explicitly untouched. Each decision was executed as a written ADR with context/decision/consequences rather than a silent choice: ADR-0001 (scoped ≥98% catalog metric), ADR-0002 (CLI+TUI first), ADR-0003 (hybrid router, local-first), ADR-0004 (M0 toolchain).
- **Self-review caught a violation of my own making:** the first `pyproject.toml` draft shipped `license = "Proprietary-Placeholder-None-Yet"` — exactly the placeholder junk guideline 1 forbids. Root cause: filling a required field with a marker instead of *omitting* the field and documenting the pendency. Fixed: license field omitted with an explanatory comment; LICENSE selection recorded as an open owner decision (PLAN §13.6, recommendation MIT/Apache-2.0). Lesson: for owner-reserved decisions, the correct artifact is an *absence plus a note*, never a stand-in value.
- **Environment note:** the sandbox provides Python 3.11.2 but no preinstalled lint/test tooling. A disposable `.venv` was used for gates; it is `.gitignore`d and excluded from session snapshots, so future sessions must recreate it (`python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`). Documented here so nobody mistakes a missing venv for a broken build.
- **Verified (locally, real runs):** `pip install -e ".[dev]"` clean (ruff 0.16.5, mypy 2.3.1, pytest 9.1.1); `ruff check .` pass; `ruff format --check .` pass; `mypy src/jarvis` pass; `pytest` 3/3 pass (packaging-integrity smoke tests).
- **Not verified (honest):** GitHub Actions runner execution — at log-writing time the workflow had only just been pushed; the claim "CI green" is made only after an observed successful run. Distro-container matrix and all functional behavior remain future work (M1+), as planned.
- **Scope discipline:** M0 contains zero runtime dependencies and no stub modules — the package root is intentionally just version metadata plus three real packaging-integrity tests. Everything else waits for M1.
- **Push incident (honest record):** the initial push was rejected by GitHub — the sandbox's GitHub App credential lacks the `workflows` permission, so `.github/workflows/ci.yml` may not be pushed by the agent. No circumvention was attempted (that control exists for good reason). Resolution: commit split — all governance + skeleton pushed; the CI workflow file remains complete in the working tree, ready to push the moment the GitHub connection carries `workflows` permission (owner reconnect in Arena) or the owner adds the file themselves. CI status remains "defined, not yet observed on a runner."
- **Incident RESOLVED (same day):** owner upgraded the connection ("Permission given"). Verified: push of `ci.yml` accepted (commit `feea3e2`); GitHub Actions run **33635129000** triggered and **observed green — 3/3 matrix jobs passed** (py3.10, py3.11, py3.12: ruff lint, ruff format, mypy, pytest). The M0 acceptance criterion "CI green on skeleton" is now an *observed fact*, not an assumption. Non-blocking annotation noted for the next change-set: `actions/checkout@v4` / `actions/setup-python@v5` target Node 20 and are force-run on Node 24 (deprecation warning) — recommend a deliberate version bump, not an emergency fix (guideline 19).

---

## 2026-09-02 · M1 Kernel implemented and verified (193 unit + 4 live tests)

- **Scale of the milestone:** ~20 source modules + ~2,700 lines under `src/jarvis/` and `tests/`: SENSE fingerprinting, five package-manager adapters (apt/dnf/pacman/zypper/apk), guarded argv-only runner, static safety analysis, tiered approval, ten seed playbooks with verification + undo, SQLite journal, orchestrator with kill-switch, argparse CLI. Zero runtime dependencies (ADR-0005) — deliberate, justified by guideline 16 and by making distro-container evaluation dependency-free.
- **The test suite caught a genuine security bug before it could ship:** my first blocklist joined argv with NUL for pattern scanning, which broke every `\s`/`$`-anchored regex — `rm -rf /`, `mkfs`, `shutdown` would have sailed through the static reviewer. Root cause: cleverness (NUL joiner) defeating the semantics of the pattern language (anchors). Fix: space-joined scanning (safe because validated tokens cannot contain whitespace) plus moving program-name patterns to argv[0]/`-c`-content checks — which also eliminated a false positive (`apt install init`). Lesson: security patterns must be tested against both attack *and* usability cases; the adversarial tests I wrote first are what found it.
- **A second catch from my own review layer:** the strict end-of-options rule rejected `df -h -- /` — a completely standard read-only command. Rather than weakening the rule (which blocks flag smuggling out of tampered journals), the playbook now passes path operands without a marker. Rules stay strict; data stays shaped for them.
- **Tooling honesty note:** several file-edit tool calls in this milestone were emitted malformed (missing path parameters), wasting turns; I caught every resulting defect via re-reads and gate re-runs rather than assuming success, and switched to full-file writes where edits proved fragile. Recorded here because directive 22 applies to my process, not just the code.
- **Verified (real runs):** `ruff check` clean; `ruff format --check` clean; `mypy` clean (20 files); `pytest` 193 passed; `RUN_LIVE=1` live integration on this Debian 12 sandbox: 4/4 (real `system info` task, real empty-index `search` reported honestly, clean privileged-step failure under `sudo -n`, `python -m jarvis status` JSON correct).
- **Not verified (honest):** real package install/remove/upgrade on live apt/dnf/pacman/zypper/apk backends — this sandbox cannot mutate safely, so that evidence comes next from the distro-container evaluation in CI (separate change-set, same milestone). Service playbooks are exercised only for honest-unsupported behavior here (sandbox systemd state makes real start/enable tests environment-dependent).
- **Design decisions made en route (documented, reversible):** sudo invocation is `sudo -n --` (never interactive, never stored); `TaskStatus.DRY_RUN` added to the enum when the CLI needed to distinguish dry-runs from refusals; `ExecResult.timed_out` defaulted False; verify functions accept `ExecResult | None` elements (skipped steps are real).

---

## 2026-09-02 · M1 container-eval harness built; sandbox ceiling discovered honestly

- The eval driver was validated locally first: 7/14 expectations met on this Debian 12 sandbox, and every failure is the *system telling the truth*: the sandbox ships **zero apt sources** (`/etc/apt/sources.list` empty — `apt-cache policy` shows no package files), so install/remove/info/undo correctly fail with "Unable to locate package". The driver itself, JSON output, task-id threading for undo, refusal cases, and privilege escalation all worked. `upgrade` passed vacuously (nothing to upgrade when no repos exist) — a noted limitation of exit-code-based verification for upgrades; deeper post-conditions need snapshots (already planned M3).
- `sudo -n` non-interactive escalation worked end to end on this host (`apt-get update` succeeded as root through the guarded runner), which validated the privilege path with a real sudo binary, not just fakes.
- Docker is unavailable in the sandbox, so the five-distro evaluation runs in GitHub Actions (workflow committed with the harness). Results land as artifacts; a curated baseline summary will be committed once observed — never before (guideline 11).

---

## 2026-09-02 · M1 CLOSED: container eval 70/70 observed across five distros

- **The acceptance gate is an observed fact:** run 33637847042 shows `eval <distro> :: 14/14 tasks passed` for debian-12, ubuntu-24.04, fedora, arch, and alpine. The 10 seed playbooks + undo round-trip + honest-refusal paths all pass on real package-manager backends. This is exactly the "verified, not asserted" model the scoped-98% metric (ADR-0001) is built on.
- **Infrastructure lessons en route:** (1) GitHub artifact names reject colons — matrix entries now carry sanitized names; (2) docker containers do not inherit `GITHUB_ACTIONS`, silently disabling the annotation channel until explicitly passed with `-e`; (3) artifact/log blob hosts are unreachable from this sandbox, so the eval driver now publishes its evidence as check-run annotations, which are readable through api.github.com — a good example of designing observability for the most constrained reader, not just the CI UI.
- **Vacuous-success watch:** locally, `upgrade` "passed" on a repo-less sandbox (nothing to upgrade). The container runs are the real evidence; the local run remains useful only as a driver-mechanics check. Recorded so nobody later cites the sandbox run as capability proof.
- **Verified:** 5/5 container jobs green twice (run 33637463538 after artifact-name fix; run 33637847042 with annotations); annotation evidence retrieved via API; local gates re-verified after every change (ruff, mypy, 193 unit + 4 live tests).
- **Not verified / deferred (honest):** live systemd `start`/`enable` against a real init (needs privileged systemd container — M3 plan); deep upgrade post-conditions (needs snapshots — M3); `pkg.remove`/service undo paths in containers (unit-tested; catalog expansion planned M3).

---

## 2026-09-02 · M2 implemented: LLM planner behind the safety kernel

- **Architecture before features:** the decisive M2 choice was made in ADR-0007 — the LLM only ever proposes natural-language intents that must pass the *same* strict matchers the deterministic engine uses; all execution stays in the M1 kernel. This turns "prevent hallucination" (owner point 6) from a prompt-engineering hope into a structural property: there is no code path from model output to a shell command that does not pass plan-builders, static argv analysis, the tier gate, verification, and journaling.
- **Tests caught a real routing bug:** `JARVIS_REMOTE_LLM=0` originally short-circuited *before* probing local Ollama — disabling planning entirely when a local model was up. The CLI routing tests failed loudly; fixed by reordering (local probe first, flag only gates the remote fallback). Lesson: privacy-critical toggles deserve their own branch tests, not just happy-path coverage.
- **The eval found a vacuous test case:** my injection-refusal eval case used request "install htop" — which the engine matches deterministically, so the malicious proposal never reached the planner (`llm_reqs=0` exposed it). The guard was fine; the case was measuring nothing. Fixed by using a non-engine request. Lesson: negative-path evals must assert they actually reached the component under test.
- **Tooling lesson (again):** string-replace patches on ruff-formatted files silently no-op'd twice (anchors drifted); one was caught only because a log printed the *old* note text. Rule adopted: structural changes go through full-file `write_file`; mechanical patches always assert their anchor hit.
- **Verified (real runs):** ruff lint+format clean; mypy clean (25 files); **231 unit + 4 live tests pass**; M2 eval **9/9** (deterministic scripted-LLM stub — no network, no weights); M1 container eval unchanged and still green in CI.
- **Not verified (honest):** no real-Ollama / real-API run exists yet (none available in this sandbox); the provider wire format is verified against a strict local HTTP stub that mirrors Ollama/OpenAI envelopes, plus documented config. First real-model smoke test is queued for the owner's machine or a CI job with Ollama installed (M3 candidate). Chat TUI (Textual) intentionally deferred (ADR-0007).

---

## 2026-09-02 · M3 implemented: the fault suite earned its keep on day one

- **The headline moment:** I wrote the injected-fault suite to prove the kernel holds — and it immediately found a real hole I had built. A tampered journal undo artifact could append to `/etc/shadow` via `tee -a`, because the file-path policy lived only inside the fileops playbook; the generic undo-replay path never re-applied it. The vector test failed loudly (runner.calls not empty). Fix: `_revalidate_undo_step` now applies `classify_for_edit` to `tee`/`truncate`/`rm` operands and `cp` destinations. Lesson (guideline 18 vindicated): the untrusted ingress is not the prompt — it is *any* persisted state that can shape execution, including our own journal. Defense-in-depth means re-validating at every boundary, not trusting upstream layers.
- **Two more self-review catches before any test ran:** the backup path was nondeterministic (timestamped → undo would restore from a path different from the one backed up to) — fixed with hash-addressed deterministic paths; and the registry's static tier would have let system-path file edits through the T1 gate — fixed by computing effective tier from built steps in the orchestrator. Static analysis of my own design docs caught both.
- **Real-file rollback evidence:** integration tests execute the actual `cp -p` → `tee -a` → verify → undo pipeline through the real LocalRunner and assert byte-identical restore. The backup directory is created at plan time so the executed copy step only copies.
- **Process note:** the string-patch fragility continued (ruff reformatting silently shifts anchors) — two patches no-op'd on stale anchors before I re-anchored with asserts. The rule from M2 stands: assert every anchor, prefer full rewrites for structural edits.
- **Verified (real runs):** ruff lint+format clean; mypy clean (28 files); **275 unit + 5 live tests** (1 honest skip: no Ollama in sandbox); fault gate **35 vectors / 0 escapes**; m2 eval 9/9 re-run; live file round-trips pass on this host.
- **Not verified (honest):** snapshot creation against a real snapper/timeshift (CI containers have neither; the honest-degradation path is what CI proves); snapshot restore stays manual by design (ADR-0008); real-model planning smoke deferred to an environment with Ollama (live test ready and skipping honestly).

---

## 2026-09-02 · M4 implemented: knowledge that cites or shuts up

- **The owner pointed at `torvalds/linux` as a knowledge source.** The engineering translation (ADR-0009): do NOT vendor a 4–5 GB tree into a repo capped at 128 MB of artifacts; treat upstream as a *reference* — kernel facts cite exact `Documentation/**` paths, and those citations are machine-verified against upstream on every CI push via the GitHub Contents API. Rationale: a citation that is never checked will rot silently; a checked citation fails loudly when upstream moves. First run live-verified both cited paths (kernel.rst 59 KB, proc.rst 107 KB fetched from torvalds/linux master).
- **Environment adversarial again:** this sandbox has no `man`/`whatis`/`sysctl` binaries and blocks raw.githubusercontent.com. That shaped the design for the better: grounding reads primary files directly (`/proc/sys/kernel/ostype`, `/etc/os-release`, `/usr/share/man` globs are the *data*, not the man binary), and the online layer got a swappable transport (api.github.com) that works in constrained environments. Constraint-driven design beats convenience-driven design.
- **The eval caught a catalog defect, not a code defect:** two eval questions were phrased so the deliberately-strict anchored matcher never saw their patterns → refusals. The agent behaved correctly (refuse rather than guess); the *test* was wrong. Fixed the phrasing. Repeated lesson from M2: when a guard fires, audit the guard and the test — in that order.
- **Structural honesty:** the KB loader refuses any fact without a source, so "answered ⇒ cited" is a property of the data structure, not a review-time promise. `verified` is only emitted when a verifier actually ran and passed; contradicted facts stay cited but say "not applicable here". The gate counts unverifiable claims; it read **0**.
- **Verified (real runs):** ruff lint+format clean; mypy clean (33 files); **297 unit + 6 live tests** (6/6 live here — including upstream verification, which works from this sandbox through api.github.com); M4 eval **12/12 online, 0 unverifiable claims**; M2 9/9 and M3 35/0 re-verified.
- **Not verified (honest):** non-kernel citations (man7/freedesktop/wiki URLs) are cited but not yet machine-checked in the eval (allowlist + HEAD probe exist; coverage is a config decision, deferred); answering is fact-lookup only — no LLM-summarized answers (deliberate, see REPORT-m4 limitations).

---

## 2026-09-02 · M5 implemented: GUI control that tells the truth about the desktop

- **Wayland fragmentation is a design input, not a bug to fight.** Wayland intentionally blocks global synthetic input; every compositor exposes a different surface. So M5 is a *capability matrix*, not a fake-universal API: `jarvis gui status` reports per-capability backends with explicit reasons, and `None` means "honest gap", never silent pretending. The M1 lesson (honest degradation) scaled from distros to desktops.
- **A unit test caught a real privacy leak:** typed text survived in the journal *step argv* even after being stripped from task params. Fix: redact the argv before recording (`<redacted: N chars sha256_16=…>`). Audit every sink, not just the obvious one — the same journal that protects you can leak for you.
- **Consent ordering matters:** capability resolution must not leak answers before consent, and consent must come after target disclosure (which window receives the keystrokes). The refusal test asserts the injection command *never ran*, not just that an exception was raised — negative tests must reach the component and verify the effect boundary (repeated M2 lesson, now applied to the kernel boundary).
- **CI as the lab, again:** the sandbox has no X at all, so the 15-task suite runs on a real Xvfb + i3 stack in CI through the actual CLI — including a real input-injection proof (typed text read back from a file). The headless subset runs everywhere (4/4 locally). Same honest-verification pattern as M1's containers.
- **T3 refused-by-policy shaped a safety decision:** window close is a graceful WM delete (apps keep their save prompts), so it is T2 with explicit data-loss disclosure rather than a fake "destructive" tier. Honest classification beats theatrical gating.
- **Verified (real runs):** ruff lint+format clean; mypy clean (41 files); **~327 unit + 9 live tests**; headless GUI eval 4/4; full suite + M2 9/9 + M3 35/0 + M4 12/0-unverifiable re-verified locally; 15-task X lane in CI.
- **Not verified (honest):** real Wayland sessions (GNOME/KDE/Hyprland) — wizard checks and backends are fixture-verified only; AT-SPI tree content on a real desktop; `gui describe` against a real vision model. All documented in REPORT-m5 §4.

---

## 2026-09-02 · M6 implemented: packaging that gets tested the way users install

- **The P1 was a path that only works in a repo.** The KB loaded via `Path(__file__).parents[3]` — fine in a checkout, silently broken in any wheel (site-packages layout differs). Classic packaging rot, caught by an M6 audit, not by a user. Fix: ship data inside the package (`importlib.resources`) and **prove it in a clean venv with `--no-index`** — then make every distro's install test grep for a KB fact so it can never regress silently. The acceptance test must test what the user actually runs.
- **Names normalize; test the normalized form.** `J.A.V.R.I.S.` became the unusable distribution name `jarvis-linux`. Renamed to `jarvis-agent` before 1.0.0 (last responsible moment), and the metadata unit test now pins the new name. Stale dist-info from the old name haunted one test run — when a package name changes, clean the old metadata too.
- **Native packages don't need magic.** deb/rpm/PKGBUILD all unpack the same wheel to `/usr/share/jarvis/lib` with a PYTHONPATH shim: zero runtime deps means zero dependency hell, no pip-in-postinst, nothing fetched at install time. The deb lifecycle was verified for real in this sandbox (dpkg -i → run → dpkg -r); rpm and PKGBUILD were verified *in their native distro containers* in CI — use each distro's own toolchain, not an approximation.
- **Honest capability boundaries, again:** the agent's installation-scoped token cannot create releases or trigger workflow_dispatch — so the release workflow is tag-driven (owner cuts tags; CI drafts the release with runner credentials) and dispatch lanes are documented for the owner. Design the pipeline around verified permissions, not assumed ones.
- **Verified (real runs):** clean-venv wheel install with KB smoke (local + CI); deb lifecycle in this sandbox; 5-distro native-artifact install matrix in CI; ruff/mypy/pytest/lives + all prior milestone gates re-verified; CHANGELOG complete (0.0.1→1.0.0).
- **Open by design:** LICENSE (owner-reserved), PyPI/AUR publication (owner), merge to main (owner-only). The agent opened the milestone PR and stopped there.

- **M6 addendum — what the 5-distro install matrix caught in its first hour:** Python 3.14 (now in fedora/alpine `latest`) removed `importlib.abc.Traversable`, invisible to 3.10–3.12 unit lanes — "latest" distro tags are a time bomb; test on them, and don't import what typeshed already types. Arch ships an *expired* `nobody`, so unprivileged build users must be created, not assumed. And one wrong glob character (`_py3` vs `-py3`) failed three distros at once — single-line error annotations made all three diagnosable without job-log access (blob endpoints stay blocked).

---

## 2026-09-02 · M7 implemented: trust is staged, not claimed

- **The owner's review was the milestone:** "RC by engineering, alpha by exposure." The correct response was not to argue but to close what code can close and make the rest a staged human decision. M7 = TOCTOU guard + safety-check + preview/blast-radius + auto-rollback + cautious mode + live-model corpus + SAFE-TESTING.md.
- **TOCTOU in GUI injection was a real race v1.0 shipped:** between target disclosure and injection, focus can move. Fix: re-check placed after consent, immediately before the argv runs — as close to the effect as possible. Testing it exposed a fixture-semantics trap: FakeRunner is first-match (probes always return the same result → the abort branch is unreachable → negative asserts pass vacuously). Built SequenceRunner (order-consuming) to actually model the race — and caught my own asserts slicing strings instead of tuples, passing vacuously. A negative test that cannot fail is decoration.
- **Auto-rollback reuses undo() end-to-end** — rebuild, revalidation, verification — under the original task's consent (`skip_consent`), because prompting mid-failure strands partial state. The journal keeps the task `failed` + undo marked applied: honest history, no silent re-apply. Ordering: `finish_task` runs after the rollback so rollback bookkeeping isn't clobbered.
- **The safety battery runs with an execution-blocked sentinel runner** — dry-run plans + consent refusal + a runner that records any execution attempt as a violation. Three independent walls; the self-test itself cannot harm the machine it proves. And it is a *command* (`jarvis safety-check`) because trust should be one command a user runs on their own hardware.
- **Verified (real runs):** battery 7/7 locally; cautious gate refused T2-with-`--yes` live; preview blast radius correct; auto-rollback restored a real file byte-identical (tests with a real journal); 352+1 tests; all prior gates re-verified.

---

## 2026-09-03 · M8a implemented: helpfulness that never leaves the consent path

- **The owner asked for Marvel-JARVIS** (helpful unrequested actions, self-development, deep user context). The design answer (ADR-0012) keeps the philosophy intact: *proactivity proposes; consent executes*. The suggestion engine is the proof that this is not a limitation but the feature — JARVIS can now be genuinely proactive (undo-orphans, stale indexes, distro pitfalls) with zero new authority.
- **Structural honesty over policy promises:** the engine takes no Runner — there is no code path from "suggestion" to execution. Accept prints the exact command; the user types it. The same pattern as the GUI: disclose target, require consent, never surprise.
- **Cite-or-abstain generalizes:** suggestions carry evidence (journal records, KB facts with sources) exactly like answers and plans. A suggestion without evidence is a hallucination with extra steps.
- **The ledger is the context seed:** reject-without-reason is refused — a rejection without a "why" is a wasted calibration signal. Suppression is immediate and inspectable (`jarvis context show`), and the store prints its own boundary: tunes suggestions, never grants authority.
- **Also this round:** the E2B workspace reset to the initial commit mid-milestone (platform outage). Recovery: `git fetch` + `reset --hard FETCH_HEAD` back to `1824602`, rebuild venv, verify 356 tests — then continue. The remote-first discipline (commit+push every milestone) is what made recovery a two-minute operation. Push early, push always (to the session branch; merges remain owner-only).
- **Verified (real runs):** suggest/accept/reject/context flows live; 369+2 tests; all prior gates re-verified after recovery.

## 2026-09-03 · M9a implemented: MCP without a side door

`jarvis mcp serve` exposes a fixed tool/resource surface over stdio JSON-RPC (stdlib-only). What kept this small: the MCP client inherits the CLI's harm model — same tiers, same journal, same refusals — so the only new decision was consent mapping (`allow: true` → `ApprovalPolicy(yes=…)` with a deterministic non-tty stdin, so a T2 plan without consent refuses instead of hanging the stream). The kernel converts `ApprovalRefused` into REFUSED outcomes (it never raises), so the server maps exit codes to MCP `isError` and restates refusals as "preview, then allow" in this surface's terms. Lesson: protocol adapters should be thin translations, never new authority paths — the whole server is ~350 lines including schemas because nothing had to be re-decided. Ops notes: stdout is protocol-only (banner on stderr); a tool call that throws must not kill the session, so handlers are wrapped and log to stderr.

## 2026-09-03 · M9c implemented: drift has a witness now

`jarvis doctor` baselines everything JARVIS *obeys* (KB data, playbooks, the safety kernel, the runner, both ingresses, the cautious flag) and verifies on demand; `status` carries the verdict. The context store now scans feedback at write time (injection patterns refused — that table tunes M8b suggestions, so poisoned feedback is a poisoning vector) and hash-chains every entry into a table digest, so edits, deletions, and forgeries all trip `verify_integrity()`. Suggestion renders carry per-invocation canaries recorded locally. Two implementation lessons. First, upsert tables can't use naive append-chains: per-row content hash + digest over hashed rows gives edit/delete/forgery detection while preserving 1.2.x-era upsert semantics, with legacy rows reported honestly instead of silently rehashed. Second, my own test fixture had the classic builder-side-effect bug — `tmp_scope()` rewrote the files, silently un-tampering them between baseline and verify; the drift engine was fine, the test was lying. Builders must be pure; seeding is a separate act.

## 2026-09-03 · M9d implemented: standing orders with circuit breakers

`jarvis charter` ships the heartbeat pattern the research endorsed — and hardens it against every failure mode the research documented. The design kept it small: a charter is *data* describing one pre-authorized request; `precheck()` re-derives the plan from the live registry at every firing and pauses on drift instead of improvising; the failure policy is fixed at pause; budgets are counted conservatively from the real journal. Two layers of tamper defense emerged naturally: `load_charter` refuses schema-violating contracts outright, while `precheck` pauses semantically-valid-but-drifted ones — the tests now cover both classes explicitly. systemd integration is best-effort with honest degradation (manual `charter run` is a first-class path), and operational state (`.state` files) deliberately sits outside the integrity glob so the tripwire only fires on policy bytes, not on pause/resume. Humbling repeat: the `--yes`-before-subcommand flag-order trap bit me again in the live demo — it's now twice-documented. Live verification on the real box: two genuine `apt-get update` firings (verified, journaled), then the budget breaker refused the third with exit 2 and paused the charter.

## 2026-09-03 · M9e + M9b implemented: ADR-0013 complete — the kernel is now the only door

Closed the ADR with the two remaining phases in one release. M9e kept faith with the research: the API path (AT-SPI EditableText) shares the consent tier, the TOCTOU guard, and the journal redaction of the injection path, with **no silent fallback** — an honest error beats an unexplained mechanism switch. The matrix now discloses api/wm/injection per capability, which is the operator-facing point of the whole exercise. M9b is the anti-ClawHub: packs are JSON (the ADR's YAML sketch bowed to the zero-dependency rule — say the deviation out loud in the ADR), they may only alias existing playbooks, evals are real dry-runs at install, receipts pin the bytes, and a drifted pack fails closed instead of matching everything. The deepest lesson of the phase: security properties got *simpler* to state because they're structural — "packs add vocabulary, not power" is checkable in one line (`playbook` must be a real playbook id). Process notes: the sandbox reset a fourth time mid-phase (HEAD back to Initial commit); the recovery ritual (backup modified files FIRST, fetch+reset --hard FETCH_HEAD, restore, rebuild venv, re-gate) worked exactly as documented — but only because the backup happened before the reset, not after.

## 2026-09-03 · M8b + M8d implemented: ADR-0012 complete — context tunes, growth proposes

Closed the adaptive-initiative ADR. The context store grew preferences and house rules inside the existing tamper-evident design — which forced a real integrity subtlety: a digest-only check on the new tables catches additions/deletions but NOT content edits, so per-row content re-hashing had to be restored for them (the M9c feedback path already had it; the bug was caught by the tamper tests before it ever shipped). The tuning-only invariant stayed structural: the suggestion engine filters by preference/rule at render time; nothing in the store can widen what the kernel will execute. Routines are deliberately *not* persisted — deriving them from the journal on demand means `context forget` leaves no stale inference, an honest improvement over the ADR sketch (documented as a deviation). M8d's growth loop validates drafts through the REAL KB loader and the REAL skill machinery, so "the store refuses uncited facts" is enforced at draft time, not by convention; promotion is owner-only with printed commands, because PR creation/merge is authority and authority is the owner's. Process: the sandbox reset a FIFTH time mid-milestone (uncommitted work in a tracked file was overwritten by `reset --hard`; the untracked new modules survived) — replaying the edits from the session transcript took minutes precisely because every change was scripted and asserted. Backup modified tracked files BEFORE resetting; untracked files survive, tracked modifications do not.

## 2026-09-03 · J.A.V.R.I.S.-GUI wired by contract: the kernel speaks, the HUD renders

The owner built a Qt6/QML HUD (real /proc telemetry, its own 8-state machine with an explicit legal-transitions table, an allow-list console that never shells) and directed that it be wired to this project. The seam chose itself: the M9a MCP stdio server already treats every client as an untrusted ingress with unchanged tiers. What I shipped is the CONTRACT, not a client: `jarvis mcp describe` publishes transport/handshake/tools/consent/state-mapping as JSON, and conformance tests replay the published example through the LIVE server — descriptor and behavior cannot drift. The state mapping was written against the GUI's actual transition table (read their state.py first — every mapped arrow is a legal transition; OFFLINE→telemetry-continues is their honesty rule, not mine to invent). Deliberately NOT done: pushing code to the GUI repo — it's another session's arena branch, it's MIT while this repo's license is owner-pending, and a QProcess client against a published protocol is small. Integration by contract, implementation stays home.

## 2026-09-04 · M10 implemented: AI failure semantics — the model is optional, breakable, and never in charge

The owner asked the right systems question: what does the agent do when the AI fails, in an unknown situation, with no AI at all? The audit found the hard part already right — propose/dispose (ADR-0007) means every LLM step re-passes the deterministic matchers, which is exactly the production norm the research confirmed — so the real work was failure *semantics* around the model, not a smarter model. Three decisions mattered. First, failure now has memory: a persisted three-state breaker (charter `.state` precedent, deliberately outside the integrity scope — a tripped breaker is an observation about the world, not policy) turns a dead Ollama from "fresh 90s timeout on every ask, forever" into "instant honest refusal after 3 strikes, auto-probe after 5 minutes". The subtle call: malformed model output trips the breaker, but an honest "unexpressible" must not — a healthy model saying "I can't express that" is correct behavior, not degradation. Second, abstention is structural, not begged: AbstentionBench shows models answer definitively when they should abstain even when prompted otherwise, so the grounded-answer contract makes "I don't know" the only possible output when citations don't resolve to supplied KB fact ids — the same cite-or-abstain idea as ADR-0009, one abstraction up. Third, unknown requests became *processed* unknowns: nearest intents, a journal record the owner can review as growth input, teaching paths — "what changed / what still works / what happens next" applied to ignorance. Process: the sandbox reset an EIGHTH time mid-milestone, and the new trap was mine — the recovery `reset --hard` itself clobbered tracked-file edits (the platform reset had made them "untracked"; backup-first saved every byte), and a follow-up `edit_file` raced a stale snapshot and wrote back a truncated app.py (caught by F821 undefined-name errors, fixed by the deterministic ritual: git-pristine checkout + scripted patcher with per-replacement count assertions). Verified: 561 passed + 2 honest skips; breaker/taxonomy/grounded-answer/no-AI suites all green over real sockets; live lane green.

## 2026-09-04 · M11 implemented: a purpose-built neural network that proposes and never disposes

The owner asked for "a neural network, specifically for this, so the program can run during AI errors" — and the honest engineering answer was to narrow the request before honoring it: a second probabilistic system as the failure-path of the first is the same trap one abstraction up (shared failure domain, doubled non-determinism). What a purpose-built model CAN do is recall: rank the playbook vocabulary for loosely-phrased requests after both the engine and the LLM planner declined. So ADR-0015 ships a tiny MLP — fastText-style hashed n-grams → 48 ReLU → softmax over 12 families plus a trained `unknown` class — 13K parameters, 107KB of weights as package data, pure-stdlib ~1ms inference, seeded reproducible trainer in-repo. Three lessons worth keeping. First, the gates caught my bugs before the weights shipped, twice in one afternoon: a backprop gradient missing the error factor (W1 got error-blind nudges that canceled), and the ReLU zero-init deadlock — at zero weights every hidden unit is dead, dh = W2·d2 = 0 forever, and only the bias learns (loss frozen at the class-prior entropy is the signature). Second, the authority contract is structural, not stylistic: suggestions must pass the real matchers, are printed as text for the user to type, `file.append` has no slot extractor (the model never reconstructs paths), and `--no-ai` switches it off — "proposals, never power" enforced in code, not convention. Third, evaluate the rounded weights you SHIP, not the full-precision sibling the trainer holds in memory — the gates are meaningless if they certify a model the user never runs. Process: the sandbox reset a NINTH time (venv loss only; the untracked new modules rode it out — the remote-first discipline again).

## 2026-09-04 · GUI coordination pass: re-verify, don't re-design

The owner pointed at the GUI again after M10/M11. The tempting mistake is to invent new integration surface; the disciplined move was to verify first. The GUI branch had moved 7 commits (attention escalation, orb/takeover, motion) — but `state.py`'s transition table and the router verbs are untouched, so every mapping and verb published in `javris-frontend/1` remains exact; the kernel's conformance tests stayed green without edits, and a subprocess-level replay of the contract example through the shipped `jarvis mcp serve` binary proved the *artifact* (not just the class) speaks the wire. The addendum's rendering guidance writes itself from the two projects' shared philosophy: their new attention-escalation system ("the HUD interrupts you on sustained critical conditions") is precisely where a breaker-open "AI degraded" disclosure belongs — telemetry, not error. Restraint recorded in the doc: a structured suggestion field would be a `javris-frontend/1.1` additive revision, proposed and owner-gated, not slipped in. One test added: `serverInfo.version` pinned to the package version, because the GUI's capability detection leans on it.

## 2026-09-04 · Backlog close: the CI flake was an unauthenticated-test problem all along

"Whatever is left" turned up a quiet discovery: `tests/test_knowledge_live.py` has no skip gate — it runs in EVERY CI matrix leg and hits api.github.com unauthenticated, 60 req/h shared per runner IP. Four+ "flakes" across months were one structural defect, not bad luck. The remedy is two-sided and both sides matter: the code honors `GITHUB_TOKEN` (1000+ req/h) with exactly one Retry-After-bounded retry — bounded because a CLI must not stall on GitHub's sake, disclosed because honesty extends to verification results — and CI supplies the token. Testing the retry taught a stub lesson: the shared StubHTTPServer answered GETs with an unconditional 200, so rate-limit paths needed real GET queueing (now added, backward compatible). Also: the sandbox reset a TENTH time mid-turn, and the recovery ritual hit its own documented trap again (reset --hard clobbering tracked-file edits) — backup-first turned it into a 30-second restore. The pattern holds: the platform is unreliable, the procedure is not.

## 2026-09-03 · Release engineering: rc tags + draft releases for 1.3.0–1.8.0 — three GitHub traps in one afternoon

Tagged every CI-green milestone commit (`v1.3.0-rc1` … `v1.8.0-rc1`, annotated, commit↔version verified from each tag's own `pyproject.toml`) and let the existing Release workflow build sdist/wheel/deb and open the drafts; then edited the drafts into shape (title, changelog-derived notes, `prerelease`) while keeping them **draft** — publishing stays owner-reserved, and `gh release edit --draft` cannot accidentally publish. Three traps worth the price of admission. First, GitHub Actions creates **no push events when more than three tags arrive in one `git push`** (documented limit) — six tags at once fired zero Release runs, silently; the remedy that works when `gh workflow run` is unavailable is deleting and re-pushing the tags **one per push event**. Second, the Arena integration token has no `actions:write`: `gh workflow run` returns HTTP 403 "Resource not accessible by integration" even though git push and `gh release edit` work — know which writes your token can do before planning around dispatch. Third, `git fetch origin --tags` **clobbers FETCH_HEAD**, so the reset-recovery ritual `reset --hard FETCH_HEAD` can silently land on `main`'s tip after a tags fetch; this clone's refspec is main-only (`origin/<branch>` doesn't exist), so the honest fix is resetting to the full SHA printed by `git ls-remote`. The sandbox also reset a seventh time mid-task — backup first, recover from remote, diff against the backup to prove zero loss, move on. The remote-first discipline is what makes these all recoverable in minutes: nothing lives only here.

---

## 2026-09-04 · Deep research delivered; hybrid residency shipped (v1.11.0 → v1.12.0)

- **The owner-directed deep research** (`docs/RESEARCH-jarvis-agent-linux-2026.md`, 45 tier-labeled sources) replaced instinct with evidence and produced the charter-compliant R1–R5 roadmap. The findings that mattered most: Linux is unusually good at screen-less desktop awareness (AT-SPI over D-Bus — "the desktop already publishes its UI"); proactivity has a taxonomy where **silence is a decision** with a denominator; prompt injection stays unsolved, so containment and consent parity are the durable defenses; and the honest scoring of our own engine ("no synthesis-over-sources playbook") became work items instead of embarrassment. Deliberate divergences were documented as charter positions, not gaps: no autonomy loops, no actuators.
- **Hybrid residency (ADR-0018, v1.12.0)** shipped the loopback, token-authenticated serve doorway with the discipline the research reinforced: residency is "a doorway, never an actor." That single rule later shaped R3's entire design.

---

## 2026-09-04 · R1 — voice front-end (v1.13.0): presentation, never authority

- Push-to-talk through the same kernel (ADR-0019): `arecord` → whisper-class STT → the normal match/plan/approve/execute/verify path → piper TTS. Zero new Python dependencies; external binaries are probed and honestly reported missing by `voice doctor`.
- Stub-binary test lessons now institutionalized: bash stubs need `#!/bin/bash` for `${!#}` indirection; the stdin sidecar must APPEND; `shutil.which` returns absolute paths so fake-path stores keep bare names; `TaskStatus.SUCCEEDED.value == "succeeded"` bit us once.
- The sandbox had no STT/TTS binaries and no Ollama — so the honest-skip design earned its keep: tests assert disclosed skips, and the suite stayed green (690+2) without faking capabilities.

---

## 2026-09-04 · R2 — owner-taught file memory (v1.14.0): the planner reads, never obeys

- Plain-file memory (ADR-0020, Anthropic-pattern) with the MINJA-style threat model answered honestly: write-time hygiene + injection scan (refuse, never sanitize), provenance tags, and a delimited *background context* block in the planner's system prompt — never instructions. Every proposed step still re-validates through the real playbooks.
- **CI lesson that local gates could not catch:** the py3.10 matrix leg failed on `datetime.UTC` (3.11+). Root cause: mypy checks `src/` only, so test-only 3.11 imports slip every local gate. Remedy applied repo-wide including tests: `from datetime import datetime, timezone` + `datetime.now(timezone.utc)`. Local green ≠ matrix green; the matrix exists for exactly this.

---

## 2026-09-04 · R3–R5b closing sprint (v1.15.0 → v1.18.0): briefings, guarded eyes, the classifier learns the whole catalog, and the digest

- **Platform honesty record:** the sandbox reset 13 times across the engagement (three during this sprint's turns). The recovery ritual (verify parentage before every push; compare `git rev-parse HEAD` to `git ls-remote`; explicit-SHA reset; venv rebuild recipe) turned each into minutes of loss, and — recorded in RELEASING.md — GitHub Actions still fires **no push events when more than three tags arrive in one push**.
- **R3 briefings (ADR-0021, v1.15.0):** the design win was making *silence* a first-class, ledgered decision with a reported silence rate — the denominator-aware transparency the proactivity literature asks for. The CI catch: our own round-trip test assumed "no systemd," which is true in the sandbox and false on GitHub runners; the fix pins the environment instead of assuming it (test-isolation bug, not product bug — the product's disclosed-skip path was correct).
- **R4 desktop awareness (ADR-0022, v1.16.0):** inspect-first paid off — the GUI milestone had already made us AT-SPI session-bus clients *without data-boundary guards*, so R4 became a hardening milestone: blocked apps (password managers, keyrings, polkit, terminals) never read; password roles withheld before any name read; sensitive names redacted; content-free audit (a test pins that a distinctive window title appears nowhere in the ledger bytes). One self-inflicted nick: files briefly landed under a typo path (`J.A.V.R.I.S/src`, missing dot) — the smoke test caught it in seconds; moved, typo root removed.
- **R5a retrain (ADR-0023, v1.17.0):** the classifier had been speaking a 12-intent vocabulary in a 56-playbook world — 44 ids invisible to it. The redesign that matters: **the kernel owns the vocabulary** (trainer derives labels from `PLAYBOOKS`; a test pins model-labels == live catalog, so staleness is a CI failure). The holdout splits unique texts *before* seeded upsampling, so gate numbers stay leakage-free; byte-reproducibility was proven by a double training run with identical sha256.
- **R5b digest (ADR-0024, v1.18.0):** the test battery earned its name — it caught **"run a health check" being matched by `gui.launch`'s greedy T2 matcher**, i.e. a digest phrase would have attempted an app launch. Digest phrases are now claimed first (T0, no launch), and the no-shadow set is pinned. Catalog 56 → 57 through its own ADR; the vocabulary-retrain cadence from R5a was exercised end-to-end exactly as designed. One silent-miss honest note: the digest paragraph failed to insert into the README last milestone (anchor sentence absent; the fallback branch was a no-op) — caught and fixed in the next turn's documentation sweep.

---

---

## 2026-09-05 · v1.19.0 — the hybrid AI upgrade; and a watch-discipline defect caught by the owner

- **The milestone (ADR-0025, owner-chosen direction):** the planner's system prompt is now DERIVED from the live catalog (one engine-legal example phrase per playbook, each pinned against the real matchers — 14 of my 57 draft hints failed that gate and were fixed before shipping; the old frozen 12-intent prompt could never see 45 of today's playbooks). Conversation + memory now reach the model only as a delimited BACKGROUND CONTEXT block. `complete_with_failover` gives local⇄API dual-path reliability behind the persisted breaker — with **mandatory disclosure** (`[jarvis] served by …`), the owner's explicit requirement that both paths be reliable. Voice now speaks sentence-by-sentence. Token-level LLM streaming was deliberately deferred: every AI surface emits a validated artifact, so streaming would be dead code today.
- **The find of the milestone:** a latent str-Enum bug — `str(FailureKind.TIMEOUT)` is `"FailureKind.TIMEOUT"`, never `"timeout"` — which silently disabled transient-retry logic and made `ai_answer` record breaker failures for calls the breaker never allowed. Fixed by enum-value comparison; a new test pins the retry semantics.
- **The defect the owner caught:** I closed the turn with a single blocking `gh run watch` loop over three freshly-pushed runs — half an hour of the owner staring at a frozen terminal. Process fix, now written into RELEASING.md: bounded snapshot polling only. Beneath it sat a genuine infra stall (ubuntu-24.04 packaging leg wedged 40+ min at the container-eval step; same eval green on 4 distros in-run and green on the paired pull_request run of the same commit) — the paired-run verification precedent applied and disclosed. Lesson: my *tooling behavior* needs the same review my code gets; "it worked before" was hiding that earlier watches started late, not that watching was cheap.

---

## 2026-09-05 · v1.20.0 — the unknown-app answer: a ladder, and packs the owner teaches

- **The milestone (ADR-0026, owner-directed deep research):** two deliverables from one question — *"when JARVIS meets an app the playbook does not know, how does it control it, and how do I set that up easily?"* The control side is a **fixed ladder** (launch → guarded AT-SPI read → the app's own **published actions** → EditableText → keys last), never vision, never synthetic clicks, never portal input — each parked behind its own future ADR. The teaching side is **data that compiles through the kernel**: `app-skill/1` JSON packs whose every field is bounded and command-free, installed by `jarvis app-skill wizard`, which validates **by constructing the real steps** (the M9b eval discipline applied to owner data) and receipts them with sha256.
- **The bug the wizard's own smoke run caught:** a pack with no `app.launch` block was normalized into `{"launch": []}` at install — which then **failed the pack's own validation on reload**, making every no-launch pack unloadable (fail-closed against myself). Fixed by omitting the key when empty; the round-trip test now pins it. Second catch in the same area: absolute-path *arguments* (`gedit /home/owner/notes.txt`) were rejected by a token regex written for command names — the fix splits first token (bare command, PATH lookup) from arguments (no shell metacharacters), which is the actual security boundary.
- **Real-pyatspi shape discipline:** duck-typed stubs that implement `__iter__` silently pass while the real Accessible binding exposes children **only by index** (`get_child_count`/`get_child_at_index`). The walker now speaks the index protocol first and iterables as fallback, and one test runs the index-protocol shape end to end. The desktop itself is an Accessible — the same fix applies at the root.
- **Exemption bookkeeping at scale:** growing the catalog 57 → 58 rippled into five pinned artifacts (registry count, tier table, CLI JSON count, hint catalog, classifier vocabulary). The D5 decision — *owner-taught playbooks carry no static hint and no classifier label, because they have no static matcher surface to template* — had to be encoded once (`OWNER_TAUGHT` in the trainer) and referenced everywhere, or the next catalog growth re-fights this battle.

---

## 2026-09-06 · Combined-repository audit — the kernel as a front end sees it

- **The exercise:** the kernel and the JAVRIS HUD were imported side by side into one
  repository, and the brief was to test the whole and strengthen it. For the kernel that
  meant running every gate in a clean venv (856 passed, 2 honest skips; M2 9/9; M3 0 escapes;
  M4 10/12 with the two GitHub-reachability misses disclosed as environment) and then
  something the kernel's own suite cannot do: sit on the *other* side of `jarvis mcp serve`
  and read what a front end actually receives.
- **What the front end sees that the tier does not say.** Four different guards answer a
  `jarvis_do` with `status: "refused"` and a tier below 3: the approval policy, cautious
  mode, the protected-path check and the refusal-to-guess. Only the first is lifted by
  `allow: true`; I proved the second by sending the T2 request *with* consent under
  cautious mode and receiving the identical sentence. The GUI had been keying its APPROVE
  button on the tier alone, so it offered consent for refusals consent cannot lift. The
  kernel was never wrong — but the one signal that disambiguates the cases is the
  `_REFUSAL_HINT` that `_tool_do` attaches *only* for the approval case, and that
  provenance is worth knowing when designing any other client. Recorded in the GUI's
  bridge doc with the four sentences verbatim.
- **A count that drifted in prose but not in code.** The README said 57 playbooks in three
  places and 58 in one. The code pins both numbers for different things — 58 in the
  catalog, 57 in the hint vocabulary and classifier labels because `gui.app` is
  owner-taught (D5) — so the honest fix was not a find-and-replace but saying which number
  is which. The D5 bookkeeping lesson from v1.20.0 applies to documentation too: an
  exemption encoded once in code still has to be stated once in prose, or the next reader
  "corrects" the wrong number.
- **File modes are part of the release contract.** The import dropped the executable bit
  on `build-deb.sh`, which `packaging.yml` and `release.yml` exec directly. Nothing in the
  test suite touches a file's mode, so the only way to see it was to diff blob modes
  against the upstream tree. Restored with `git update-index --chmod=+x`; a docs-only,
  code-untouched change, and disclosed as such.
- **What I did not do:** no kernel code changed in this round, no tag, no merge. The GUI's
  findings did not surface a kernel defect to fix; they surfaced the fact that the kernel's
  refusal vocabulary is richer than its tier field, which a client must respect.

---

## 2026-09-06 · Deep research II — how an agent is actually made, and what "surviving" should mean here

- **The brief was open-ended ("more capable, environmental, surviving") and the temptation was to
  answer it with a shopping list.** What kept it honest was reading the kernel *after* each search:
  three things I expected to recommend turned out to be already shipped (constrained decoding via
  Ollama `format` + `PLAN_JSON_SCHEMA`, ADR-0014 D4; a hash-chained store — but only for the
  context ledger, not the task journal; a computed no-LLM digest, ADR-0024). Each became a
  "confirmed" or a "half-present" line instead of a proposal, which is the difference between
  research and marketing.
- **"Surviving" needed a definition before it could be researched.** Every source that uses the
  word means one of four bounded things — the process staying up under a watchdog, state surviving
  a crash so a task can resume *or be undone*, recovery under explicit budgets, and the agent
  proving its own code is unmodified. None means self-preservation, and I wrote that down as an
  explicit limit (§4.5) so the word cannot drift later.
- **Provenance discipline cost more than the searching.** Roughly half the sources were only ever
  seen as search excerpts. Rather than launder them into confident prose, every claim carries
  `[fetched]` or `[snippet]`, and §11 lists what was *not* verified (UPower/NetworkManager interface
  names, MCP stateless rules for stdio, Landlock struct layouts, `ProtectHome`/`sudo -n`
  interaction). A future session should treat the `[snippet]` items as leads, not facts.
- **One residual I chose to name rather than hide:** `net.dns` is technically an outbound channel
  whose payload is a hostname. It is safe today only because the planner never sees private data
  it could encode — so the "no tool output into the planner" rule is now documented as
  load-bearing, not incidental.
- **Nothing was decided.** Eleven candidates, ten owner questions, zero code. The one item that is
  a plain recommendation (a `--runs k` / `pass^k` option in the eval drivers) was deliberately not
  implemented either — the task was research, and the charter's scope rule applies to me too.
- **Verification honesty:** no tests, benchmarks or live systems were run for this document;
  repository facts were checked by reading files at `48d9771`. No commit or push was made this
  turn (none was instructed).

## 2026-09-06 · C6 — `pass^k` in the eval drivers (ADR-0027), first item of the owner-gated sequence

- **Inspect-before-modify paid for itself within ten minutes.** Reading the M2 driver alongside
  `providers/breaker.py` raised a question the code could not answer on paper — *does the fixed
  `/tmp` state dir let the breaker count refusals across invocations?* — so I ran the unchanged
  driver four times. Invocations 1–3 passed 9/9; the fourth failed 6/9 with `BREAKER_OPEN`. The
  driver had been quietly un-rerunnable for anyone iterating locally, and CI's fresh runners hid
  it. A `--runs K` feature with K ≥ 4 was literally impossible until that was fixed, which is why
  the fix is in this item and not parked as a recommendation (guideline 15 applies to scope, not
  to preconditions).
- **The metric was fetched, not remembered.** I re-read τ-bench §3 for the exact estimator
  (`C(c,k)/C(n,k)`, averaged over tasks) rather than implement "all k pass" from memory; the
  binomial form is what makes a 5-run session yield the whole `pass^1 … pass^5` curve instead of
  a single number, and it collapses to today's pass rate at n = 1 — which is the property the
  tests pin and the reason `--runs 1` is byte-compatible.
- **Baseline first, then diff.** Both drivers were run from the pre-change tree into a baseline
  JSON before editing; after editing, `--runs 1` console output was diffed (identical apart from
  the results path I chose) and every pre-existing JSON field compared value-by-value (identical;
  only additive keys). That is a stronger claim than "should be unchanged", and it cost two
  minutes.
- **A test is only evidence if it can fail.** I reverted the isolation fix in a scratch copy and
  ran the new `--runs 5` test: 3/5 passes instead of 5/5, exactly the breaker threshold. Restored,
  9/9. Without that check the test would have been an assertion of intent, not of behaviour.
- **Two honest exclusions and one honest limit.** `m1` mutates hosts, `m3` exposes only an
  aggregate verdict, `m5` needs an X stack this sandbox lacks — all three keep today's interface
  and are named in ADR-0027 D5 rather than half-instrumented. And `pass^k` on scripted/KB-only
  drivers measures *determinism*, not model reliability; the informative lane is the weekly real-
  Ollama job, which cannot run here and is recorded as follow-up C6b for the owner.
- **A tooling trap worth recording:** bare `pytest` (venv entry point) fails
  `tests/test_intent_model.py::test_vocabulary_covers_the_whole_catalog` with
  `ModuleNotFoundError: training` because only `python -m pytest` puts the repo root on
  `sys.path`. Pre-existing, unrelated to this change (reproduced with my files stashed); CI's
  `unit_gate.py` uses `sys.executable -m pytest`, so the gate is unaffected. Noted as a
  recommendation (a `pythonpath = ["."]` pytest option), not changed.
- **Verified here:** `ruff check .` / `ruff format --check .` clean (184 files); `mypy src/jarvis`
  clean (78 files) and `mypy --strict` clean on the new harness module + test; `python -m pytest`
  **865 passed, 2 skipped** (the two live-LLM gates); M2 `--runs 5` 9/9 with `pass^1…5 = 1.0`
  in 27 s; M4 `--runs 3` 10/10, 0 unverifiable claims. **Not verified:** CI execution
  (`api.github.com` unreachable from the sandbox); any real-model run. No commit or push was
  made (none instructed).

## 2026-09-06 · C11 — journal evidence chain (ADR-0028), second item of the sequence

- **The obvious design was wrong for this table, and it took reading the precedent closely to
  see why.** M9c's digest is `sha256(sorted(row hashes))`, recomputed from whatever rows exist on
  every write. For a store touched a few times a week that is fine; for a journal written on
  every task, step and brief-timer run it means **a deleted row is healed into a fresh, valid
  digest by the next legitimate write** — within minutes. Copying M9c literally would have let me
  write "deletions are detected" in an ADR while the code quietly forgot them. The chain
  therefore links *write events* (append-only, `prev_hash`), and `AUTOINCREMENT`'s never-reuse
  property is what makes a wiped or truncated event table stay visible after later writes.
- **Rows here are mutable; events are not.** `finish_task` rewrites `status`, `mark_undo_applied`
  rewrites the artifact. So the verifier compares each row with its *latest* attested hash, not
  its first — which is also why the tests check that restoring a flipped value restores the
  verdict: the chain attests content, not time. Both hashing sites call one function on a
  re-read row, so writer and verifier can never disagree about bytes.
- **Concurrency was designed, then attacked.** The link happens inside the transaction that
  already holds SQLite's RESERVED lock from the row DML, so the tail read and the event insert are
  atomic with respect to other writers. I broke that on purpose (commit the row, then link) and
  the three-process test failed with `UNIQUE constraint failed: journal_chain.seq` on the second
  of three runs — flaky exactly as a race should be — then passed reliably with the invariant
  restored. The backfill's `BEGIN IMMEDIATE` was tested the same way: four simultaneous first
  opens, one backfill.
- **Measured before claiming "near-zero cost."** +0.2 ms per write on this sandbox, 49 ms to
  absorb a 2 000-row legacy journal, 28 ms to verify 2 600 events. Numbers are in the CHANGELOG
  rather than adjectives.
- **What I did not do, and why:** no new verb (`doctor` already owns this verdict), no anchoring
  of the head in the M9c baseline (it moves on every write and would drift immediately), no
  silent anchor written by `doctor` (a read-only verb must stay read-only). Both anchoring
  options are recorded for the owner as C11b, and the ADR's limitation paragraph says plainly
  that the chain makes tampering visible, not impossible.
- **Version discipline:** this is the first runtime change of the sequence, so it targets
  1.21.0 — but I have not touched `__version__`/`pyproject`: the bump belongs to the
  owner-authorized commit/tag step, not to a working tree that is still awaiting a commit
  instruction. The CHANGELOG says so in the heading.
- **Verified here:** `ruff check .` / `ruff format --check .` clean; `mypy src/jarvis` clean;
  `python -m pytest` full suite green (count in the report); live `jarvis doctor` on a scratch
  state dir — `fs.disk_free` task journaled (3 events / 2 rows), status flipped by hand →
  `journal chain  : TAMPERED — task:… differs from its last attested write`, exit 1, `--json`
  `clean: false`; `jarvis tasks`/`status` output unchanged. **Not verified:** CI on the changed
  tree (`api.github.com` unreachable). No commit or push (none instructed).

## 2026-09-06 · C3 — ADR-0029 drafted, paused, then accepted the same day (design commit; code follows)

- **The hardening "recipe" would have broken the product.** Research II flagged
  `NoNewPrivileges=` as incompatible with `sudo -n` and left the rest as ASSUMED. Reading
  systemd.exec(5) for the *user* manager turned the assumption into a wall: every seccomp-backed
  directive (`SystemCallFilter=`, `RestrictAddressFamilies=`, `LockPersonality=`, …) implies
  `NoNewPrivileges=yes` there, and every mount-namespace directive (`ProtectSystem=`,
  `ProtectHome=`, `PrivateTmp=`, …) needs an unprivileged user namespace — where setuid is void.
  Both were confirmed empirically in one line each (`setpriv --no-new-privs sudo -n true`,
  `unshare -U sudo -n true`) with sudo's own error messages, and `UMask=0077` fell to a third
  probe (sudo unions umasks). So the honest answer for the doorway is "supervision, not
  confinement, score stays 9.6", and the ADR says so instead of shipping a green score that
  silently turns every `pkg.install` into a sudo failure.
- **Split by what each unit is *allowed to do*, not by what the analyser rewards.** The brief
  unit never runs a playbook, so it can take the full profile (measured 9.6 → 2.0); the doorway
  and charters can escalate, so they cannot. That distinction is the ADR's spine.
- **Opt-in until one real run exists.** The confined brief profile passes the offline analyser,
  but executing under seccomp + userns cannot be tested in this sandbox (no user service
  manager). A timer that dies on every run would be a regression, so D3 proposes `--harden`
  with the promotion criterion and the exact `journalctl` commands written down.
- **Kept `Restart=on-failure`, did not switch to `on-watchdog`.** The man page lists watchdog
  expiry among what `on-failure` already covers; `on-watchdog` would have *dropped* crash
  restarts. Small, but it is the kind of change a recipe copies without reading.
- **Verified:** offline `systemd-analyze security` scores for every variant quoted (system and
  `--user` views), the stdlib notify round-trip over an abstract `AF_UNIX` datagram socket, the
  `serve_forever` → `service_actions()` hook in CPython 3.11's `socketserver`. **Not verified:**
  anything under a live user manager (watchdog restart, `Type=notify` readiness, the confined
  brief actually running). No files outside `docs/`, `CHANGELOG.md`, this file and `TASKS.md`
  were touched for C3.

## 2026-09-06 · C3 implemented — the doorway talks to systemd

- **Wire the ping where a hang cannot reach it.** `socketserver.BaseServer.serve_forever` calls
  `service_actions()` on the accept-loop thread every `poll_interval`; request handlers run on
  their own threads. Putting `WATCHDOG=1` in `service_actions()` gives exactly the semantics
  wanted: a stuck *request* (say `sudo` waiting on a lock) does not restart the doorway, a
  stuck *interpreter* does. The test blocks a handler and watches the next ping arrive anyway;
  moving the ping into the handler (mutation 1) fails that test and the conversation test.
- **Consume the environment, then prove it with a real child.** The C API's
  `unset_environment=1` is not decoration: the Runner copies `os.environ` into every playbook
  step. A test spawns an actual `python -c` with `dict(os.environ)` and asserts no
  `NOTIFY_SOCKET`/`WATCHDOG_*` reaches it — an in-process dict check would not have caught a
  future refactor that reads the variables without popping them.
- **The fake systemd is the real protocol.** An abstract `AF_UNIX` datagram socket is what
  `$NOTIFY_SOCKET` names on a live system, so every assertion is about bytes systemd would
  receive. The end-to-end run of the actual CLI under that socket gave `READY` in 0.10 s and
  pings at 0.25/0.75/1.25/1.75 s for a 1 s watchdog — the cadence is visible, not inferred.
- **Small things found by running, not reading:** `{:.0f}` printed "watchdog every 0s" for a
  sub-second test interval (now `:g`); the analyser's "2.0 OK :-)" line broke a naive
  `split(":")` parser (now a regex). Both would have shipped from a desk review.
- **Refuse before writing.** `--harden` renders `ReadWritePaths=` from the resolved state dir;
  a path with whitespace or quotes is refused *before* the unit files are touched, and the
  test checks that nothing was half-written. Implementing systemd's quoting rules for the one
  state dir that would need them is not worth the bug surface.
- **Verified:** ruff / format / mypy clean; 904 passed (`-m "not live"`); 30 new tests stable
  over three runs; four mutations caught; live CLI conversation as above; offline analyser
  brief 9.6 → 2.0, doorway 9.6 unchanged (asserted as an honesty check). **Not verified:**
  anything under a live user service manager. Promotion of `--harden` to default waits for one
  clean `journalctl --user -u jarvis-brief` on the owner's machine.

## 2026-09-06 · C1 — ADR-0030 drafted, paused for the owner (no code)

- **Bind rules to params, not argv.** The first draft keyed rules on argv tokens; running
  `match()` + `build()` for the T1/T2 catalogue showed why that is wrong for an owner-facing
  file: the same intent renders as `apt-get remove -y -- htop` here and `pacman -Rs -- htop`
  there. The params dict (`names`, `path`, `src`/`dst`, `unit`) is the stable, owner-meaningful
  object, and it is exactly what the orchestrator has in hand at the three `check_argv` sites.
- **The undo path is the awkward one — say so instead of hand-waving.** `_undo_payload` stores
  steps and argv only; `_rebuild_undo_steps` never learns which playbook produced them. Three
  honest options (skip / argv-only subset / add `playbook_id`+`params` additively) went to the
  owner as D-B rather than being decided in the ADR, because U3 touches a persisted format.
- **Fail closed *per scope*, not system-wide.** A policy file with a typo that stops every
  playbook would teach the owner to delete the file — the worst outcome for a deny-list. The ADR
  therefore refuses only what the broken file names, keeps T0 (all 38 verified
  `requires_root=False`), and reports the degraded state in `doctor`/`status`.
- **Fetched the primary source before drafting.** Research II had Progent as a `[snippet]`; the
  v3 HTML (§4.1–4.2) confirmed the two details the design leans on — forbid rules are sorted
  before allow rules, and policy updates are classified narrowing-vs-expansion — and surfaced
  the fallback taxonomy (terminate / ask / return message) that D3 mirrors.
- **Verified:** every repo line cited in the ADR was read this session; params keys observed
  by executing `match()`; T0 root-free claim checked by grep (`requires_root=True` occurs 0
  times in `inspect_cmds.py`) and by building 31 of 38 T0 playbooks from test/eval phrases.
  **Not verified:** nothing to run yet — no code in this entry.

## 2026-09-06 · C1 implemented — the policy that can only say no

- **The oracle for "absent = identical" is the whole suite, not a new test.** Wiring the
  policy into the orchestrator and running the existing 904 tests with no policy file present
  is the strongest available proof that today's behaviour is untouched; the new tests then only
  need to cover what the file *adds*. Worth remembering for any future "inert by default" layer.
- **A rule that can only refuse makes precedence trivial — test it anyway.** With every effect
  being a refusal there is no allow-overrides-deny bug to have, but a future "return early on
  allow match" refactor would reintroduce one silently. The two-order test exists so that
  refactor fails loudly; mutation 3 confirmed it does.
- **The protected set got in the way of the first test phrase.** `remove linux-image-generic`
  is already refused by the code-level protected set, so it could not show the *owner's* rule
  firing; `uninstall grub` (not protected in code, denied by the example rule) does. The
  example policy deliberately overlaps the code set — belt and braces is the point — but tests
  must pick values where only the new layer speaks.
- **`match_intent` surprised me twice**: `remove linux-image-6.8-generic` matched `fs.remove`
  (a path), not `pkg.remove`; the example rule's phrase had to be checked by running the
  matcher, not by reading it. Verify phrasing empirically before putting it in a doc.
- **Deny-all is a legitimate configuration and the fault gate must survive it.** It does (0
  escapes); the one pytest failure under deny-all is `dry_run` being refused *before* the
  dry-run — exactly what a validator refusal does today (`delete the file /etc/shadow`
  → refused, no dry-run). Consistent, and recorded rather than special-cased.
- **Verified:** gate clean; 941 passed; 40 new tests; 6 mutations caught; M3 0 escapes ×3
  configurations; CLI round-trip by running the verbs. **Not verified:** nothing outstanding.

## 2026-09-06 · C4 design — reading the sources changed the architecture, not just the citations

- **"Fetch and cite before the ADR" paid for itself in the first hour.** The research doc had
  *assumed* the access path was fixed-argv `busctl`/`gdbus` for everything. The kernel's own sysfs
  ABI documents (`sysfs-class-power`, `sysfs-class-net`, `sysfs-power`) show that battery, link and
  suspend-count are plain files with documented value sets — four of the six research rows need no
  bus at all, and the briefing's zero-subprocess promise survives for them. The bus is left for the
  three facts only logind/NetworkManager know (metered, sleep-imminent, locked). Verify the cheap
  path exists before designing around the expensive one.
- **The HUD had already solved half the problem.** `proc_reader.py::read_battery()` filters
  `type == Battery`, clamps `capacity`, and maps `status` — the ADR mirrors that filter exactly so a
  HUD cell and a briefing line can never disagree. When two repos read the same kernel fact, one
  filter, written down once, is the seam rule.
- **`busctl get-property` was the obvious verb and the wrong one.** `--auto-start=` and
  `--timeout=` are documented for `call`, with defaults of *yes* and *25 s*. A sensing probe that
  could bus-activate UPower or hang a oneshot for 25 s is not "sensing"; the ADR uses
  `call … org.freedesktop.DBus.Properties Get` with `--auto-start=no --timeout=2` and says why.
  Read the option table, not just the command list.
- **Two logind facts are poll-only by design.** `PreparingForSleep`/`PreparingForShutdown` "do not
  send out PropertyChanged signals" — so a listener would not even help for them, which made the
  poll-at-briefing-time decision easier to defend than the research had framed it.
- **Honesty about what the timer can see.** systemd catches up a calendar timer *after* resume,
  when `PreparingForSleep` is already false again, so the flagship "suppress on sleep" signal will
  rarely fire in practice; the ADR says so and turns "resume" into a counted ledger fact instead of
  a trigger.
- **Verified:** every interface/property/value in the ADR fetched at source today; sandbox
  facts (no bus → `Failed to connect to bus`, rc 1, 6 ms; `busctl` 252 has the three options;
  sysfs paths present). **Not verified:** any live sensing; five items are marked ASSUMED in the
  ADR with the exact commands the owner can run.

