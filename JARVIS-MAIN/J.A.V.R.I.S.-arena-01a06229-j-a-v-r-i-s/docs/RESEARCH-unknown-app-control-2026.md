# Deep research: controlling an unknown app — and teaching JARVIS new apps (2026-09-05)

**Owner question (verbatim intent):** *"When JARVIS will try to control and use another APP,
which the playbook does not know — then how will it do it? And how will I easily, later, set
that up?"* — i.e. (a) the unknown-app control mechanism, (b) the owner-side teach workflow.
**Method:** web research (10 sources, 2024–2026, tier-labeled below) + the committed 2026
corpus (`docs/RESEARCH-jarvis-agent-linux-2026.md` §3.3) + first-party inspection of our own
GUI/AT-SPI surface (ADR-0010/0022). Companion decision: `docs/adr/0026-unknown-app-control.md`.

## 1. The mechanism landscape (how agents control apps they were never hardcoded for)

| Tier | Mechanism | Maturity 2026 | Sources |
|---|---|---|---|
| **T-a: published actions** | AT-SPI **Action interface**: `queryAction()` → `get_action_name(i)` → `doAction(i)`; typical names "click", "press", "release", "open", "menu". This is how screen readers "press buttons" — the app itself performs the action; no synthetic input at all. | Production (dogtail/LDTP/Accerciser/computer-use-linux all use it) | [1][2][3][5] |
| **T-b: direct text write** | AT-SPI **EditableText** (`setTextContents`) on a located node — API-first typing, already shipped in JARVIS (ADR-0010 M9e) | Production (ours + [2]) | [2] |
| **T-c: synthetic input** | **Wayland:** `ydotool` (uinput — kernel-level, below the compositor; needs the `ydotoold` daemon + input-group membership) or **xdg-desktop-portal RemoteDesktop** (per-session user-consent dialog; **restore token** grants persistence; breaks on locked sessions/headless). **X11:** xdotool (legacy, already our injection backend) | Working but consent-laden | [6][7][8] |
| **T-d: vision (screenshots + VLM)** | Screenshot → model → coordinates | The 2026 *fallback*, not the default: brittle, high-latency, privacy-hostile; consensus is a11y-tree-first with vision only for canvas/custom-drawn UI | [9][10] |

**Consensus 2026 ([9][10]):** accessibility-tree reasoning by default; deterministic scripting
for validation/replay; vision only where structure runs out. Custom-drawn UIs (games, canvas)
may expose *no* accessibility tree at all — an honest limitation to disclose, not hide.

## 2. The security boundary (why tiers and walls are non-negotiable)

- "AT-SPI exposes window contents to **any client on your session bus**" — the screen-reader
  trust boundary; every current-gen tool re-states it [5][4→corpus 23]. Actions are *mutators*:
  computer-use-linux classifies `perform_action`, `type_text`, `set_value` as **destructive**
  MCP mutators vs read-only observation [5].
- The guarded pattern is stable across the corpus: **blocked-app set (password managers,
  terminals, keyrings, polkit), blocked roles (password text), sensitive-name redaction,
  permission tiers, per-op audit** [4 = corpus 23] — exactly what JARVIS shipped in ADR-0022.
- The `run_shell` escape hatch exists in production tools behind an opt-in env var [5]; the
  2026 corpus and this project **reject it** — it converts an agent into a shell with extra
  steps.
- Tiered-permission best practice [9]: Silent (read) / Logged (writes) / Confirmed (shell,
  cross-scope) / Blocked (credentials, system modification). JARVIS's T0–T3 maps 1:1.

## 3. The teachability landscape (how owners "add" an app today)

- **LDTP "AppMap"** [3]: an application map of widgets (class, name, instance index) generated
  by introspection, plus **keyword-driven scripts** and record-&-playback; verification APIs
  (`guiexist`, `verifystate`). The canonical proof that *declarative UI maps + bounded keyword
  vocabulary* works on AT-SPI.
- **Strongwind** [2]: "application wrappers" — object-oriented per-app representations reused
  across scripts; logs action/expected-result per step.
- **Modern MCP packs/hermes skills** [5]: apps ship skills that teach an agent *how to install,
  verify and call* — data, not code.
- Nobody in the surveyed set combines owner-taught app packs **with** a consent kernel, walls,
  and journaling — the combination is again this project's differentiator (corpus §3.7).

## 4. Design conclusions carried into ADR-0026

1. **The unknown-app answer is a ladder, not a leap:** launch (already `gui.launch`) → see it
   (ADR-0022 guarded read) → **invoke its published AT-SPI actions** (new, API-first, no
   synthetic input) → API text write (already shipped) → synthetic keys last resort (ydotool
   fixed argv) → vision: never (parked, charter). Custom-drawn UIs: honestly out of reach v1.
2. **Teaching = data that compiles through the kernel** (the M9b discipline extended to GUI):
   declarative app packs over a *bounded step vocabulary* — `focus` / `action` / `type` /
   `key` — each step constructible only through the real builders, receipt-pinned, integrity-
   scoped, every run a consent-gated T2 task. No argv, no shell, no scripts anywhere in the
   schema.
3. **Portals are researched but parked**: per-session consent + restore-token custody conflicts
   with per-action consent and needs an interactive consent daemon — its own future ADR.
   ydotool remains the opt-in synthetic tier behind the existing wizard.
4. **Runs go through the catalog**, not a side door: one new deterministic playbook (`gui.app`)
   whose match consults installed packs and whose build emits the bounded steps — so packs are
   journaled, consent-gated, and classifier-visible like everything else.

## Sources

1. GNOME/pyatspi2, `action.py` — the Action interface (`doAction`, action names) `[eng]` — github.com/GNOME/pyatspi2
2. modehnal, "Automation through Accessibility" (dogtail patterns: `doActionNamed`, clicks, `.text` writes) `[eng]` — modehnal.github.io
3. LDTP — Linux Desktop Testing Project: AppMaps, keyword-driven scripts, record/replay, verification APIs `[eng]` — qatestingtools.com/ldtp; ldtp.freedesktop.org appmap howto; Grokipedia LDTP (2026-01)
4. lobehub `linux-at-spi2` skill — guarded `perform_action` (tiers, BLOCKED_APPS/ROLES, audit) `[eng]` — corpus ref [23]
5. agent-sh/computer-use-linux (Rust MCP, 2026-08): AT-SPI trees, `perform_action`/`set_value` as destructive mutators, doctor readiness, portal prompts, env-gated `run_shell` (rejected here) `[eng]` — github.com/agent-sh/computer-use-linux
6. thelastguardian, "Screen control on Wayland" (2026-04): ydotool/uinput below the compositor; portal RemoteDesktop + restore tokens; single-session action chains `[eng]`
7. Monodes, "Remote Desktop on Wayland in 2026" (2026-02): compositor-mediated capture/control; per-scope consent prompts `[eng]`
8. pinggy.io (2026-08): locked-session/headless breaks portal consent and restore tokens `[eng]`
9. Zylos, "Computer Use and GUI Agents in 2026" (2026-02): a11y-tree-first + vision fallback consensus; tiered permissions `[eng]`
10. Tizkova, "How do computer use agents work?" (2026-08): a11y tree roles/names/states; hybrid backend routing `[eng]`

**Verified vs assumption:** [1][3][4][5] verified from primary docs/code; [2][6][7][9][10]
practitioner write-ups (engineering tier); latency/persistence claims ([6][8]) are
single-source observations, treated as directional. No benchmark numbers were adopted from
this pass.
