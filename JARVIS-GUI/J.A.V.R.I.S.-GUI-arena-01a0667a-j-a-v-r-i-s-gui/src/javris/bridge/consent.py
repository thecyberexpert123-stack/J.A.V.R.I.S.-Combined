"""The hybrid consent policy: two independent gates, different in kind.

The kernel's safety tiers are authoritative and this front-end never widens
them. But tiers answer "how much authority does this need?", not "can this be
taken back?", and those are different questions. Live probing of kernel 1.20.0
made the gap concrete:

    do remove the file /tmp/x   ->  tier 1, executed immediately,
                                    undo.status = "unavailable"

That is the kernel behaving exactly as designed -- ``rm`` of a user-owned file
is a user-level action, and requiring system-level consent for it would be
wrong. It is nonetheless an irreversible deletion that happened with no
confirmation, because the GUI asked for none.

So this module implements two gates:

**Gate 1 -- kernel authority (mandatory, kernel-owned).** When the kernel
refuses a T2 action pending consent, the owner is asked. This gate cannot be
disabled, and the GUI can never satisfy it on the owner's behalf. T3 is never
offered at all.

**Gate 2 -- reversibility (advisory, GUI-owned, owner-configurable).** Before
sending a mutation the GUI previews it, and if the kernel's own ``undo`` field
says the action cannot be taken back, the owner is shown the plan first. This
gate adds *friction*, never *authority*: clearing it does not add ``allow`` to
anything, and a T2 action that clears it still meets gate 1 afterwards.

The distinction matters and is preserved everywhere in the UI: gate 1 says
"the kernel will not do this without you", gate 2 says "this cannot be undone".
Conflating them would teach the owner that both are the same kind of warning,
which would devalue the one that carries real authority.

Gate 2 is driven entirely by the kernel's own ``undo.status``. There is no
hardcoded list of dangerous-looking words -- pattern-matching on request text
would be security theatre, and would disagree with the kernel about what a
request actually does.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .plan import Plan


class ConfirmPolicy(str, Enum):
    """How much GUI-side friction the owner wants before a mutation.

    The kernel's own gate (gate 1) applies under every setting; these values
    only change gate 2.
    """

    #: Ask before anything the kernel reports as not undoable. The default: it
    #: catches irreversible T1 actions while staying silent for reversible ones.
    IRREVERSIBLE = "IRREVERSIBLE"
    #: Ask before every mutation, undoable or not. For operators who want a
    #: beat before any change at all.
    ALWAYS = "ALWAYS"
    #: Never add GUI-side friction; defer entirely to the kernel's tiers.
    KERNEL_ONLY = "KERNEL_ONLY"


class Gate(str, Enum):
    """Which gate is asking, and therefore what the question means."""

    #: The kernel refused pending explicit consent. Authority-bearing.
    KERNEL_CONSENT = "KERNEL_CONSENT"
    #: The GUI is pausing because the action cannot be undone. Advisory.
    REVERSIBILITY = "REVERSIBILITY"


@dataclass(frozen=True, slots=True)
class ConfirmRequest:
    """A pending question for the owner."""

    gate: Gate
    #: The verbatim request text. What the owner approves is what gets sent.
    request: str
    #: The previewed plan, when one was obtained.
    plan: Plan | None = None
    #: The kernel's hint, for the consent gate.
    hint: str = ""
    tier: int | None = None

    @property
    def is_authority(self) -> bool:
        """True when clearing this actually grants the kernel new permission."""
        return self.gate is Gate.KERNEL_CONSENT

    @property
    def headline(self) -> str:
        """The one line stating what is being asked, and why."""
        if self.gate is Gate.KERNEL_CONSENT:
            label = f"tier-{self.tier} " if self.tier is not None else ""
            return f"This {label}action needs your explicit consent before the kernel will run it."
        return "This action cannot be undone."


def needs_reversibility_confirmation(plan: Plan, policy: ConfirmPolicy) -> bool:
    """Whether gate 2 should stop this plan before it is sent.

    Returns False for an unmatched request: there is nothing to run, so there
    is nothing to confirm, and the owner should be shown the kernel's
    refusal-to-guess instead of a confirmation dialog.
    """
    if policy is ConfirmPolicy.KERNEL_ONLY:
        return False
    if plan.unmatched or not plan.steps:
        return False
    if policy is ConfirmPolicy.ALWAYS:
        return True
    return plan.irreversible


def reversibility_summary(plan: Plan) -> str:
    """One line explaining the reversibility position, in the kernel's terms."""
    if plan.undo_reason:
        return plan.undo_reason
    if plan.irreversible:
        return "The kernel does not offer a way to reverse this."
    return "This action can be reversed."
