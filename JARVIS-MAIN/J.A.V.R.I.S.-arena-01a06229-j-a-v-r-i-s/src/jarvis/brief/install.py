"""Opt-in scheduling for briefings (ADR-0021 D5): a systemd --user timer.

Mirrors the residency install discipline (ADR-0018 D3): validate first,
write files, then enable — an absent systemd is an honestly-disclosed skip
with the manual command, never a silent claim. Packaging never enables it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from jarvis.safety.tiers import SafetyRefusal

_TIMER_NAME = "jarvis-brief.timer"
_SERVICE_NAME = "jarvis-brief.service"
_CALENDAR = {"daily": "OnCalendar=*-*-* 09:00:00", "weekly": "OnCalendar=Mon *-*-* 09:00:00"}


def timer_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / _TIMER_NAME


def service_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / _SERVICE_NAME


def service_content(python_exe: str) -> str:
    return (
        "[Unit]\n"
        "Description=JARVIS briefing (propose-only; ADR-0021)\n"
        "\n"
        "[Service]\n"
        f"ExecStart={python_exe} -m jarvis brief --quiet\n"
        "Type=oneshot\n"
    )


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


def install_timer(schedule: str, home: Path) -> int:
    if schedule not in _CALENDAR:
        raise SafetyRefusal("schedule must be daily or weekly")
    service_dir = service_path(home).parent
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path(home).write_text(service_content(sys.executable), encoding="utf-8")
    timer_path(home).write_text(timer_content(schedule), encoding="utf-8")
    print(f"[jarvis] wrote {service_path(home)} and {timer_path(home)} ({schedule})")
    if _systemctl_available():
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", _TIMER_NAME],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"[jarvis] enabled + started {_TIMER_NAME} (systemd --user)")
        else:
            print(
                f"[jarvis] timer written but enable failed: {result.stderr.strip()}; "
                f"manual: systemctl --user enable --now {_TIMER_NAME}"
            )
    else:
        print(
            "[jarvis] systemd --user unavailable here: files written but NOT enabled. "
            f"Manual: systemctl --user enable --now {_TIMER_NAME}"
        )
    print(
        "[jarvis] disclosure: the timer runs 'jarvis brief --quiet', which only reads local "
        "state and writes a report - it never executes commands. Remove: jarvis brief uninstall"
    )
    return 0


def uninstall_timer(home: Path) -> int:
    if _systemctl_available():
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", _TIMER_NAME],
            check=False,
            capture_output=True,
            text=True,
        )
    removed = 0
    for path in (timer_path(home), service_path(home)):
        if path.exists():
            path.unlink()
            removed += 1
            print(f"[jarvis] removed {path}")
    if not removed:
        print("[jarvis] nothing to remove - the briefing timer was not installed")
    return 0
