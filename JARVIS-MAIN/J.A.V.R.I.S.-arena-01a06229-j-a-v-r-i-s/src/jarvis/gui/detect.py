"""GUI environment detection: session type, desktop, available tools (ADR-0010).

Detection is read-only and side-effect free; a fully headless machine is a
normal, honestly-reported state — never an error.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

_TOOLS = (
    "xdotool",
    "wmctrl",
    "scrot",
    "ydotool",
    "ydotoold",
    "grim",
    "spectacle",
    "gdbus",
    "kdotool",
    "i3-msg",
    "swaymsg",
    "hyprctl",
    "gnome-screenshot",
)

_Which = Callable[[str], str | None]

# XDG_CURRENT_DESKTOP tokens we normalize (first token, lowercased variants).
_DESKTOP_ALIASES = {"kde": "kde", "kde-full": "kde", "plasma": "kde", "ubuntu": "ubuntu"}


@dataclass(frozen=True)
class GuiEnvironment:
    session_type: str  # "x11" | "wayland" | "headless"
    desktop: str  # normalized: gnome, kde, i3, sway, hyprland, xfce, unknown, ...
    display: str  # $DISPLAY (x11)
    wayland_display: str  # $WAYLAND_DISPLAY (wayland)
    tools: tuple[str, ...]  # relevant tools found on PATH

    @property
    def headless(self) -> bool:
        return self.session_type == "headless"

    def has_tool(self, name: str) -> bool:
        return name in self.tools

    def to_json_dict(self) -> dict[str, object]:
        return {
            "session_type": self.session_type,
            "desktop": self.desktop,
            "display": self.display,
            "wayland_display": self.wayland_display,
            "tools": list(self.tools),
        }


def _normalize_desktop(raw: str) -> str:
    token = raw.split(":")[0].strip().lower()
    if not token:
        return "unknown"
    return _DESKTOP_ALIASES.get(token, token)


def probe(
    env: Mapping[str, str] | None = None,
    which_fn: _Which | None = None,
) -> GuiEnvironment:
    """Detect the GUI environment from process env + PATH tool probes."""
    source = env if env is not None else dict(os.environ)
    which = which_fn if which_fn is not None else shutil.which

    wayland = source.get("WAYLAND_DISPLAY", "").strip()
    x11 = source.get("DISPLAY", "").strip()
    if wayland:
        session_type = "wayland"
    elif x11:
        session_type = "x11"
    else:
        session_type = "headless"

    # Compositor identification: explicit env beats XDG_CURRENT_DESKTOP.
    if source.get("HYPRLAND_INSTANCE_SIGNATURE"):
        desktop = "hyprland"
    elif source.get("SWAYSOCK"):
        desktop = "sway"
    elif source.get("I3SOCK"):
        desktop = "i3"
    else:
        desktop = _normalize_desktop(source.get("XDG_CURRENT_DESKTOP", ""))
        if desktop in ("ubuntu",) and session_type == "wayland":
            desktop = "gnome"  # ubuntu:GNOME sessions report themselves as GNOME

    tools = tuple(name for name in _TOOLS if which(name))
    return GuiEnvironment(
        session_type=session_type,
        desktop=desktop,
        display=x11,
        wayland_display=wayland,
        tools=tools,
    )


def ydotool_socket(env: Mapping[str, str] | None = None) -> Path:
    """Default ydotoold socket path (respects $YDOTOOL_SOCKET)."""
    source = env if env is not None else dict(os.environ)
    raw = source.get("YDOTOOL_SOCKET", "").strip()
    if raw:
        return Path(raw)
    return Path("/tmp/.ydotool_socket")
