"""Typed plan artifacts (pipeline stage PLAN output, consumed by APPROVE/EXECUTE)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from jarvis.execution.runner import ExecResult, Runner
from jarvis.safety.tiers import Tier
from jarvis.system.models import MachineProfile

Params = dict[str, object]


class TaskStatus(str, Enum):
    REFUSED = "refused"
    RUNNING = "running"
    DRY_RUN = "dry_run"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    UNDONE = "undone"


class UndoStatus(str, Enum):
    NONE_NEEDED = "none_needed"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PlannedStep:
    """One concrete, guarded command within a plan."""

    description: str
    argv: tuple[str, ...]
    tier: Tier
    requires_root: bool = False
    timeout_s: float = 300.0
    optional: bool = False
    extra_env: Mapping[str, str] | None = None
    stdin_text: str = ""  # piped to the process when non-empty (e.g. tee)
    detach: bool = False  # DEVNULL stdios; for spawns that outlive the command


@dataclass(frozen=True)
class CheckSpec:
    """A post-condition probe: argv must (or must not) exit zero."""

    name: str
    argv: tuple[str, ...]
    expect_zero: bool = True


@dataclass(frozen=True)
class Verification:
    """Aggregated post-condition result (pipeline stage VERIFY)."""

    ok: bool
    detail: str
    checks: tuple[tuple[str, bool, str], ...] = ()  # (name, passed, detail)


@dataclass(frozen=True)
class UndoPlan:
    """Reverse path for a mutating task, built BEFORE execution (never after)."""

    status: UndoStatus
    reason: str = ""
    steps: tuple[PlannedStep, ...] = ()
    verify_checks: tuple[CheckSpec, ...] = ()
    params: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Refusal:
    """A request refused before execution (no journal-less refusals exist)."""

    reason: str
    hint: str = ""


class _Build(Protocol):
    def __call__(self, params: Params, profile: MachineProfile) -> list[PlannedStep]: ...


class _Verify(Protocol):
    def __call__(
        self,
        params: Params,
        profile: MachineProfile,
        runner: Runner,
        step_results: Sequence[ExecResult | None] | None,
    ) -> Verification: ...


class _Undo(Protocol):
    def __call__(self, params: Params, profile: MachineProfile) -> UndoPlan: ...


@dataclass(frozen=True)
class Playbook:
    """One deterministic capability: NL match -> guarded build -> verify -> undo.

    Home: planner.models (ADR-0016) so catalog family modules can construct
    playbooks without importing the engine module (no import cycles).
    """

    id: str
    description: str
    tier: Tier
    match: Callable[[str], Params | None]
    build: _Build
    verify: _Verify
    undo: _Undo
