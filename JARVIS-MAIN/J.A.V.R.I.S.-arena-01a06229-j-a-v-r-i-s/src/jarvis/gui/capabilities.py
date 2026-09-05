"""Capability matrix: which GUI capability uses which backend (ADR-0010).

The matrix is the contract of `jarvis gui status`. `None` always carries a
reason — GUI support is honest per machine, never silently pretended.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.gui.atspi import atspi_available
from jarvis.gui.detect import GuiEnvironment, ydotool_socket

CAPABILITIES = (
    "windows",
    "launch",
    "focus",
    "type_text",
    "key",
    "screenshot",
    "close",
    "describe",
    "atspi",
)

# M9e: how an action reaches the machine. "api"/"wm" = OS-level interfaces
# (accessibility, window-manager IPC, portals, capture APIs); "injection" =
# synthetic input (xdotool/ydotool) — the last resort, consent-gated as always.
_PATH_BY_BACKEND = {
    "i3-msg": "wm",
    "swaymsg": "wm",
    "wmctrl": "wm",
    "hyprctl": "wm",
    "kdotool": "wm",
    "setsid": "api",
    "scrot": "api",
    "grim": "api",
    "spectacle": "api",
    "gdbus-gnome-screenshot": "api",
    "ollama-vision": "api",
    "pyatspi": "api",
    "xdotool": "injection",
    "ydotool": "injection",
}


@dataclass(frozen=True)
class CapabilityBinding:
    capability: str
    backend: str | None  # None = unavailable on this machine
    reason: str  # why, in plain words (for status output)
    path: str = "api"  # "api" | "injection" | "wm" (M9e disclosure)

    def __post_init__(self) -> None:
        if self.backend is not None and self.path not in ("api", "injection", "wm"):
            raise ValueError(f"unknown action path: {self.path}")


def _ydotool_ready(env: GuiEnvironment) -> bool:
    return env.has_tool("ydotool") and ydotool_socket().exists()


def available(env: GuiEnvironment) -> dict[str, CapabilityBinding]:
    """Resolve the matrix for THIS machine."""
    out: dict[str, CapabilityBinding] = {}
    t = env.has_tool

    if env.headless:
        for cap in CAPABILITIES:
            if cap == "describe":
                out[cap] = CapabilityBinding(
                    "describe", "ollama-vision", "needs a reachable Ollama vision model"
                )
            elif cap == "atspi":
                out[cap] = CapabilityBinding("atspi", None, "headless: no desktop tree")
            else:
                out[cap] = CapabilityBinding(cap, None, "headless: no display session")
        return out

    # launch is universal on graphical sessions (detached argv spawn).
    out["launch"] = CapabilityBinding("launch", "setsid", "detached process spawn", path="api")

    # window management backend per session/desktop
    if env.session_type == "x11":
        wm = (
            "i3-msg"
            if env.desktop == "i3" and t("i3-msg")
            else "swaymsg"
            if env.desktop == "sway" and t("swaymsg")
            else "wmctrl"
            if t("wmctrl")
            else None
        )
        input_backend = "xdotool" if t("xdotool") else None
        input_reason = "xdotool on X11" if input_backend else "xdotool not installed"
        shot = "scrot" if t("scrot") else None
    else:  # wayland
        if env.desktop == "hyprland" and t("hyprctl"):
            wm = "hyprctl"
        elif env.desktop == "sway" and t("swaymsg"):
            wm = "swaymsg"
        elif env.desktop == "kde" and t("kdotool"):
            wm = "kdotool"
        else:
            wm = None  # GNOME Wayland: no listing backend without AT-SPI/Shell eval
        input_backend = "ydotool" if _ydotool_ready(env) else None
        input_reason = (
            "ydotool via uinput"
            if input_backend
            else "ydotool needs the binary + a running ydotoold socket"
        )
        if env.desktop == "hyprland" and t("grim"):
            shot = "grim"
        elif env.desktop == "kde" and t("spectacle"):
            shot = "spectacle"
        elif t("grim"):
            shot = "grim"
        elif env.desktop == "gnome" and t("gdbus"):
            shot = "gdbus-gnome-screenshot"
        else:
            shot = None

    for cap in ("windows", "focus", "close"):
        out[cap] = CapabilityBinding(
            cap,
            wm,
            f"{wm} window control"
            if wm
            else f"no window-control backend for {env.desktop} on {env.session_type}",
            path=_PATH_BY_BACKEND.get(wm or "", "wm"),
        )
    if atspi_available():
        out["type_text"] = CapabilityBinding(
            "type_text",
            "atspi-editable",
            "API-first: AT-SPI EditableText on the focused object (no synthetic keys)",
            path="api",
        )
    else:
        out["type_text"] = CapabilityBinding(
            "type_text",
            input_backend,
            (
                f"injection via {input_backend} (install python3-pyatspi for the API path)"
                if input_backend
                else input_reason
            ),
            path="injection",
        )
    out["key"] = CapabilityBinding(
        "key",
        input_backend,
        (
            input_reason + " (no honest API path exists for key synthesis)"
            if input_backend
            else input_reason
        ),
        path="injection",
    )
    out["screenshot"] = CapabilityBinding(
        "screenshot", shot, f"{shot} capture" if shot else "no screenshot backend found"
    )
    out["describe"] = CapabilityBinding(
        "describe", "ollama-vision", "needs a reachable Ollama vision model"
    )
    out["atspi"] = CapabilityBinding(
        "atspi",
        "pyatspi",
        "accessibility tree via pyatspi (importability checked at call time)",
    )
    return out
