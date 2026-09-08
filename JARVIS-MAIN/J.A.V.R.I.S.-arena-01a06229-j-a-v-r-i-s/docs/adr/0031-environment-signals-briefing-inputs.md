# ADR-0031: Environment signals as briefing inputs — sensed at briefing time, never acted on

- **Status:** **Accepted 2026-09-06 as a hybrid — implemented in kernel 1.23.0.** Proposed the
  same day (docs-only commit `183afe2`) with owner questions Q-A…Q-D; the owner answered "do a
  hybrid upgrade" and, on four follow-ups (`TASKS.md` decision D13): **both** sensing paths in the
  scheduled poll with **`sysfs` as the default**, plus an **opt-in resident listener in its own
  unit** (`jarvis brief listen` / `jarvis-signals.service`, *not* inside the doorway), whose only
  powers are **record events + deliver a held briefing on unlock/resume**, and D-Bus through a
  **stdlib client over the AF_UNIX socket** (`busctl` child processes rejected — zero subprocesses
  in every mode). Owner-directed "continue" sequence, `TASKS.md` item B-C4 (*security-sensitive*:
  the first time the briefing reads anything outside JARVIS's own state directory, and the first
  resident JARVIS process besides the doorway). Origin: deep research II
  `docs/RESEARCH-agent-construction-and-future-tech-2026.md` §5 (Part D), candidate C4, owner
  question 4. Sections marked *(as proposed)* record the superseded design for the audit trail.

- **Context — what the briefing can see today (VERIFIED in this tree).**
  `src/jarvis/brief/engine.py` is compose → decide → deliver → ledger (ADR-0021). `compose()`
  (line 83) gathers exactly four local sources — recent journal failures, the suggestions engine,
  unmapped requests, and disk pressure through the `statvfs` seam. The module docstring promises
  "zero subprocesses in composition" and `tests/test_brief.py::test_compose_never_spawns_subprocess`
  enforces it by monkeypatching `subprocess.run` to raise. `decide()` (line 145) is the v1 policy:
  notify iff any item, else silence with a recorded reason. `run_once()` (line 265) writes
  `briefings/latest.md`, calls `desktop_notify()` (fixed-argv `notify-send`, gated by
  `shutil.which`, 10 s timeout) unless its `no_desktop` keyword is set (a function parameter, not a
  CLI flag today), and appends one `{"kind": "run", …}` line to
  `briefings/ledger.jsonl` (`ts`, `id`, `decision`, `reasons`, `delivered`). The briefing text never
  reaches a model: `grep -rn brief src/jarvis/providers src/jarvis/cli/mcp_server.py` finds
  nothing. Nothing in `src/` speaks D-Bus, inotify, logind, UPower or NetworkManager. The unit
  written by `brief install` runs `python -m jarvis brief --quiet` as `Type=oneshot` under a
  `Persistent=true` calendar timer; with `--harden` (ADR-0029 D3) it runs under
  `PrivateUsers=yes`, `ProtectKernelTunables=yes` (which makes `/sys` read-only),
  `PrivateDevices=yes`, `RestrictAddressFamilies=AF_UNIX`, `SystemCallFilter=@system-service`.

  The GUI HUD already reads battery state from the kernel:
  `JARVIS-GUI/…/src/javris/telemetry/proc_reader.py::read_battery()` walks
  `/sys/class/power_supply`, keeps only supplies whose `type` is `Battery`, clamps `capacity` to
  0–100 and maps `status` (`Charging` → charging; `Discharging` / `Not charging` / `Full` → not
  charging; anything else → unknown). The HUD does **not** consume briefings (no `brief` reference
  anywhere in the GUI tree).

- **Context — what the research asked, and what the sources actually say.** Research §5.4 offered
  six signal → proposal rows for the owner to prune; §5.2 *assumed* the access path would be
  fixed-argv `busctl`/`gdbus`; §11 listed the UPower and NetworkManager interface names as
  **unverified**. Fetched today (see Sources): the logind, UPower and NetworkManager D-Bus
  references, `busctl(1)`, and — the finding that reshapes the design — the kernel's stable sysfs
  ABI documents for power supplies, network interfaces and suspend statistics. **Four of the six
  rows can be sensed from sysfs with `open()`**, keeping composition zero-subprocess; only *metered
  network* and the three *interruption-cost* facts (idle, locked, sleep imminent) need the bus.

## Decision (accepted hybrid; deltas from the proposal called out inline)

### D1 — The signal set: six facts; each becomes a line or a hold, never a trigger

| # | Fact | Source (all names verified — see Sources) | Enters the briefing as | Mode |
|---|---|---|---|---|
| **S1** | Battery discharging at or below **N %** (default 20) | sysfs `/sys/class/power_supply/<s>/{type,scope,status,capacity}`: only `type == Battery` **and `scope != Device`** (the HID layer registers mouse/keyboard cells with `POWER_SUPPLY_SCOPE_DEVICE` — verified in `hid-input.c`); `status == Discharging`; `capacity` clamped 0–100 — the HUD's `read_battery()` filter plus the kernel's own peripheral marker | item: `battery 12% and discharging — not a moment for a long upgrade` | `sysfs`, `bus` |
| **S2** | No network link | sysfs `/sys/class/net/<i>/{operstate,type,carrier}`: no interface with `type != 772` (ARPHRD_LOOPBACK) has `operstate == up` **or `operstate == unknown` with `carrier == 1`** (the ABI says an `unknown` interface "must be considered for user data") | item: `no network link — package-index suggestions need a connection` | `sysfs`, `bus` |
| **S3** | Metered connection | bus: NetworkManager `Metered` ∈ {1 `YES`, 3 `GUESS_YES`} (NM's own guidance: treat `GUESS_YES` like `YES`, everything else as not metered) | item: `on a metered link — a package refresh would spend it` | `bus` |
| **S4** | Sleep or shutdown imminent | bus: login1 Manager `PreparingForSleep` / `PreparingForShutdown` = `true` | **hold** — no desktop knock; `latest.md` + ledger still written | `bus` |
| **S5** | Session locked | bus: login1 Session `LockedHint` = `true` on `/org/freedesktop/login1/session/auto` | **hold** (same shape) | `bus` |
| **S6** | Slept since the last briefing | sysfs `/sys/power/suspend_stats/success` delta against the previous run record, keyed by `/proc/sys/kernel/random/boot_id` | **recorded only** (`signals.suspend_cycles`) — no item, no hold | `sysfs`, `bus` |

Also recorded, never acted on, in `bus` mode: login1 Manager `IdleHint` (a deferral policy needs
a queue the oneshot does not have; the ledger keeps the datum for a future, owner-gated L3 policy —
ADR-0021 D4). **Deliberately not in v1:** UPower (S1 comes from the very kernel attributes UPower
reads; probing UPower could bus-activate it — see D2), lid state, compositor idle APIs (fragmented
per compositor; research §5.1), inotify (needs a resident watcher — D2), and
`/run/reboot-required` (useful, Debian-family-specific, not in the research table → recorded under
Consequences as a recommendation, not proposed).

Why this shape: items only **add text**; holds only **remove a knock**; there is no code path from
a signal to `execution/`, to the planner, or to consent — ADR-0017 D3 and ADR-0021 D1 hold
unchanged. In Horvitz's terms (research §5.3) S1–S3 change the *value* of speaking, S4–S5 make the
*cost* of interrupting infinite for this run, and S6/idle are context for the owner-as-oracle.

### D2 — Access path: sysfs first, a stdlib D-Bus client second, no child process, no activation

One flag: `jarvis brief [run] --signals off|sysfs|bus` (default **`sysfs`** — owner decision D13;
the proposal recommended `off`).

- **`off`** — the pre-ADR engine, byte-for-byte: `sense()` is not called; `latest.md`, stdout, the
  briefing id and the ledger `run` record are unchanged (golden test
  `test_off_mode_output_is_byte_identical_to_v1_22`).
- **`sysfs`** — `sense()` reads S1, S2, S6 with `open()` on fixed paths, ≤ 256 bytes each, every
  `OSError`/`ValueError` → that fact is *absent*. Zero subprocesses; works in containers, without
  any bus, and under `--harden` (a read-only `/sys` is all it needs).
- **`bus`** — everything in `sysfs`, plus S3–S5 (and `IdleHint`) through
  **`src/jarvis/system/dbus_client.py`**: one AF_UNIX connection per run, SASL `EXTERNAL` (the
  NUL byte, `AUTH EXTERNAL <hex uid>`, `OK`, `BEGIN`), `Hello`, then six
  `org.freedesktop.DBus.Properties.Get` calls, each with the **`NO_AUTO_START` flag** so sensing can
  never bus-activate UPower, NetworkManager or anything else, and never with
  `ALLOW_INTERACTIVE_AUTHORIZATION` (a probe must not raise a polkit prompt). The reply must be a
  variant of the expected signature (`b` or `u`); anything else — an `ERROR` reply
  (`ServiceUnknown`, `UnknownProperty`, …), a wrong type, a malformed frame, a timeout — makes that
  fact *absent*, and a transport failure records `"bus": "unavailable: <reason>"`. Budget: 2 s per
  call, 6 s per run; the sandbox's failed connect costs ≈ 1 ms.

*Why a wire-protocol client and not `busctl` (as proposed):* the owner rejected child processes
for sensing. What JARVIS needs from the bus is small — `Hello`, `Properties.Get`, `AddMatch` and
the ability to read signals — and the protocol has been frozen since 2006, so ~900 lines of
stdlib Python (address parsing with `%XX` escapes and `;` fallbacks, `AUTH EXTERNAL`, the
`yyyyuua(yv)` header, marshalling for every type code except `h`, strict validation that
disconnects on any deviation, a 1 MiB message cap, both endiannesses on input) cost less than a
dependency (ADR-0005) and remove the one subprocess the proposal had to apologise for. The codec
was checked **byte-for-byte against an independent implementation** (jeepney 0.9.0, installed
only to generate eleven golden vectors and removed again — it is not a dependency; the vectors
are in `tests/test_dbus_client.py`). The client's public surface is exactly `connect`, `call`,
`get_property`, `add_match`, `next_signal`, `close`, `connected` — there is no method on it
that could change bus state, and a test pins that set.

`sense()` runs **before** `compose()` and hands it a frozen `Signals` value; `compose()` stays
subprocess-free and bus-free by construction, and `test_compose_never_spawns_subprocess` stays
green as written (`test_compose_stays_subprocess_free_with_signals` repeats the check with
`sense("bus")` in the path).

**Listener (owner decision D13 — was "not proposed", now D8).** The proposal explained why S4
would rarely fire from a calendar timer (systemd catches the timer up *after* resume) and why a
held briefing would wait for tomorrow. The owner chose to close both gaps with a **separate,
opt-in** resident unit rather than a doorway child — see D8. The scheduled poll is unchanged by
it: the listener never composes.

### D3 — Interruption cost lives in `decide()`, as holds, additively

`Briefing` gains two frozen fields with defaults — `holds: tuple[str, ...] = ()` and
`signals: Mapping[str, object] = MappingProxyType({})` — so every existing constructor call is
untouched. `decide()` keeps `decision ∈ {"notify", "silence"}` (the ledger vocabulary is unchanged)
and sets `holds` from S4/S5 (`"sleep-imminent"`, `"session-locked"`). `run_once()` skips
`desktop_notify()` when `holds` is non-empty, still writes `latest.md`, and records
`delivered=false` plus the additive `holds` key; `brief status` gains an additive `held` count.
`markdown()` appends one `context: …` line **only when at least one fact was sensed** (so the file
is byte-identical in `off` mode) and a `held: …` line when a hold applied. The briefing **id** is
unchanged unless a signal *line* (S1–S3) was added — context alone never changes it, so ledgers
before and after the upgrade agree on ids for the same inputs. *(As proposed:* held briefings were
not retried until the next calendar fire.*)* **Accepted:** when the opt-in listener (D8) is
running, the day's held briefing is delivered once, when the hold clears (unlock or resume with
the screen unlocked); without the listener the proposal's semantics stand — `latest.md` holds the
note until tomorrow's fire. `brief status` gains additive `held`, `events`, `late_deliveries` and
`held_undelivered` fields.

### D4 — Wire shape: additive keys, HUD untouched, one seam rule

`jarvis --json brief` and each ledger `run` record gain:

```json
"signals": {
  "mode": "sysfs | bus",                                     // {} in off mode
  "battery":  {"percent": 12, "status": "Discharging", "discharging": true},   // or null
  "network":  {"link": true, "metered": null, "connectivity": null},
  "session":  {"locked": null, "idle": null, "preparing_for_sleep": null, "preparing_for_shutdown": null},
  "suspend":  {"boot_id": "…", "success": 7},                // or null; the S6 memory
  "suspend_cycles": null,                                    // int when known
  "bus": "off | ok | unavailable: <reason>"
},
"holds": []
```

Ledger rows stay append-only and additive: a `run` row carries `holds`/`signals` **only when they
carry information** (the `off`-mode row is the v1.22 row, key for key); the listener appends
`{"kind": "event", "ts", "event": "sleep|resume|shutdown|lock|unlock|network|bus|event-limit", …}`
and `{"kind": "delivery", "ts", "id", "trigger": "unlock|resume", "delivered": bool}` rows.
Existing rows are never rewritten.

`null` always means *not sensed*, never *normal* — the HUD's own rule ("absent, not full or
empty"). MCP: no tool change (`jarvis_status` does not expose briefings; nothing to add). HUD: **no
change**; the one cross-repo rule is that the kernel's S1 filter mirrors `read_battery()` exactly
(type filter, clamp, status mapping) so a HUD battery cell and a briefing line can never disagree
about the number — the audit round found the seam is where defects hide.

### D5 — Configuration and persistence

Mode and threshold are CLI flags (`--signals`, `--battery-low N`), rendered into the unit's
`ExecStart=` by `brief install --signals … [--battery-low N]` **only when they differ from the
defaults** — a default install renders the v1.22 unit text byte-for-byte
(`test_brief_unit_default_is_unchanged` still passes unmodified); `--listen [--record-only]`
writes and enables the second unit of D8; `brief uninstall` removes both; the same install-time
pattern as `--harden`; already-installed units are untouched until re-installed; packaging never
enables anything. **No config file:** two knobs do not justify one, and a file that can only add text or
remove a knock has no integrity value worth a re-baseline (contrast ADR-0030 D-A). S6 state
(`boot_id`, `suspend_success`) lives inside the run record — the ledger already is the memory.
Nothing sensed leaves the machine: signals go to `latest.md`, the ledger and `notify-send` only.

### D6 — Tests (all offline; the sandbox has no bus, battery or suspend)

Implemented as `tests/test_dbus_client.py` (44), `tests/test_brief_signals.py` (51) and the
in-process bus `tests/fakebus.py`; the pre-existing `tests/test_brief.py` and
`tests/test_sdnotify.py` pass unmodified.

- **Codec:** eleven golden frames from an independent implementation (Hello, `Properties.Get`,
  a variant return, a `PropertiesChanged` signal, nested dicts, an empty array, an empty dict, a
  struct in a variant, every basic type in one body) encode identically and round-trip; big-endian
  input accepted; nine malformed frames (short, bad endianness marker, version 2, zero serial,
  truncated, trailing bytes, invalid object path, non-zero padding, boolean 2) are `ProtocolError`;
  a known header field with the wrong type is corrupt while an unknown field code is ignored; the
  1 MiB cap is enforced from the fixed header; invalid signatures and un-marshallable values are
  refused before anything is sent.
- **Fake bus** (`fakebus.py`, a real AF_UNIX listener speaking NUL/`AUTH`/`OK`/`BEGIN` plus the
  binary protocol): Hello is the first frame; `NO_AUTO_START` is on every call and
  `ALLOW_INTERACTIVE_AUTHORIZATION` on none; `AddMatch` rules arrive verbatim and signals come
  back; `REJECTED` → `BusUnavailable`; `ERROR` → `RemoteError` with the error name (connection
  kept); wrong reply signature → `ProtocolError`; garbage after Hello and an oversize frame →
  disconnect; absent socket names every path tried; a silent peer times out honestly;
  `Peer.Ping` is answered and any other inbound call gets `UnknownMethod`.
- **sysfs sensors** on fake roots: a UPS, a mains adapter and a `scope=Device` mouse cell sorted
  before the real battery are skipped; `capacity` 101 clamps; every `status` value; a vendor
  status reads as unknown and never yields S1; loopback excluded; `unknown` + `carrier` counts as a
  link; no `/sys` → `null`; loopback-only → `null` (not a judgement); S6 delta within one
  `boot_id`, `null` across boots.
- **bus mode:** the six properties read read-only; the `NMMetered` enum mapped
  (0 → `null`, 1/3 → `true`, 2/4 → `false`, 99 → `null`); an absent NetworkManager leaves its facts
  `null` while logind's stand; no bus → sysfs facts intact, `"bus": "unavailable: …"`; a wrongly
  typed `LockedHint` → `null`; rejected authentication is not an error.
- **Holds:** only an explicit `true` holds; a held run writes `latest.md` with the `held:` line,
  records `delivered=false` + `holds` + `signals`, does **not** call `desktop_notify`, and shows up
  as `held`/`held_undelivered` in `status`; an un-held run still knocks.
- **Golden byte-identity in `off`** (stdout, `latest.md`, id `0e7583e21c1a`, ledger keys) and
  **id stability** when signals add context but no line.
- **Listener:** exactly four match rules (none with `eavesdrop`); delivers once on unlock and on
  resume; not while the screen is still locked on resume; never in `--record-only`; a failed
  `notify-send` is not retried inside the 5-minute back-off; network/shutdown events recorded; a
  newer un-held run supersedes a held one; yesterday's hold is not delivered today; only
  `Hello`/`AddMatch`/`Get` ever appear in fake-bus traffic across every handled frame; the
  module source references neither `compose(`, `run_once(`, `Orchestrator`, `subprocess`,
  `playbook` nor `Runner`; the 120-events/hour ledger limit; `run_listener` one pass with and
  without a bus.
- **Units/CLI:** default service text unchanged; flags rendered only when non-default;
  `--battery-low 101` and `--signals busctl` refused before anything is written; listener unit
  supervised (`Type=notify`, `WatchdogSec=60`, `Restart=on-failure`) and, with `--harden`, carrying
  the full ADR-0029 D3 block; install writes both units and uninstall removes both; `brief`,
  `brief run`, `status`, `listen --once`, `install --help`.
- **Mutation checks run before the tick** (each must fail, all did): drop `NO_AUTO_START`; treat
  `NM_METERED_UNKNOWN` as not metered; count loopback as a link; knock despite a hold; deliver
  twice; deliver while locked; hold on *not sensed*; skip the padding check; render `--signals`
  into the default unit; drop the `type == Battery` filter; drop the `scope` filter; make the
  listener import `compose`; record every delivery as failed.

### D7 — Non-goals

- No signal ever reaches the planner or a model; none triggers execution, scheduling or consent.
- No inotify; no D-Bus *methods* other than `Hello`, `org.freedesktop.DBus.Properties.Get` and
  `AddMatch`; no `Set`, no `Lock()`/`Unlock()`, no `Inhibit()` — JARVIS will not take inhibitor
  locks to delay sleep for a briefing. The listener is the one resident addition and it is opt-in,
  separate from the doorway, and limited to the two powers of D8.
- No listener-triggered composition: a briefing is composed by the timer (or by hand) only. An
  L3 "compose on events" step remains its own, future, owner-gated ADR (ADR-0021 D4).
- No per-compositor idle protocols; logind's `IdleHint` is the portable, DE-maintained hint, and
  even that is recorded, not acted on.

### D8 — The opt-in listener: `jarvis brief listen` in `jarvis-signals.service`

- **Home.** Its own `systemd --user` unit, written by `brief install --listen [--record-only]
  [--harden]` next to the timer: `Type=notify`, `NotifyAccess=main`, `WatchdogSec=60`,
  `Restart=on-failure`, `RestartSec=5`, `WantedBy=default.target`, `ExecStart=<python> -m jarvis
  brief listen`. It reuses the doorway's stdlib `sd_notify` client (ADR-0029 D1: `READY=1`,
  `STATUS=`, `WATCHDOG=1` at half the interval, `STOPPING=1`) and, with `--harden`, the brief's
  confinement block verbatim — `RestrictAddressFamilies=AF_UNIX` already admits both the bus
  socket and `$NOTIFY_SOCKET` (`systemd-analyze security --offline`: plain 9.6, hardened 2.0, same
  as the hardened brief). Not in the doorway: ADR-0018's "a doorway, never an actor" contract and
  its exposure figure are untouched.
- **Subscriptions.** After `Hello`, four `AddMatch` rules (fixed strings, built from a validated
  `key='value'` helper that refuses quoting and unknown keys): logind Manager
  `PrepareForSleep` and `PrepareForShutdown`; `PropertiesChanged` under `path_namespace=
  '/org/freedesktop/login1/session'`; `PropertiesChanged` on `/org/freedesktop/NetworkManager`.
  Because signals are only emitted on concrete session objects (the man page: the convenience
  paths are caller-relative and carry no signals), a `LockedHint` change on *any* session makes the
  listener re-read **its own** `LockedHint` via `Properties.Get` on `session/auto` — logind resolves
  that to the caller's session, or to the owning user's display session when the caller (a user
  unit) is outside any session (`get_sender_session(..., consult_display=true)` in
  `logind-dbus.c`, verified). No session path is guessed, no `ListSessions()` is walked.
- **Power 1 — record.** `sleep`/`resume`/`shutdown`/`lock`/`unlock`/`network` (metered,
  connectivity)/`bus` (connected, lost) become `{"kind": "event"}` ledger rows, capped at 120 per
  hour (one `event-limit` marker, then silence until the hour turns) so a flapping link cannot
  grow the ledger without bound.
- **Power 2 — deliver late.** On `unlock`, and on `resume` when the session is not locked, the
  day's most recent held `run` row with no successful `delivery` row is delivered with the same
  hygiened `notify-send` line the timer would have used — **once per briefing id**; a failed
  attempt (no `notify-send`) is recorded and not retried for five minutes; a newer un-held run
  supersedes an older held one; a hold from another UTC day is never delivered. `--record-only`
  disables this power entirely.
- **What it cannot do.** It never composes (no `compose`/`run_once` import — pinned by a source
  test), never touches the planner, executor or consent, never calls a D-Bus method beyond
  `Hello`/`AddMatch`/`Properties.Get` (pinned by the fake-bus traffic test), never sets
  `ALLOW_INTERACTIVE_AUTHORIZATION`, and answers inbound calls only with `Peer.Ping` →
  empty return / anything else → `UnknownMethod`.
- **Failure.** No bus → stays up, `STATUS=no bus (retrying)`, exponential back-off 2 s → 60 s;
  bus lost → `bus lost` event, reconnect with back-off; a frame the client cannot parse →
  disconnect and reconnect (never a crash on peer input); SIGTERM/SIGINT → `STOPPING=1`, clean
  exit 0. `once=True` (`brief listen --once`) does a single subscribe/poll pass for diagnostics.

## Owner decisions (asked 2026-09-06 — answered the same day; see Status and TASKS.md D13)

**Q-A — Signals.** Keep S1–S6 as specified? Prune or add? Battery threshold default **20 %**?
→ **Kept as specified**, 20 % default (`--battery-low` adjusts); S1 gained the kernel `scope`
filter during implementation (a correctness fix, not a scope change).

**Q-B — Default mode.** `off` (recommended in the proposal) or `sysfs`? → **`sysfs`** ("both"
paths available; the owner chose the zero-subprocess facts on by default, the bus opt-in).

**Q-C — Listener.** Poll-at-briefing only? → **No — hybrid:** a resident listener, in its **own
opt-in unit** (not the doorway), with **record + deliver-held-briefing** powers only (no
composition, no execution), talking to the bus through the **stdlib wire client** (no `busctl`
children). See D8.

**Q-D — Hold semantics.** No retry until the next calendar fire? → **With the listener installed,
a held briefing is delivered once when the hold clears; without it, the proposal's semantics
stand.**

## Failure modes

| Precondition absent / fault | Behaviour | Same as today? |
|---|---|---|
| `--signals off` | `sense()` not called | yes — `latest.md`/stdout/id/ledger row byte-identical; JSON gains additive keys only |
| `--signals sysfs` (default) on a host where nothing new is sensed (no battery, link up, no suspend) | one `context: link: up` line under the decision; id unchanged | text-only delta; the knock and the ledger vocabulary are unchanged |
| No `/sys/class/power_supply` entries (desktop, VM, container) | `battery: null`; no S1 item | yes |
| Only loopback / no `operstate == up` | S2 item (in `sysfs`/`bus` mode) | n/a — new line, text only |
| `/sys/power/suspend_stats` missing (older kernels; the ABI entry is dated July 2019) or `boot_id` changed | `suspend_cycles: null` | yes |
| No system bus socket, connection refused, `EXTERNAL` rejected, hung bus, malformed or oversize reply | bus facts `null`; `"bus": "unavailable: …"`; no holds; sysfs facts still present; no exception escapes | degrades to `sysfs` |
| `--harden` unit: `PrivateUsers=` + `ProtectSystem=strict` between the client and `/run/dbus/system_bus_socket` | if the connect fails → as above; sysfs reads unaffected (`ProtectKernelTunables=` keeps `/sys` readable) | degrades to `sysfs` (**ASSUMED**, verify on the owner's machine) |
| `session/auto` does not resolve for a `systemd --user` unit (no session, no display session) | `locked: null`; no S5 hold; listener records events but cannot judge the lock — delivers on `resume` only | degrades (**ASSUMED** rare: logind falls back to the user's display session) |
| Listener installed, no bus / bus lost | unit stays up with `STATUS=no bus (retrying)`; back-off 2 s → 60 s; nothing delivered, nothing composed | n/a — new unit, opt-in |
| Listener: `notify-send` absent when the hold clears | `delivery` row with `delivered=false`; retry only after 5 min and only on a new unlock/resume; `latest.md` still has the text | same as the timer's own "desktop notification unavailable" |
| Listener: a flapping link | ≤ 120 events/hour recorded, then one `event-limit` row | bounded |
| DE never calls `SetLockedHint` | `locked: false` while the screen is locked → knock delivered | today's behaviour (limit, documented) |
| S4/S5 hold fires | no `notify-send`; `latest.md` + ledger written; `delivered=false`, `holds=[…]` | new; silence-with-receipt (ADR-0021 D2 spirit) |
| Timer catches up after resume | brief runs once; `PreparingForSleep` already `false`; S6 counts the cycle | yes (systemd semantics unchanged) |

## Consequences

- The briefing gains eyes, not hands: four kernel facts and up to four bus facts become lines,
  holds or ledger context; the catalog stays 58 playbooks; no execution path is added.
- Kernel version on implementation: **1.23.0** (additive feature; interfaces preserved — CLI verbs,
  MCP tools, journal schema and existing unit contents unchanged; new flags and JSON keys only).
- The zero-subprocess promise is **kept, not refined**: composition stays pure, and neither
  sensing mode nor the listener spawns a child — the D-Bus wire client is ~900 lines of stdlib
  with no dependency. The cost is that JARVIS now owns a protocol codec; the mitigation is the
  independent golden vectors, the strict-disconnect discipline and the pinned public surface.
- JARVIS gains its second resident process (after the doorway), opt-in, separate, supervised the
  same way, confinable the same way, and limited to two powers. `TASKS.md` records the promotion
  criterion: the listener stays opt-in until one verified run on the owner's machine shows a held
  briefing delivered on unlock.
- The seam rule of D4 now runs the other way too: the kernel's S1 filter is *stricter* than the
  HUD's (`scope=Device` skipped). Recommendation, not done here (GUI is out of C4's scope): port the
  `scope` check into `proc_reader.read_battery()` so a wireless-mouse cell cannot show as the
  laptop's battery in the HUD either.
- Recommendations recorded, not proposed: (a) `/run/reboot-required` as a seventh sysfs-style
  fact; (b) reusing UPower's `WarningLevel` (3 = Low, 4 = Critical, verified) instead of a JARVIS
  threshold *if* the owner prefers the system's own policy — requires accepting an UPower probe;
  (c) the L3 step — composing *on* events — once L2 has a feedback history to learn from.

## Verified vs. assumed (implementation, 2026-09-06)

- **VERIFIED (fetched):** every D-Bus service, object, interface, property, signal and value
  quoted below; the D-Bus wire protocol (addresses, SASL `EXTERNAL`, header layout and field
  codes, alignment and padding rules, array/struct/variant/dict-entry marshalling, message-type
  requirements, `NO_AUTO_START`/`NO_REPLY_EXPECTED`/`ALLOW_INTERACTIVE_AUTHORIZATION`, match-rule
  grammar, `Hello`/`AddMatch`/`GetNameOwner` semantics and error names); logind's session
  resolution for caller-relative paths (`get_sender_session` with `consult_display`) and that
  `Lock`/`Unlock` signals and `LockedHint` `PropertiesChanged` are emitted on concrete session
  objects (`logind-session-dbus.c`); the HID layer's `POWER_SUPPLY_SCOPE_DEVICE` for peripheral
  batteries (`hid-input.c`) and the `scope` text values `Unknown`/`System`/`Device`
  (`power_supply_sysfs.c`); sysfs attribute names and value sets for power supplies, network
  interfaces and suspend statistics; ARPHRD numbers.
- **VERIFIED (this sandbox, real runs):** codec byte-identity against jeepney 0.9.0 on eleven
  frames (then uninstalled); the full non-live gate (`ruff check`, `ruff format --check`, `mypy
  src/jarvis` clean, `python -m pytest -q -o addopts="" -m "not live"` → **1039 passed, 11
  deselected**); 13 mutation probes each break at least one test; `jarvis brief --quiet`,
  `brief run --signals off|bus`, `--json brief --signals bus` (bus honestly `unavailable: …`,
  `link: true`, `suspend.success = 0`), `brief status` with the new counters, `brief listen
  --once` (no bus → `retry in 2s`, exit 0), `brief install --help`; `systemd-analyze security
  --offline=true` on the generated listener units (9.6 plain, 2.0 hardened) and `systemd-analyze
  verify` clean; `pip install -e .` → `jarvis 1.23.0`; golden `off`-mode output equal to the
  v1.22.0 engine's output for the same seeded journal.
- **ASSUMED (to check on the owner's machine before the item is called verified live):**
  (1) `session/auto` resolves for the timer and the listener as a `systemd --user` unit (the
  display-session fallback exists in the source; whether the owner's login manager marks a
  display session is per-setup); (2) the client reaches `/run/dbus/system_bus_socket` from a
  `--harden` unit; (3) real logind/NetworkManager reply shapes match the spec-derived encoder
  (the golden vectors prove agreement with jeepney, not with a live broker); (4) the D-Bus
  specification describes itself as "accurate, though incomplete" — behaviour the spec leaves
  open is handled by disconnecting, which is the safe side; (5) UPower `PercentageLow=10` default
  (`[snippet]`, two secondary sources).
- **NOT VERIFIABLE HERE:** any live sensing or a live listener session: this sandbox has no
  system bus (`dbus-daemon`/`dbus-broker` are not installable — apt mirrors unreachable), no user
  service manager, no battery, no suspend history. Commands for the owner, to run once and paste
  into the TASKS.md verification block:

  ```
  jarvis --json brief --signals bus | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["signals"], indent=1))'
  jarvis brief listen --once                      # expect: "subscribed as :1.N"
  jarvis brief install --signals bus --listen     # then lock, unlock, and: jarvis brief status
  systemctl --user status jarvis-signals.service  # expect: Status: "subscribed; N event(s) recorded; …"
  ```

## Sources (fetched 2026-09-06 unless marked)

- systemd, `org.freedesktop.login1` D-Bus interface (systemd 261) — Manager properties
  `IdleHint`, `IdleSinceHint`, `IdleSinceHintMonotonic`, `PreparingForSleep`,
  `PreparingForShutdown`, `LidClosed`, `OnExternalPower`, `Docked`; signal `PrepareForSleep(b start)`
  ("right before (`true`) or after (`false`)"); `PreparingForSleep`/`PreparingForShutdown` "do not
  send out `PropertyChanged` signals" (polling is the only way to read them); Session properties
  `LockedHint`, `IdleHint`, `Active`, `Type`, `Class`; `SetLockedHint()` "intended to be used by the
  desktop environment"; convenience objects `session/self` and `session/auto` "can only be
  dereferenced relative to a method caller"; `Inhibit()` semantics.
  https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.login1.html
- D-Bus Specification (freedesktop.org) — server addresses (`unix:path=`/`unix:abstract=`,
  `%XX` escapes, `;`-separated fallbacks, `DBUS_SYSTEM_BUS_ADDRESS`, the well-known system socket
  path); SASL authentication (`AUTH EXTERNAL` with the hex-encoded uid, `OK <guid>`, `BEGIN`,
  `REJECTED`, `NEGOTIATE_UNIX_FD`); the message format (`yyyyuua(yv)` header, endianness byte,
  message types 1–4, flags `NO_REPLY_EXPECTED` 0x1 / `NO_AUTO_START` 0x2 /
  `ALLOW_INTERACTIVE_AUTHORIZATION` 0x4, header field codes 1–9 and their required types, "unknown
  header fields must be ignored", 8-aligned body); type system and marshalling (alignments,
  NUL padding, array length excludes the element-alignment pad, structs/dict entries 8-aligned,
  variant = signature + value, depth ≤ 64, strings UTF-8 without NUL, 128 MiB/64 MiB limits);
  "unless a message has the flag `NO_AUTO_START` … a program to own the destination name will be
  started"; `org.freedesktop.DBus.Hello` first, `AddMatch`/`RemoveMatch`, `GetNameOwner` →
  `NameHasNoOwner`, `GetConnectionCredentials`; `org.freedesktop.DBus.Properties.Get`/`GetAll`/
  `PropertiesChanged(s, a{sv}, as)`; `org.freedesktop.DBus.Peer.Ping`; match-rule grammar
  (`type`, `sender`, `interface`, `member`, `path`, `path_namespace`, `arg0`); "accurate, though
  incomplete". https://dbus.freedesktop.org/doc/dbus-specification.html
- systemd source, `src/login/logind-dbus.c` (`get_sender_session`: "checks if the sending process
  is inside a session itself, and returns that. If not and 'consult_display' is true, this returns
  the display session of the owning user"; `manager_get_session_from_creds`: `self` → caller's
  session, `auto` → caller's session "if they have one, otherwise their user's display session")
  and `src/login/logind-session-dbus.c` (`session_send_changed_strv` emits `PropertiesChanged` on
  the concrete session path; `session_send_lock` emits `Lock`/`Unlock` there; `LockedHint`,
  `IdleHint`, `Active`, `State` are `EMITS_CHANGE`; `SetLockedHint` requires the session owner or
  root). https://github.com/systemd/systemd/tree/main/src/login
- Linux source, `drivers/hid/hid-input.c` (`POWER_SUPPLY_PROP_SCOPE` → `POWER_SUPPLY_SCOPE_DEVICE`
  for HID batteries) and `drivers/power/supply/power_supply_sysfs.c` (`POWER_SUPPLY_SCOPE_TEXT`:
  "Unknown", "System", "Device"; `POWER_SUPPLY_STATUS_TEXT`; `POWER_SUPPLY_TYPE_TEXT` including the
  `USB_*` variants). https://github.com/torvalds/linux
- `busctl(1)` (systemd 261) — read during the proposal for the rejected child-process design;
  retained for the record. https://www.freedesktop.org/software/systemd/man/latest/busctl.html
- jeepney 0.9.0 (BSD-3) — used **only** as an independent oracle to generate the eleven golden
  frames in `tests/test_dbus_client.py`; not a dependency, not vendored, uninstalled afterwards.
  https://gitlab.com/takluyver/jeepney
- UPower reference — `org.freedesktop.UPower` on the system bus at `/org/freedesktop/UPower`:
  properties `OnBattery` (b), `LidIsClosed` (b); `GetDisplayDevice()` → guaranteed path
  `/org/freedesktop/UPower/devices/DisplayDevice`; `org.freedesktop.UPower.Device`: `Percentage`
  (d), `State` (u: 1 Charging, 2 Discharging, 4 Fully charged …), `WarningLevel` (u: 3 Low,
  4 Critical, 5 Action), `TimeToEmpty` (x), `PowerSupply` (b), `Type` (u: 2 Battery), `IsPresent`
  (b). https://upower.freedesktop.org/docs/UPower.html ·
  https://upower.freedesktop.org/docs/Device.html — verified, **not used in v1** (D1).
- NetworkManager D-Bus reference — `org.freedesktop.NetworkManager` at
  `/org/freedesktop/NetworkManager`: properties `Metered` (u), `Connectivity` (u), `State` (u),
  `PrimaryConnectionType` (s); signal `StateChanged(u)`; "the State property is more suitable" for
  "is the Internet accessible". `nm-dbus-types`: `NMMetered` 0 UNKNOWN / 1 YES / 2 NO / 3 GUESS_YES
  / 4 GUESS_NO with "most applications probably should treat the runtime state NM_METERED_GUESS_YES
  like NM_METERED_YES, and all other states as not metered"; `NMState` 0/10/20/30/40/50/60/70
  (70 = CONNECTED_GLOBAL); `NMConnectivityState` 0 UNKNOWN / 1 NONE / 2 PORTAL / 3 LIMITED / 4 FULL.
  https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html ·
  https://networkmanager.dev/docs/api/latest/nm-dbus-types.html
- Linux sysfs ABI, `sysfs-class-power` — `type` ("Battery", "UPS", "Mains", "USB", "Wireless"),
  `capacity` (0–100), `capacity_level` ("Unknown", "Critical", "Low", "Normal", "High", "Full"),
  `status` ("Unknown", "Charging", "Discharging", "Not charging", "Full"), `present`, `online`.
  https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-class-power · power-supply class
  overview (`TIME_TO_EMPTY`, units): https://www.kernel.org/doc/html/latest/power/power_supply_class.html
- Linux sysfs ABI, `sysfs-class-net` — `operstate` (RFC 2863: "unknown", "notpresent", "down",
  "lowerlayerdown", "testing", "dormant", "up"), `carrier` (0/1), `type` (ARPHRD decimal),
  `carrier_changes`. https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-class-net
- Linux sysfs ABI, `sysfs-power` — `/sys/power/suspend_stats/success` ("number of times entering
  system sleep state succeeded", July 2019), `fail`.
  https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-power
- `clock_gettime(2)` — `CLOCK_BOOTTIME` "identical to CLOCK_MONOTONIC, except that it also includes
  any time that the system is suspended"; `CLOCK_MONOTONIC` "does not count time that the system is
  suspended". https://man7.org/linux/man-pages/man2/clock_gettime.2.html (an alternative S6 source;
  `suspend_stats` chosen because it counts cycles, which is what the ledger wants)
- `systemd.timer(5)` — a calendar timer that elapses while the system sleeps is processed "once the
  system is later resumed … only … a single service activation"; `Persistent=`.
  https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html
- E. Horvitz, "Principles of Mixed-Initiative User Interfaces," CHI 1999 — threshold *p\**, cost of
  interruption rising with attention; H. Chase, "Introducing ambient agents" (2025) — notify /
  question / review. Both via research §5.3 `[snippet of PDF][peer-reviewed]` / `[fetched][eng]`,
  not re-fetched.
- `[snippet]` UPower.conf defaults `PercentageLow=10`, `PercentageCritical=3`,
  `PercentageAction=2` (gist of a stock `/etc/UPower/UPower.conf`; askubuntu 92794). Secondary.
- `[snippet]` LKML 2011-12-08, "power_supply: add power supply scope" — the origin of
  `POWER_SUPPLY_PROP_SCOPE`; superseded by the kernel source above (verified).
- In-repo: `src/jarvis/brief/engine.py`, `src/jarvis/brief/signals.py`, `src/jarvis/brief/listen.py`,
  `src/jarvis/brief/install.py` (`HARDENING_DIRECTIVES`, `listener_content`),
  `src/jarvis/system/dbus_client.py`, `src/jarvis/system/sdnotify.py`, `src/jarvis/cli/serve.py`
  (`unit_content` mirrored), `tests/test_brief.py`, `tests/test_sdnotify.py`, `tests/fakebus.py`,
  `tests/test_dbus_client.py`, `tests/test_brief_signals.py`; ADR-0005, ADR-0017 D3, ADR-0018,
  ADR-0021, ADR-0029, ADR-0030; `JARVIS-GUI/…/src/javris/telemetry/proc_reader.py::read_battery()`.
