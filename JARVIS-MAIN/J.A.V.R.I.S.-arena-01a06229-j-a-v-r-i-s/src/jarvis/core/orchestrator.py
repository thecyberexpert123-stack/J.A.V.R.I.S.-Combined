"""Task orchestration: the pipeline SENSE→GROUND→PLAN→APPROVE→EXECUTE→VERIFY.

Owns the task lifecycle and the kill-switch. Nothing executes anywhere else:
all real work flows through here so that journaling, tier gating, revalidation,
and interrupt handling cannot be bypassed (PLAN §4.1, §4.2).
"""

from __future__ import annotations

import json
import re
import signal
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from jarvis.core.fingerprint import MachineProfile
from jarvis.execution.runner import ExecResult, Runner
from jarvis.journal.sqlite import Journal, state_dir
from jarvis.planner.models import (
    CheckSpec,
    PlannedStep,
    TaskStatus,
    UndoPlan,
    UndoStatus,
    Verification,
)
from jarvis.planner.playbooks import PLAYBOOKS, Playbook, match_intent
from jarvis.safety.approval import ApprovalPolicy, ApprovalRefused
from jarvis.safety.paths import classify_for_edit
from jarvis.safety.snapshots import SnapshotManager
from jarvis.safety.tiers import SafetyRefusal, Tier, check_argv, check_removal_allowed
from jarvis.system.models import InvalidInputError, UnsupportedError

_TASK_ID_RE = re.compile(r"^[0-9a-f]{12}$")

# argv prefixes that remove packages — undo steps get the protected-set check.
_REMOVE_PREFIXES = (
    ("apt-get", "remove"),
    ("dnf", "remove"),
    ("pacman", "-Rs"),
    ("zypper", "remove"),
    ("apk", "del"),
)


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class TaskOutcome:
    """Complete, serializable result of one orchestrated task."""

    playbook_id: str
    status: TaskStatus
    task_id: str | None = None
    tier: int = 0
    steps: list[dict[str, object]] = field(default_factory=list)
    verification: Verification | None = None
    undo_status: UndoStatus | None = None
    undo_reason: str = ""
    error: str = ""
    hint: str = ""
    snapshot_note: str = ""
    rolled_back: bool = False
    rollback_task_id: str = ""

    def exit_code(self) -> int:
        match self.status:
            case TaskStatus.SUCCEEDED | TaskStatus.DRY_RUN | TaskStatus.UNDONE:
                return 0
            case TaskStatus.INTERRUPTED:
                return 130
            case TaskStatus.REFUSED:
                return 2
            case _:
                return 1

    def to_json_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "playbook": self.playbook_id,
            "tier": self.tier,
            "status": self.status.value,
            "steps": self.steps,
            "verification": None
            if self.verification is None
            else {
                "ok": self.verification.ok,
                "detail": self.verification.detail,
                "checks": [
                    {"name": n, "passed": p, "detail": d} for n, p, d in self.verification.checks
                ],
            },
            "undo": None
            if self.undo_status is None
            else {"status": self.undo_status.value, "reason": self.undo_reason},
            "error": self.error,
            "hint": self.hint,
            "snapshot": self.snapshot_note or None,
        }


class Orchestrator:
    def __init__(
        self,
        profile: MachineProfile,
        journal: Journal,
        runner: Runner,
        policy: ApprovalPolicy,
        echo: bool = True,
        snapshot_manager: SnapshotManager | None = None,
        auto_rollback: bool = False,
        cautious_ok: bool = False,
    ) -> None:
        self._profile = profile
        self._journal = journal
        self._runner = runner
        self._policy = policy
        self._echo = echo
        self._auto_rollback = auto_rollback
        self._cautious_ok = cautious_ok
        self._snapshots = snapshot_manager or SnapshotManager(runner)
        self._interrupted = False
        self._prev_handlers: dict[int, object] = {}
        self._last_error = ""

    # -- kill-switch -------------------------------------------------------
    def _on_signal(self, signum: int, _frame: object) -> None:
        self._interrupted = True
        self._runner.terminate_current()

    def _install_handlers(self) -> None:
        self._interrupted = False
        self._last_error = ""
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._prev_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, self._on_signal)

    def _restore_handlers(self) -> None:
        for sig, handler in self._prev_handlers.items():
            signal.signal(sig, cast("signal._HANDLER", handler))
        self._prev_handlers.clear()

    # -- cautious mode (M7) ---------------------------------------------------
    def _cautious_active(self) -> bool:
        return (state_dir() / "cautious").exists()

    def _cautious_block(self, tier: int) -> str | None:
        """Refusal reason when cautious mode gates a T2+ action, else None."""
        if tier < int(Tier.T2) or self._cautious_ok or not self._cautious_active():
            return None
        return (
            "cautious mode is ON (early-days guard): T2+ actions are blocked. "
            'Review the plan (jarvis do "..." --preview), then either pass '
            "--cautious-ok for this one action or turn the guard off: jarvis cautious off"
        )

    def _maybe_auto_rollback(self, task_id: str) -> tuple[bool, str]:
        """Best-effort automatic reversal of a failed consented task (M7).

        Reuses undo() end-to-end — artifact rebuild, kernel revalidation
        (check_argv + _revalidate_undo_step), verification — under the consent
        already given to the original task (skip_consent), because prompting
        mid-failure would strand partial state.
        """
        try:
            rollback = self.undo(task_id, skip_consent=True)
        except Exception as exc:
            self._last_error = f"auto-rollback error: {exc}"
            return False, ""
        if rollback.status is TaskStatus.SUCCEEDED:
            return True, rollback.task_id or ""
        return False, ""

    # -- main entry --------------------------------------------------------
    def run_intent(self, text: str, *, dry_run: bool = False) -> TaskOutcome:
        try:
            matched = match_intent(text)
        except InvalidInputError as exc:
            return TaskOutcome(
                playbook_id="<unmatched>",
                status=TaskStatus.REFUSED,
                error=f"invalid input: {exc}",
            )
        if matched is None:
            # M9b: installed, receipt-verified skill packs extend matching with
            # new phrasings for EXISTING playbooks only — the kernel decides
            # argv and tier exactly as before; packs add vocabulary, not power.
            from jarvis.planner.skills import match_skill

            matched = match_skill(text)
        if matched is None:
            known = ", ".join(pb.id for pb in PLAYBOOKS)
            return TaskOutcome(
                playbook_id="<unmatched>",
                status=TaskStatus.REFUSED,
                error=(
                    "I cannot map this request to a known playbook and I will not guess "
                    "(anti-hallucination policy)."
                ),
                hint=f"Known playbooks: {known}",
            )
        playbook, params = matched

        try:
            steps = playbook.build(params, self._profile)
        except UnsupportedError as exc:
            return TaskOutcome(
                playbook_id=playbook.id,
                status=TaskStatus.FAILED,
                tier=int(playbook.tier),
                error=f"unsupported on this machine: {exc}",
            )
        except InvalidInputError as exc:
            return self._refused_no_journal(playbook, f"invalid input: {exc}")
        except SafetyRefusal as exc:
            return self._refused_no_journal(playbook, str(exc))

        for step in steps:
            try:
                check_argv(step.argv)
            except SafetyRefusal as exc:
                return self._refused_no_journal(playbook, f"static safety check failed: {exc}")

        undo_plan = playbook.undo(params, self._profile)

        if dry_run:
            if self._echo:
                print("[dry-run] plan (nothing executed, nothing journaled):")
                for i, step in enumerate(steps, 1):
                    print(f"  {i}. {step.description}\n       $ {' '.join(step.argv)}")
                extra = f" — {undo_plan.reason}" if undo_plan.reason else ""
                print(f"  undo: {undo_plan.status.value}{extra}")
            return TaskOutcome(
                playbook_id=playbook.id,
                status=TaskStatus.DRY_RUN,
                tier=max(int(playbook.tier), max(int(s.tier) for s in steps)),
                undo_status=undo_plan.status,
                undo_reason=undo_plan.reason,
                steps=[_step_summary(i, s) for i, s in enumerate(steps)],
            )

        tier = max(int(playbook.tier), max(int(s.tier) for s in steps))
        cautious_reason = self._cautious_block(tier)
        if cautious_reason is not None:
            return self._refuse_journaled(text, playbook, params, cautious_reason, steps, tier)
        try:
            self._policy.decide(Tier(tier), steps)
        except ApprovalRefused as exc:
            return self._refuse_journaled(text, playbook, params, str(exc), steps, tier)

        task_id = _new_task_id()
        self._journal.begin_task(task_id, text, playbook.id, tier, params, self._profile.to_dict())
        snapshot_note = self._preflight_snapshot(task_id, tier, playbook.id)

        results, status = self._execute(task_id, steps)
        verification: Verification | None = None
        error = self._last_error
        if status is None:  # all required steps succeeded -> VERIFY stage
            try:
                verification = playbook.verify(params, self._profile, self._runner, results)
            except Exception as exc:
                verification = Verification(ok=False, detail=f"verification error: {exc}")
            status = TaskStatus.SUCCEEDED if verification.ok else TaskStatus.FAILED
            if not verification.ok:
                error = f"verification failed: {verification.detail}"

        if (
            int(playbook.tier) >= int(Tier.T1)
            and undo_plan.status is UndoStatus.AVAILABLE
            and status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.INTERRUPTED)
        ):
            self._journal.store_undo(task_id, _undo_payload(undo_plan))
        rolled_back, rollback_task_id = False, ""
        if (
            self._auto_rollback
            and status in (TaskStatus.FAILED, TaskStatus.INTERRUPTED)
            and self._journal.get_undo(task_id) is not None
        ):
            rolled_back, rollback_task_id = self._maybe_auto_rollback(task_id)
        self._journal.finish_task(task_id, status.value)

        return TaskOutcome(
            task_id=task_id,
            playbook_id=playbook.id,
            status=status,
            tier=tier,
            steps=self._journal.steps_for_task(task_id),
            verification=verification,
            undo_status=undo_plan.status,
            undo_reason=undo_plan.reason,
            error=error,
            snapshot_note=snapshot_note,
            rolled_back=rolled_back,
            rollback_task_id=rollback_task_id,
        )

    def run_plan(
        self,
        request: str,
        parts: Sequence[tuple[Playbook, dict[str, object]]],
        *,
        explanation: str = "",
        provider_label: str = "llm",
        dry_run: bool = False,
    ) -> TaskOutcome:
        """Execute a validated multi-part plan (LLM-proposed, kernel-disposed).

        Parts are (playbook, params) pairs already normalized by the planner;
        building them here re-applies every deterministic check. One composite
        journal task; the undo reverses parts last-first.
        """
        if not parts:
            return TaskOutcome(playbook_id="plan", status=TaskStatus.REFUSED, error="empty plan")
        all_steps: list[PlannedStep] = []
        slices: list[tuple[int, int]] = []
        for idx, (playbook, params) in enumerate(parts, 1):
            try:
                steps = playbook.build(params, self._profile)
            except UnsupportedError as exc:
                return TaskOutcome(
                    playbook_id="plan",
                    status=TaskStatus.FAILED,
                    error=f"part {idx} ({playbook.id}) unsupported on this machine: {exc}",
                )
            except InvalidInputError as exc:
                return TaskOutcome(
                    playbook_id="plan",
                    status=TaskStatus.REFUSED,
                    error=f"plan part {idx} ({playbook.id}): invalid input: {exc}",
                )
            except SafetyRefusal as exc:
                return TaskOutcome(
                    playbook_id="plan",
                    status=TaskStatus.REFUSED,
                    error=f"plan part {idx} ({playbook.id}): {exc}",
                )
            slices.append((len(all_steps), len(all_steps) + len(steps)))
            all_steps.extend(steps)
        for step in all_steps:
            try:
                check_argv(step.argv)
            except SafetyRefusal as exc:
                return TaskOutcome(
                    playbook_id="plan",
                    status=TaskStatus.REFUSED,
                    error=f"static safety check failed: {exc}",
                )

        undo_plan = _composite_undo(
            [playbook.undo(params, self._profile) for playbook, params in parts],
            [playbook.id for playbook, _ in parts],
        )
        tier = max(int(s.tier) for s in all_steps)

        if dry_run:
            if self._echo:
                print("[dry-run] plan (nothing executed, nothing journaled):")
                if explanation:
                    print(f"  explanation: {explanation}")
                for i, step in enumerate(all_steps, 1):
                    print(f"  {i}. {step.description}\n       $ {' '.join(step.argv)}")
                extra = f" \u2014 {undo_plan.reason}" if undo_plan.reason else ""
                print(f"  undo: {undo_plan.status.value}{extra}")
            return TaskOutcome(
                playbook_id="plan",
                status=TaskStatus.DRY_RUN,
                tier=tier,
                undo_status=undo_plan.status,
                undo_reason=undo_plan.reason,
                steps=[_step_summary(i, s) for i, s in enumerate(all_steps)],
            )

        plan_tier = max(int(s.tier) for s in all_steps)
        cautious_reason = self._cautious_block(plan_tier)
        if cautious_reason is not None:
            block_id = _new_task_id()
            self._journal.begin_task(
                block_id,
                request[:300],
                f"plan/{provider_label}",
                plan_tier,
                {
                    "intents": [playbook.id for playbook, _ in parts],
                    "explanation": explanation[:200],
                },
                self._profile.to_dict(),
            )
            self._journal.finish_task(block_id, TaskStatus.REFUSED.value)
            return TaskOutcome(
                playbook_id="plan",
                status=TaskStatus.REFUSED,
                task_id=block_id,
                tier=plan_tier,
                steps=[_step_summary(i, s) for i, s in enumerate(all_steps)],
                error=cautious_reason,
            )
        try:
            self._policy.decide(Tier(plan_tier), all_steps)
        except ApprovalRefused as exc:
            task_id = _new_task_id()
            self._journal.begin_task(
                task_id,
                request[:300],
                f"plan/{provider_label}",
                tier,
                {
                    "intents": [playbook.id for playbook, _ in parts],
                    "explanation": explanation[:200],
                },
                self._profile.to_dict(),
            )
            self._journal.finish_task(task_id, TaskStatus.REFUSED.value)
            return TaskOutcome(
                playbook_id="plan",
                status=TaskStatus.REFUSED,
                task_id=task_id,
                tier=tier,
                error=str(exc),
            )

        task_id = _new_task_id()
        self._journal.begin_task(
            task_id,
            request[:300],
            f"plan/{provider_label}",
            tier,
            {
                "intents": [playbook.id for playbook, _ in parts],
                "explanation": explanation[:200],
            },
            self._profile.to_dict(),
        )
        snapshot_note = self._preflight_snapshot(task_id, tier, "plan")

        results, terminal = self._execute(task_id, all_steps)
        verification: Verification | None = None
        error = self._last_error
        if terminal is None:
            checks: list[tuple[str, bool, str]] = []
            details = []
            all_ok = True
            for (playbook, params), (a, b) in zip(parts, slices, strict=True):
                part_v = playbook.verify(params, self._profile, self._runner, results[a:b])
                all_ok = all_ok and part_v.ok
                checks.extend(part_v.checks)
                details.append(part_v.detail)
            verification = Verification(
                ok=all_ok, detail="; ".join(details)[:400], checks=tuple(checks)
            )
            terminal = TaskStatus.SUCCEEDED if all_ok else TaskStatus.FAILED
            if not all_ok:
                error = f"verification failed: {verification.detail}"

        if (
            tier >= int(Tier.T1)
            and undo_plan.status is UndoStatus.AVAILABLE
            and terminal in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.INTERRUPTED)
        ):
            self._journal.store_undo(task_id, _undo_payload(undo_plan))
        rolled_back, rollback_task_id = False, ""
        if (
            self._auto_rollback
            and terminal in (TaskStatus.FAILED, TaskStatus.INTERRUPTED)
            and self._journal.get_undo(task_id) is not None
        ):
            rolled_back, rollback_task_id = self._maybe_auto_rollback(task_id)
        self._journal.finish_task(task_id, terminal.value)

        return TaskOutcome(
            task_id=task_id,
            playbook_id="plan",
            status=terminal,
            tier=tier,
            steps=self._journal.steps_for_task(task_id),
            verification=verification,
            undo_status=undo_plan.status,
            undo_reason=undo_plan.reason,
            error=error,
            snapshot_note=snapshot_note,
            rolled_back=rolled_back,
            rollback_task_id=rollback_task_id,
        )

    # -- undo --------------------------------------------------------------
    def undo(
        self, original_task_id: str, *, dry_run: bool = False, skip_consent: bool = False
    ) -> TaskOutcome:
        if not _TASK_ID_RE.match(original_task_id):
            return TaskOutcome(
                playbook_id="undo",
                status=TaskStatus.REFUSED,
                error=f"malformed task id {original_task_id!r}",
            )
        artifact = self._journal.get_undo(original_task_id)
        if artifact is None:
            return TaskOutcome(
                playbook_id="undo",
                status=TaskStatus.REFUSED,
                error=f"no undo artifact for task {original_task_id}",
            )
        if artifact["status"] != "available":
            return TaskOutcome(
                playbook_id="undo",
                status=TaskStatus.REFUSED,
                error=(
                    f"undo for task {original_task_id} is {artifact['status']!r}, "
                    "not available (already applied?)"
                ),
            )
        original = self._journal.get_task(original_task_id)
        if original is None:
            return TaskOutcome(
                playbook_id="undo", status=TaskStatus.REFUSED, error="original task missing"
            )
        if str(original["status"]) == "undone":
            return TaskOutcome(
                playbook_id="undo",
                status=TaskStatus.REFUSED,
                error=f"task {original_task_id} is already undone",
            )

        try:
            steps, verify_checks, tier = _rebuild_undo_steps(artifact["payload"])
        except (KeyError, TypeError, ValueError) as exc:
            return TaskOutcome(
                playbook_id="undo",
                status=TaskStatus.REFUSED,
                error=f"undo artifact failed validation: {exc}",
            )
        for step in steps:
            try:
                check_argv(step.argv)
                _revalidate_undo_step(step)
            except SafetyRefusal as exc:
                return TaskOutcome(
                    playbook_id="undo",
                    status=TaskStatus.REFUSED,
                    error=f"undo artifact failed safety revalidation: {exc}",
                )

        if dry_run:
            if self._echo:
                print("[dry-run] undo plan (nothing executed):")
                for i, step in enumerate(steps, 1):
                    print(f"  {i}. {step.description}\n       $ {' '.join(step.argv)}")
            return TaskOutcome(
                playbook_id="undo",
                status=TaskStatus.DRY_RUN,
                tier=tier,
                steps=[_step_summary(i, s) for i, s in enumerate(steps)],
            )

        if not skip_consent:
            try:
                self._policy.decide(Tier(tier), steps)
            except ApprovalRefused as exc:
                return TaskOutcome(playbook_id="undo", status=TaskStatus.REFUSED, error=str(exc))

        undo_task_id = _new_task_id()
        self._journal.begin_task(
            undo_task_id,
            f"undo of {original_task_id}",
            "undo",
            tier,
            {"original_task": original_task_id},
            self._profile.to_dict(),
        )
        _results, status = self._execute(undo_task_id, steps)
        verification: Verification | None = None
        error = self._last_error
        if status is None:
            verification = self._run_verify_checks(verify_checks)
            status = TaskStatus.SUCCEEDED if verification.ok else TaskStatus.FAILED
            if not verification.ok:
                error = f"undo verification failed: {verification.detail}"

        if status is TaskStatus.SUCCEEDED:
            self._journal.mark_undo_applied(original_task_id, undo_task_id)
            self._journal.mark_undone(original_task_id)

        self._journal.finish_task(undo_task_id, status.value)
        return TaskOutcome(
            task_id=undo_task_id,
            playbook_id="undo",
            status=status,
            tier=tier,
            steps=self._journal.steps_for_task(undo_task_id),
            verification=verification,
            error=error,
        )

    # -- shared execution loop ------------------------------------------------
    def _execute(
        self, task_id: str, steps: Sequence[PlannedStep]
    ) -> tuple[list[ExecResult | None], TaskStatus | None]:
        """Run steps with journaling. Returns (results, None) when all required
        steps succeeded, else (results, terminal_status)."""
        self._install_handlers()
        results: list[ExecResult | None] = []
        terminal: TaskStatus | None = None
        try:
            for seq, step in enumerate(steps):
                if self._interrupted or terminal is not None:
                    self._journal.record_step(
                        task_id,
                        seq,
                        step.description,
                        list(step.argv),
                        step.requires_root,
                        int(step.tier),
                        "skipped",
                    )
                    results.append(None)
                    continue
                try:
                    res = self._runner.run(
                        step.argv,
                        requires_root=step.requires_root,
                        timeout_s=step.timeout_s,
                        extra_env=step.extra_env,
                        echo=self._echo,
                        stdin_text=step.stdin_text,
                        detach=step.detach,
                    )
                except Exception as exc:
                    self._journal.record_step(
                        task_id,
                        seq,
                        step.description,
                        list(step.argv),
                        step.requires_root,
                        int(step.tier),
                        "failed",
                        stderr_tail=str(exc),
                    )
                    results.append(None)
                    if not step.optional:
                        terminal = TaskStatus.FAILED
                        self._last_error = f"step {seq + 1} failed to start: {exc}"
                    continue

                step_ok = res.ok
                self._journal.record_step(
                    task_id,
                    seq,
                    step.description,
                    list(step.argv),
                    step.requires_root,
                    int(step.tier),
                    "succeeded" if step_ok else "failed",
                    exit_code=res.exit_code,
                    stdout_tail=res.stdout_tail,
                    stderr_tail=res.stderr_tail,
                )
                results.append(res)
                if step_ok:
                    continue
                if res.exit_code < 0:  # terminated by signal
                    terminal = TaskStatus.INTERRUPTED
                elif not step.optional:
                    terminal = TaskStatus.FAILED
                    self._last_error = (
                        f"step {seq + 1} ({step.description}) failed with exit code {res.exit_code}"
                    )
            return results, terminal
        finally:
            self._restore_handlers()

    # -- helpers -----------------------------------------------------------
    def _run_verify_checks(self, checks: Sequence[CheckSpec]) -> Verification:
        results = []
        all_ok = True
        for spec in checks:
            res = self._runner.run(list(spec.argv), requires_root=False, timeout_s=60, echo=False)
            passed = (res.exit_code == 0) if spec.expect_zero else (res.exit_code != 0)
            all_ok = all_ok and passed
            results.append((spec.name, passed, res.stdout_tail or res.stderr_tail or "ok"))
        return Verification(
            ok=all_ok,
            detail="all post-conditions hold" if all_ok else "post-condition(s) failed",
            checks=tuple(results),
        )

    def _refused_no_journal(self, playbook: Playbook, reason: str) -> TaskOutcome:
        return TaskOutcome(playbook_id=playbook.id, status=TaskStatus.REFUSED, error=reason)

    def _refuse_journaled(
        self,
        text: str,
        playbook: Playbook,
        params: dict[str, object],
        reason: str,
        steps: Sequence[PlannedStep],
        tier: int | None = None,
    ) -> TaskOutcome:
        effective = tier if tier is not None else int(playbook.tier)
        task_id = _new_task_id()
        self._journal.begin_task(
            task_id, text, playbook.id, effective, params, self._profile.to_dict()
        )
        for seq, step in enumerate(steps):
            self._journal.record_step(
                task_id,
                seq,
                step.description,
                list(step.argv),
                step.requires_root,
                int(step.tier),
                "skipped",
            )
        self._journal.finish_task(task_id, TaskStatus.REFUSED.value)
        return TaskOutcome(
            task_id=task_id,
            playbook_id=playbook.id,
            status=TaskStatus.REFUSED,
            tier=effective,
            error=reason,
        )

    def _preflight_snapshot(self, task_id: str, tier: int, label: str) -> str:
        """Attempt a snapshot for T2+ tasks; always honest, never blocking."""
        if tier < int(Tier.T2):
            return ""
        snap = self._snapshots.create(f"task {task_id}: {label}")
        self._journal.set_meta(
            task_id,
            "snapshot",
            json.dumps({"status": snap.status, "tool": snap.tool, "detail": snap.detail}),
        )
        return snap.note()


# --------------------------------------------------------------------------
# module-level helpers
# --------------------------------------------------------------------------


def _step_summary(seq: int, step: PlannedStep) -> dict[str, object]:
    return {
        "seq": seq,
        "description": step.description,
        "argv": list(step.argv),
        "requires_root": step.requires_root,
        "tier": int(step.tier),
        "status": "planned",
    }


def _undo_payload(plan: UndoPlan) -> dict[str, object]:
    return {
        "reason": plan.reason,
        "tier": int(max(step.tier for step in plan.steps)) if plan.steps else int(Tier.T1),
        "steps": [
            {
                "description": s.description,
                "argv": list(s.argv),
                "requires_root": s.requires_root,
                "timeout_s": s.timeout_s,
                "extra_env": dict(s.extra_env) if s.extra_env else {},
            }
            for s in plan.steps
        ],
        "verify_checks": [
            {"name": c.name, "argv": list(c.argv), "expect_zero": c.expect_zero}
            for c in plan.verify_checks
        ],
    }


def _composite_undo(undos: Sequence[UndoPlan], labels: Sequence[str]) -> UndoPlan:
    """Combine per-part undo plans; a part without a reverse path poisons all."""
    for label, undo in zip(labels, undos, strict=True):
        if undo.status is UndoStatus.UNAVAILABLE:
            return UndoPlan(
                status=UndoStatus.UNAVAILABLE,
                reason=f"part {label!r} cannot be reversed automatically: {undo.reason}",
            )
    steps: list[PlannedStep] = []
    checks: list[CheckSpec] = []
    for undo in reversed(undos):
        if undo.status is UndoStatus.AVAILABLE:
            steps.extend(undo.steps)
            checks.extend(undo.verify_checks)
    if not steps:
        return UndoPlan(status=UndoStatus.NONE_NEEDED, reason="read-only plan")
    return UndoPlan(
        status=UndoStatus.AVAILABLE,
        reason="reverses executed parts last-first",
        steps=tuple(steps),
        verify_checks=tuple(checks),
    )


def _rebuild_undo_steps(
    payload: object,
) -> tuple[list[PlannedStep], list[CheckSpec], int]:
    """Strictly rehydrate an undo payload from the (user-editable) journal."""
    if not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("payload has no steps")
    steps: list[PlannedStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise ValueError("step is not an object")
        argv_raw = raw.get("argv")
        if not isinstance(argv_raw, list) or not all(isinstance(a, str) for a in argv_raw):
            raise ValueError("step argv invalid")
        if not argv_raw:
            raise ValueError("step argv empty")
        timeout = raw.get("timeout_s", 300.0)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("step timeout invalid")
        extra_env = raw.get("extra_env") or {}
        if not isinstance(extra_env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in extra_env.items()
        ):
            raise ValueError("step extra_env invalid")
        tier_raw = raw.get("tier", int(Tier.T1))
        if not isinstance(tier_raw, int) or tier_raw < int(Tier.T0) or tier_raw > int(Tier.T2):
            raise ValueError("step tier invalid")
        steps.append(
            PlannedStep(
                description=str(raw.get("description", "undo step")),
                argv=tuple(argv_raw),
                tier=Tier(tier_raw),
                requires_root=bool(raw.get("requires_root", False)),
                timeout_s=float(timeout),
                extra_env={str(k): str(v) for k, v in extra_env.items()},
            )
        )
    checks: list[CheckSpec] = []
    for raw in payload.get("verify_checks", []):
        if not isinstance(raw, dict):
            raise ValueError("verify check invalid")
        argv_raw = raw.get("argv")
        if not isinstance(argv_raw, list) or not all(isinstance(a, str) for a in argv_raw):
            raise ValueError("verify check argv invalid")
        checks.append(
            CheckSpec(
                name=str(raw.get("name", "check")),
                argv=tuple(argv_raw),
                expect_zero=bool(raw.get("expect_zero", True)),
            )
        )
    tier = int(payload.get("tier", int(Tier.T1)))
    return steps, checks, tier


def _revalidate_undo_step(step: PlannedStep) -> None:
    """Journal files are user-editable: re-apply domain rules to undo argvs.

    Covers both the package-removal protected set and the file-edit path
    policy (ADR-0008): a tampered artifact cannot smuggle writes to
    protected files through tee/cp/rm.
    """
    argv = step.argv
    for prefix in _REMOVE_PREFIXES:
        if tuple(argv[: len(prefix)]) == prefix:
            marker = list(argv).index("--") if "--" in argv else -1
            names = argv[marker + 1 :] if marker >= 0 else ()
            for name in names:
                check_removal_allowed(name)

    program = argv[0].rsplit("/", 1)[-1]
    if program in ("tee", "truncate", "rm"):
        for operand in argv[1:]:
            if operand.startswith("-"):
                continue
            classify_for_edit(operand)  # raises SafetyRefusal on protected paths
    elif program == "cp" and len(argv) >= 3:
        classify_for_edit(argv[-1])  # destination
