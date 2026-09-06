# ADR-0031: Environment signals as briefing inputs — sensed at briefing time, never acted on

- **Status:** **Proposed 2026-09-06 — paused for the owner.** Owner-directed "continue" sequence,
  `TASKS.md` item B-C4, gated as OWNER-Q in decision D4 (*security-sensitive*: this is the first
  time the briefing would read anything outside JARVIS's own state directory, and the first time a
  scheduled JARVIS process could spawn a helper while *sensing*). Origin: deep research II
  `docs/RESEARCH-agent-construction-and-future-tech-2026.md` §5 (Part D), candidate C4, owner
  question 4. **No code in this commit** — the decision questions are at the end.

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

## Decision (proposed)

### D1 — The signal set: six facts; each becomes a line or a hold, never a trigger

| # | Fact | Source (all names verified — see Sources) | Enters the briefing as | Mode |
|---|---|---|---|---|
| **S1** | Battery discharging at or below **N %** (default 20) | sysfs `/sys/class/power_supply/<s>/{type,status,capacity}`: only `type == Battery`; `status == Discharging`; `capacity` clamped 0–100 — **the same filter as the HUD's `read_battery()`** | item: `battery 12% and discharging — not a moment for a long upgrade` | `sysfs`, `bus` |
| **S2** | No network link | sysfs `/sys/class/net/<i>/{operstate,type}`: no interface with `type != 772` (ARPHRD_LOOPBACK) has `operstate == up` | item: `no network link — package-index suggestions need a connection` | `sysfs`, `bus` |
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

### D2 — Access path: sysfs first, `busctl call` second, no daemon, no activation

One flag: `jarvis brief [run] --signals off|sysfs|bus` (default **`off`** — owner question Q-B).

- **`off`** — today, byte-for-byte: the new `sense()` stage is not called; `latest.md` and stdout
  are unchanged; the `--json` payload and the ledger record gain only the additive keys of D4.
- **`sysfs`** — `sense()` reads S1, S2, S6 with `open()` on fixed paths, ≤ 256 bytes each, every
  `OSError`/`ValueError` → that fact is *absent*. Zero subprocesses; works in containers, without
  any bus, and under `--harden` (a read-only `/sys` is all it needs).
- **`bus`** — everything in `sysfs`, plus S3–S5 (and `IdleHint`) through **one fixed argv per
  property**, e.g.

  ```
  busctl --system --auto-start=no --timeout=2 call \
      org.freedesktop.login1 /org/freedesktop/login1 \
      org.freedesktop.DBus.Properties Get ss org.freedesktop.login1.Manager PreparingForSleep
  ```

  *Why `call … Properties.Get` and not `get-property`:* `--auto-start=` and `--timeout=` are
  documented for the `call` command (defaults: auto-start **yes**, timeout 25 s). With
  `--auto-start=no` a probe can never bus-activate a service — **sensing must not start UPower,
  NetworkManager or anything else as a side effect.** The reply is in `busctl`'s documented terse
  format (a variant: signature, then value — `v b true`, `v u 3`), parsed by a small strict
  function that accepts only `b` and `u`; `--json=` exists but its shape for this command is not
  documented, so the terse format is the contract. Gates, in order: `shutil.which("busctl")`;
  `subprocess.run(argv, capture_output=True, timeout=3)`; stdout capped at 4 KiB; any non-zero
  exit, timeout, oversize or unparsable reply → that fact is *absent* and the payload records
  `"bus": "unavailable: <first line of stderr>"`. Budget: six `call`s per run (login1 Manager ×3,
  Session ×1, NM ×2), ≈10–20 ms each with a live bus (**ASSUMED**; 6 ms here for a failed
  connect); worst case with a hung bus 6 × 3 s.

`sense()` runs **before** `compose()` and hands it a frozen `Signals` value; `compose()` stays
subprocess-free and `test_compose_never_spawns_subprocess` stays green as written. A sibling test
asserts `sense(mode="sysfs")` never spawns either.

**Listener in the doorway: not proposed** (owner question Q-C). `busctl wait` (systemd ≥ 257) and
`busctl monitor` exist and would work as fixed argv, but a resident process that composes *on
events* is the step from Scheduled (L2) to Situation-Aware (L3) proactivity — research §5 and
ADR-0021 both park that as its own owner-gated decision — and it would put a long-lived child
inside a unit ADR-0018 defines as "a doorway, never an actor". Polling at briefing time covers five
of the six research rows. Two honest consequences: S4 will fire rarely (systemd catches up a
calendar timer that elapsed during sleep *after* resume, when `PreparingForSleep` is already
`false` again; S4 mainly protects the shutdown-in-progress case) — it stays because it is cheap,
correct, and the one signal §5.3 singled out; and "resume from suspend" becomes S6, a count in the
ledger, rather than a trigger.

### D3 — Interruption cost lives in `decide()`, as holds, additively

`Briefing` gains two frozen fields with defaults — `holds: tuple[str, ...] = ()` and
`signals: Mapping[str, object] = MappingProxyType({})` — so every existing constructor call is
untouched. `decide()` keeps `decision ∈ {"notify", "silence"}` (the ledger vocabulary is unchanged)
and sets `holds` from S4/S5 (`"sleep-imminent"`, `"session-locked"`). `run_once()` skips
`desktop_notify()` when `holds` is non-empty, still writes `latest.md`, and records
`delivered=false` plus the additive `holds` key; `brief status` gains an additive `held` count.
`markdown()` appends one `context: …` line **only when at least one fact was sensed** (so the file
is byte-identical in `off` mode). Held briefings are not retried — `Persistent=true` means the next
calendar fire is tomorrow; the note is in `latest.md` meanwhile (owner question Q-D).

### D4 — Wire shape: additive keys, HUD untouched, one seam rule

`jarvis --json brief` and each ledger `run` record gain:

```json
"signals": {
  "mode": "off | sysfs | bus",
  "battery":  {"percent": 12, "discharging": true}          // or null = not sensed
  "network":  {"link": true, "metered": null, "connectivity": null},
  "session":  {"locked": null, "idle": null, "preparing_for_sleep": null},
  "suspend_cycles": null,                                    // int when known
  "bus": "off | ok | unavailable: <reason>"
},
"holds": []
```

`null` always means *not sensed*, never *normal* — the HUD's own rule ("absent, not full or
empty"). MCP: no tool change (`jarvis_status` does not expose briefings; nothing to add). HUD: **no
change**; the one cross-repo rule is that the kernel's S1 filter mirrors `read_battery()` exactly
(type filter, clamp, status mapping) so a HUD battery cell and a briefing line can never disagree
about the number — the audit round found the seam is where defects hide.

### D5 — Configuration and persistence

Mode and threshold are CLI flags (`--signals`, `--battery-low N`), rendered into the unit's
`ExecStart=` by `brief install --signals … [--battery-low N]` — the same install-time pattern as
`--harden`; already-installed units are untouched until re-installed; packaging never enables
anything. **No config file:** two knobs do not justify one, and a file that can only add text or
remove a knock has no integrity value worth a re-baseline (contrast ADR-0030 D-A). S6 state
(`boot_id`, `suspend_success`) lives inside the run record — the ledger already is the memory.
Nothing sensed leaves the machine: signals go to `latest.md`, the ledger and `notify-send` only.

### D6 — Tests (all offline; the sandbox has no bus, battery or suspend)

- sysfs sensors take a `root: Path` (default `/`) → fake trees under `tmp_path`: battery
  present / absent / non-`Battery` supplies skipped / `capacity` 104 clamps / each `status` value /
  a `carrier` read raising `OSError` tolerated / loopback-only host → no link / `suspend_stats`
  missing → `null` / `boot_id` change → delta resets to `null`.
- bus sensors take `which` and `runner` callables → fixtures in the documented terse format
  (`v b true`, `v u 3`), the real failure text captured here (`Failed to connect to bus: No such
  file or directory`, rc 1), timeout → absent, garbage → absent, oversize → absent; **argv asserted
  exactly, including `--auto-start=no`**.
- `sense(mode="off")` returns the empty `Signals`; golden comparison: `latest.md` and stdout of
  `run_once` with seeded fixtures are byte-identical before and after the change.
- `decide()` with S4/S5 → holds; `run_once` with holds → `desktop_notify` not called, `latest.md`
  written, ledger `holds` recorded; `status` counts `held`.
- `test_compose_never_spawns_subprocess` unchanged + `test_sense_sysfs_never_spawns_subprocess`.
- Mutation checks planned before the tick: drop `--auto-start=no` (argv test fails); treat `null`
  as `false` (a *not sensed* fact must never produce an item or a hold); loopback not excluded
  (lo-only tree must report no link); `GUESS_NO` treated as metered; hold ignored by `run_once`.

### D7 — Non-goals

- No signal ever reaches the planner or a model; none triggers execution, scheduling or consent.
- No listener, no inotify, no D-Bus *methods* other than `org.freedesktop.DBus.Properties.Get`, no
  `set-property`, no `Inhibit()` — JARVIS will not take inhibitor locks to delay sleep for a
  briefing.
- No per-compositor idle protocols; logind's `IdleHint` is the portable, DE-maintained hint, and
  even that is recorded, not acted on.

## Owner decisions (please answer before any code)

**Q-A — Signals.** Keep S1–S6 as specified? Prune (S2 is noise on an always-wired desktop) or add
(`/run/reboot-required`)? Battery threshold default **20 %** (UPower's own *low* default is 10 %
`[snippet]`; 20 leaves time to decline a T2 upgrade)?

**Q-B — Default mode.** **`off`** (my recommendation for the ADR: the briefing changes only when
you ask) or **`sysfs`** (zero-subprocess; the same facts the HUD already displays; still no bus)?

**Q-C — Listener.** Confirm poll-at-briefing only: no doorway listener and no inotify in this
ADR (a later L3 ADR if ever wanted).

**Q-D — Hold semantics.** Held = `latest.md` + ledger, no knock, no retry until the next calendar
fire. Alternative: re-arm via `OnUnitInactiveSec=` (more knocks, more complexity — not
recommended).

## Failure modes

| Precondition absent / fault | Behaviour | Same as today? |
|---|---|---|
| `--signals off` (default) or flag not given | `sense()` not called | yes — `latest.md`/stdout byte-identical; JSON gains additive keys only |
| No `/sys/class/power_supply` entries (desktop, VM, container) | `battery: null`; no S1 item | yes |
| Only loopback / no `operstate == up` | S2 item (in `sysfs`/`bus` mode) | n/a — new line, text only |
| `/sys/power/suspend_stats` missing (older kernels; the ABI entry is dated July 2019) or `boot_id` changed | `suspend_cycles: null` | yes |
| `busctl` missing, no system bus, hung bus, garbage reply | bus facts `null`; `"bus": "unavailable: …"`; no holds; sysfs facts still present | degrades to `sysfs` |
| `--harden` unit: `PrivateUsers=` + `ProtectSystem=strict` between `busctl` and `/run/dbus/system_bus_socket` | if the connect fails → as above; sysfs reads unaffected (`ProtectKernelTunables=` keeps `/sys` readable) | degrades to `sysfs` (**ASSUMED**, verify on the owner's machine) |
| `session/auto` does not resolve from a `systemd --user` timer | `locked: null`; no S5 hold | degrades (**ASSUMED**) |
| DE never calls `SetLockedHint` | `locked: false` while the screen is locked → knock delivered | today's behaviour (limit, documented) |
| S4/S5 hold fires | no `notify-send`; `latest.md` + ledger written; `delivered=false`, `holds=[…]` | new; silence-with-receipt (ADR-0021 D2 spirit) |
| Timer catches up after resume | brief runs once; `PreparingForSleep` already `false`; S6 counts the cycle | yes (systemd semantics unchanged) |

## Consequences

- The briefing gains eyes, not hands: four kernel facts and up to four bus facts become lines,
  holds or ledger context; the catalog stays 58 playbooks; no execution path is added.
- Kernel version on implementation: **1.23.0** (additive feature; interfaces preserved — CLI verbs,
  MCP tools, journal schema and existing unit contents unchanged; new flags and JSON keys only).
- The zero-subprocess promise is *refined*, not broken: composition stays pure; the optional
  `bus` mode is the first scheduled JARVIS process that spawns a helper, and it does so with fixed
  argv, `--auto-start=no`, a 2 s bus timeout and a 3 s process timeout — the exception ADR-0021
  said "deserves its own ADR" is this one.
- Recommendations recorded, not proposed: (a) `/run/reboot-required` as a seventh sysfs-style
  fact; (b) reusing UPower's `WarningLevel` (3 = Low, 4 = Critical, verified) instead of a JARVIS
  threshold *if* the owner prefers the system's own policy — requires accepting an UPower probe;
  (c) an L3 ADR for a doorway listener (`busctl wait org.freedesktop.login1 /org/freedesktop/login1
  org.freedesktop.login1.Manager PrepareForSleep`) once L2 has a feedback history to learn from.

## Verified vs. assumed (this ADR)

- **VERIFIED (fetched today):** every D-Bus service, object, interface, property and value quoted
  below; `busctl` command grammar, `--auto-start=`/`--timeout=`/`--json=` semantics, terse output
  format; sysfs attribute names and value sets for power supplies, network interfaces and suspend
  statistics; `CLOCK_BOOTTIME` vs `CLOCK_MONOTONIC`; systemd calendar-timer catch-up after sleep;
  ARPHRD numbers (local `/usr/include/linux/if_arp.h`: ETHER 1, PPP 512, LOOPBACK 772, IEEE80211
  801, NONE 0xFFFE).
- **VERIFIED (repo / sandbox):** engine structure and the zero-subprocess test; `--harden`
  directive list; HUD `read_battery()` filter; sandbox `busctl` (systemd 252) offers `--json=`,
  `--auto-start=`, `--timeout=`; no system bus here → `Failed to connect to bus: No such file or
  directory`, rc 1, 6 ms; `/sys/class/net/{lo,eth0}` → `operstate` `unknown`/`up`, `type`
  772/1; `/sys/power/suspend_stats/success` = 0; `/sys/class/power_supply/` empty;
  `CLOCK_BOOTTIME − CLOCK_MONOTONIC` = 0.0 s.
- **ASSUMED (to check on the owner's machine before the implementation is called verified):**
  (1) `/org/freedesktop/login1/session/auto` resolves to the owner's graphical session when the
  brief runs from a `systemd --user` timer (the reference only says the convenience objects "can
  only be dereferenced relative to a method caller"); (2) `busctl` reaches the system bus from a
  `--harden` unit; (3) the terse reply of `call … Properties.Get` is `v <sig> <value>` — derived
  from the documented parameter-formatting rules for variants, not from a captured run; (4) UPower
  `PercentageLow=10` default (`[snippet]`, two secondary sources); (5) the `scope`
  (`System`/`Device`) power-supply attribute exists for peripheral batteries (`[snippet]`, LKML) —
  the implementation skips `Device` when present and otherwise relies on the `type == Battery`
  filter the HUD already uses.
- **NOT VERIFIABLE HERE:** any live sensing. Commands for the owner, to run once before
  implementation and paste into the TASKS.md verification block:

  ```
  busctl --system --auto-start=no --timeout=2 call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.DBus.Properties Get ss org.freedesktop.login1.Manager IdleHint
  busctl --system --auto-start=no --timeout=2 call org.freedesktop.login1 /org/freedesktop/login1/session/auto org.freedesktop.DBus.Properties Get ss org.freedesktop.login1.Session LockedHint
  busctl --system --auto-start=no --timeout=2 call org.freedesktop.NetworkManager /org/freedesktop/NetworkManager org.freedesktop.DBus.Properties Get ss org.freedesktop.NetworkManager Metered
  cat /sys/class/power_supply/*/type /sys/class/power_supply/*/status /sys/class/power_supply/*/capacity
  cat /sys/power/suspend_stats/success; for i in /sys/class/net/*; do echo "$i $(cat $i/type) $(cat $i/operstate)"; done
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
- `busctl(1)` (systemd 261) — `call SERVICE OBJECT INTERFACE METHOD [SIGNATURE [ARGUMENT…]]`,
  `get-property`, `wait` (added in 257), `monitor`; `--auto-start=BOOL` ("when used with the call
  or emit command … defaults to yes"), `--timeout=SECS` ("when used with the call command … default
  25s"), `--json=MODE`, `--system` implied; parameter/output formatting ("for variants, the
  signature of the contents shall be specified, followed by the contents"; examples `s "debug"`,
  `as 2 "…" "…"`). https://www.freedesktop.org/software/systemd/man/latest/busctl.html
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
- `[snippet]` LKML 2011-12-08, "power_supply: add power supply scope" — `POWER_SUPPLY_PROP_SCOPE`
  (`System`/`Device`) and `drivers/acpi/ac.c` exposing `ONLINE`. Secondary.
- In-repo: `src/jarvis/brief/engine.py`, `src/jarvis/brief/install.py` (`HARDENING_DIRECTIVES`),
  `tests/test_brief.py`, ADR-0017 D3, ADR-0018, ADR-0021, ADR-0029, ADR-0030;
  `JARVIS-GUI/…/src/javris/telemetry/proc_reader.py::read_battery()`.
