# JARVIS Evaluation Report — M4 addendum: Knowledge System (grounding & citations)

**Date:** 2026-09-02 · **Version:** 0.4.0 · **Scope:** M4 knowledge system (ADR-0009)
**Companion to:** [REPORT-m3.md](REPORT-m3.md) (M1/M2/M3 gates remain in force and green).

---

## 1. Grounding eval (M4 catalog) — **12/12 checks, 0 unverifiable claims**

Offline mode: 10/10 catalog cases. Online mode (`JARVIS_ONLINE_DOCS=1`): **12/12** — the 10 cases
plus 2 upstream existence checks. Reproduce:
`JARVIS_ONLINE_DOCS=1 python3 evals/harness/m4_grounding.py --catalog evals/catalog/m4.json --results /tmp/m4.json`

| Check class | Cases | Result |
|---|---|---|
| Answered + **verified on this machine** | 5 (ostype, meminfo, os-release, apt, systemctl-exit) | cited + local verifier passed |
| Answered + **honest unverified/contradicted here** | 3 (dnf absent, Arch pitfall, apt-vs-apt-get) | cited, uncertainty explicit |
| Refusals outside the KB | 2 (out-of-scope questions) | refused, never guessed |
| Upstream citation existence (torvalds/linux) | 2 (kernel.rst, proc.rst) | reachable, 59 KB / 107 KB fetched |

**Gate:** answered ⇒ ≥1 source (structural — the store *rejects* uncited facts at load);
`verified` ⇒ local verifier actually passed; kernel citations re-verified against
`torvalds/linux` master on every CI push. **0 unverifiable claims.**

## 2. Use of the torvalds/linux repository (owner pointer)

- The kernel tree is **not vendored** (~4–5 GB; ADR-0009). Kernel facts cite exact
  `Documentation/**` paths; the eval verifies those paths exist upstream via the GitHub
  Contents API (`api.github.com` transport — chosen because raw hosts are blocked from some
  environments; the transport is swappable).
- Live-verified during this milestone from the sandbox:
  - `Documentation/admin-guide/sysctl/kernel.rst` → exists, documents `ostype`
  - `Documentation/filesystems/proc.rst` → exists, documents `meminfo`
- CI re-checks both on every push; a future upstream move/rename fails the eval loudly instead
  of silently rotting the KB.

## 3. Knowledge base v1 contents

12 facts across three topics — `kernel` (ostype, procfs/meminfo, uname -r), `distros`
(os-release identity; apt/dnf/pacman/apk), `pitfalls` (Arch partial upgrades,
DEBIAN_FRONTEND=noninteractive, apt vs apt-get for scripts, systemctl is-active exit codes).
Every fact: sources (kernel-doc / man-page / spec / distro docs) + optional local verifier.

## 4. Quality gates at publication

- ruff lint+format clean; mypy clean (33 source files)
- pytest: **297 unit + 6 live** (all live tests pass in this sandbox incl. upstream checks)
- M4 grounding eval 12/12 online; M2 planner eval 9/9; M3 fault gate 35 vectors / 0 escapes;
  M1 container eval 70/70 — all green in CI (see annotations on the latest branch run)

## 5. Known limitations (honest)

1. Answers are fact-lookup, not free-text QA: the matcher is deterministic (anchored patterns);
   paraphrase coverage is only as good as the curated patterns. No LLM is involved in answering
   (deliberate: answers must be cite-or-abstain; LLM answering would require the M2-style
   validation layer and is deferred).
2. Upstream existence checks cover **kernel-doc citations only** in v1; man-page/spec URLs are
   cited but not machine-checked (allowlist + generic HEAD probe exist; extending coverage is a
   config change, deferred until needed).
3. Non-English documentation and older distro versions are not represented in KB v1.
