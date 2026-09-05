# ADR-0018: Hybrid residency — the agent stays on-demand; an opt-in resident *doorway* may exist

- **Status:** Accepted and implemented (2026-09-04; owner-directed: "Combine both, and make a
  Hybrid, option" — combining the systemd user-unit doorway and the GUI-autostart option into
  one opt-in hybrid mode).
- **Context:** JARVIS never autostarts (charter: no unsolicited action — nothing runs unless the
  human runs it). The owner asked for a hybrid that keeps that guarantee for the **agent** while
  removing the *availability* cost: after login, a resident process may exist whose only job is
  to answer the door. The resident thing is a **doorway, never an actor** — it holds no
  authority the CLI does not have, and every request that passes through it crosses the same
  match → plan → approve → execute → verify pipeline with the same consent semantics.

## Decision

**D1 — `jarvis serve`: a loopback-only, token-authenticated doorway with MCP parity.**
`src/jarvis/cli/serve.py` reuses the MCP server's tool handlers verbatim
(`cli/mcp_server.py::_tool_*`) over a stdlib HTTP transport (`ThreadingHTTPServer`):

- `GET /v1/health` → `{"ok": true}` and nothing else (no auth, zero information).
- `POST /v1/tools/<name>` for exactly the six MCP tools (`jarvis_status`, `jarvis_facts`,
  `jarvis_explain`, `jarvis_suggest`, `jarvis_preview`, `jarvis_do`) with the identical argument
  schema and identical response envelopes. Consent parity is therefore structural, not
  reimplemented: `jarvis_do` needs the same per-call `"allow": true` for T2, refusals carry the
  same preview-then-allow hint, T3 is refused unconditionally. **No persistent yes exists
  anywhere in serve mode** — every consent arrives with its request and is journaled as on the CLI.
- There is deliberately NO exec/passthrough tool. Serve adds availability, never authority.

**D2 — Hardening (each item asserted by a test):** loopback-only bind (a non-loopback address is
refused, never sanitized); bearer-token auth with constant-time comparison (token stored
`0600` under the JARVIS state dir, generated on first run or at install); `Host` header must
match the bind address (DNS-rebinding defense); method and path allowlists; 64 KiB body cap;
JSON-only bodies; unknown tools 404; no CORS/preflight answers; one stderr log line per request
that never contains the token or body. Single-owner, low-traffic by design — not a web service.

**D3 — Opt-in install, opt-out anytime: `jarvis serve install [--with-gui]`.** Install writes a
**systemd user unit** (`~/.config/systemd/user/jarvis-serve.service`) that runs
`<python> -m jarvis serve` at login (`WantedBy=default.target`, `Restart=onfailure`), then
enables it via `systemctl --user`. If systemd-user is unavailable, the files are still written
and the skip is disclosed with the manual command — never silently claimed. `--with-gui`
additionally writes an XDG autostart entry (`~/.config/autostart/jarvis-gui.desktop`) that
launches the GUI frontend **only if** a `jarvis-gui` command exists on PATH (probed first; a
missing frontend refuses that piece honestly — the GUI repo remains read-only and untouched:
this is contract-side integration only). `jarvis serve uninstall` reverses everything;
`jarvis serve status` reports the truth of each piece.

**D4 — Packaging never enables residency.** The deb/rpm/AUR/wheel ship the *capability* (the
`serve` command); nothing in any postinst/automatically-run path creates or enables the unit.
Residency exists only where the owner typed `jarvis serve install`. The default shape remains
exactly what it was: nothing runs unless the human runs it.

**D5 — Divergence bookkeeping.** This is not the DFA autonomous loop (ADR-0017 D3): the doorway
never originates work, never iterates, never observes-and-continues. It answers requests that a
human (or the owner's own frontend) issues. Capability manifests (ADR-0017 D2) remain parked.

## Consequences

- After `jarvis serve install`, a local process holding the token can reach the same six tools
  the MCP surface exposes — including T1 file mutations and (with per-call `allow: true`) T2.
  This is disclosed here and in `serve install`'s output; the token file's 0600 permission and
  the loopback bind are the boundary. Owners who do not want this simply do not install it.
- Kill switch is trivial and complete: `jarvis serve uninstall` (or `systemctl --user disable
  --now jarvis-serve`) returns the machine to pure on-demand.
- The GUI gains a *resident* mode (no need to spawn `jarvis mcp serve` per session) without any
  change in consent semantics; the existing per-session stdio spawn remains fully supported.
- Tests exercise the HTTP surface over real sockets on ephemeral loopback ports; unit/desktop
  generation is a pure function tested with a fake HOME; enablement steps probe for systemd and
  disclose honestly when absent (CI sandboxes have no systemd).
