"""file.append playbook: one-line file edit with real backup + undo (ADR-0008).

The narrowest useful file operation: append a single validated line. The
backup step runs *before* the edit and the undo artifact restores the file
from it byte-for-byte; for previously-absent targets the undo removes the
created file. Everything flows through the standard kernel (static argv
analysis, tier gate, journal). The backup location is deterministic per
target (hash-addressed) so the undo plan and the executed plan always agree.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from jarvis.execution.runner import ExecResult, Runner
from jarvis.journal.sqlite import state_dir
from jarvis.planner.models import CheckSpec, PlannedStep, UndoPlan, UndoStatus, Verification
from jarvis.safety.paths import classify_for_edit, validate_edit_text
from jarvis.safety.tiers import Tier
from jarvis.system.models import MachineProfile

# Same shape as planner.playbooks.Params (local alias avoids an import cycle).
Params = dict[str, object]


def _match_append(text: str) -> Params | None:
    """`append <text> to (the) (file) <path>` — path is the final token.

    The verb is matched case-insensitively; everything after it keeps its
    original case because Linux paths are case-sensitive.
    """
    lower = text.lower()
    if not lower.startswith("append "):
        return None
    body = text[len("append ") :]
    cut = body.rfind(" to ")
    if cut <= 0 or cut + 4 >= len(body):
        return None
    text_part = body[:cut].strip()
    path_part = body[cut + 4 :].strip()
    # optional connector: "to [the] [file] <path>"
    for word in ("the ", "file "):
        if path_part.startswith(word):
            path_part = path_part[len(word) :].strip()
    if len(text_part) >= 2 and text_part[0] == text_part[-1] and text_part[0] in ("'", '"'):
        text_part = text_part[1:-1]
    if not text_part or not path_part:
        return None
    return {"text": text_part, "path": path_part}


def backup_path_for(resolved: Path) -> Path:
    """Deterministic per-target backup location (state dir, hash-addressed)."""
    digest = hashlib.sha256(resolved.as_posix().encode("utf-8")).hexdigest()[:16]
    return state_dir() / "backups" / digest / resolved.name


def build_file_append(
    path_str: str, text: str, profile: MachineProfile
) -> tuple[list[PlannedStep], UndoPlan, Tier]:
    """Materialize steps + undo for one append. Raises SafetyRefusal per policy."""
    clean_text = validate_edit_text(text)
    tier, resolved = classify_for_edit(path_str)
    root_needed = tier is Tier.T2

    steps: list[PlannedStep] = []
    if resolved.is_file():
        backup = backup_path_for(resolved)
        # backup directory is created at plan time (state-dir preparation) so
        # the executed cp step only performs the copy itself
        backup.parent.mkdir(parents=True, exist_ok=True)
        steps.append(
            PlannedStep(
                description=f"back up {resolved} -> {backup}",
                argv=("cp", "-p", str(resolved), str(backup)),
                tier=tier,
                requires_root=root_needed,
                timeout_s=60.0,
            )
        )
        undo = UndoPlan(
            status=UndoStatus.AVAILABLE,
            reason=f"restores {resolved} from the pre-edit backup",
            steps=(
                PlannedStep(
                    description=f"restore {resolved} from backup",
                    argv=("cp", "-p", str(backup), str(resolved)),
                    tier=Tier.T1,
                    requires_root=root_needed,
                    timeout_s=60.0,
                ),
            ),
            verify_checks=(
                CheckSpec(
                    name="file present after restore",
                    argv=("test", "-f", str(resolved)),
                    expect_zero=True,
                ),
            ),
            params={"path": str(resolved), "backup": str(backup)},
        )
    else:
        undo = UndoPlan(
            status=UndoStatus.AVAILABLE,
            reason=f"removes {resolved} (created by this task)",
            steps=(
                PlannedStep(
                    description=f"remove created file {resolved}",
                    argv=("rm", "-f", str(resolved)),
                    tier=Tier.T1,
                    requires_root=root_needed,
                    timeout_s=60.0,
                ),
            ),
            verify_checks=(
                CheckSpec(
                    name="created file absent after undo",
                    argv=("test", "-f", str(resolved)),
                    expect_zero=False,
                ),
            ),
            params={"path": str(resolved)},
        )

    steps.append(
        PlannedStep(
            description=f"append line to {resolved}",
            argv=("tee", "-a", str(resolved)),
            tier=tier,
            requires_root=root_needed,
            timeout_s=60.0,
            stdin_text=clean_text + "\n",
        )
    )
    return steps, undo, tier


def _build_append(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    steps, _undo, _tier = build_file_append(str(params["path"]), str(params["text"]), profile)
    return steps


def _undo_append(params: Params, profile: MachineProfile) -> UndoPlan:
    _steps, undo, _tier = build_file_append(str(params["path"]), str(params["text"]), profile)
    return undo


def _verify_append(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    text = str(params["text"])
    path = str(params["path"])
    res = runner.run(["grep", "-F", "-q", text, path], timeout_s=30, echo=False)
    ok = res.exit_code == 0
    return Verification(
        ok=ok,
        detail="appended line is present" if ok else "appended line NOT found after edit",
        checks=((f"contains:{path}", ok, "grep -F match" if ok else res.stderr_tail),),
    )
