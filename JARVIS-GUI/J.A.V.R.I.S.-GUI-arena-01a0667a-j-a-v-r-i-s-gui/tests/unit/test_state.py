"""Tests for the assistant state machine.

The point of an explicit transition table is that illegal moves are caught, so
these tests assert the refusals as strictly as the permissions.
"""

from __future__ import annotations

import pytest

from javris.state import (
    AssistantState,
    InvalidTransitionError,
    allowed_targets,
    can_transition,
)


@pytest.mark.parametrize("state", list(AssistantState))
def test_self_transition_is_always_legal(state: AssistantState) -> None:
    assert can_transition(state, state)


@pytest.mark.parametrize("state", list(AssistantState))
def test_error_and_offline_are_reachable_from_anywhere(state: AssistantState) -> None:
    assert can_transition(state, AssistantState.ERROR)
    assert can_transition(state, AssistantState.OFFLINE)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AssistantState.BOOTING, AssistantState.STANDBY),
        (AssistantState.STANDBY, AssistantState.LISTENING),
        (AssistantState.LISTENING, AssistantState.PROCESSING),
        (AssistantState.PROCESSING, AssistantState.EXECUTING),
        (AssistantState.EXECUTING, AssistantState.SPEAKING),
        (AssistantState.SPEAKING, AssistantState.STANDBY),
        (AssistantState.ERROR, AssistantState.STANDBY),
        (AssistantState.OFFLINE, AssistantState.BOOTING),
    ],
)
def test_nominal_cycle_is_legal(current: AssistantState, target: AssistantState) -> None:
    assert can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        # Cannot speak or act before understanding the request.
        (AssistantState.STANDBY, AssistantState.SPEAKING),
        (AssistantState.LISTENING, AssistantState.EXECUTING),
        # Boot must complete before anything else happens.
        (AssistantState.BOOTING, AssistantState.LISTENING),
        (AssistantState.BOOTING, AssistantState.PROCESSING),
        # Cannot go straight back to work from a fault without acknowledgement.
        (AssistantState.ERROR, AssistantState.PROCESSING),
        (AssistantState.OFFLINE, AssistantState.STANDBY),
        # Processing must resolve to an action or a reply.
        (AssistantState.PROCESSING, AssistantState.STANDBY),
    ],
)
def test_illegal_transitions_are_refused(current: AssistantState, target: AssistantState) -> None:
    assert not can_transition(current, target)


def test_allowed_targets_includes_self_and_fault_states() -> None:
    targets = allowed_targets(AssistantState.STANDBY)
    assert AssistantState.STANDBY in targets
    assert AssistantState.ERROR in targets
    assert AssistantState.OFFLINE in targets
    assert AssistantState.LISTENING in targets
    assert AssistantState.SPEAKING not in targets


def test_every_state_has_a_transition_entry() -> None:
    for state in AssistantState:
        assert allowed_targets(state)


def test_every_state_can_reach_standby_eventually() -> None:
    """No state may be a dead end: the HUD must always be recoverable."""
    reachable = {AssistantState.STANDBY}
    changed = True
    while changed:
        changed = False
        for state in AssistantState:
            if state in reachable:
                continue
            if allowed_targets(state) & reachable:
                reachable.add(state)
                changed = True
    assert reachable == set(AssistantState)


def test_invalid_transition_error_reports_alternatives() -> None:
    error = InvalidTransitionError(AssistantState.BOOTING, AssistantState.SPEAKING)
    message = str(error)
    assert "BOOTING -> SPEAKING" in message
    assert "STANDBY" in message
    assert error.current is AssistantState.BOOTING
    assert error.target is AssistantState.SPEAKING
