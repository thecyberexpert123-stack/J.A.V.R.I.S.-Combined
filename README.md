# J.A.V.R.I.S. — Combined

One repository holding the two halves of the project side by side:

| Directory | Package | What it is | Version |
| --- | --- | --- | --- |
| [`JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s/`](JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s/) | `jarvis-agent` (`jarvis`) | The **kernel**: a Linux automation agent with a safety kernel, tiered consent, an audit journal, undo, a cited knowledge base and an MCP surface. Zero runtime dependencies. | 1.23.0 |
| [`JARVIS-GUI/J.A.V.R.I.S.-GUI-arena-01a0667a-j-a-v-r-i-s-gui/`](JARVIS-GUI/J.A.V.R.I.S.-GUI-arena-01a0667a-j-a-v-r-i-s-gui/) | `javris-gui` (`javris`) | The **HUD**: a Qt 6 / QML heads-up display driven by real `/proc` telemetry, with a console that talks to the kernel over MCP. PySide6-Essentials only. | 0.1.0 |

Each directory is a complete, independently installable project with its own
`README.md`, `CHANGELOG.md`, `AGENT-EXPERIENCE.md`, ADRs, tests and quality gate.
This file only explains how they fit together and how to verify the whole.

## How the two halves connect

The HUD never imports the kernel. It speaks to it over the kernel's MCP surface
(`jarvis mcp serve`, newline-delimited JSON-RPC on stdio) or, when the owner has
installed it, the kernel's loopback HTTP doorway (`jarvis serve install`). The
contract is documented from both sides:

- kernel: [`docs/integration/JAVRIS-GUI.md`](JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s/docs/integration/JAVRIS-GUI.md)
- HUD: [`docs/BACKEND-BRIDGE.md`](JARVIS-GUI/J.A.V.R.I.S.-GUI-arena-01a0667a-j-a-v-r-i-s-gui/docs/BACKEND-BRIDGE.md)

Two properties of that seam are worth knowing before touching either side:

1. **The HUD never connects on launch.** Starting a program that can change the
   machine is the owner's decision. In the HUD, type `agent connect` or press
   `LINK` in the console panel.
2. **Consent originates in one place.** Only the HUD's consent prompt can send
   `allow: true`, and only after the kernel has refused with its approval
   sentence. Refusals that consent cannot lift (cautious mode, protected paths,
   the refusal-to-guess) are shown in the kernel's own words with no approve
   button.

## Running both from this checkout

```bash
# Kernel
cd JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/jarvis status

# HUD — needs `jarvis` on PATH to connect; prepend the kernel's venv
cd ../../JARVIS-GUI/J.A.V.R.I.S.-GUI-arena-01a0667a-j-a-v-r-i-s-gui
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
PATH="$PWD/../../JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s/.venv/bin:$PATH" .venv/bin/javris --windowed
```

Both require Python ≥ 3.10. The HUD additionally needs a display with OpenGL
(or `QT_QUICK_BACKEND=software`); the kernel needs nothing beyond the standard
library at runtime.

## Verifying the whole

Each project ships its own gate; both must pass.

```bash
# Kernel: lint, format, strict types, 856 tests (2 live-LLM skips)
cd JARVIS-MAIN/J.A.V.R.I.S.-arena-01a06229-j-a-v-r-i-s
.venv/bin/ruff check . && .venv/bin/ruff format --check . \
  && .venv/bin/mypy src/jarvis && .venv/bin/python -m pytest -q

# HUD: lint, format, strict types, unit tests, qmllint, Qt Quick Test, headless render
cd JARVIS-GUI/J.A.V.R.I.S.-GUI-arena-01a0667a-j-a-v-r-i-s-gui
./tools/check.sh            # add JAVRIS_GL_STUBS=1 in a container without libGL
```

The kernel's evaluation harnesses (`evals/harness/`) and the HUD's live bridge
verification (recorded in `docs/BACKEND-BRIDGE.md`) exercise the two together
against a real `jarvis mcp serve`.

## Repository conventions

- **Branching.** Work lands on session branches; `main` is merged only by the
  owner. Nothing in either project's tooling merges or pushes to `main`.
- **Changelogs.** Each project keeps its own `CHANGELOG.md` (Keep a Changelog)
  and `AGENT-EXPERIENCE.md`. The root [`CHANGELOG.md`](CHANGELOG.md) records only
  changes to the combined repository itself and cross-cutting audits, and links
  to the detailed entries.
- **Task list.** [`TASKS.md`](TASKS.md) tracks the owner-gated follow-through of
  the 2026-09-06 deep research (candidates C1–C11): per-item sub-tasks,
  acceptance, verification plan, sandbox limits, and the owner's decisions.
- **Licensing.** The HUD is MIT (`JARVIS-GUI/…/LICENSE`, with Qt used unmodified
  under LGPLv3 — see its `THIRD-PARTY-NOTICES.md`). The kernel's licence is an
  owner decision still pending (its `pyproject.toml` says so explicitly); no
  placeholder licence is asserted here.
- **Generated artefacts** (`build/`, `dist/`, venvs, caches, eval JSON) are
  ignored by the per-project `.gitignore` files; the root `.gitignore` adds only
  what applies to the combined tree.
