"""Tests for the hybrid consent policy.

The property that matters most is asserted first and repeatedly: the GUI's own
gate adds *friction*, never *authority*. Clearing it must never cause ``allow``
to be sent.
"""

from __future__ import annotations

from javris.bridge.consent import (
    ConfirmPolicy,
    ConfirmRequest,
    Gate,
    needs_reversibility_confirmation,
    reversibility_summary,
)
from javris.bridge.plan import Plan, Step

#: A path appearing inside captured kernel payloads. These tests never
#: touch the filesystem; this is payload text, not a file they open.
SAMPLE_PATH = "/tmp/x"  # noqa: S108 - literal from a recorded kernel response

IRREVERSIBLE = Plan(
    playbook="fs.remove",
    tier=1,
    steps=(Step(description="delete /tmp/x", argv=("rm", "-f", SAMPLE_PATH)),),
    undo_status="unavailable",
    undo_reason="deletion is not reversible",
)

REVERSIBLE = Plan(
    playbook="svc.restart",
    tier=2,
    steps=(Step(description="restart unit ssh", argv=("systemctl", "restart", "ssh")),),
    undo_status="none_needed",
    undo_reason="a restart is idempotent",
)

UNMATCHED = Plan(unmatched=True, error="I will not guess", hint="Known playbooks: fs.list.")

EMPTY = Plan()


# -- the reversibility gate ------------------------------------------------


def test_irreversible_tier_one_action_is_confirmed_by_default() -> None:
    # The gap this gate exists to close: the kernel runs this without asking.
    assert needs_reversibility_confirmation(IRREVERSIBLE, ConfirmPolicy.IRREVERSIBLE) is True


def test_reversible_action_is_not_confirmed_by_default() -> None:
    # Asking about everything would train the owner to dismiss the prompt,
    # which would weaken the gate that actually matters.
    assert needs_reversibility_confirmation(REVERSIBLE, ConfirmPolicy.IRREVERSIBLE) is False


def test_always_policy_confirms_a_reversible_action_too() -> None:
    assert needs_reversibility_confirmation(REVERSIBLE, ConfirmPolicy.ALWAYS) is True


def test_kernel_only_policy_never_adds_gui_friction() -> None:
    for plan in (IRREVERSIBLE, REVERSIBLE):
        assert needs_reversibility_confirmation(plan, ConfirmPolicy.KERNEL_ONLY) is False


def test_unmatched_request_is_never_confirmed() -> None:
    # Nothing would run, so a confirmation dialog would be asking about
    # nothing. The owner should see the kernel's refusal-to-guess instead.
    for policy in ConfirmPolicy:
        assert needs_reversibility_confirmation(UNMATCHED, policy) is False


def test_a_plan_with_no_steps_is_never_confirmed() -> None:
    for policy in ConfirmPolicy:
        assert needs_reversibility_confirmation(EMPTY, policy) is False


# -- the gates are different in kind ---------------------------------------


def test_only_the_kernel_gate_carries_authority() -> None:
    # This is the distinction the whole design rests on. The reversibility gate
    # is an acknowledgement; the kernel gate is a grant of permission.
    kernel = ConfirmRequest(gate=Gate.KERNEL_CONSENT, request="upgrade", tier=2)
    reversibility = ConfirmRequest(gate=Gate.REVERSIBILITY, request="rm", tier=1)
    assert kernel.is_authority is True
    assert reversibility.is_authority is False


def test_the_two_gates_say_different_things() -> None:
    kernel = ConfirmRequest(gate=Gate.KERNEL_CONSENT, request="upgrade", tier=2)
    reversibility = ConfirmRequest(gate=Gate.REVERSIBILITY, request="rm", tier=1)
    assert "consent" in kernel.headline.lower()
    assert "tier-2" in kernel.headline
    assert "undone" in reversibility.headline.lower()
    assert kernel.headline != reversibility.headline


def test_kernel_headline_without_a_tier_does_not_invent_one() -> None:
    request = ConfirmRequest(gate=Gate.KERNEL_CONSENT, request="something")
    assert "tier-" not in request.headline


def test_the_request_text_is_carried_verbatim() -> None:
    # The owner approves the exact words that will be sent.
    text = "  remove   the file /tmp/x  "
    assert ConfirmRequest(gate=Gate.REVERSIBILITY, request=text).request == text


# -- summaries -------------------------------------------------------------


def test_summary_prefers_the_kernels_own_words() -> None:
    assert reversibility_summary(IRREVERSIBLE) == "deletion is not reversible"


def test_summary_falls_back_when_the_kernel_gave_no_reason() -> None:
    plan = Plan(steps=(Step(description="x", argv=("x",)),), undo_status="unavailable")
    assert "reverse" in reversibility_summary(plan).lower()


def test_summary_for_a_reversible_plan_says_so() -> None:
    plan = Plan(steps=(Step(description="x", argv=("x",)),), undo_status="available")
    assert "can be reversed" in reversibility_summary(plan)


def test_every_policy_has_a_stable_wire_name() -> None:
    # These names are persisted and typed by the owner at the console; renaming
    # one silently would change behaviour rather than fail.
    assert {policy.value for policy in ConfirmPolicy} == {
        "IRREVERSIBLE",
        "ALWAYS",
        "KERNEL_ONLY",
    }


# -- the plan must belong to the request it is shown beside -----------------


def test_a_confirm_request_carries_its_own_plan() -> None:
    # Regression guard for a defect found by live testing: under the
    # kernel-only policy no preview runs before a mutation, so a plan cached
    # from an earlier command was rendered beside an unrelated consent prompt.
    # The owner would have been reading one command while approving another.
    request = ConfirmRequest(gate=Gate.KERNEL_CONSENT, request="upgrade", plan=IRREVERSIBLE)
    assert request.plan is IRREVERSIBLE

    # A prompt with no matching plan carries none, rather than a stale one.
    without = ConfirmRequest(gate=Gate.KERNEL_CONSENT, request="upgrade", plan=None)
    assert without.plan is None
    assert without.headline, "a prompt must still explain itself without a plan"
