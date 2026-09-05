# ADR-0016: Playbook catalog breadth — command families, not a shell

- **Status:** Accepted and implemented (2026-09-04; owner-directed: "add almost every possible
  Linux Command in the Playbook, also maintain my guidelines").
- **Context:** The catalog covered package/service/file-core/GUI families (12 playbooks). The owner
  wants breadth. The guideline constraint is the architecture itself: ADR-0006 (argv-only, no
  shell, refusal not sanitization), ADR-0007 (every step re-validates through real matchers),
  ADR-0013 (every capability enters through the kernel or not at all — **no eval-style
  passthrough**). Research baseline: OpenClaw's exec-approval "safe bins" (fixed binaries, literal
  argv tokens, per-binary flag denials) and the OWASP-style no-shell allowlist pattern (pin the
  operation, validate arguments by regex, never expand metacharacters); see also the committed
  landscape research (injection classes, approval fatigue) — external sources listed below.

## Decision

**D1 — Breadth by auditable families, never a passthrough.** Each new command is a real Playbook
(match → validate → fixed-argv build → verify → undo) produced by a declarative spec + factory in
`src/jarvis/planner/`. A spec pins: the binary, the FULL fixed flag set, the argument slot(s) with
a per-kind validator, natural-language patterns, tier, timeout. Factory-built playbooks are
byte-auditable in review exactly like hand-written ones — the spec table IS the review surface.

**D2 — Argument policy.** No user-supplied flags, ever: a leading `-` in any user argument is a
refusal (flags change semantics — `find -delete`, `sort -o`, `grep -R`). Kinds: `path` (no control
chars, no leading dash, ≤200 chars, case preserved), `name` (strict token), `host`
(hostname/IP token), `glob` (find `-name`: glob metachars allowed, `/` and dashes forbidden —
glob expansion is the runner's business, there is no shell). `unit` reuses `validate_unit_name`.

**D3 — Tier map.** All pure readers are **T0** (~31 commands: ls/cat/head/tail/wc/stat/file/which/
du/md5sum/find/grep-fixed + df/free/ps/uptime/date/hostname/lscpu/lspci/lsusb/lsblk/ss/ip
addr/ip route/journalctl/dmesg/who/last/env/id + ping/dig). File mutations are **T1** with real
undo semantics where honesty allows (mkdir→rmdir; touch/cp→remove-created-if-absent-at-plan-time;
mv→move-back; ln→remove-link; rm→UNAVAILABLE with an honest reason — deletion is irreversible),
all through `classify_for_edit` so protected sets and T2 prefixes are enforced exactly as for
`file.append`. Process/system mutations are **T2** (svc.stop/restart/disable, kill, pkill -x).

**D4 — The never-list is part of the design.** There is deliberately NO playbook for: `dd`, `mkfs*`,
`fdisk`/`parted` (block-device destruction = T3-class), `shutdown`/`reboot`/`halt` (session-owning
disruption is the operator's console job), `curl`/`wget` as generic fetchers (new egress path —
network stays behind `knowledge/fetch.py`'s allowlist), `sed -i`/`awk` as free-program tools
(programmable interpreters are injection surfaces), and `chmod`/`chown` (recursion and ownership
changes deserve their own designed milestone, not factory breadth). Tests assert these are
unmatchable. "Almost every possible command" is honored as: every command that can be given a
honest verify/undo story under the kernel — and an explicit, tested refusal for the rest.

**D5 — Case sensitivity and scoping.** The `fs.*` family joins `file.*`/`gui.*` in match_intent's
case-preserved lane (Linux paths are case-sensitive). The LLM planner's prompt vocabulary stays
core-only (the deterministic engine owns the long tail — a model proposing rare intents would
mostly miss anyway); `nearest_intents` and the M11 classifier disclosure operate over the full
catalog automatically. MCP surface untouched (tools play playbooks, whatever their count).

## Consequences

- Catalog: 12 → **56 playbooks** (T0 37 / T1 10 / T2 9; counts as shipped in v1.11.0). New modules:
  `planner/catalog_common.py` (validators, exit-0 verify, undo helper),
  `planner/inspect_cmds.py`, `planner/file_cmds.py`, `planner/proc_cmds.py`;
  `playbooks.py` concatenates the families into `PLAYBOOKS`.
- Readers may honestly fail without root (`dmesg`, `journalctl` on some systems) — that is the
  disclosure contract, not a bug. `--no-ai` behavior unchanged (all of this is deterministic).
- Future families (network config, containers, user mgmt, chmod) follow the same spec+factory and
  the `unknown_requests` journal tells the owner which to add next.

## External sources

- OpenClaw exec approvals / safe bins — fixed-binary allowlists with literal argv tokens and
  per-binary flag denials: https://dev.to/hex_agent/openclaw-exec-approvals-controlling-what-your-ai-agent-can-run-32fn
- No-shell allowlist wrapper pattern (pin operation, regex-validate args, `shell=False`):
  https://codenote.net/en/posts/aws-cli-ai-agent-secure-access-defense-in-depth/
- Project-internal: ADR-0006/0007/0013 (no shell, propose/dispose, kernel-only door);
  `docs/RESEARCH-agent-landscape-2026.md` (injection/taxonomy, approval fatigue).
