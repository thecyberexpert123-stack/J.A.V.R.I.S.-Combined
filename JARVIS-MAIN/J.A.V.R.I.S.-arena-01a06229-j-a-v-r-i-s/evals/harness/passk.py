"""``pass^k`` reliability estimator shared by the eval drivers (ADR-0027).

τ-bench (Yao et al., arXiv:2406.12045, §3) defines ``pass^k`` as the chance
that *all* ``k`` i.i.d. trials of a task succeed, averaged across tasks. With
``c`` successful runs out of ``n`` per task, the unbiased estimate is

    pass^k = E_task[ C(c, k) / C(n, k) ]

``pass^1`` is the ordinary mean success rate, so a single-run session
(``n = 1``) reports exactly what the drivers reported before this module
existed. Stdlib only; lives in the harness, never in ``src/jarvis``.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from math import comb


def positive_int(text: str) -> int:
    """argparse type for ``--runs``: an integer >= 1, rejected before any case runs."""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer >= 1, got {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected an integer >= 1, got {value}")
    return value


def add_runs_argument(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--runs K`` option (default 1 = today's single pass)."""
    parser.add_argument(
        "--runs",
        type=positive_int,
        default=1,
        metavar="K",
        help=(
            "run every catalog case K times; a case passes only if all K runs pass "
            "and the summary reports pass^1..pass^K (default: 1)"
        ),
    )


def pass_hat_k(successes: int, runs: int, k: int) -> float:
    """Per-task ``C(c, k) / C(n, k)`` for ``c`` successes out of ``n`` runs."""
    if runs < 1:
        raise ValueError(f"runs must be >= 1, got {runs}")
    if not 1 <= k <= runs:
        raise ValueError(f"k must be within 1..{runs}, got {k}")
    if not 0 <= successes <= runs:
        raise ValueError(f"successes must be within 0..{runs}, got {successes}")
    return comb(successes, k) / comb(runs, k)


def suite_pass_hat(successes_per_task: Sequence[int], runs: int, k: int) -> float:
    """``pass^k`` averaged over tasks; ``0.0`` for an empty suite (nothing to claim)."""
    if not successes_per_task:
        return 0.0
    total = sum(pass_hat_k(c, runs, k) for c in successes_per_task)
    return total / len(successes_per_task)


def pass_hat_curve(successes_per_task: Sequence[int], runs: int) -> dict[str, float]:
    """``{"1": pass^1, ..., "<runs>": pass^runs}`` rounded to 4 dp (JSON-friendly keys)."""
    return {
        str(k): round(suite_pass_hat(successes_per_task, runs, k), 4) for k in range(1, runs + 1)
    }


def render_curve(curve: Mapping[str, float]) -> str:
    """One-line console rendering: ``pass^1=1.0000 pass^2=0.6667 ...``."""
    return " ".join(f"pass^{k}={value:.4f}" for k, value in curve.items())
