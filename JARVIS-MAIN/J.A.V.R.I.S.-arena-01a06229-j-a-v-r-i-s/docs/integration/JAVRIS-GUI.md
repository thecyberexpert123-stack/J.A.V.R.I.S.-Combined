# Wiring J.A.V.R.I.S.-GUI to the J.A.V.R.I.S. kernel

**Status:** Active contract (2026-09-03) · **Backend:** this repository (jarvis-agent ≥ 1.8.0) · **Front-end:** [J.A.V.R.I.S.-GUI](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.-GUI) (javris ≥ 0.1.0)

The GUI is a front-end to the same kernel — identical in standing to the CLI. This
document is the wiring contract; `jarvis mcp describe` publishes it as JSON, and
`tests/test_frontend_contract.py` asserts that published form against live server
behavior, so the two cannot drift.

## 1. Architecture — who owns what

```
┌────────────────────────────┐        spawns (fixed argv)        ┌──────────────────────────┐
│  J.A.V.R.I.S.-GUI (Qt6)    │ ────────────────────────────────► │  jarvis mcp serve        │
│  HUD, telemetry, console   │   stdin/stdout, newline JSON-RPC  │  (this repo, stdio only) │
│  owns presentation only    │ ◄──────────────────────────────── │  owns tiers + journal    │
└────────────────────────────┘                                   └──────────────────────────┘
```

- **The GUI never gains authority.** It renders state and relays owner intent; every
  mutation flows through the kernel's tiers exactly as on the CLI (ADR-0013 M9a harm
  model: a front-end is another untrusted-ingress surface).
- **The kernel never renders.** The server returns JSON; the GUI decides presentation.
- One fixed spawn (`jarvis mcp serve`) — this is the GUI's single extension of its
  "no processes" posture, pinned to one argv, no shell, no network.

## 2. Transport and handshake (normative)

- Spawn `jarvis mcp serve`; speak newline-delimited JSON-RPC 2.0 on its stdio. One
  object per line; stdout carries protocol frames only (server logs go to stderr).
- `initialize` → the server echoes the client's date `protocolVersion` (fallback
  `2024-11-05`); read `result.serverInfo.version` for the version handshake.
- `notifications/initialized` (no response), then `tools/list`.
- Full machine-readable form: `jarvis mcp describe` (`contract: javris-frontend/1`).

## 3. Tools and consent UX

| Tool | Consent | GUI behavior |
|---|---|---|
| `jarvis_status`, `jarvis_facts`, `jarvis_explain`, `jarvis_suggest`, `jarvis_preview` | `read-only` | fire freely |
| `jarvis_do` | `explicit-allow` | call **without** `allow` first; on `isError` with `payload.outcome.status == "refused"` show the plan/refusal to the owner; re-call with `"allow": true` **only** after an explicit owner action (button/dialog), once per call |

Invariants (non-negotiable): the GUI never synthesizes `allow: true` without an owner
action; T3 is refused by the kernel unconditionally; charters (`jarvis charter`) remain
the only pre-authorized automation. `jarvis_preview` powers a "show me the plan" flow —
the refusal hint already points there.

## 4. State-machine mapping (legal transitions only)

Mapped onto `javris`'s explicit `AssistantState` table — every arrow below is a legal
transition (or an always-reachable one):

| GUI state | When |
|---|---|
| `BOOTING` | spawning the server + handshake |
| `STANDBY` | handshake done, idle. `jarvis` missing from PATH → `OFFLINE` (telemetry continues — honest degradation, never a faked agent) |
| `LISTENING` | console focused |
| `PROCESSING` | any request in flight |
| `EXECUTING` | `jarvis_do` running with the owner's per-call allow |
| `SPEAKING` | rendering a result |
| `ERROR` | `isError` result, consent refusal, protocol/parse error → acknowledged back to `STANDBY` |

## 5. Suggested console verbs (GUI-side vocabulary)

Extending the fixed `CommandRouter` vocabulary (still no shell; each verb maps to one
bridge call): `ask <question>` → `jarvis_explain` · `do <request>` → consent flow above ·
`agent status` → server info/health · `plan <request>` → `jarvis_preview` ·
`agent disconnect` → close the child process (SIGTERM) and go `STANDBY`/`OFFLINE`.

## 6. Security posture (both sides keep their guarantees)

- GUI side: the console's allow-list, input capping, and control-char stripping are
  unchanged; the bridge is one more allow-listed handler set. `jarvis` text output is
  length-capped before entering the log renderer.
- Kernel side: nothing changes for other callers — the MCP server already treats every
  client identically; the GUI gets no private API, no elevated tier, no bypass.
- Local-only: stdio pipes between parent and child; no sockets, no network, no keys.

## 7. Licensing note (deliberate)

The contract (protocol + descriptor) is the integration surface; each project
implements its own client/server code. This repository's license is
`LicenseRef-Proprietary-Until-Owner-Decides` while the GUI is MIT — so no code is
copied across repos in either direction until the owner sets the license. The
protocol is fully specified by `jarvis mcp describe`; a QProcess-based client for the
GUI is small (framing + JSON parse + signal wiring).

## 8. Coordination log — re-verified against kernel 1.10.0 and GUI @ `d5233d5` (2026-09-04)

**Wire stability: `javris-frontend/1` is unchanged from v1.8.0 through v1.10.0.**
The kernel's M10 (AI failure semantics) and M11 (learned intent recall) releases
changed what the kernel *says* in failure and unknown situations — not the wire.
Conformance tests (`tests/test_frontend_contract.py`, 6) green at kernel 1.10.0; a
subprocess-level replay of the contract's example frames through the shipped
`jarvis mcp serve` binary verified: protocolVersion echo, `serverInfo.version =
1.10.0`, deterministic `jarvis_explain`, honest T2 refusal without `allow:true`,
and protocol-free stderr. On the GUI side (branch `arena/01a0667a-j-a-v-r-i-s-gui`
@ `d5233d5`): `state.py` transition table and `commands/router.py` verbs/limits
are unchanged since `3e908e6`, so every mapping in §4 and every verb in §5
remains exact. The branch's new work (attention escalation, ASSISTANT orb/takeover,
motion language, battery/host telemetry, `--no-ambient`) is rendering-side and
orthogonal to this contract.

**What M10/M11 let a front-end render better (all optional, nothing new to parse):**

- *Degraded AI is telemetry, not an error.* A failing model trips a kernel-side
  circuit breaker and is disclosed via `jarvis_status`-style reporting — the
  GUI's `PROCESSING`/`ERROR` mapping is unchanged; `ERROR` stays reserved for
  protocol faults and refusals. Recommended: surface "AI degraded — engine
  fully operational" through the attention-escalation system (a sustained
  degraded condition is exactly what it exists to promote), never as a crash.
- *Unknown requests carry suggestions.* The kernel now answers an unmappable
  request with `unknown-request:`-prefixed refusal text that may include an
  engine-legal suggestion ("it looks like: `jarvis do install htop` — type that
  yourself to run it"). A GUI console can render that as a pre-filled input or
  suggestion chip: the user still presses enter, so the consent model of §3 is
  untouched (the suggestion is text, the user disposes). A structured
  suggestion field on the wire would be a `javris-frontend/1.1` additive
  revision — proposed, owner-gated, deliberately NOT done now.
- *No-AI mode.* Launching the server with `JARVIS_NO_AI=1` (or the operator's
  global `--no-ai`) gives an air-gapped mode: engine, cited KB answers, journal
  only. The state machine is unaffected; `jarvis_explain` stays deterministic
  (fast) either way, so §4 latency expectations hold.

**Kernel-side steps: none required by the GUI beyond v1.8.0's plan** — spawn
`jarvis mcp serve`, speak §2, render §3–§5. The GUI's QProcess client (§1) is
implementable today against this descriptor; the contract tests on the kernel
side and the GUI's own `tools/check.sh` are the two gates.

## 9. Resident mode (optional; ADR-0018, kernel 1.12.0+)

The per-session spawn (`jarvis mcp serve` on stdio) remains the default and fully supported
contract. For front-ends that want the agent reachable any time after login **without spawning
it themselves**, the kernel offers an opt-in resident doorway:

- The frontend owner enables it once: `jarvis serve install` (systemd `--user` unit,
  `jarvis-serve.service`), optionally `--with-gui` to autostart the GUI app itself (XDG
  autostart, written only when a `jarvis-gui` command exists). `jarvis serve uninstall`
  returns the machine to pure on-demand; `jarvis serve status` reports each piece.
- Transport: `http://127.0.0.1:<port>` (default 8777; loopback bind enforced — a non-loopback
  bind is refused). `GET /v1/health` → `{"ok": true}`. `POST /v1/tools/<tool>` with
  `Authorization: Bearer <token>` and `Content-Type: application/json`; the token lives at
  `<state>/serve/token` (0600, never logged). `<tool>` is one of the six MCP tool names with
  the identical argument schema and response envelope (`{"result": ..., "isError": ...}`).
- Consent semantics are **identical** to the stdio contract: `jarvis_do` still requires the
  per-call `allow: true` for T2; T3 is refused; no persistent yes; `jarvis_preview` remains the
  pre-consent step. The STATE_MAPPING of §4 applies unchanged (STANDBY ≙ health ok, no request
  in flight).
- Security posture (§6) unchanged and test-asserted: loopback bind, constant-time token
  compare, Host-header check, method/path allowlist, 64 KiB cap, no CORS answers, no
  passthrough tool. The doorway holds no authority the stdio surface does not have.
