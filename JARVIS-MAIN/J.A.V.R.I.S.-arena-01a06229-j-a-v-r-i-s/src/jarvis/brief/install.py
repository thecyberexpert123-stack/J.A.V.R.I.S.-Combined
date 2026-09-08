"""Opt-in scheduling for briefings (ADR-0021 D5): a systemd --user timer.

Mirrors the residency install discipline (ADR-0018 D3): validate first,
write files, then enable — an absent systemd is an honestly-disclosed skip
with the manual command, never a silent claim. Packaging never enables it.

``--harden`` (ADR-0029 D3, opt-in): the briefing never executes a playbook —
it reads the journal and context store, writes under the state dir and calls
``notify-send`` — so it is the one JARVIS unit that can take systemd's full
confinement profile without breaking ``sudo -n``. The profile is measured
(``systemd-analyze security --offline``: 9.6 → 2.0) but cannot be *executed*
under a user service manager in the development sandbox, hence opt-in until
one verified run exists on real hardware (promotion criterion in the ADR).

``--signals`` / ``--battery-low`` (ADR-0031 D5) are rendered into the timer
unit's ``ExecStart=`` — no config file. ``--listen`` (ADR-0031 D8) writes and
enables a second, separate unit, ``jarvis-signals.service``: the resident
listener that records sleep / lock / network events and delivers a held
briefing when the hold clears. It takes the same confinement block when
``--harden`` is given (it, too, never runs a playbook), plus the ``sd_notify``
supervision the doorway has.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from jarvis.brief.signals import DEFAULT_BATTERY_LOW, MODES
from jarvis.journal.sqlite import state_dir
from jarvis.safety.tiers import SafetyRefusal

_TIMER_NAME = "jarvis-brief.timer"
_SERVICE_NAME = "jarvis-brief.service"
LISTENER_UNIT = "jarvis-signals.service"
LISTENER_WATCHDOG_SEC = 60
_CALENDAR = {"daily": "OnCalendar=*-*-* 09:00:00", "weekly": "OnCalendar=Mon *-*-* 09:00:00"}

#: ADR-0029 D3 — every directive is justified for *this* unit in the ADR table.
#: Order: namespace/privilege first (so the rest is not silently skipped in a
#: user manager), then the file-system view, then kernel surfaces, then seccomp.
HARDENING_DIRECTIVES: tuple[str, ...] = (
    "PrivateUsers=yes",
    "NoNewPrivileges=yes",
    "ProtectSystem=strict",
    "ProtectHome=read-only",
    # ReadWritePaths= is rendered per install (the resolved state dir)
    "PrivateTmp=yes",
    "PrivateDevices=yes",
    "ProtectKernelTunables=yes",
    "ProtectKernelModules=yes",
    "ProtectKernelLogs=yes",
    "ProtectClock=yes",
    "ProtectHostname=yes",
    "RestrictRealtime=yes",
    "RestrictSUIDSGID=yes",
    "LockPersonality=yes",
    "RestrictNamespaces=yes",
    "CapabilityBoundingSet=",
    "RestrictAddressFamilies=AF_UNIX",
    "SystemCallArchitectures=native",
    "SystemCallFilter=@system-service",
    "SystemCallErrorNumber=EPERM",
    "UMask=0077",
    "LimitCORE=0",
)


def timer_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / _TIMER_NAME


def service_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / _SERVICE_NAME


def listener_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / LISTENER_UNIT


def _signal_flags(signals: str, battery_low: int) -> str:
    """The ``ExecStart=`` suffix; empty for the defaults so existing units are unchanged."""
    if signals not in MODES:
        raise SafetyRefusal(f"--signals must be one of {', '.join(MODES)}")
    if not 0 <= battery_low <= 100:
        raise SafetyRefusal("--battery-low must be between 0 and 100")
    flags = ""
    if signals != "sysfs":
        flags += f" --signals {signals}"
    if battery_low != DEFAULT_BATTERY_LOW:
        flags += f" --battery-low {battery_low}"
    return flags


def _hardening_lines(state: Path | None) -> list[str]:
    writable = _unit_safe_path(state if state is not None else state_dir())
    lines = ["# ADR-0029 D3: confinement profile — this unit never runs a playbook"]
    for directive in HARDENING_DIRECTIVES:
        lines.append(directive)
        if directive == "ProtectHome=read-only":
            lines.append(f"ReadWritePaths={writable}")
    return lines


def _unit_safe_path(path: Path) -> str:
    """A path that can be written verbatim into ``ReadWritePaths=``.

    systemd splits the value on whitespace and applies quoting rules; rather
    than implement its escaping we refuse the rare state dir that would need
    it (the default ``~/.local/state/jarvis`` never does).
    """
    text = str(path)
    if not path.is_absolute() or any(ch.isspace() or ch in "\"'\\" for ch in text):
        raise SafetyRefusal(
            f"--harden: state dir {text!r} contains whitespace or quotes and cannot be written "
            "into ReadWritePaths= safely; move JARVIS_STATE_DIR or install without --harden"
        )
    return text


def service_content(
    python_exe: str,
    *,
    harden: bool = False,
    state: Path | None = None,
    signals: str = "sysfs",
    battery_low: int = DEFAULT_BATTERY_LOW,
) -> str:
    """The oneshot service unit; ``harden`` adds the ADR-0029 D3 profile.

    ``state`` is the state directory the confined unit may write (resolved
    from the environment when omitted, so ``$JARVIS_STATE_DIR`` /
    ``$XDG_STATE_HOME`` overrides are honoured at install time). ``signals``
    and ``battery_low`` (ADR-0031 D5) are appended to ``ExecStart=`` only
    when they differ from the defaults, so a default install renders the
    same unit text as before.
    """
    flags = _signal_flags(signals, battery_low)
    lines = [
        "[Unit]",
        "Description=JARVIS briefing (propose-only; ADR-0021)",
        "",
        "[Service]",
        f"ExecStart={python_exe} -m jarvis brief --quiet{flags}",
        "Type=oneshot",
    ]
    if harden:
        lines += _hardening_lines(state)
    return "\n".join(lines) + "\n"


def listener_content(
    python_exe: str,
    *,
    harden: bool = False,
    state: Path | None = None,
    record_only: bool = False,
) -> str:
    """``jarvis-signals.service`` (ADR-0031 D8): resident, supervised, opt-in.

    ``Type=notify`` + ``WatchdogSec`` reuse the doorway's ``sd_notify``
    discipline (ADR-0029 D1); ``Restart=on-failure`` covers crashes and
    watchdog expiry alike. With ``harden`` the brief's confinement block
    applies verbatim: the listener needs only ``AF_UNIX`` (the bus socket and
    ``$NOTIFY_SOCKET``), a read-only system view and the state dir.
    """
    suffix = " --record-only" if record_only else ""
    lines = [
        "[Unit]",
        "Description=JARVIS signal listener (records events, delivers held briefings; ADR-0031)",
        "After=default.target",
        "",
        "[Service]",
        "Type=notify",
        "NotifyAccess=main",
        f"ExecStart={python_exe} -m jarvis brief listen{suffix}",
        f"WatchdogSec={LISTENER_WATCHDOG_SEC}",
        "Restart=on-failure",
        "RestartSec=5",
    ]
    if harden:
        lines += _hardening_lines(state)
    lines += ["", "[Install]", "WantedBy=default.target"]
    return "\n".join(lines) + "\n"


def timer_content(schedule: str) -> str:
    return (
        "[Unit]\n"
        "Description=JARVIS briefing schedule (opt-in; ADR-0021)\n"
        "\n"
        "[Timer]\n"
        f"{_CALENDAR[schedule]}\n"
        "Persistent=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def _systemctl_available() -> bool:
    return shutil.which("systemctl") is not None and bool(os.environ.get("XDG_RUNTIME_DIR"))


def install_timer(
    schedule: str,
    home: Path,
    *,
    harden: bool = False,
    signals: str = "sysfs",
    battery_low: int = DEFAULT_BATTERY_LOW,
    listen: bool = False,
    record_only: bool = False,
) -> int:
    if schedule not in _CALENDAR:
        raise SafetyRefusal("schedule must be daily or weekly")
    # Validate (state dir quoting, flag ranges) BEFORE writing anything — never a half install.
    service_text = service_content(
        sys.executable, harden=harden, signals=signals, battery_low=battery_low
    )
    listener_text = (
        listener_content(sys.executable, harden=harden, record_only=record_only) if listen else None
    )
    service_dir = service_path(home).parent
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path(home).write_text(service_text, encoding="utf-8")
    timer_path(home).write_text(timer_content(schedule), encoding="utf-8")
    profile = "hardened (ADR-0029 D3)" if harden else "plain"
    print(
        f"[jarvis] wrote {service_path(home)} and {timer_path(home)} "
        f"({schedule}, {profile}, signals={signals}, battery-low={battery_low}%)"
    )
    if listener_text is not None:
        listener_path(home).write_text(listener_text, encoding="utf-8")
        print(
            f"[jarvis] wrote {listener_path(home)} (resident listener; "
            f"{'record-only' if record_only else 'record + deliver held briefings'})"
        )
    if harden:
        print(
            "[jarvis] --harden: the unit runs under PrivateUsers + seccomp + a read-only view of "
            "the system; verify the first run with: systemctl --user start jarvis-brief.service "
            "&& journalctl --user -u jarvis-brief -n 30 . Re-install without --harden to revert."
        )
    if _systemctl_available():
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        units = [_TIMER_NAME] + ([LISTENER_UNIT] if listen else [])
        for unit in units:
            result = subprocess.run(
                ["systemctl", "--user", "enable", "--now", unit],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"[jarvis] enabled + started {unit} (systemd --user)")
            else:
                print(
                    f"[jarvis] {unit} written but enable failed: {result.stderr.strip()}; "
                    f"manual: systemctl --user enable --now {unit}"
                )
    else:
        manual = _TIMER_NAME + (f" {LISTENER_UNIT}" if listen else "")
        print(
            "[jarvis] systemd --user unavailable here: files written but NOT enabled. "
            f"Manual: systemctl --user enable --now {manual}"
        )
    print(
        "[jarvis] disclosure: the timer runs 'jarvis brief --quiet', which only reads local "
        "state and writes a report - it never executes commands. Remove: jarvis brief uninstall"
    )
    if signals != "off":
        print(
            f"[jarvis] signals={signals}: the briefing reads battery / link / suspend count from "
            "/sys"
            + (
                " and metered / locked / sleep-imminent from the system bus"
                if signals == "bus"
                else ""
            )
            + "; facts add a line or withhold the desktop knock, nothing more (ADR-0031)"
        )
    if listen:
        print(
            "[jarvis] listener: 'jarvis brief listen' subscribes to logind and NetworkManager "
            "signals, records them in the briefing ledger and re-delivers a held briefing when "
            "you unlock or resume - it never composes or executes anything (ADR-0031 D8)"
        )
    return 0


def uninstall_timer(home: Path) -> int:
    if _systemctl_available():
        for unit in (_TIMER_NAME, LISTENER_UNIT):
            if unit == LISTENER_UNIT and not listener_path(home).exists():
                continue
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", unit],
                check=False,
                capture_output=True,
                text=True,
            )
    removed = 0
    for path in (timer_path(home), service_path(home), listener_path(home)):
        if path.exists():
            path.unlink()
            removed += 1
            print(f"[jarvis] removed {path}")
    if not removed:
        print("[jarvis] nothing to remove - the briefing timer was not installed")
    return 0
