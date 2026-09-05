"""The guarded reader (ADR-0022): bounded, hygiened, audited AT-SPI walks.

Duck-typed on purpose: nodes only need ``getRoleName()``, ``name``, and
iteration — so the guards are unit-tested against stub trees without
pyatspi, exactly like the ADR-0010 tests inject a fake ``pyatspi`` module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.desktop.guards import (
    REDACTED_NAME,
    WITHHELD_APP,
    WITHHELD_PASSWORD,
    hygiene,
    is_blocked_app,
    is_password_role,
    is_sensitive_name,
)
from jarvis.journal.sqlite import state_dir
from jarvis.safety.tiers import SafetyRefusal

MAX_DEPTH = 4
MAX_NODES = 512
WINDOW_ROLES = frozenset({"frame", "dialog", "window"})


class _Budget(Exception):
    """Internal: raised when the node budget is exhausted."""


@dataclass(frozen=True)
class ReadResult:
    lines: tuple[str, ...]
    apps_blocked: tuple[str, ...]
    roles_withheld: int
    names_redacted: int
    nodes_read: int
    truncated: bool


def guarded_desktop_walk(
    desktop: Iterable[Any], *, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES
) -> ReadResult:
    """Walk the desktop tree through the three walls (ADR-0022 D2/D3)."""
    lines: list[str] = []
    apps_blocked: list[str] = []
    counters = {"roles": 0, "redacted": 0, "nodes": 0}
    state = {"truncated": False}

    def visit(node: Any, depth: int) -> None:
        if counters["nodes"] >= max_nodes:
            state["truncated"] = True
            raise _Budget()
        counters["nodes"] += 1
        try:
            role = str(node.getRoleName())
        except Exception:
            lines.append("[unreadable node]")
            return
        if is_password_role(role):
            # wall 2: withheld before the name is ever read
            counters["roles"] += 1
            lines.append(WITHHELD_PASSWORD)
            return
        name = ""
        try:
            name = hygiene(str(getattr(node, "name", "") or ""))
        except Exception:
            name = ""
        if is_sensitive_name(name):
            # wall 3: read, then redacted before display/persist
            counters["redacted"] += 1
            display: str = REDACTED_NAME
        else:
            display = name or "(unnamed)"
        lines.append(f"{'  ' * depth}{role}: {display}")
        if depth >= max_depth:
            return
        try:
            children: Iterable[Any] = node
            for child in children:
                visit(child, depth + 1)
        except _Budget:
            raise
        except Exception:
            lines.append(f"{'  ' * depth}[unreadable subtree]")

    for app in desktop:
        try:
            app_name = hygiene(str(getattr(app, "name", "") or ""))
        except Exception:
            lines.append("[unreadable application node]")
            continue
        if is_blocked_app(app_name):
            # wall 1: the subtree is never read at all
            apps_blocked.append(app_name)
            lines.append(WITHHELD_APP.format(name=app_name))
            continue
        try:
            visit(app, 1)
        except _Budget:
            break

    if state["truncated"]:
        lines.append("[node budget exhausted — truncated]")
    return ReadResult(
        lines=tuple(lines),
        apps_blocked=tuple(apps_blocked),
        roles_withheld=counters["roles"],
        names_redacted=counters["redacted"],
        nodes_read=counters["nodes"],
        truncated=state["truncated"],
    )


def guarded_titles(desktop: Iterable[Any]) -> tuple[list[str], str]:
    """Guarded window titles for the ADR-0010 contract: (titles, reason).

    Blocked applications contribute nothing; sensitive titles render as a
    withheld marker; unavailability stays the caller's honest-reason path.
    """
    titles: list[str] = []
    blocked = 0
    for app in desktop:
        try:
            app_name = str(getattr(app, "name", "") or "")
        except Exception:
            continue
        if is_blocked_app(app_name):
            blocked += 1
            continue
        try:
            for window in app:
                try:
                    role = str(window.getRoleName())
                except Exception:
                    continue
                if is_password_role(role):
                    continue
                if role not in WINDOW_ROLES:
                    continue
                raw = str(getattr(window, "name", "") or "")
                if is_sensitive_name(raw):
                    titles.append("(withheld: sensitive title)")
                    continue
                titles.append(hygiene(raw) or "(untitled)")
        except Exception:
            continue
    reason = "guarded accessibility tree"
    if blocked:
        reason += f" ({blocked} application(s) withheld by the blocklist)"
    return titles, reason


class DesktopAudit:
    """Content-free per-operation audit ledger (ADR-0022 D4).

    `<state>/desktop/ledger.jsonl` records timestamps, the read source,
    blocked-app identifiers (blocklist names, never user content), counts,
    and the truncated flag. No tree content is ever persisted.
    """

    def __init__(self, state: Path | None = None) -> None:
        self._dir = (state_dir() if state is None else state) / "desktop"

    @property
    def path(self) -> Path:
        return self._dir / "ledger.jsonl"

    def record_read(self, result: ReadResult, *, source: str) -> None:
        if source not in {"cli", "gui"}:
            raise SafetyRefusal("audit source must be cli or gui")
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self._append(
            {
                "ts": stamp,
                "kind": "read",
                "source": source,
                "apps_blocked": list(result.apps_blocked),
                "nodes_read": result.nodes_read,
                "roles_withheld": result.roles_withheld,
                "names_redacted": result.names_redacted,
                "truncated": result.truncated,
            }
        )

    def _append(self, entry: dict[str, object]) -> None:
        import json

        self._dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    def entries(self) -> list[dict[str, object]]:
        import json

        if not self.path.exists():
            return []
        out: list[dict[str, object]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # tolerant parse: a torn tail line never blocks a read
        return out

    def stats(self) -> dict[str, object]:
        entries = [e for e in self.entries() if e.get("kind") == "read"]

        def _as_int(value: object) -> int:
            return int(value) if isinstance(value, int) else 0

        blocked = 0
        for entry in entries:
            blocked_apps = entry.get("apps_blocked")
            blocked += len(blocked_apps) if isinstance(blocked_apps, (list, tuple)) else 0
        return {
            "reads": len(entries),
            "apps_blocked_total": blocked,
            "roles_withheld_total": sum(_as_int(e.get("roles_withheld")) for e in entries),
            "names_redacted_total": sum(_as_int(e.get("names_redacted")) for e in entries),
            "truncated_reads": sum(1 for e in entries if e.get("truncated")),
            "last_read": entries[-1].get("ts") if entries else None,
            "ledger": str(self.path),
        }


def read_desktop(
    *, source: str = "cli", state: Path | None = None
) -> tuple[ReadResult | None, str]:
    """Availability → guarded walk → audit. (None, honest reason) if unavailable."""
    from jarvis.gui.atspi import atspi_available

    if not atspi_available():
        return None, "pyatspi not installed (distro package python3-pyatspi)"
    try:
        import pyatspi  # type: ignore[import-not-found]

        desktop = pyatspi.Registry.getDesktop(0)
        result = guarded_desktop_walk(desktop)
        DesktopAudit(state).record_read(result, source=source)
        return result, "guarded accessibility tree"
    except Exception as exc:
        return None, f"pyatspi present but unavailable: {exc}"
