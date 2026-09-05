"""System snapshot preflight (ADR-0008).

Best-effort snapshot creation before T2+ tasks via snapper (preferred) or
timeshift. Honest degradation: whatever happens is reported precisely and
never blocks an approved task — the user decides with full information.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from jarvis.execution.runner import Runner

_SNAPSHOT_TIMEOUT_S = 120.0
_Which = Callable[[str], str | None]


@dataclass(frozen=True)
class SnapshotResult:
    """Outcome of one snapshot attempt."""

    status: str  # "created" | "unavailable" | "failed"
    tool: str  # "snapper" | "timeshift" | "none"
    detail: str

    def note(self) -> str:
        if self.status == "created":
            return f"snapshot created via {self.tool} ({self.detail})"
        if self.status == "unavailable":
            return (
                "no snapshot tool available "
                "(install/configure snapper or timeshift for system-level "
                "rollback points); proceeding with targeted backups only"
            )
        return f"snapshot attempt failed ({self.tool}): {self.detail}"


class SnapshotManager:
    def __init__(
        self,
        runner: Runner,
        which: _Which | None = None,
    ) -> None:
        self._runner = runner
        self._which = which if which is not None else shutil.which

    def _tools(self) -> list[str]:
        present = []
        for tool in ("snapper", "timeshift"):
            found = self._which(tool)
            if found:
                present.append(tool)
        return present

    def create(self, label: str) -> SnapshotResult:
        tools = self._tools()
        if not tools:
            return SnapshotResult("unavailable", "none", "no snapper/timeshift on PATH")
        for tool in tools:
            argv: Sequence[str]
            if tool == "snapper":
                argv = (
                    "snapper",
                    "create",
                    "--description",
                    f"jarvis: {label}",
                    "--cleanup-algorithm",
                    "number",
                )
            else:
                argv = (
                    "timeshift",
                    "--create",
                    "--scripted",
                    "--comments",
                    f"jarvis: {label}",
                )
            result = self._runner.run(
                list(argv), requires_root=True, timeout_s=_SNAPSHOT_TIMEOUT_S, echo=False
            )
            if result.ok:
                detail = (result.stdout_tail or result.stderr_tail).strip().splitlines()
                return SnapshotResult("created", tool, detail[-1][:80] if detail else "ok")
        last = result
        return SnapshotResult(
            "failed",
            str(tools[-1]),
            (last.stderr_tail or f"exit {last.exit_code}").strip()[:120],
        )
