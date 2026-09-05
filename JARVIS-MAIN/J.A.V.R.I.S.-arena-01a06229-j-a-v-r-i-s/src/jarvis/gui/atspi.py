"""AT-SPI accessibility access — optional read *and* action layer (ADR-0010, M9e).

Uses `pyatspi` when importable (distro package `python3-pyatspi`); absence is
an honest capability gap, never an error and never a blocker for other
backends. M9e adds the API-first *action* path: text entry via the
EditableText interface on the focused object — no synthetic keystrokes. Key
combination synthesis has no honest AT-SPI API and stays injection-only.
"""

from __future__ import annotations

import importlib.util
from typing import Any


def atspi_available() -> bool:
    try:
        return importlib.util.find_spec("pyatspi") is not None
    except (ImportError, ValueError):
        return False


def desktop_window_titles() -> tuple[list[str] | None, str]:
    """Guarded window titles (ADR-0022): blocked apps never appear at all.

    Contract unchanged from ADR-0010: (titles, reason); titles=None with a
    reason when unavailable. Since ADR-0022 the walk runs through the guard
    walls, so the GUI service cannot list/focus/type into a blocked app.
    """
    if not atspi_available():
        return None, "pyatspi not installed (distro package python3-pyatspi)"
    try:
        import pyatspi  # type: ignore[import-not-found]

        desktop = pyatspi.Registry.getDesktop(0)
        from jarvis.desktop.read import guarded_titles

        titles, reason = guarded_titles(desktop)
        return titles, reason
    except Exception as exc:
        return None, f"pyatspi present but unavailable: {exc}"


_MAX_DEPTH = 12


def _find_focused_editable(obj: object, state_focused: int, depth: int = 0) -> object | None:
    """Depth-limited search for the focused editable-text object."""
    if depth > _MAX_DEPTH:
        return None
    try:
        state = obj.getState()  # type: ignore[attr-defined]
        if not state.contains(state_focused):
            return None
    except Exception:
        return None
    try:
        obj.queryEditableText()  # type: ignore[attr-defined]
        return obj  # implements EditableText and holds focus
    except Exception:
        pass
    try:
        children: Any = obj  # pyatspi nodes are iterable at runtime
        for child in children:
            found = _find_focused_editable(child, state_focused, depth + 1)
            if found is not None:
                return found
    except Exception:
        pass
    return None


def set_focused_text(text: str) -> tuple[bool, str]:
    """API-first text entry: EditableText on the focused object (no keystrokes).

    Returns (ok, detail). Never raises; absence/failure is an honest gap so
    the caller can refuse or route elsewhere knowingly.
    """
    if not atspi_available():
        return False, "pyatspi not installed (distro package python3-pyatspi)"
    try:
        import pyatspi

        desktop = pyatspi.Registry.getDesktop(0)
        for app in desktop:
            for frame in app:
                target = _find_focused_editable(frame, pyatspi.STATE_FOCUSED)
                if target is not None:
                    editable: Any = target
                    editable.queryEditableText().setTextContents(text)
                    return True, "set via AT-SPI EditableText (API-first, no synthetic keys)"
        return False, "no focused editable-text object found in the accessibility tree"
    except Exception as exc:
        return False, f"pyatspi present but the API action failed: {exc}"
