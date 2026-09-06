# ADR-0029: Doorway survival — `sd_notify` readiness/watchdog/status, and per-unit hardening that respects what each unit is allowed to do

- **Status:** **Accepted 2026-09-06** — drafted and decided the same day (owner-directed "continue"
  sequence, `TASKS.md` item B-C3, gated as OWNER-Q in decision D4; origin: deep research II
  `docs/RESEARCH-agent-construction-and-future-tech-2026.md` §4.2 (`sd_notify(3)`), §3.7 (systemd
  hardening), candidate C3, owner question 3). Owner answers (`TASKS.md` §D7/§D8): **D1 + D2
  accepted**; **D3 accepted as opt-in `--harden`**; C3b/C3c kept as recorded options.
  Implementation follows in the next commit; this text is the accepted design.
- **Context — three systemd user units, no supervision, no confinement.** JARVIS renders three
  unit templates: the resident doorway `jarvis-serve.service` (`cli/serve.py::unit_content`,
  ADR-0018; `Restart=on-failure`, `RestartSec=2`, nothing else), the briefing oneshot
  `jarvis-brief.service` (`brief/install.py::service_content`, ADR-0021) and per-charter oneshots
  (`safety/charter.py::unit_documents`, `TimeoutStartSec=` only). `grep` finds no `NOTIFY_SOCKET`,
  `WatchdogSec`, `Protect*` or `SystemCallFilter` anywhere in `src/`. Measured with
  `systemd-analyze security --offline=true` (systemd 252, this sandbox): **doorway 9.6 UNSAFE**,
  **brief 9.6 UNSAFE**, **charter 9.6 UNSAFE** (`--user` view: 9.8).
- **Context — what a hung doorway looks like today.** `run_server()` is `ThreadingHTTPServer.
  serve_forever(poll_interval=0.25)`; `Restart=on-failure` fires only on *exit*. An interpreter
  deadlock (a C call that never returns while holding the GIL) leaves the unit `active (running)`
  and every GUI/CLI request hanging until the owner notices. systemd's watchdog exists for exactly
  this: `WatchdogSec=` + periodic `WATCHDOG=1` from the main process; on expiry the service is
  placed in the failed state and terminated with `SIGABRT` (`WatchdogSignal=` default), and
  `Restart=on-failure` restarts it — `on-failure` **already covers watchdog timeouts**, so the unit
  does not need (and must not switch to) `Restart=on-watchdog`, which would drop crash restarts.
- **Context — the finding that reshaped D2 (verified here, not assumed).** In a *user* service
  manager the sandboxing directives cannot be applied the way PID 1 applies them. systemd 252's
  systemd.exec(5) (Debian 12, this sandbox) states on every seccomp-backed directive —
  `SystemCallFilter=`, `SystemCallArchitectures=`, `RestrictAddressFamilies=`, `RestrictNamespaces=`,
  `LockPersonality=`, `MemoryDenyWriteExecute=`, `RestrictRealtime=`, `RestrictSUIDSGID=`,
  `ProtectKernelTunables=`, `ProtectKernelModules=`, `PrivateDevices=` … — "if running in user
  mode … **`NoNewPrivileges=yes` is implied**" (the kernel accepts a seccomp filter only from a
  thread that has `CAP_SYS_ADMIN` in its user namespace *or* has `no_new_privs` set). The current
  manual instead routes user-manager sandboxing through an **implicit `PrivateUsers=`** — an
  unprivileged user namespace, inside which the process holds its own capabilities — and every
  mount-namespace directive (`ProtectSystem=`, `ProtectHome=`, `PrivateTmp=`, `ReadWritePaths=`,
  `ProtectClock=`, `CapabilityBoundingSet=` …) has always required that namespace (silently
  skipped on older releases without an explicit `PrivateUsers=yes`, per the 2022 systemd-devel
  notice). Whichever mechanism a given release uses, the result is the same for the only
  privilege path JARVIS has, and both were reproduced here:
  - `setpriv --no-new-privs sudo -n true` → `sudo: The "no new privileges" flag is set, which
    prevents sudo from running as root.`
  - `unshare -U sudo -n true` → `sudo: /usr/bin/sudo must be owned by uid 0 and have the setuid bit
    set` (setuid is void inside an unprivileged user namespace).
  So on every systemd release in scope, **any unit that may legitimately run a T1/T2 step
  (`sudo -n`) can take none of the score-moving directives**, and `systemd-analyze security` will keep calling it UNSAFE — not
  because the doorway is careless, but because the score measures OS-level confinement of a
  process whose *contract* includes escalation. Also verified: `UMask=0077` is unsafe for such a
  unit because `sudo` **unions** the caller's umask with its own (`(umask 077; sudo -n sh -c
  umask)` → `0077`), so maintainer scripts during a `pkg.install` would create root-only files.
- **Context — which units may escalate.** The doorway serves `jarvis_do` → full Orchestrator →
  T1/T2 playbooks (10 of the 20 T1/T2 playbooks have a `requires_root` path; the 38 T0 playbooks
  have none). Charter units run `charter run <id>` → same Orchestrator, bounded by the charter's
  `tier_ceiling` (0..2). The **brief unit never executes a playbook**: it reads the journal and
  context store, writes `briefings/` + a ledger under the state dir, and spawns `notify-send`
  (session D-Bus over `AF_UNIX`). No network, no `sudo`, no `ctypes`.

## Decision

**D1 — A stdlib `sd_notify` client, wired into the doorway only; no-op outside systemd.**
New module `src/jarvis/system/sdnotify.py` (≈80 lines, stdlib `socket`/`os`/`time`): reads
`$NOTIFY_SOCKET` (leading `@` → abstract socket, `\0` prefix), `$WATCHDOG_USEC`, `$WATCHDOG_PID`
once at construction, then **removes them from `os.environ`** — the equivalent of the C API's
`unset_environment=1`, so playbook children spawned by the Runner (which copies `os.environ`)
never inherit a notify socket or believe they are watchdog-supervised. Messages are the
documented assignments only: `READY=1` + `STATUS=` once the socket is listening (sent right
before `serve_forever`), `WATCHDOG=1` at **half `WATCHDOG_USEC`** (the `sd_watchdog_enabled(3)`
convention) from `service_actions()` — the hook `serve_forever` calls on the *accept loop*
thread every `poll_interval`, so a slow or hung *request* (handled on its own thread) never
starves the ping while a dead interpreter does stop it, which is the intended semantics —
`STATUS=serving N requests; last: <METHOD> <path> -> <code>` after each request (the same
token-free, body-free content as the existing stderr audit line), and `STOPPING=1` from
`shutdown()`. Send errors are logged to stderr once and never raised (a notification must never
take the doorway down). `WATCHDOG=trigger` is **never** sent: integrity drift and other policy
failures mean *pause*, not restart-and-retry (charter Part C). Ping only when `WATCHDOG_PID` is
unset or equals `os.getpid()`. When `NOTIFY_SOCKET` is unset (manual `jarvis serve`, tests, CI)
the client is inert and behaviour is byte-identical to today.

**D2 — Doorway unit: supervision, not confinement.** `unit_content()` gains exactly
`Type=notify`, `NotifyAccess=main`, `WatchdogSec=30` (a stuck loop is noticed within 30 s;
pings every 15 s cost one datagram); `Restart=on-failure` / `RestartSec=2` stay. **No hardening
directives**, for the reasons in Context: each one either implies `NoNewPrivileges` or requires a
user namespace, and both silently turn every T1/T2 request into a `sudo` failure; `UMask=` is
excluded because of the umask union. Measured consequence stated plainly: the exposure score
**stays 9.6** after D1+D2; what actually protects the doorway remains ADR-0018 D2 (loopback bind,
bearer token, Host check, body cap, no CORS) plus the tier system. `Type=notify` has one new
failure mode — if `READY=1` never arrives, systemd kills the start after `TimeoutStartSec`
(default 90 s) — which is why D1 sends it unconditionally right after the bind and why
`serve install`'s `systemctl --user enable --now` (which now blocks until READY) still returns
promptly on the real failure paths (bind refusal / token error exit non-zero).

**D3 — Brief unit: the confined profile, as an explicit opt-in this release.** `jarvis brief
install --on <schedule> --harden` renders `service_content(python_exe, state_dir=<resolved>)`
with this measured set (`systemd-analyze security --offline`: **9.6 → 2.0**, `--user` view
**9.8 → 2.2**):

| directive | why it is safe *for this unit* |
|---|---|
| `PrivateUsers=yes` | explicit so mount-namespace options are not silently skipped on systemd < 258; the brief never uses setuid binaries |
| `NoNewPrivileges=yes` | the brief runs no playbook, so `sudo -n` is never on its path |
| `ProtectSystem=strict` + `ProtectHome=read-only` + `ReadWritePaths=<state dir>` | its only writes are `briefings/`, the ledger, `journal.db`, `context.db` — all under the resolved state dir (rendered from `state_dir()` at install time, so `$JARVIS_STATE_DIR`/`$XDG_STATE_HOME` overrides are honoured; the install refuses a path containing whitespace or quotes rather than mis-quote it) |
| `PrivateTmp=yes`, `PrivateDevices=yes` | needs only `/dev/null`, `/dev/urandom` |
| `ProtectKernelTunables/Modules/Logs=yes`, `ProtectClock=yes`, `ProtectHostname=yes`, `RestrictRealtime=yes`, `RestrictSUIDSGID=yes`, `LockPersonality=yes`, `RestrictNamespaces=yes`, `CapabilityBoundingSet=` (empty) | none of these touch anything the brief does |
| `RestrictAddressFamilies=AF_UNIX` | its only socket is the session bus for `notify-send` |
| `SystemCallArchitectures=native`, `SystemCallFilter=@system-service`, `SystemCallErrorNumber=EPERM` | the upstream-recommended baseline allow-list; EPERM instead of SIGSYS so an unexpected call surfaces as a Python `PermissionError` in the journal, not a silent kill |
| `UMask=0077`, `LimitCORE=0` | state dir is already 0700; no core files of a process that read the journal |

`MemoryDenyWriteExecute=` is deliberately **left out** (0.1 of score; CPython 3.11 has no JIT but
libffi trampolines could be hit by a future dependency — not worth an unverifiable risk).
**Why opt-in:** the profile is validated here only by the offline analyser; *executing* the brief
under seccomp + a user namespace cannot be tested in this sandbox (no user service manager), and
a briefing timer that dies on every run is a regression, not a degradation. Default behaviour
therefore stays exactly today's; the promotion criterion to default-on is one verified run on the
owner's machine (commands in Consequences). `--no-harden` re-renders the plain unit; `brief
uninstall` removes everything as before. The `-m jarvis brief --quiet` `ExecStart` line is
unchanged; existing tests keep passing because they assert substrings.

**D4 — Charter units: unchanged in this item.** A `tier_ceiling` ≥ 1 charter may escalate, so
only the score-neutral directives would apply (none worth a unit change). A `tier_ceiling = 0`
charter could take the D3 profile (T0 playbooks never `requires_root`), but T0 playbooks do call
system tools (`df`, `free`, `uptime`, `systemctl`, package-manager queries, …) whose syscall and
address-family needs (`systemctl` talks to the bus; a query may reach `AF_NETLINK`) are wider
than the brief's and equally unverifiable here. Recorded as **C3b** in
`TASKS.md`: confined T0-charter profile *after* the brief profile is proven on real hardware.

**D5 — Tests (all runnable here).** `tests/test_sdnotify.py` + additions to `tests/test_serve.py`
and `tests/test_brief.py`: a bound `AF_UNIX` datagram socket (abstract name) receives `READY=1`
+ `STATUS=` when the doorway starts serving, `WATCHDOG=1` at the half-interval cadence with a
fake clock, `STATUS=` after a request that never contains the token or body, `STOPPING=1` on
shutdown; inert when `NOTIFY_SOCKET` is unset; children `env` (via the Runner's `os.environ`
copy) stripped of all three variables; `WATCHDOG_PID` mismatch → no pings; unit text asserts
(`Type=notify`, `WatchdogSec=30`, `Restart=on-failure` retained, no `NoNewPrivileges`/`UMask` in
the doorway unit; every D3 directive present with `--harden`, none without); and, when
`systemd-analyze` is on PATH, `security --offline=true --threshold=…` run against the rendered
brief unit asserting the score ≤ 2.5 (`--threshold=25` exits 0 for the D3 set and non-zero at
`--threshold=15`, checked here; skips honestly when the binary is absent).

**D6 — What this ADR does *not* do.** No new dependency (`ADR-0005`: stdlib only — the protocol is
documented as stable by systemd and the man page ships a reference Python client). No new verb.
No `WATCHDOG=trigger`. No change to what the doorway may execute. No change to MCP payloads,
journal schema, or the GUI (`bridge/resident.py` only polls `/v1/health`). Runtime code changes
→ ships in the same next minor (1.21.0) as ADR-0028; bump applied at the authorized commit.

## Failure modes

| situation | behaviour after this ADR | today |
|---|---|---|
| `jarvis serve` run by hand / in CI (no `NOTIFY_SOCKET`) | client inert; identical output and timing | same |
| interpreter deadlock in the doorway | no `WATCHDOG=1` for 30 s → `SIGABRT` → `Restart=on-failure` after 2 s; journal shows `Watchdog timeout` | hangs indefinitely |
| one tool call hangs (e.g. `sudo` waiting on a lock) | accept loop keeps pinging; other requests keep being served; the hung request is unaffected by the watchdog | same |
| `READY=1` cannot be delivered | logged once; systemd fails the start after 90 s (`TimeoutStartSec`) and restarts per policy; `serve status` shows it | n/a (`Type=simple`) |
| repeated watchdog kills | default `StartLimitBurst=5/10s` puts the unit in failed state — visible, needs `systemctl --user reset-failed`; same as today's crash loops | same for crashes |
| `systemctl --user stop` during a running step | `STOPPING=1`, then the process exits as today (handler threads are daemon threads — the step is cut, **pre-existing** behaviour, unchanged, noted) | same |
| brief `--harden` on a kernel with unprivileged user namespaces disabled | mount-namespace directives are skipped by systemd; seccomp set still applies; brief runs; score lower than measured | n/a |
| brief `--harden` breaks the brief on the owner's machine (unforeseen syscall/path) | run fails with `PermissionError`/`EROFS` in `journalctl --user -u jarvis-brief`; `jarvis brief install --on … --no-harden` restores today's unit; briefings are propose-only, nothing else is affected | n/a |
| owner sets `$JARVIS_STATE_DIR` *after* installing with `--harden` | `ReadWritePaths=` points at the old dir → brief fails loudly as above; re-run install | n/a |
| integrity drift / breaker open / any policy failure | **never** wired to the watchdog; unchanged pause semantics | same |

## Consequences

- The doorway becomes *supervised*: a dead loop is restarted within ~32 s and `systemctl --user
  status jarvis-serve` shows a live `Status:` line — the honest availability improvement research
  II asked for, without the doorway gaining any authority.
- The doorway's exposure score does **not** improve, and this ADR says why instead of pasting a
  hardening recipe that would break T1/T2 silently. A confined doorway is possible only as a
  *different* unit that refuses T1/T2 (`jarvis serve --max-tier 0`), recorded as owner option
  **C3c** — an architectural change (two doorway modes), not a directive set.
- The brief unit gets a real confinement profile (9.6 → 2.0) behind an opt-in flag until one
  verified run exists on real hardware.
- **Owner-machine verification (cannot be done in this sandbox — no user service manager):**
  ```console
  $ jarvis serve install && systemctl --user status jarvis-serve      # Status: listening … · Type=notify
  $ systemctl --user show jarvis-serve -p WatchdogUSec -p NotifyAccess   # 30s / main
  $ kill -STOP $(systemctl --user show jarvis-serve -p MainPID --value)  # simulate a hang
  $ sleep 35 && journalctl --user -u jarvis-serve -n 5                  # "Watchdog timeout" → restarted
  $ jarvis brief install --on daily --harden && systemctl --user start jarvis-brief.service
  $ journalctl --user -u jarvis-brief -n 30 && jarvis brief status      # one clean run = promotion criterion
  ```
- **Owner decisions (asked 2026-09-06 — answered the same day, recorded in `TASKS.md` §D7/§D8):**
  1. Accept D1 + D2 for the doorway (supervision, `WatchdogSec=30`, no hardening, score stays 9.6)?
  2. Accept D3 as **opt-in** (`--harden`) for the brief unit — or do you prefer default-on with
     `--no-harden` as the escape hatch, accepting that the first real run happens on your machine?
  3. Record C3b (confined T0 charters) and C3c (`--max-tier 0` confined doorway mode) as future
     items, or drop either?

## Sources (fetched 2026-09-06 unless marked)

- `sd_notify(3)`, systemd 261 — assignments `READY=1`, `STATUS=`, `WATCHDOG=1`, `WATCHDOG=trigger`,
  `STOPPING=1`, `MAINPID=`; `NotifyAccess=` gating; `unset_environment`; MIT-0 reference Python
  client; protocol stability note. https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html
- `systemd.service(5)` (Debian testing) — `WatchdogSec=` semantics (`SIGABRT`, `WATCHDOG_USEC=`
  env, restart with `on-failure`/`on-watchdog`/`on-abnormal`/`always`), `Type=notify`,
  `NotifyAccess=` implicit `main`. https://manpages.debian.org/testing/systemd/systemd.service.5.en.html
- `systemd.exec(5)` (Debian unstable, 2026-06) — per-user instance: mount-namespace options need
  `PrivateUsers=`; `ProtectControlGroups=`/`RemoveIPC=` system-only; `@system-service` +
  `SystemCallErrorNumber=EPERM` recommendation; `SystemCallFilter=~@mount` with namespacing
  options. Bookworm (systemd 252) text: "If running in user mode … `NoNewPrivileges=yes` is
  implied" on every seccomp-backed option. https://manpages.debian.org/unstable/systemd/systemd.exec.5.en.html
- `sd_watchdog_enabled(3)` — ping at half the interval; `WATCHDOG_PID` semantics.
  https://www.man7.org/linux/man-pages/man3/sd_watchdog_enabled.3.html (snippet)
- `systemd.kill(5)` — `WatchdogSignal=` defaults to `SIGABRT`.
  https://manpages.debian.org/unstable/systemd/systemd.kill.5.en.html (snippet)
- systemd-devel, L. Boccassi, Dec 2022 — user units silently skipped mount-namespace sandboxing
  without `PrivateUsers=yes`; PR #25233 made it implicit.
  https://lists.freedesktop.org/archives/systemd-devel/2022-December/048682.html
- Empirical, this sandbox (systemd 252, sudo 1.9): the `setpriv --no-new-privs` / `unshare -U`
  `sudo` messages and the umask union quoted in Context; all `systemd-analyze security
  --offline=true` scores quoted above (`--user` variants with a scratch `XDG_RUNTIME_DIR`).
