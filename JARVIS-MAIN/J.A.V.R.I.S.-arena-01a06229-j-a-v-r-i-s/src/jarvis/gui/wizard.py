"""ydotool setup wizard: real checks + distro-specific fixes (ADR-0010).

`jarvis gui wizard` answers one question honestly: can synthetic input work
on this Wayland session right now, and if not, what exactly is missing?
"""

from __future__ import annotations

import grp
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jarvis.gui.detect import GuiEnvironment, probe, ydotool_socket

PathExists = Callable[[Path], bool]

_PACKAGE_HINTS: dict[str, dict[str, str]] = {
    "apt": {
        "install": "sudo apt install ydotool",
        "service": "sudo systemctl enable --now ydotool",
        "group": "sudo usermod -aG input $USER  # then log out and back in",
    },
    "dnf": {
        "install": "sudo dnf install ydotool",
        "service": "sudo systemctl enable --now ydotool",
        "group": "sudo usermod -aG input $USER  # then log out and back in",
    },
    "pacman": {
        "install": "sudo pacman -S ydotool",
        "service": "sudo systemctl enable --now ydotool",
        "group": "sudo usermod -aG input $USER  # then log out and back in",
    },
    "apk": {
        "install": "sudo apk add ydotool",
        "service": "rc-update add ydotool && rc-service ydotool start",
        "group": "sudo adduser $USER input  # then log out and back in",
    },
}


@dataclass(frozen=True)
class WizardCheck:
    name: str
    ok: bool
    detail: str
    fix: str  # empty = nothing to fix


def run_checks(
    env: GuiEnvironment | None = None,
    *,
    env_vars: dict[str, str] | None = None,
    exists: PathExists = Path.exists,
    uinput_path: Path = Path("/dev/uinput"),
    in_input_group: Callable[[], bool] | None = None,
    which_fn: Callable[[str], str | None] | None = None,
) -> list[WizardCheck]:

    source = (
        env
        if env is not None
        else probe(env_vars, which_fn=which_fn)
        if which_fn
        else probe(env_vars)
    )
    evars = env_vars if env_vars is not None else dict(os.environ)
    socket = ydotool_socket(evars)
    group_fn = in_input_group if in_input_group is not None else _default_in_input_group

    checks: list[WizardCheck] = []
    session_ok = source.session_type in ("x11", "wayland")
    checks.append(
        WizardCheck(
            "graphical session detected",
            session_ok,
            f"{source.session_type} ({source.desktop})",
            "" if session_ok else "log into a graphical session (X11 or Wayland)",
        )
    )
    if session_ok and source.session_type == "x11":
        checks.append(
            WizardCheck(
                "input backend (X11)",
                source.has_tool("xdotool"),
                "xdotool on PATH" if source.has_tool("xdotool") else "xdotool missing",
                "sudo apt install xdotool  # (or your distro equivalent)"
                if not source.has_tool("xdotool")
                else "",
            )
        )
    checks.append(
        WizardCheck(
            "ydotool binary",
            source.has_tool("ydotool"),
            "found" if source.has_tool("ydotool") else "not on PATH",
            "" if source.has_tool("ydotool") else _hint(evars, which_fn).get("install", ""),
        )
    )
    socket_ok = exists(socket)
    checks.append(
        WizardCheck(
            "ydotoold socket",
            socket_ok,
            str(socket),
            "" if socket_ok else _hint(evars, which_fn).get("service", ""),
        )
    )
    uinput_exists = exists(uinput_path)
    checks.append(
        WizardCheck(
            "/dev/uinput (kernel uinput)",
            uinput_exists,
            "present" if uinput_exists else "missing",
            "" if uinput_exists else "sudo modprobe uinput",
        )
    )
    if uinput_exists:
        writable = os.access(uinput_path, os.W_OK)
        grouped = group_fn()
        checks.append(
            WizardCheck(
                "/dev/uinput writable",
                writable or grouped,
                "directly writable" if writable else f"input group: {grouped}",
                "" if (writable or grouped) else _hint(evars).get("group", ""),
            )
        )
    return checks


def _default_in_input_group() -> bool:
    try:
        import pwd

        username = pwd.getpwuid(os.getuid()).pw_name
        group = grp.getgrnam("input")
        return username in group.gr_mem or group.gr_gid in os.getgroups()
    except (KeyError, OSError):
        return False


def _hint(
    evars: dict[str, str], which_fn: Callable[[str], str | None] | None = None
) -> dict[str, str]:
    """Pick fix commands by detected package manager (fall back to apt)."""
    from shutil import which

    probe_which = which_fn or which
    for pm in ("dnf", "pacman", "apk", "apt"):
        if probe_which(pm):
            return _PACKAGE_HINTS["dnf" if pm == "dnf" else pm]
    return _PACKAGE_HINTS["apt"]


def report(checks: list[WizardCheck]) -> str:
    lines = ["GUI input wizard — ydotool readiness:"]
    for check in checks:
        mark = "OK  " if check.ok else "MISS"
        lines.append(f"  [{mark}] {check.name}: {check.detail}")
        if not check.ok and check.fix:
            lines.append(f"         fix: {check.fix}")
    ready = all(c.ok for c in checks)
    lines.append(
        "  => synthetic input READY" if ready else "  => synthetic input NOT ready (see fixes)"
    )
    return "\n".join(lines)
