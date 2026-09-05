"""Structured interpretation of a kernel plan and its blast radius.

``jarvis_preview`` returns considerably more than a list of step descriptions:
it reports the exact argv that would run, the safety tier, whether root is
required, whether the network is touched, which paths are affected, and --
crucially -- whether the action can be undone. The bridge's first version
flattened all of that into a single console line, which threw away precisely
the information an owner needs in order to consent meaningfully.

This module turns those payloads into value objects. It is pure: no Qt, no
I/O, no policy about what the UI does with the result. The one judgement it
does encode is :attr:`Plan.irreversible`, because "can this be taken back?" is
a property of the kernel's own ``undo.status`` field and should be read the
same way everywhere.

Verified against live payloads from kernel 1.20.0; see ``docs/BACKEND-BRIDGE.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: ``undo.status`` values the kernel uses. Anything else is treated as unknown,
#: and unknown is treated as irreversible -- the safe reading.
#: The kernel's sentinel in the ``playbook`` field when nothing matched. It is
#: not a playbook name and must never be displayed as one.
UNMATCHED_SENTINEL = "<unmatched>"

UNDO_AVAILABLE = "available"
UNDO_NONE_NEEDED = "none_needed"
UNDO_UNAVAILABLE = "unavailable"

#: Cap on how many steps or paths are modelled from one payload. A plan longer
#: than this is a plan no one is really reviewing, and the renderer should not
#: be asked to lay out an unbounded list.
MAX_STEPS = 64
MAX_PATHS = 64


@dataclass(frozen=True, slots=True)
class Step:
    """One command the kernel would run."""

    description: str
    #: The literal argv. Shown verbatim: this is the ground truth of what runs,
    #: and it is the only field that cannot be paraphrased away.
    argv: tuple[str, ...] = ()
    tier: int | None = None
    requires_root: bool = False

    @property
    def command_line(self) -> str:
        """The argv rendered for display.

        Deliberately *not* shell-quoted: the kernel never uses a shell, and
        quoting would suggest this string could be pasted into one and mean the
        same thing. Tokens are joined for reading, not for re-execution.
        """
        return " ".join(self.argv)


@dataclass(frozen=True, slots=True)
class BlastRadius:
    """What a plan would touch, as reported by the kernel."""

    commands: tuple[str, ...] = ()
    max_tier: int = 0
    network: bool = False
    requires_root: bool = False
    paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    """A previewed course of action, ready to review."""

    #: The matched playbook id, e.g. ``pkg.upgrade``. Empty when unmatched.
    playbook: str = ""
    tier: int | None = None
    steps: tuple[Step, ...] = ()
    blast: BlastRadius = field(default_factory=BlastRadius)
    undo_status: str = ""
    undo_reason: str = ""
    #: Set when the kernel could not map the request to any playbook.
    unmatched: bool = False
    #: The kernel's refusal-to-guess message, when unmatched.
    error: str = ""
    #: The kernel's hint, which for an unmatched request lists known playbooks.
    hint: str = ""

    @property
    def irreversible(self) -> bool:
        """True when the kernel does not offer a way back.

        ``none_needed`` counts as reversible: the kernel is saying the action is
        idempotent, not that it is destructive. Anything unrecognised counts as
        irreversible, because guessing optimistically about reversibility is the
        one error that cannot be corrected afterwards.
        """
        if not self.steps:
            return False
        return self.undo_status not in (UNDO_AVAILABLE, UNDO_NONE_NEEDED)

    @property
    def is_empty(self) -> bool:
        """True when there is nothing to show."""
        return not self.steps and not self.unmatched


def _as_str_tuple(value: Any, limit: int) -> tuple[str, ...]:
    """Coerce a JSON list into a bounded tuple of strings."""
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value[:limit])


def parse_blast_radius(raw: Any) -> BlastRadius:
    """Build a :class:`BlastRadius` from the kernel's ``blast_radius`` object."""
    if not isinstance(raw, dict):
        return BlastRadius()

    # `paths` is an object keyed by kind (e.g. {"absolute": [...]}) rather than
    # a flat list, so the values are collected across every kind.
    paths: list[str] = []
    raw_paths = raw.get("paths")
    if isinstance(raw_paths, dict):
        for group in raw_paths.values():
            paths.extend(_as_str_tuple(group, MAX_PATHS))
    elif isinstance(raw_paths, list):
        paths.extend(_as_str_tuple(raw_paths, MAX_PATHS))

    max_tier = raw.get("max_tier")
    return BlastRadius(
        commands=_as_str_tuple(raw.get("commands"), MAX_PATHS),
        max_tier=max_tier if isinstance(max_tier, int) else 0,
        network=bool(raw.get("network")),
        requires_root=bool(raw.get("requires_root")),
        paths=tuple(paths[:MAX_PATHS]),
    )


def parse_step(raw: Any) -> Step | None:
    """Build a :class:`Step`, or None when the entry is not usable."""
    if not isinstance(raw, dict):
        return None
    tier = raw.get("tier")
    description = str(raw.get("description") or "").strip()
    argv = _as_str_tuple(raw.get("argv"), MAX_PATHS)
    if not description and not argv:
        return None
    return Step(
        # Fall back to the argv so a step is never rendered as a blank row.
        description=description or " ".join(argv),
        argv=argv,
        tier=tier if isinstance(tier, int) else None,
        requires_root=bool(raw.get("requires_root")),
    )


def parse_plan(payload: dict[str, Any]) -> Plan:
    """Build a :class:`Plan` from a ``jarvis_preview`` payload.

    Handles the unmatched case explicitly. When the kernel cannot map a request
    it returns ``isError`` with an empty step list and an anti-hallucination
    message -- that is the kernel refusing to guess, which is a feature, and it
    must not be rendered as a crash.
    """
    preview = payload.get("preview")
    preview = preview if isinstance(preview, dict) else {}

    raw_steps = preview.get("steps")
    steps: list[Step] = []
    if isinstance(raw_steps, list):
        for entry in raw_steps[:MAX_STEPS]:
            step = parse_step(entry)
            if step is not None:
                steps.append(step)

    undo = preview.get("undo")
    undo = undo if isinstance(undo, dict) else {}

    tier = preview.get("tier")
    error = str(preview.get("error") or "").strip()

    playbook = str(preview.get("playbook") or "")
    if playbook == UNMATCHED_SENTINEL:
        # The kernel's placeholder, not a name. Blanked so no part of the UI
        # can present "<unmatched>" as though it were a matched playbook.
        playbook = ""

    return Plan(
        playbook=playbook,
        tier=tier if isinstance(tier, int) else None,
        steps=tuple(steps),
        blast=parse_blast_radius(payload.get("blast_radius")),
        undo_status=str(undo.get("status") or ""),
        undo_reason=str(undo.get("reason") or ""),
        # No steps *and* an error message means "I will not guess", which is
        # distinct from a plan that legitimately has nothing to do.
        unmatched=not steps and bool(error),
        error=error,
        hint=str(preview.get("hint") or "").strip(),
    )


def known_playbooks(hint: str) -> tuple[str, ...]:
    """Extract the playbook ids from an unmatched-request hint.

    The kernel answers an unmapped request with ``Known playbooks: fs.list,
    fs.read, ...``. Presenting those as a list is far more useful than printing
    one long truncated sentence, so the ids are pulled out for the UI.

    Returns an empty tuple when the hint is not in that form -- the caller then
    shows the hint text verbatim rather than a mangled parse of it.
    """
    marker = "known playbooks:"
    lowered = hint.lower()
    index = lowered.find(marker)
    if index < 0:
        return ()
    tail = hint[index + len(marker) :]
    names: list[str] = []
    for chunk in tail.split(","):
        name = chunk.strip().rstrip(".").strip()
        # Playbook ids are dotted lowercase identifiers; the sentence may run on
        # past the list, so anything not matching that shape ends it.
        if name and name.replace(".", "").replace("_", "").isalnum():
            names.append(name)
        elif names:
            break
    return tuple(names[:MAX_STEPS])
