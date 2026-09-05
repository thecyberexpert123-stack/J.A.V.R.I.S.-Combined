"""GUI backends: argv builders + output parsers per backend (ADR-0010).

Pure functions over the standard Runner — every GUI action is an argv-only
command, journaled like everything else. No shell, ever.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.execution.runner import ExecResult, Runner


class GuiBackendError(RuntimeError):
    """A backend command failed or returned unusable output."""


@dataclass(frozen=True)
class Window:
    id: str  # backend-specific window/con/address identifier
    title: str
    backend: str


def _ok(result: ExecResult, what: str) -> ExecResult:
    if not result.ok:
        raise GuiBackendError(
            f"{what} failed (exit {result.exit_code}): {result.stderr_tail[:200]}"
        )
    return result


# -- X11: wmctrl + xdotool -----------------------------------------------------


def wmctrl_list(runner: Runner) -> list[Window]:
    result = _ok(runner.run(["wmctrl", "-l"]), "wmctrl -l")
    windows: list[Window] = []
    for line in result.stdout_tail.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 4:
            windows.append(Window(id=parts[0], title=parts[3], backend="wmctrl"))
    return windows


def wmctrl_focus(runner: Runner, window_id: str) -> None:
    _ok(runner.run(["wmctrl", "-i", "-a", window_id]), "wmctrl -i -a")


def wmctrl_close(runner: Runner, window_id: str) -> None:
    _ok(runner.run(["wmctrl", "-i", "-c", window_id]), "wmctrl -i -c")


def xdotool_active_title(runner: Runner) -> str | None:
    result = runner.run(["xdotool", "getactivewindow", "getwindowname"])
    if not result.ok:
        return None  # no focused window (e.g. desktop focused) — honest None
    title = result.stdout_tail.strip()
    return title or None


def xdotool_type(runner: Runner, text: str) -> None:
    _ok(runner.run(["xdotool", "type", "--delay", "40", "--", text]), "xdotool type")


def xdotool_key(runner: Runner, combo: str) -> None:
    _ok(runner.run(["xdotool", "key", "--", combo]), "xdotool key")


def scrot_screenshot(runner: Runner, path: str) -> None:
    _ok(runner.run(["scrot", "-o", "-q", "90", path]), "scrot")


# -- i3 / sway IPC (JSON tree) ---------------------------------------------------


def _walk_i3_tree(node: object, out: list[Window], backend: str) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "dockarea":
        return  # i3bar and tray containers are not user windows
    if node.get("window") is not None and not node.get("nodes") and node.get("name"):
        out.append(
            Window(
                id=str(node.get("id", node.get("window"))),
                title=str(node.get("name", "")),
                backend=backend,
            )
        )
        if node.get("focused"):
            out[-1] = Window(id=out[-1].id, title=out[-1].title, backend=backend)
    for key in ("nodes", "floating_nodes"):
        for child in node.get(key, []) or []:
            _walk_i3_tree(child, out, backend)


def _focused_i3_title(node: object) -> str | None:
    if not isinstance(node, dict):
        return None
    if node.get("focused") and node.get("name"):
        return str(node["name"])
    for key in ("nodes", "floating_nodes"):
        for child in node.get(key, []) or []:
            found = _focused_i3_title(child)
            if found is not None:
                return found
    return None


def i3_list(runner: Runner, *, backend: str = "i3-msg") -> list[Window]:
    argv = ["swaymsg", "-t", "get_tree"] if backend == "swaymsg" else ["i3-msg", "-t", "get_tree"]
    result = _ok(runner.run(argv), f"{argv[0]} get_tree")
    try:
        tree = json.loads(result.stdout_tail)
    except json.JSONDecodeError as exc:
        raise GuiBackendError(f"{argv[0]} returned invalid JSON: {exc}") from exc
    windows: list[Window] = []
    _walk_i3_tree(tree, windows, backend)
    return windows


def i3_focused_title(runner: Runner, *, backend: str = "i3-msg") -> str | None:
    argv = ["swaymsg", "-t", "get_tree"] if backend == "swaymsg" else ["i3-msg", "-t", "get_tree"]
    result = _ok(runner.run(argv), f"{argv[0]} get_tree")
    try:
        tree = json.loads(result.stdout_tail)
    except json.JSONDecodeError as exc:
        raise GuiBackendError(f"{argv[0]} returned invalid JSON: {exc}") from exc
    return _focused_i3_title(tree)


def i3_focus_title(runner: Runner, title: str, *, backend: str = "i3-msg") -> None:
    argv = [
        "swaymsg" if backend == "swaymsg" else "i3-msg",
        f'[title="{title}"]',
        "focus",
    ]
    _ok(runner.run(argv), f"{argv[0]} focus by title")


def i3_close_title(runner: Runner, title: str, *, backend: str = "i3-msg") -> None:
    argv = [
        "swaymsg" if backend == "swaymsg" else "i3-msg",
        f'[title="{title}"]',
        "kill",
    ]
    _ok(runner.run(argv), f"{argv[0]} kill by title")


# -- Hyprland --------------------------------------------------------------------


def hyprland_list(runner: Runner) -> list[Window]:
    result = _ok(runner.run(["hyprctl", "-j", "clients"]), "hyprctl -j clients")
    try:
        clients = json.loads(result.stdout_tail)
    except json.JSONDecodeError as exc:
        raise GuiBackendError(f"hyprctl returned invalid JSON: {exc}") from exc
    if not isinstance(clients, list):
        raise GuiBackendError("hyprctl clients: unexpected payload")
    return [
        Window(id=str(c.get("address", "")), title=str(c.get("title", "")), backend="hyprctl")
        for c in clients
        if isinstance(c, dict)
    ]


def hyprland_focused_title(runner: Runner) -> str | None:
    result = _ok(runner.run(["hyprctl", "-j", "activewindow"]), "hyprctl -j activewindow")
    try:
        data = json.loads(result.stdout_tail)
    except json.JSONDecodeError:
        return None
    title = data.get("title") if isinstance(data, dict) else None
    return str(title) if title else None


def hyprland_focus(runner: Runner, title: str) -> None:
    _ok(runner.run(["hyprctl", "dispatch", "focuswindow", f"title:{title}"]), "hyprctl focuswindow")


def hyprland_close(runner: Runner, title: str) -> None:
    _ok(runner.run(["hyprctl", "dispatch", "closewindow", f"title:{title}"]), "hyprctl closewindow")


def grim_screenshot(runner: Runner, path: str) -> None:
    _ok(runner.run(["grim", path]), "grim")


# -- KDE / GNOME desktop integration ----------------------------------------------


def kdotool_list(runner: Runner) -> list[Window]:
    result = _ok(runner.run(["kdotool", "search", "--name", "."]), "kdotool search")
    windows: list[Window] = []
    for line in result.stdout_tail.splitlines():
        wid = line.strip()
        if not wid:
            continue
        named = runner.run(["kdotool", "getwindowname", wid])
        title = named.stdout_tail.strip() if named.ok else ""
        windows.append(Window(id=wid, title=title, backend="kdotool"))
    return windows


def kdotool_focus(runner: Runner, window_id: str) -> None:
    _ok(runner.run(["kdotool", "windowactivate", window_id]), "kdotool windowactivate")


def kdotool_active_title(runner: Runner) -> str | None:
    result = runner.run(["kdotool", "getactivewindowname"])
    if not result.ok:
        return None
    title = result.stdout_tail.strip()
    return title or None


def spectacle_screenshot(runner: Runner, path: str) -> None:
    _ok(
        runner.run(["spectacle", "-b", "-n", "-o", path]),
        "spectacle background capture",
    )


def gnome_screenshot(runner: Runner, path: str) -> None:
    _ok(
        runner.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell.Screenshot",
                "--object-path",
                "/org/gnome/Shell/Screenshot",
                "--method",
                "org.gnome.Shell.Screenshot.Screenshot",
                "true",
                "false",
                path,
            ]
        ),
        "GNOME Shell Screenshot via gdbus",
    )


# -- Wayland input: ydotool -------------------------------------------------------


def ydotool_type(runner: Runner, text: str) -> None:
    _ok(runner.run(["ydotool", "type", "--", text]), "ydotool type")


def ydotool_key(runner: Runner, combo: str) -> None:
    _ok(runner.run(["ydotool", "key", combo]), "ydotool key")


# -- shared ------------------------------------------------------------------------


def setsid_launch(argv_tail: Sequence[str]) -> tuple[str, ...]:
    """Detached spawn: setsid forks and exits immediately (no shell)."""
    return ("setsid", "--fork", *argv_tail)
