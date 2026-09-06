# Changelog — combined repository

Changes to the combined tree and cross-cutting audits only. Each sub-project
keeps its own detailed changelog:

- kernel: [`JARVIS-MAIN/…/CHANGELOG.md`](JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s/CHANGELOG.md)
- HUD: [`JARVIS-GUI/…/CHANGELOG.md`](JARVIS-GUI/J.A.V.R.I.S.-GUI-arena-01a0667a-j-a-v-r-i-s-gui/CHANGELOG.md)

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The combined
repository is not versioned independently; the sub-projects are.

> Merge policy: the development agent never merges into `main`. Entries land on
> the session branch and reach `main` only through owner-approved merges.

## [Unreleased]

### Added
- Root `README.md` (how the halves connect, how to run and verify both),
  this `CHANGELOG.md`, `AGENT-EXPERIENCE.md` and a root `.gitignore`. The
  initial import (`e3a8d8d`) contained only the two project trees.

### Fixed
- **File modes lost in the import.** Seven scripts that are `100755` in the
  upstream repositories were committed as `100644`: the HUD's `tools/check.sh`,
  `tools/generate_qmltypes.py`, `tools/headless_render.py`,
  `tools/sandbox_gl_stubs.py`, `tests/qml/run_qml_tests.py`, and the kernel's
  `packaging/deb/build-deb.sh` and `evals/harness/install_test.sh`. The kernel's
  `packaging.yml` and `release.yml` exec `build-deb.sh` directly. Restored with
  `git update-index --chmod=+x`; content is unchanged (verified by comparing
  blob modes against the upstream tree listings — content was identical).

### Audit — 2026-09-06 (cross-cutting; details in each sub-project's changelog)
- **Kernel** (`jarvis-agent` 1.20.0): full gate green in a fresh venv — ruff,
  ruff format, mypy strict, **856 passed / 2 skipped**; M2 eval 9/9, M3
  fault-injection 0 escapes, M4 grounding 10/12 (the two misses are
  GitHub-reachability limits of the audit sandbox, not regressions). Docs-only
  fixes: README playbook counts (58 catalog / 57 hinted), file modes.
- **HUD** (`javris-gui` 0.1.0): three functional defects found by driving the
  real controller against the real kernel, all fixed with tests —
  (1) `connectAgent()` had no caller, so the agent could not be connected from
  the running HUD; added `agent connect` and a `LINK` control;
  (2) the state machine lacked `PROCESSING -> STANDBY` and the `OFFLINE`
  recovery edges, leaving six ordinary sequences stuck in `PROCESSING`;
  (3) every low-tier refusal was offered for approval, including cautious-mode
  and protected-path refusals that `allow: true` does not lift — consent is
  now keyed on the kernel's approval sentence and hint. Also regenerated the
  stale `javris.core.qmltypes` and added a drift test. Gate green: **344**
  unit (was 306) and **112** QML (was 103) tests, headless render inspected.
- **Live verification** of the fixed HUD against a spawned `jarvis mcp serve`
  1.20.0 (state traces and console text recorded in the HUD's
  `docs/BACKEND-BRIDGE.md`). Not re-driven live: the resident HTTP transport
  (shares the classifier; unit-covered with the kernel's real refusal text).
