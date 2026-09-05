"""Guarded AT-SPI action invocation (ADR-0026 D1/D2): the unknown-app rung.

API-first control: locate a node by role+name in a target application's
accessibility tree and invoke the app's OWN published action ("click",
"press", "open", ...) — no synthetic input. The ADR-0022 walls bind here:
blocked applications are refused before their tree is read; password roles
are refused before any name is read; names are hygiened; walks are bounded.
Duck-typed like gui.atspi so tests inject stub trees without pyatspi.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from jarvis.desktop.guards import hygiene, is_blocked_app, is_password_role

MAX_DEPTH = 4
MAX_NODES = 256


class ActionRefused(RuntimeError):
    """A wall refused this action (ADR-0026 D2). Never a guess, never a retry."""


@dataclass(frozen=True)
class NodeFound:
    node: object
    role: str
    name: str


def _iter_children(node: Any) -> Iterable[Any]:
    """Yield a node's children.

    Real pyatspi Accessible objects expose children by index
    (``get_child_count``/``get_child_at_index``, camelCase ``getChildCount``
    on some bindings) and do NOT implement ``__iter__``; duck-typed test
    stubs typically do. Try the index protocol first, fall back to ``iter``.
    """
    try:
        get_count = getattr(node, "get_child_count", None) or getattr(node, "getChildCount", None)
        get_at = getattr(node, "get_child_at_index", None) or getattr(node, "getChildAtIndex", None)
        if callable(get_count) and callable(get_at):
            count = int(get_count())
            return [get_at(i) for i in range(max(0, count))]
        return list(iter(node))
    except Exception:
        return []


def find_node(
    desktop: Any,
    *,
    app: str,
    role: str,
    name: str,
) -> NodeFound:
    """Locate (app, role, name) through the walls; refuse or return NodeFound.

    Raises ActionRefused on a blocked application or a password-role match
    (before any name read); returns the first bounded-walk match.
    """
    want_app = app.strip().lower()
    want_role = role.strip().lower()
    want_name = name.strip().lower()
    if not want_app or not want_role or not want_name:
        raise ActionRefused("app, role and name must all be non-empty")
    if is_blocked_app(want_app):
        # wall 1: the subtree is never read at all
        raise ActionRefused(f"application '{hygiene(want_app)}' is on the blocked list")
    budget = {"nodes": 0}

    def visit(node: object, depth: int) -> NodeFound | None:
        if budget["nodes"] >= MAX_NODES or depth > MAX_DEPTH:
            return None
        budget["nodes"] += 1
        try:
            this_role = str(node.getRoleName()).strip().lower()  # type: ignore[attr-defined]
        except Exception:
            return None
        if is_password_role(this_role):
            # wall 2: password fields are never read, never actuated
            raise ActionRefused("password text fields are never actuated")
        try:
            this_name = hygiene(str(getattr(node, "name", "") or "")).lower()
        except Exception:
            this_name = ""
        if this_role == want_role and this_name == want_name:
            return NodeFound(node=node, role=this_role, name=this_name)
        for child in _iter_children(node):
            found = visit(child, depth + 1)
            if found is not None:
                return found
        return None

    for application in _iter_children(desktop):
        try:
            app_name = str(getattr(application, "name", "") or "").strip()
        except Exception:
            continue
        if app_name.lower() != want_app:
            continue
        found = visit(application, 1)
        if found is not None:
            return found
    raise ActionRefused(
        f"no node matching app={app!r} role={role!r} name={name!r} in the accessibility tree"
    )


def list_actions(node: object) -> list[str]:
    """The node's published action names via the AT-SPI Action interface."""
    try:
        action: Any = node.queryAction()  # type: ignore[attr-defined]
        count = int(action.get_n_actions())
        names = [str(action.getName(i)) for i in range(count)]
    except Exception as exc:
        raise ActionRefused(f"node publishes no readable actions: {exc}") from exc
    return names


def do_named_action(node: object, action: str) -> str:
    """Invoke a published action by name; returns the performed name."""
    wanted = action.strip().lower()
    if not wanted or len(wanted) > 40:
        raise ActionRefused("action name must be 1..40 chars")
    names = list_actions(node)
    published = [n.strip().lower() for n in names]
    if wanted not in published:
        listing = ", ".join(names) or "none"
        raise ActionRefused(f"action {action!r} not published by this node (published: {listing})")
    try:
        action_iface: Any = node.queryAction()  # type: ignore[attr-defined]
        index = [n.strip().lower() for n in names].index(wanted)
        performed = bool(action_iface.doAction(index))
    except ActionRefused:
        raise
    except Exception as exc:
        raise ActionRefused(f"the app refused the action: {exc}") from exc
    if not performed:
        raise ActionRefused("the app reported the action as not performed")
    return str(names[index])


def set_node_text(node: object, text: str) -> str:
    """API-first text write via EditableText on a located node (ADR-0010 style)."""
    if not text or len(text) > 200:
        raise ActionRefused("text must be 1..200 chars")
    if any(ord(ch) < 0x20 and ch not in "\t" for ch in text):
        raise ActionRefused("control characters are not allowed")
    try:
        editable: Any = node.queryEditableText()  # type: ignore[attr-defined]
        editable.setTextContents(text)
    except Exception as exc:
        raise ActionRefused(f"node does not accept text edits: {exc}") from exc
    return "text set via AT-SPI EditableText"
