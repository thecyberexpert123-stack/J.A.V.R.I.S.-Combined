"""Approval policy (pipeline stage APPROVE).

Maps the safety tier of a plan to a decision, honoring three modes:
- interactive TTY: T0/T1 proceed automatically, T2 asks, T3 refused;
- `--yes` (explicit non-interactive consent): T0-T2 proceed, T3 refused;
- non-TTY without `--yes`: T2 refused rather than guessed (never hangs).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from jarvis.planner.models import PlannedStep
from jarvis.safety.tiers import Tier


class ApprovalRefused(RuntimeError):
    """The approval gate refused to proceed."""


def plan_summary(steps: Sequence[PlannedStep]) -> str:
    lines = []
    for i, step in enumerate(steps, 1):
        root = " (root)" if step.requires_root else ""
        lines.append(f"  {i}. [{step.tier.name}]{root} {step.description}")
        lines.append(f"       $ {' '.join(step.argv)}")
    return "\n".join(lines)


class ApprovalPolicy:
    def __init__(self, yes: bool = False, silent: bool = False, stdin=None) -> None:
        self._yes = yes
        self._silent = silent
        self._stdin = sys.stdin if stdin is None else stdin

    def decide(self, tier: Tier, steps: Sequence[PlannedStep]) -> None:
        """Raise ApprovalRefused unless execution may proceed. Returns silently otherwise."""
        if tier == Tier.T3:
            raise ApprovalRefused("T3 (destructive/irreversible) actions are refused by policy")
        if tier <= Tier.T1:
            return
        # T2: system-level, needs explicit consent.
        if self._yes:
            if not self._silent:
                print(
                    f"[jarvis] T2 action auto-approved via --yes ({len(steps)} step/s)",
                    flush=True,
                )
            return
        if not self._stdin.isatty():
            raise ApprovalRefused(
                "T2 (system-level) action requires explicit approval; "
                "re-run with --yes to consent non-interactively"
            )
        print("JARVIS plans the following system-level action:\n" + plan_summary(steps))
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            raise ApprovalRefused("declined by user")
