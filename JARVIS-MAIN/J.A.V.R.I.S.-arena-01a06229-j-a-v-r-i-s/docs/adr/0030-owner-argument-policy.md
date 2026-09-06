# ADR-0030: Owner-authored, narrowing-only argument policy over playbook argv

- **Status:** **Accepted and implemented 2026-09-06** (drafted, decided and shipped the same
  day; owner-directed "continue" sequence, `TASKS.md` item B-C1, gated as OWNER-Q in decision
  D4 — *security-sensitive*; origin: deep research II
  `docs/RESEARCH-agent-construction-and-future-tech-2026.md` §3.3 (Progent, CaMeL), §3.4
  (AgentSpec), candidate C1, owner question 1). **Owner answers (`TASKS.md` §D9–§D11):
  D-A = A3** (integrity-scoped + lint hint), **D-B = B2** for `plan` and **U3 + U1** for
  `undo`, **D-C = ship empty** ("do all"). Implemented in `safety/argpolicy.py`,
  `core/orchestrator.py` (three sites + `origins` in undo artefacts), `cli/app.py`
  (`policy lint|show|explain|example`, `doctor`/`status` lines), `cli/mcp_server.py`
  (additive `argument_policy` key), `safety/integrity.py` (scope), `tests/test_argpolicy.py`
  (40 tests). Kernel **1.22.0**.

- **Context — what the safety layer can and cannot say today (VERIFIED in this tree).**
  Every argv JARVIS executes passes `safety/tiers.py::check_argv` at three sites in
  `core/orchestrator.py` (single playbook, line 224; composite `plan`, 345; `undo` replay, 536),
  after the playbook's own `build()` validation (`planner/catalog_common.py::clean_arg`, protected
  package set via `check_removal_allowed`, protected-path classification via
  `classify_for_edit`). `check_argv` is a **fixed, code-level** policy: dangerous `argv[0]`s
  (`shutdown`, `dd`, `mkfs*`, …), regex patterns for shell content, and the token rule after
  `--`. It has no notion of *which playbook* produced the argv, and there is **no file the owner
  can edit** to say things like:

  - "`pkg.remove` may never name anything matching `^linux-image|^grub`" (the protected set is
    frozen in code, `safety/tiers.py::is_protected_package`);
  - "`fs.remove` / `fs.move` may only touch paths under `~/Downloads/**` or `~/tmp/**`";
  - "`svc.restart` / `svc.stop` may not touch `sshd|NetworkManager|systemd-logind`";
  - "`pkg.install` on this machine is limited to `^(htop|tmux|ripgrep|fd-find)$`";
  - "`proc.kill_name` may never name `Xorg|gnome-shell|plasmashell`".

  Cautious mode (`state_dir()/cautious`) is the only owner-side dial, and it is binary: it blocks
  *all* T2. The research (§3.3) found the missing rung stated cleanly by **Progent** (Shi et al.,
  arXiv:2504.11703 v3, fetched 2026-09-06 for this ADR): privilege as *symbolic rules over tool
  names and arguments*, checked by a deterministic procedure with no LLM in the loop, where
  **forbid rules are evaluated before allow rules** and every proposed policy change is
  classified as a *narrowing* (applied automatically) or an *expansion* (needs explicit approval)
  — "monotonic confinement". **AgentSpec** (ICSE 2026, §3.4) adds the sobering number that
  LLM-*generated* rules reached 70.96 % recall — a third of hazards missed — so the rules must
  be **human-owned**. Claude Code's `PreToolUse` hooks (§3.4) are the shipping-product version:
  a deterministic layer that can `deny` a tool call, with `deny` winning over parallel `allow`s.

  JARVIS already has the two halves Progent needs: a fixed tool vocabulary (58 playbooks, ids
  known at import time) and deterministic argv construction. What it lacks is the
  owner-authored, per-playbook, per-argument layer. The consent asymmetry Progent formalises
  (narrow silently, widen only with approval) is exactly JARVIS's existing shape — cautious mode
  only removes permissions — so C1 extends an invariant rather than introducing one.

- **What C1 must NOT become (charter Part B, ADR-0013 non-goals, guideline 17).** A policy file
  that could *grant* would be a second consent path outside the journaled per-call `allow`.
  Therefore: **rules can only refuse.** They never raise or lower a tier, never satisfy consent,
  never bypass `check_argv` or the playbook validators, never add an execution path. An empty or
  absent policy is byte-identical to today. A malformed policy **fails closed** for the
  playbooks it names — but not for the whole system (see D3), because "policy file has a typo,
  so nothing runs" would push the owner to delete the file, which is the worst outcome.

## Decision

### D1 — Policy document: one JSON file, owner-written, rules that only refuse

`state_dir()/policy/argument-policy.json` (path under the state dir like charters; **where it
sits relative to the integrity scope is D-A below**). Shape, all keys required unless marked:

```json
{
  "schema": 1,
  "rules": [
    {
      "id": "no-kernel-removal",
      "playbooks": ["pkg.remove"],
      "argument": "names[]",
      "deny_regex": "^(linux-image|linux-headers|grub|systemd|sudo)",
      "reason": "boot- and login-critical; remove by hand if ever"
    },
    {
      "id": "scratch-dirs-only",
      "playbooks": ["fs.remove", "fs.move"],
      "argument": "path|src|dst",
      "allow_prefixes": ["~/Downloads/", "~/tmp/"],
      "reason": "JARVIS deletes/moves only inside scratch space"
    },
    {
      "id": "never-touch-login-services",
      "playbooks": ["svc.stop", "svc.restart", "svc.disable"],
      "argument": "unit",
      "deny_regex": "^(sshd|ssh|NetworkManager|systemd-logind|gdm|sddm)(\\.service)?$",
      "reason": "would lock me out of the box"
    }
  ]
}
```

- **`playbooks`** — list of playbook ids (validated against the catalog at load; an unknown id
  is a lint error, so a typo cannot silently disable a rule). `"*"` is allowed and means *every
  playbook that has that argument name*.
- **`argument`** — the **params key** the playbook's `match()` produced (`names`, `path`, `src`,
  `dst`, `unit`, `text`, `app`, `pid` — VERIFIED by running `match()`: `pkg.install` →
  `{"names": [...]}`, `fs.move` → `{"src", "dst"}`, `svc.restart` → `{"unit"}`,
  `file.append` → `{"text", "path"}`). `name[]` addresses each element of a list value;
  `a|b|c` addresses any of several keys. Rules bind to **params, not argv**, because params are
  the owner-meaningful objects ("the package", "the path"); the argv is a rendering the owner
  should not have to reverse-engineer (`apt-get remove -y -- htop` vs `pacman -Rs -- htop`).
- **Exactly one of `deny_regex` / `allow_prefixes` / `allow_regex`** per rule. Semantics:
  - `deny_regex`: refuse when the value matches (Python `re.search`, compiled once, anchored by
    the owner as they see fit; rule text is shown in the refusal).
  - `allow_prefixes`: refuse unless the **resolved** value (`~` expanded, `os.path.realpath`
    for path arguments) starts with one of the prefixes — the same normalisation the playbook
    itself applies before building argv, so `../` tricks are caught by the same function.
  - `allow_regex`: refuse unless the value matches.
  Multiple rules for the same playbook/argument are all evaluated; **any refusal refuses**
  (Progent's forbid-before-allow, with no allow rule able to override a deny — by construction,
  since allow-style rules also only *refuse* when unmatched).
- **`reason`** — free text, ≤ 200 chars, single line; it is what the owner reads in the
  refusal and in the journal.
- **Values that are not strings or lists of strings** (e.g. `pid` as int, `tokens` list) are
  compared as `str(value)`; a rule naming an argument the playbook does not produce is a lint
  **warning** (kept, inert) so a rule can be written ahead of a playbook.

No `allow` effect that *grants*; no tier field; no per-rule "skip consent"; no wildcards in
regexes beyond what `re` provides; **no `updatedInput`** (Claude Code's rewrite-the-call
option) — JARVIS refuses, it never silently changes the plan (ADR-0016 D2 "refusal, never
sanitization").

### D2 — Enforcement point: once, between `build()` and `check_argv`, on params *and* argv

A new module `safety/argpolicy.py` with `load_policy(env) -> Policy` and
`Policy.check(playbook_id, params) -> None | raises SafetyRefusal`. Called at the **three
existing sites** (the same places `check_argv` runs), never anywhere else:

| Site | Input available | Behaviour |
|---|---|---|
| single playbook (orchestrator 224) | `playbook.id`, `params`, `steps` | `policy.check(playbook.id, params)` **before** `check_argv`; refusal → `_refused_no_journal` today's path, message `argument policy rule 'no-kernel-removal' refused pkg.remove names=linux-image-6.8: boot- and login-critical…` |
| composite `plan` (345) | per-part `(playbook, params)` | each part checked; first refusal refuses the whole plan (today's semantics for `check_argv`) — **see D-B** |
| `undo` replay (536) | argv only; `_rebuild_undo_steps` has no params | **see D-B** — the artefact carries `playbook_id`-free steps; options below |

The check is **pure**: no I/O beyond reading the file once per `Orchestrator` (cached with the
file's mtime+size so a long-lived doorway picks up edits without restart, and a fresh MCP
`Journal`/orchestrator per call — VERIFIED `cli/mcp_server.py::_orchestrator()` — needs no
extra plumbing). Cost: one regex per rule per argument; with tens of rules this is microseconds.

### D3 — Failure semantics: fail closed per named playbook, never system-wide

| Condition | Behaviour |
|---|---|
| File absent | No rules; behaviour identical to today (the default ship state). |
| File present, valid | Rules enforced as above. |
| File present, **invalid JSON / schema** | `load_policy` returns a `Policy` in *degraded* state: **every rule's `playbooks` that could be parsed are refused outright** ("argument policy file is malformed; refusing pkg.remove until `jarvis policy lint` passes"), playbooks the broken file does not mention run as today. If *nothing* parses (not even the rule list), **all T1+ playbooks are refused** and T0 runs — T0 is read-only by construction (VERIFIED: 0 of 38 T0 playbooks set `requires_root`, none writes). `jarvis doctor` and `jarvis status` show the degraded state. |
| Rule regex fails to compile | That rule is treated as "refuse everything it names" (fail closed for its scope), lint names the rule. |
| Policy names an unknown playbook id | Lint error; at runtime that entry is ignored (it can bind to nothing) and reported. |
| Owner edits the file while the doorway runs | mtime/size cache reloads on next call; a half-written file hits the malformed row above for one call, then recovers. |

Rationale: Progent's default fallback is "return an error message so the agent can continue
with other tools"; ours is the same shape — the *named* capability refuses with the reason, the
rest of the system stays usable — but a broken file must never widen anything, hence the
asymmetric degradation toward refusal.

### D4 — CLI surface (additive): `jarvis policy lint | show | explain`

- `jarvis policy lint [PATH]` — validates schema, playbook ids, argument names against the
  catalog, compiles regexes, expands prefixes; prints one line per finding; exit 0 clean / 1
  errors. Same style as `jarvis doctor`.
- `jarvis policy show [--json]` — the effective rules and which playbooks each binds to.
- `jarvis policy explain "<request>"` — runs match + build + policy check with **no execution
  and no journal** (dry-run semantics) and prints which rule, if any, would refuse. This is the
  owner's way to test a rule before relying on it.
- No `jarvis policy add/remove`: the owner edits the file (guideline "human-owned rules";
  AgentSpec's finding). A future ADR may add LLM-*proposed* narrowings behind the same
  narrowing-only check; not here.
- `jarvis doctor` gains one line: `argument policy: N rules over M playbooks (ok)` /
  `(absent)` / `MALFORMED — …` (JSON key `argument_policy`), so the M9c verdict covers it.
- MCP: **no new tool**. `jarvis_status` payload gains `argument_policy: {"rules": N,
  "state": "ok|absent|malformed"}` (additive key; ADR-0018 parity keeps the doorway identical).
- Refusals from the policy are journaled exactly like other refusals (`_refuse_journaled` for
  the paths that already journal; `_refused_no_journal` where `check_argv` refusals are not
  journaled today — **unchanged classification**, no new journal columns).

### D5 — Tests (all offline)

- `tests/test_argpolicy.py`: schema accept/reject table; each of the three effects; list
  arguments (`names[]`); multi-key `path|src|dst`; `~` and `realpath` normalisation catches
  `~/Downloads/../.ssh/id_rsa`; unknown playbook → lint error + inert; regex compile failure →
  fail closed for its scope; malformed file → named playbooks refused, T0 runs; absent file →
  `Policy.empty()` and orchestrator behaviour byte-identical (existing suite is the oracle).
- Orchestrator tests at all three sites (with the `undo` behaviour per D-B), including "a
  rule never turns a REFUSED into anything else" and "a rule never changes the tier".
- **M3 fault suite must still report 0 escapes** with a policy file present that names every
  T1/T2 playbook with permissive rules (proves the layer is additive), and with a deny-all file
  (proves fail-closed does not crash).
- `jarvis policy explain` golden outputs for the three sample rules above.
- Mutation checks recorded in the CHANGELOG as for C3 (e.g. swap `re.search` for `re.match`,
  drop the `realpath` step, evaluate allow before deny).

### D6 — Non-goals

Per-request dynamic policies generated by an LLM (Progent's headline feature) — JARVIS's
planner never sees tool output, so the injection vector Progent targets is absent (research
§3.2); SMT-checked policy diffs — unnecessary when every rule can only refuse (a diff is a
narrowing iff it adds rules or tightens regexes, which `jarvis policy lint --diff` could report
textually later); rules over *step argv* (the owner would have to know package-manager
spellings); any change to tiers, consent, or the runner.

## Owner decisions (asked and answered 2026-09-06 — see Status; kept verbatim for the record)

**D-A. Where does the policy file live — integrity-scoped or operational?**

| Option | Mechanism (VERIFIED against `safety/integrity.py`) | Pro | Con |
|---|---|---|---|
| **A1 — integrity-scoped** | Add `state_dir()/policy` to `default_scope().dirs`; the `*.json` glob picks the file up. Editing it then shows as `changed` drift in `jarvis doctor` until `jarvis doctor --baseline` is re-run (same discipline as charters and the KB). | Tamper-evident: a silent *removal* of a rule by malware or a mistaken script is reported as drift — the property that makes a deny-list trustworthy. Matches how charters are already treated. | Every legitimate edit needs a re-baseline; a policy the owner tunes weekly will train them to re-baseline reflexively (the "click OK" failure mode). |
| **A2 — operational** | Path `state_dir()/policy/argument-policy.json` **outside** the scope (or `.policy` extension to dodge the glob, as `charter.py::state_path` does for `.state`). | Frictionless editing; the file is *only* ever restrictive, so tampering can only *loosen* it — and loosening returns to today's (already accepted) behaviour, not below it. | Silent rule removal is invisible; the layer becomes advisory against an attacker with file write access to the state dir (who could also, today, flip `cautious` off — the same trust boundary). |
| **A3 — both (recommended by me, decision is yours)** | Scope the file (A1) **and** make `jarvis policy lint` print "baseline is stale for this file — run `jarvis doctor --baseline` when you are done editing" so the friction is explained once, not felt as noise. | Tamper-evidence with an honest UX. | Slightly more code (one message). |

**D-B. What happens on `plan` and `undo`?**

- **`plan` (composite):** B1 — first refusing part refuses the whole plan (today's `check_argv`
  semantics; simplest; the owner sees which part and why). B2 — refuse the whole plan but list
  *all* refusing parts. I recommend **B2** (more useful message, same safety).
- **`undo`:** the undo artefact (`_undo_payload`) stores steps and argv but **not the playbook
  id or params**; `_revalidate_undo_step` re-applies domain rules to argv. Options: U1 — policy
  does **not** apply to undo (undo reverses a change the policy already allowed or that predates
  the rule; refusing the reverse could strand a system in the state the rule was written to
  prevent). U2 — apply argv-level checks only for rules whose effect is expressible on argv
  (`deny_regex` over the tokens after `--` for package rules, over operands for `rm`/`mv`/`cp`),
  skip prefix rules. U3 — extend the artefact with `playbook_id` + `params` (**additive JSON
  keys**, old artefacts keep working via U1 fallback) so undo is checked exactly like a forward
  run. I recommend **U3 with U1 for legacy artefacts**, and I flag that U3 touches the undo
  payload shape (additive, but it is a persisted format — hence your call).

**D-C (minor, default if you do not object).** Ship **no rules** by default, plus an
`examples/argument-policy.example.json` with the three rules above and comments in the README;
packaging never installs the file (same rule as residency and timers).

## Failure modes

| Failure | Behaviour | Degrades to |
|---|---|---|
| No policy file | Empty policy | Today, byte-identical |
| Malformed file | Named playbooks refused, T0 runs, doctor/status report it | Safer than today, never wider |
| Rule too broad (owner error) | Legitimate request refused with the rule id and reason; `jarvis policy explain` shows why | Owner edits the rule; no state changed |
| Rule too narrow / typo in playbook id | Lint error; runtime ignores the dead entry and reports it | Today for that playbook (not silently "protected") |
| Policy edited mid-run of the doorway | Reloaded on next call by mtime/size | One call may see the malformed row; then recovers |
| Attacker with state-dir write access deletes rules | A1/A3: `jarvis doctor` DRIFT; A2: invisible | Never below today's fixed `check_argv` |
| Regex catastrophic backtracking (owner-authored) | Lint rejects patterns > 200 chars and nested quantifier forms `(x+)+`; runtime applies `re` with no timeout (stdlib has none) | Documented limit; the owner authors their own rules |

## Consequences

- Least privilege becomes **owner-configurable per playbook and argument** without a second
  consent path; the effective action space can only shrink relative to today.
- `check_argv`, the tiers, the consent flow, the runner, MCP tool names/payloads (beyond one
  additive key) and the journal schema are unchanged. Unit files unchanged.
- One new state file, one new CLI verb group (`policy`), one new `doctor` line, one new module
  (`safety/argpolicy.py`, stdlib only — `re`, `json`, `os.path`), + tests. Estimated size M
  (≈ 300 lines + tests), one minor version bump (1.22.0) when it ships.
- Owner-machine verification: none required beyond the offline suite — this item has no
  sandbox limits (`TASKS.md` §C).

## Sources (fetched 2026-09-06 unless marked)

- T. Shi, J. He, Z. Wang, H. Li, L. Wu, W. Guo, D. Song, "Progent: Securing AI Agents with
  Privilege Control," arXiv:2504.11703 v3 (14 May 2026) — abstract page and HTML §2, §4.1–4.2
  fetched: policy = list of rules `E t when {e_i} fallback f` with `E ∈ {allow, forbid}`,
  conditions over arguments incl. `match` (regex) and `in`; runtime sorts **forbid before
  allow**; fallbacks = terminate / ask user / return message; updates classified narrowing vs
  expansion by SMT ("monotonic confinement"); ASR 39.9 % → 1.0 % on AgentDojo, 70.3 % → 3.9 %
  on ASB.
- H. Wang, C. M. Poskitt, J. Sun, "AgentSpec," arXiv:2503.18666 (ICSE 2026) — research II §3.4,
  `[fetched abstract]`: LLM-generated rules 95.56 % precision / 70.96 % recall → rules must be
  human-owned.
- Claude Code hooks documentation (research II §3.4, `[snippet]`): `PreToolUse` `deny` wins
  across parallel hooks; `updatedInput` exists there and is deliberately **not** adopted here.
- E. Debenedetti et al., "CaMeL," arXiv:2503.18813 (research II §3.3, `[snippet]`): capability
  tracking on values — the *next* rung after C1, out of scope.
- This repository (VERIFIED by reading/running on 2026-09-06): `safety/tiers.py` 39–175;
  `core/orchestrator.py` 205–235, 335–355, 486–545, 753–771 (`_undo_payload`), 798–836
  (`_rebuild_undo_steps`), 855–877 (`_revalidate_undo_step`); `safety/integrity.py` 51–81,
  92–166; `safety/charter.py` 45–56 (`.state` outside the glob); `planner/models.py`
  (`Params = dict[str, object]`, `PlannedStep`); `planner/catalog_common.py::clean_arg`;
  `cli/mcp_server.py::_orchestrator`; catalogue: 58 playbooks (T0 38 / T1 10 / T2 10), params
  keys observed via `match()`: `names`, `path`, `src`, `dst`, `unit`, `text`, `app`, `tokens`.
