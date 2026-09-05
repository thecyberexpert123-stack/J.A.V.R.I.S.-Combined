# ADR-0026: Unknown-app control — the guarded action ladder and owner-taught app packs

- **Status:** Accepted and implemented (2026-09-05; owner-directed: "when JARVIS must control
  an app the playbooks do not know — how does it do it, and how do I easily set that up
  later"; deep research at `docs/RESEARCH-unknown-app-control-2026.md`).
- **Context:** Today JARVIS can launch any app (`gui.launch`, T2), read any *guarded* desktop
  (ADR-0022), and write focused text via EditableText (ADR-0010) — but it cannot *operate* an
  app that has no playbook: it cannot press the app's own buttons, and the owner has no easy,
  charter-clean way to teach a new app. The research is unambiguous about the mechanism
  (published AT-SPI actions first; synthetic input last; vision never), and about teaching
  (LDTP-style declarative app maps, not scripts).

## Decision

**D1 — The control ladder (and nothing beyond it in v1).** For an unknown app, JARVIS:
(1) launches it (`gui.launch`, unchanged); (2) *sees* it through the ADR-0022 walls
(`desktop read`); (3) **invokes the app's own published AT-SPI actions** — `queryAction()` /
`doAction(i)` on a node located by role+name ("click", "press", "open", "menu", …); no
synthetic input at all; (4) writes text via the EditableText interface (located node, not
merely focused); (5) sends key combos as the **last resort** via the existing injection
backends. Vision/screenshot control stays parked (charter: structured state over pixels);
portal-based RemoteDesktop input is researched and **parked for its own ADR** (per-session
consent + restore-token custody conflicts with per-action consent); synthetic *clicks* are
parked with them (coordinates without an accessibility node are the brittle case the research
warns about). Custom-drawn UIs that expose no tree are an honestly disclosed gap.

**D2 — Walls are inherited downward by every rung.** `jarvis/gui/actions.py` reuses the
ADR-0022 guard constants: a blocked application (password managers, keyrings, polkit,
terminals) is refused before its tree is read; `password text` roles are refused **before any
name is read**; names are hygiened; walks are bounded (depth 4 / 256 nodes). The walls bind at
plan time (pack validation) *and* at execution time (the action runner re-checks) — defense in
depth against a pack written before an app landed on the blocklist.

**D3 — Execution is a fixed-argv kernel step, not a side door.** AT-SPI needs pyatspi
in-process, so `gui/gui/action_exec.py` is a module entry point run as an ordinary
`PlannedStep`: `python -m jarvis.gui.action_exec --app <app> --role <role> --name <name>
(--action <name> | --text <string> | --list)` — fixed argv (the `jarvis brief` timer
precedent), no shell, one JSON result line, honest exit codes (2 = refused by a wall, 3 = not
found, 0 = performed/ok). It journals like any step and its output feeds verification.

**D4 — Teaching is data that compiles through the kernel: app packs (`app-skill/1`).** The
owner writes (or edits) a small declarative pack: `id`, `description`, optional `app.launch`
tokens, `phrases` (anchored regexes the owner will speak), and bounded `steps` —
`{"focus": "<title substring>"}` | `{"action": {app?, role, name, action}}` |
`{"type": {app?, role?, name?, text}}` | `{"key": "<combo>"}`. **The schema has no field that
can carry a command**: the first launch token must be a bare command name (no slash —
resolved via PATH, so no path-based exec), the remaining tokens are plain arguments (paths,
flags, simple values — still no shell metacharacters), text is hygiene-checked (≤200 chars),
combos pass the GUI combo alphabet, titles are plain substrings, and every value is
length-bounded. `jarvis app-skill wizard --file <pack>` validates every
step by constructing it through the real builders (the M9b eval discipline), refuses anything
illegal, and installs the pack with a sha256 receipt in the M9c integrity scope. Removing is
`app-skill remove`. Packs never widen authority — they compose exactly the rungs of D1.

**D5 — Runs go through the catalog: `gui.app` (T2).** One new deterministic playbook whose
match consults installed packs' phrase regexes and whose build emits the pack's bounded steps
(launch → focus → actions/types → keys), then the standard tier gate, consent, journal, and
verification. Catalog grows **57 → 58** by the breadth discipline (its own ADR); the
classifier vocabulary follows the ADR-0023 cadence automatically (`gui.app` carries no static
hint — the prompt lists it as owner-taught, and absent packs make proposals abstain honestly
through the real matcher). Every pack run is one consented T2 task with the full plan
displayed — consent parity with `gui type/key`, and T2 is still not voice-consentable.

**D6 — Unchanged invariants.** The model is untouched by this ADR (no LLM anywhere in the
ladder); walls > packs; stdlib-only (pyatspi is the distro's accessibility package, ydotool a
probed binary per the ADR-0010/0019 pattern); no shell; every step journaled; `--no-ai`
irrelevant here (nothing AI); blocked apps never read, never actuated.

## Consequences

- The owner's question has a concrete answer: *unknown app* → JARVIS walks rungs 1–5 and
  honestly reports the ceiling; *teaching* → edit a ≤20-line JSON pack, run one wizard
  command, then speak the phrase.
- Follow-ups parked deliberately: portal input (needs its own consent design), synthetic
  clicks, vision fallback, and pack sharing/promotion through the growth loop (owner-merged).
