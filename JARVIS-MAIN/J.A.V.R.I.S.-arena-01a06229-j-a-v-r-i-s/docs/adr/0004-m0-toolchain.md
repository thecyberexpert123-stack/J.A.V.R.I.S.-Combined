# ADR-0004: M0 toolchain & dependency set

- **Status:** Accepted (2026-09-02)
- **Context:** Guideline 16 requires every dependency to be justified. M0 needs: build/packaging, lint, format, type check, test, CI.
- **Decision:**
  - **Build:** `setuptools` (PEP 517 backend) — ubiquitous, zero extra tooling, src-layout supported. Distribution name `jarvis-linux` (avoids near-certain PyPI collision of `jarvis`); import package `jarvis`.
  - **Lint+format:** `ruff` — one tool replaces flake8/black/isort-equivalents (fewer deps = smaller attack/maintenance surface), permissive MIT license, actively maintained.
  - **Types:** `mypy` — configured now, strictness tightened per-module as `core`/`safety`/`execution` land (M1+).
  - **Tests:** `pytest` — de-facto standard; lowest friction for the container-matrix harness planned in M3.
  - **CI baseline:** plain `pip install -e ".[dev]"` on GitHub Actions (3.10/3.11/3.12). `uv` remains an optional developer convenience, not a required layer (guideline 14).
  - **pre-commit hooks:** deferred to M1 when real code volume makes them pay off; CI is the authoritative gate for now.
  - **No runtime dependencies in M0.** Runtime deps (typer/pydantic/etc.) enter only at M1/M2 with individual justification.
- **Consequences:** Dev extras: `ruff`, `mypy`, `pytest` (lower-bound pinned). Tool config lives in `pyproject.toml` (single source).
