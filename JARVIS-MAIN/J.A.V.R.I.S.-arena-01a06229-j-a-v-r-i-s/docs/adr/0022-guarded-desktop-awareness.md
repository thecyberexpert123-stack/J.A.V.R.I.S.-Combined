# ADR-0022: Guarded desktop awareness — the read-only tier of the AT-SPI family

- **Status:** Accepted and implemented (2026-09-04; owner-directed "continue" — roadmap item R4
  from `docs/RESEARCH-jarvis-agent-linux-2026.md`).
- **Context:** The research names the boundary precisely: "AT-SPI exposes window contents to
  any client on your session bus" — the same trust boundary screen readers get. JARVIS has been
  such a client since M9e (`gui/atspi.py`, ADR-0010): `desktop_window_titles()` reads window
  titles and `set_focused_text()` writes to the focused editable — with **no guards at the data
  boundary**. The published hardening posture for agent desktop access (blocked-app set,
  blocked roles, sensitive-name redaction, tiers, per-operation audit) is the missing piece.
  R4 in the research plan is the *guarded family*: T0 read tools now; action tools already have
  their own consent surface (GUI service, ADR-0010) and stay as they are; input injection via
  portals/ydotool stays parked.

## Decision

**D1 — The tier shipped now is read-only, and the guard is at the data boundary, not the
transport.** `src/jarvis/desktop/` adds pure, transport-agnostic guard logic (`guards.py`) and
one guarded reader (`read.py`). The pyatspi transport is unchanged from ADR-0010 — its absence
remains an honest capability gap, never an error. Action tooling (`set_focused_text` and the
GUI service's consent+journal flow) is not modified by this ADR beyond inheriting blocked-app
visibility. Wayland portals / ydotool / compositor input remain parked for a future ADR; the
`run_shell`-style escape hatch of production MCP servers is rejected, as in the research.

**D2 — Fail-closed walls, in order, before anything is displayed or stored:**

1. **Blocked applications** (`BLOCKED_APPS`): password managers (keepass*, bitwarden,
   1password, passwordsafe, dashlane, lastpass, enpass, proton pass), keyrings/secret services
   (seahorse, *keyring*, kwallet), polkit/pkexec/askpass privilege agents, and terminal
   emulators (gnome-terminal, konsole, xterm, st, urxvt, alacritty, kitty, wezterm, tilix,
   terminator, foot) — shell content is out of scope for a read-only agent. A blocked app's
   subtree is never read at all; its presence is disclosed as `[withheld: application '<name>'
   is on the blocked list]`. Matching is case-insensitive exact-or-substring; the bias is
   explicit: **false-positive blocks are acceptable, false-negative reads of a secret-bearing
   surface are not** (e.g. an app named "football manager" is withheld too).
2. **Password roles** (`PASSWORD_ROLES = {"password text"}`): a node with the AT-SPI secure-entry
   role is withheld **before its name is ever read** — the field appears as
   `[withheld: password text field]` and nothing about its content crosses the boundary.
3. **Sensitive-name redaction**: after a name is read but before display/persist, names matching
   the sensitive pattern (password/passphrase/passcode, secret, token, credential, API/auth
   key, private key, OTP/TOTP/2FA, CVV/CVC/CSC, card/account number, PIN — word-boundary
   regex, so "author", "passport", "pinning" do not match) render as
   `(redacted: sensitive field)`.

All three walls are frozen constants + pure functions, pinned by tests, and shared by every
reader (CLI and GUI service alike).

**D3 — Budgets and hygiene.** Walk depth ≤ 4 (desktop → application → window → two widget
layers), node budget 512 with an honest `[node budget exhausted — truncated]` marker, names
hygiened (control chars stripped, whitespace collapsed, ≤ 120 chars) at every boundary
crossing. A node that fails to answer (bus error) becomes `[unreadable node]` and the walk
continues. The walk is read-only by construction: no method that can mutate state is called —
pinned by a test asserting `queryEditableText` is never invoked during a read.

**D4 — Per-operation audit, content-free, zero retention of tree content.** Every read appends
one line to `<state>/desktop/ledger.jsonl`: timestamp, source (cli/gui), blocked-app
identifiers (blocklist names, not user content), counts (nodes, withheld roles, redacted
names), and the truncated flag. **No title, field name, or any other tree content is ever
persisted** — a test pins that a distinctive window title appears nowhere in the ledger bytes.
Desktop content never enters planner prompts, memory blocks, or briefings; the
situation-aware combination (briefings reading the desktop) is parked for a future ADR.

**D5 — Consent posture and blast radius.** Reads are on-demand, owner-issued commands — there
is no scheduled or ambient reading. `jarvis desktop read` prints the guarded outline plus a
guard summary (withheld/redacted/truncated counts and the audit path); `jarvis desktop status`
reports availability honestly plus audit totals. The one existing consumer is rewired through
the guard: `desktop_window_titles()` now returns guarded titles, so the GUI service's
window list / focus / type flows **cannot list, focus, or type into a blocked app at all** —
the guard inherits downward, never upward. Unavailability keeps the ADR-0010 contract:
`(None, honest reason)`.

## Consequences

- The agent can finally answer "what is on my desktop" without screenshots — inside walls
  that assume the session bus is hostile territory until proven otherwise.
- The guard lives in one place; future readers (MCP surface, situation-aware briefings) must
  consume `jarvis.desktop.guards` — the tests pin the constants so drift is a CI failure.
- What is deliberately not here: input injection (portals/ydotool — future ADR, per-action
  consent), deep-tree extraction for LLM grounding, and any ambient/scheduled read. Each is a
  separate decision with its own consent design.
