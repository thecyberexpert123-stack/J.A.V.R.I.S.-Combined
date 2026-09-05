# Safe-testing ladder for JARVIS

Read this before running JARVIS on a machine you care about. It is the honest
map of what is verified, what is not, and how to build trust in stages.

## What is verified (see `evals/results/`)

- Known destructive commands cannot execute: 35-vector injection gate, 0 escapes (CI).
- Protected paths (`/etc/shadow`, sudoers, `/boot`, kernel trees) are refused; symlinks are resolved first.
- Nothing system-level (T2) runs without your explicit consent; T3 (destructive) is refused by policy, always.
- Every action is journaled (`jarvis tasks`); file edits are backed up and restorable byte-identical (`jarvis undo`).
- Execution is argv-only — no shell, no interpolation, controlled stdin.
- Zero telemetry.

## What is NOT verified — residual risks

1. **Novel destructive commands**: the blocklist is a deny-list; an unlisted destructive tool could pass.
2. **Real-model behavior**: CI validates with scripted planners; a live LLM proposes new things (the kernel gates them, but kernel code can have bugs — M3 found and fixed one).
3. **GUI focus races**: between target disclosure and injection, window focus can change on a real desktop (mitigated by the TOCTOU re-check in v1.1.0, but treat GUI `type` as experimental).
4. **Partial-failure state**: composite plans can leave partial changes if they die mid-way (auto-rollback exists since v1.1.0 — opt in with `--auto-rollback`; otherwise use `jarvis undo`).
5. **Your machine is not a catalog**: evals ran in containers; real hardware has state no catalog predicted.
6. JARVIS runs as **you** (plus sudo for root steps): blast radius = your account and everything sudo reaches.

## The ladder (build trust rung by rung)

**Rung 0 — disposable containers** (what CI does): any distro image; throw tasks; delete.

**Rung 1 — disposable VM of your distro:** snapshot first, then exercise the full
flow (including `--yes`, undo, `file append`). Compare before/after.

**Rung 2 — your real machine, read-only + refusal drills:**
```sh
jarvis safety-check                        # the guards, self-tested live (no side effects)
jarvis status && jarvis explain "what is ostype"
jarvis do "check service sshd"             # T0, read-only
jarvis do --preview "install htop"         # full plan + blast radius, never executes
jarvis do "install htop"                   # T2 on non-tty must REFUSE (or ask on a tty)
jarvis file append /etc/shadow x           # must be refused
```
If any refusal above does not happen exactly as described — stop and report it.

**Rung 3 — real T2 tasks under a contract:**
```sh
jarvis cautious on                         # early-days guard: T2+ blocked per invocation
jarvis do "upgrade the system" --preview   # review the plan...
jarvis do "upgrade the system" --cautious-ok --auto-rollback   # ...then one-shot it
jarvis tasks && jarvis undo <task-id>      # your rollback path
```
Rules that never expire: snapshot/backup before T2; read the plan before
consenting; prefer explicit CLI over ambiguous NL; never `--yes` a plan you
haven't read.

## Reporting a safety bug

Open an issue with: the request text, the plan echo, the outcome, and
`jarvis tasks` output. Redact nothing except personal paths — the journal
already keeps typed GUI text out (length + hash only).
