"""The assistant state machine and its legal transitions.

The eight-state model is adapted from the pattern published by the MIT-licensed
Open.Jarvis project (https://github.com/dmrr35/Open.Jarvis), which drives its UI
from an explicit runtime state stream. No source code was copied; the transition
table below is specific to this application.

Making the transitions explicit (rather than letting any state follow any other)
means an inconsistent UI is a caught bug instead of a visual glitch.
"""

from __future__ import annotations

from enum import Enum


class AssistantState(str, Enum):
    """Operational state of the assistant, as reflected by the HUD."""

    BOOTING = "BOOTING"
    STANDBY = "STANDBY"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"


#: Terminal-ish states reachable from anywhere: any subsystem may fail at any
#: time, and a running assistant may always be taken offline.
_ALWAYS_REACHABLE: frozenset[AssistantState] = frozenset(
    {AssistantState.ERROR, AssistantState.OFFLINE}
)

_TRANSITIONS: dict[AssistantState, frozenset[AssistantState]] = {
    AssistantState.BOOTING: frozenset({AssistantState.STANDBY}),
    AssistantState.STANDBY: frozenset({AssistantState.LISTENING, AssistantState.PROCESSING}),
    AssistantState.LISTENING: frozenset({AssistantState.PROCESSING, AssistantState.STANDBY}),
    # PROCESSING resolves to an action (EXECUTING), a reply (SPEAKING), or to
    # nothing at all (STANDBY). The third arm is real, not a shortcut: the
    # kernel's refusals, a declined prompt, a dictation handed back to the
    # input field, a lost connection and a completed handshake all end a
    # request without producing anything to say or do. Without it every one
    # of those left the HUD spinning in PROCESSING with no request in flight.
    AssistantState.PROCESSING: frozenset(
        {AssistantState.EXECUTING, AssistantState.SPEAKING, AssistantState.STANDBY}
    ),
    AssistantState.EXECUTING: frozenset({AssistantState.SPEAKING, AssistantState.STANDBY}),
    AssistantState.SPEAKING: frozenset({AssistantState.STANDBY, AssistantState.LISTENING}),
    # Recovery paths: an error is acknowledged back to standby; coming back
    # online replays the boot sequence so the UI is rebuilt from a known state.
    AssistantState.ERROR: frozenset({AssistantState.STANDBY, AssistantState.BOOTING}),
    # OFFLINE is "the agent is unavailable", not "the HUD is dead": telemetry
    # keeps running and the owner may retry the connection. A retry is a
    # request in flight (PROCESSING); success settles to STANDBY. The BOOTING
    # arm remains for a full re-initialisation.
    AssistantState.OFFLINE: frozenset(
        {AssistantState.BOOTING, AssistantState.PROCESSING, AssistantState.STANDBY}
    ),
}


def can_transition(current: AssistantState, target: AssistantState) -> bool:
    """Return whether moving from ``current`` to ``target`` is legal.

    Self-transitions are legal and idempotent, so repeated notifications of the
    same state are harmless.
    """
    if current is target:
        return True
    if target in _ALWAYS_REACHABLE:
        return True
    return target in _TRANSITIONS[current]


def allowed_targets(current: AssistantState) -> frozenset[AssistantState]:
    """Return every state legally reachable in one step from ``current``."""
    return _TRANSITIONS[current] | _ALWAYS_REACHABLE | {current}


class InvalidTransitionError(RuntimeError):
    """Raised when an illegal state transition is requested."""

    def __init__(self, current: AssistantState, target: AssistantState) -> None:
        super().__init__(
            f"Illegal assistant state transition {current.value} -> {target.value}. "
            f"Allowed: {sorted(state.value for state in allowed_targets(current))}"
        )
        self.current = current
        self.target = target
