# JARVIS Security & Quality Audit — v1.2.1

**Date:** 2026-09-03 · **Scope:** full codebase hardening review (owner-directed)
**Method:** automated sweep (bandit high-severity, pip-audit, dangerous-pattern grep, bare-except inventory) + manual review of every subprocess/network/consent path + packaging scripts.

---

## Fixed in this release

| # | Severity | Finding | Fix |
|---|---|---|---|
| A | **P1 · security** | `knowledge/fetch.py` checked the URL allowlist only on the *initial* request; `urllib` follows redirects by default, so a redirecting allowlisted host could bounce a request off-allowlist (allowlist must bound the whole chain) | `SafeRedirectHandler` re-validates **every redirect** against the allowlist before following; all 3 request sites routed through the validating opener; unit tests assert the refusal and that raw `urlopen` never returns |
| B | **P1 · bug** | `safety/selftest.py` GUI battery used `ApprovalPolicy(yes=False)` with default stdin (`sys.stdin`) — on a **graphical desktop** with a focused window, `jarvis safety-check` would reach consent and **block on the interactive prompt** (invisible in CI: headless exits earlier) | battery now uses a non-tty stdin; battery passes 7/7 |
| C | P2 · packaging | `install_test.sh` fedora branch hardcoded `Version: 1.0.0` (and renamed the wheel to match): the install-tested rpm was **mislabeled** (said 1.0.0, contained 1.2.0) | version derived from the wheel filename; harness now **verifies** `rpm -q` matches; spec/PKGBUILD bumped to 1.2.0 |
| D | P2 · hygiene | `gui/detect.py` used `__import__("os")` twice; dev-env setuptools had a published advisory (66.1.1 → fixed in 83) | normal imports; setuptools upgraded (build-system already requires ≥68; **zero runtime deps** so no product exposure) |

## Checked and found sound

- **bandit**: no findings at high severity across `src/` and harnesses.
- **Execution surface**: argv-only everywhere (no `shell=True`/`eval`/`exec`/`os.system`); all 5 `subprocess` sites use fixed argv; runner timeout path does SIGTERM→grace→SIGKILL with full reaping (no zombies); detached spawns use DEVNULL stdios (M7).
- **SQL**: all journal/context queries parameterized (no string interpolation into SQL).
- **SSRF surface**: fetch is the only outbound HTTP; allowlist + redirect validation + opt-in env; vision talks to localhost Ollama only.
- **Consent paths**: preview/safety-check/cautious all cannot execute; suggestion engine holds no runner.
- **Broad excepts (14)**: each is a deliberate, commented boundary ("status must never crash", "rollback must not mask the failure", "broken journal must not break suggestions") — verified none swallow errors silently in the success path.

## Documented limitations (deliberate, not oversights)

1. **File-op symlink check is classify-time only.** A *local* attacker able to swap a symlink between classification and execution already has user-level code execution — JARVIS is not the boundary in that threat model. Adding racy re-checks would add complexity without a real boundary; documented per guideline 14.
2. `context.db` connections are closed at process exit (CLI lifetime); harmless.
3. Wayland backends remain fixture-verified (REPORT-m5 §4).

## Gates after fixes

ruff ✓ · mypy (47 files) ✓ · **372 passed + 2 honest skips** · battery 7/7 · all CI lanes green on push.
