# M1 Container-Eval Baseline (observed 2026-09-02)

**Catalog:** `m1.json` (v1) — 14 executable expectations per distro.
**Result: 70/70 task expectations passed across five distributions.**

| Distro container | Passed | Run | Evidence |
|---|---|---|---|
| debian:12 | **14/14** | [33637847042](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S./actions/runs/33637463538) | check annotation `eval debian-12 :: 14/14 tasks passed` |
| ubuntu:24.04 | **14/14** | 33637847042 | annotation `eval ubuntu-24.04 :: 14/14 tasks passed` |
| fedora:latest | **14/14** | 33637847042 | annotation `eval fedora :: 14/14 tasks passed` |
| archlinux:latest | **14/14** | 33637847042 | annotation `eval arch :: 14/14 tasks passed` |
| alpine:latest | **14/14** | 33637847042 | annotation `eval alpine :: 14/14 tasks passed` |

Job wall-times on run [33637463538](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S./actions/runs/33637463538) (same eval, artifact-name fix only): debian 23s · arch 23s · fedora 39s · alpine 17s · ubuntu 57s.

## What each task proves

| Group | Tasks | Property verified |
|---|---|---|
| Read-only | `sysinfo-1`, `search-1`, `info-1` | T0 playbooks execute and verify post-conditions on every backend |
| Mutating, reversible | `refresh-1`, `install-1`, `install-2-idempotent`, `undo-install-1`, `install-3-reinstall`, `remove-1` | Real package install across apt/dnf/pacman/zypper/apk; post-condition probes pass; **undo artifact replays and its own post-condition (package absent/present) holds** |
| System-level | `upgrade-1` (T2, `--yes`) | Approval-gated system upgrade executes on all five backends, incl. apt/apk refresh-first sequencing and `pacman -Syu` |
| Honest refusal (environment) | `svc-status-honest-refusal` | In non-systemd containers the agent **fails with an explicit systemd explanation** — never a fake success |
| Honest refusal (policy) | `refuse-protected`, `refuse-unmatched`, `refuse-invalid-name` | Protected-set refusal, unmatched-intent refusal ("will not guess"), option-injection refusal |

## Method notes

- Containers run as root (docker default) with network; `bootstrap.sh` installs python3 per backend (the agent itself has **zero runtime dependencies**, ADR-0005).
- The driver runs the real CLI (`python3 -m jarvis --json --yes …`) per task — the same code path a user exercises — and exits non-zero on any expectation mismatch.
- Failures also surface as GitHub check annotations (`::error`), so regressions are visible without artifact downloads.

## Known limitations of this baseline (honest, per governance §11)

1. `svc.start`/`svc.enable` are **not** executed against a live systemd here — containers do not boot systemd. The catalog asserts the honest-refusal path instead; real systemd verification is planned with a privileged systemd container in M3+.
2. Upgrade verification is exit-code based (plus successful execution); deep post-upgrade state checks require snapshots (M3).
3. Undo round-trip is proven for `pkg.install`; `pkg.remove` undo (reinstall) and service undo paths are covered by unit tests and the same replay machinery, and will join the container catalog in M3's eval expansion.
