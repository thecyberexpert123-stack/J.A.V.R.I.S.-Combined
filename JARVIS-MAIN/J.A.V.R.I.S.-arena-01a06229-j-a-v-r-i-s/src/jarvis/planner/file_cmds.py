"""File-management commands (ADR-0016 D3): the T1 catalog family.

Same kernel discipline as file.append (ADR-0008): every mutation goes through
`classify_for_edit` (protected sets refused, T2 prefixes escalate the step
tier), and the undo plan is built BEFORE execution with honest availability —
plan-time existence decides whether "remove what this task created" is a real
reverse path or a disclosed impossibility (rm).
"""

from __future__ import annotations

import re
from pathlib import Path

from jarvis.planner.catalog_common import Params, path_arg, verify_ran
from jarvis.planner.models import (
    CheckSpec,
    PlannedStep,
    Playbook,
    UndoPlan,
    UndoStatus,
)
from jarvis.safety.paths import classify_for_edit
from jarvis.safety.tiers import SafetyRefusal, Tier
from jarvis.system.models import MachineProfile


def _clean_src(value: str) -> Path:
    """A source path: validated, ~-expanded, no policy restriction on reads."""
    return path_arg(value)


def _destination_tier(path_str: str) -> tuple[Tier, Path]:
    """Destination paths follow the full edit policy (protected set refused)."""
    return classify_for_edit(path_str)


# --------------------------------------------------------------------------
# fs.mkdir / fs.rmdir
# --------------------------------------------------------------------------


def _match_mkdir(text: str) -> Params | None:
    m = re.match(
        r"^(?:mkdir|create|make)(?: the| a| this| new)* (?:directory|folder|dir) ?"
        r"(?:named |called |at |in )?(?P<path>.+)$",
        text,
    )
    if m is None or not m.group("path").strip():
        return None
    path = m.group("path").strip()
    if path.startswith(("file ", "directory ", "folder ")):
        return None  # wrong noun: never mkdir something called "file X"
    return {"path": path}


def _core_mkdir(path_str: str) -> tuple[list[PlannedStep], UndoPlan, Tier]:
    tier, resolved = _destination_tier(path_str)
    root = tier is Tier.T2
    existed = resolved.is_dir()
    steps = [
        PlannedStep(
            description=f"create directory {resolved}",
            argv=("mkdir", "-p", str(resolved)),
            tier=tier,
            requires_root=root,
            timeout_s=30.0,
        )
    ]
    if existed:
        undo = UndoPlan(status=UndoStatus.NONE_NEEDED, reason=f"{resolved} already existed")
    else:
        undo = UndoPlan(
            status=UndoStatus.AVAILABLE,
            reason=f"removes the created directory {resolved} (must still be empty)",
            steps=(
                PlannedStep(
                    description=f"remove created directory {resolved}",
                    argv=("rmdir", "--ignore-fail-on-non-empty", str(resolved)),
                    tier=Tier.T1,
                    requires_root=root,
                    timeout_s=30.0,
                ),
            ),
            verify_checks=(
                CheckSpec(
                    name="dir absent after undo",
                    argv=("test", "-d", str(resolved)),
                    expect_zero=False,
                ),
            ),
            params={"path": str(resolved)},
        )
    return steps, undo, tier


def _build_mkdir(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    steps, _undo, _tier = _core_mkdir(str(params["path"]))
    return steps


def _undo_mkdir(params: Params, profile: MachineProfile) -> UndoPlan:
    _steps, undo, _tier = _core_mkdir(str(params["path"]))
    return undo


# --------------------------------------------------------------------------
# fs.touch
# --------------------------------------------------------------------------


def _match_touch(text: str) -> Params | None:
    m = re.match(
        r"^(?:touch|create)(?: an? | the )?(?:empty )?(?:file |regular file )(?P<path>.+)$", text
    )
    if m is None:
        return None
    path = m.group("path").strip()
    if path.startswith(("directory ", "folder ", "dir ")):
        return None  # wrong noun: never touch something called "directory X"
    return {"path": path}


def _core_touch(path_str: str) -> tuple[list[PlannedStep], UndoPlan, Tier]:
    tier, resolved = _destination_tier(path_str)
    root = tier is Tier.T2
    existed = resolved.exists()
    steps = [
        PlannedStep(
            description=f"create/touch {resolved}",
            argv=("touch", str(resolved)),
            tier=tier,
            requires_root=root,
            timeout_s=30.0,
        )
    ]
    if existed:
        undo = UndoPlan(
            status=UndoStatus.NONE_NEEDED,
            reason=f"{resolved} already existed; only timestamps were updated",
        )
    else:
        undo = UndoPlan(
            status=UndoStatus.AVAILABLE,
            reason=f"removes the created file {resolved}",
            steps=(
                PlannedStep(
                    description=f"remove created file {resolved}",
                    argv=("rm", "-f", str(resolved)),
                    tier=Tier.T1,
                    requires_root=root,
                    timeout_s=30.0,
                ),
            ),
            verify_checks=(
                CheckSpec(
                    name="file absent after undo",
                    argv=("test", "-f", str(resolved)),
                    expect_zero=False,
                ),
            ),
            params={"path": str(resolved)},
        )
    return steps, undo, tier


def _build_touch(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    steps, _undo, _tier = _core_touch(str(params["path"]))
    return steps


def _undo_touch(params: Params, profile: MachineProfile) -> UndoPlan:
    _steps, undo, _tier = _core_touch(str(params["path"]))
    return undo


# --------------------------------------------------------------------------
# fs.copy / fs.move
# --------------------------------------------------------------------------


def _match_two_paths(text: str, verbs: tuple[str, ...]) -> Params | None:
    for verb in verbs:
        prefix = f"{verb} "
        if not text.startswith(prefix):
            continue
        body = text[len(prefix) :]
        cut = body.find(" to ")
        if cut <= 0 or cut + 4 >= len(body):
            continue
        src = body[:cut].strip()
        dst = body[cut + 4 :].strip()
        if src and dst:
            return {"src": src, "dst": dst}
    return None


def _match_two_token_paths(text: str, verbs: tuple[str, ...]) -> Params | None:
    r"""Space-separated two-path form ("move /a /b") — single tokens only.

    Paths with spaces must use the " to " form. Both tokens are validated at
    MATCH time (dash ban included) so bad input falls through instead of
    hijacking the request.
    """
    m = re.match(r"^(?:copy|cp|move|mv|rename|symlink|link) (?P<src>\S+) (?P<dst>\S+)$", text)
    if m is None or not text.startswith(verbs):
        return None
    try:
        path_arg(m.group("src"))
        path_arg(m.group("dst"))
    except SafetyRefusal:
        return None
    return {"src": m.group("src"), "dst": m.group("dst")}


def _match_copy(text: str) -> Params | None:
    matched = _match_two_paths(text, ("copy", "cp"))
    if matched is None:
        m = re.match(r"^(?:duplicate|make a copy of) (?P<src>.+) (?:as|to) (?P<dst>.+)$", text)
        if m is not None:
            matched = {"src": m.group("src"), "dst": m.group("dst")}
    if matched is None:
        matched = _match_two_token_paths(text, ("copy", "cp"))
    return matched


def _core_copy(src_str: str, dst_str: str) -> tuple[list[PlannedStep], UndoPlan, Tier]:
    src = _clean_src(src_str)
    tier, dst = _destination_tier(dst_str)
    root = tier is Tier.T2
    if not src.is_file():
        raise SafetyRefusal(f"source is not a regular file: {src}")
    dst_existed = dst.exists()
    steps = [
        PlannedStep(
            description=f"copy {src} -> {dst}",
            argv=("cp", "-p", str(src), str(dst)),
            tier=tier,
            requires_root=root,
            timeout_s=120.0,
        )
    ]
    if dst_existed:
        undo = UndoPlan(
            status=UndoStatus.UNAVAILABLE,
            reason=f"{dst} already existed and was overwritten; restore it from your own backup",
        )
    else:
        undo = UndoPlan(
            status=UndoStatus.AVAILABLE,
            reason=f"removes the created copy {dst}",
            steps=(
                PlannedStep(
                    description=f"remove created copy {dst}",
                    argv=("rm", "-f", str(dst)),
                    tier=Tier.T1,
                    requires_root=root,
                    timeout_s=60.0,
                ),
            ),
            verify_checks=(
                CheckSpec(
                    name="copy absent after undo",
                    argv=("test", "-f", str(dst)),
                    expect_zero=False,
                ),
            ),
            params={"path": str(dst)},
        )
    return steps, undo, tier


def _build_copy(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    steps, _undo, _tier = _core_copy(str(params["src"]), str(params["dst"]))
    return steps


def _undo_copy(params: Params, profile: MachineProfile) -> UndoPlan:
    _steps, undo, _tier = _core_copy(str(params["src"]), str(params["dst"]))
    return undo


def _match_move(text: str) -> Params | None:
    matched = _match_two_paths(text, ("move", "mv", "rename"))
    if matched is None:
        m = re.match(r"^rename (?P<src>.+) (?:as|to) (?P<dst>.+)$", text)
        if m is not None:
            matched = {"src": m.group("src"), "dst": m.group("dst")}
    if matched is None:
        matched = _match_two_token_paths(text, ("move", "mv", "rename"))
    return matched


def _core_move(src_str: str, dst_str: str) -> tuple[list[PlannedStep], UndoPlan, Tier]:
    src = _clean_src(src_str)
    tier, dst = _destination_tier(dst_str)
    root = tier is Tier.T2
    if not src.exists():
        raise SafetyRefusal(f"source does not exist: {src}")
    steps = [
        PlannedStep(
            description=f"move {src} -> {dst}",
            argv=("mv", str(src), str(dst)),
            tier=tier,
            requires_root=root,
            timeout_s=120.0,
        )
    ]
    undo = UndoPlan(
        status=UndoStatus.AVAILABLE,
        reason=f"moves {dst} back to {src}",
        steps=(
            PlannedStep(
                description=f"move {dst} back to {src}",
                argv=("mv", str(dst), str(src)),
                tier=Tier.T1,
                requires_root=root,
                timeout_s=120.0,
            ),
        ),
        verify_checks=(
            CheckSpec(name="source restored", argv=("test", "-e", str(src)), expect_zero=True),
        ),
        params={"src": str(src), "dst": str(dst)},
    )
    return steps, undo, tier


def _build_move(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    steps, _undo, _tier = _core_move(str(params["src"]), str(params["dst"]))
    return steps


def _undo_move(params: Params, profile: MachineProfile) -> UndoPlan:
    _steps, undo, _tier = _core_move(str(params["src"]), str(params["dst"]))
    return undo


# --------------------------------------------------------------------------
# fs.remove / fs.link
# --------------------------------------------------------------------------


def _match_remove(text: str) -> Params | None:
    m = re.match(
        r"^(?:remove|delete|unlink) (?:the |this |that )?(?:file |regular file )?(?P<path>.+)$",
        text,
    )
    if m is None:
        return None
    path = m.group("path").strip()
    # Path-shaped requests only: a bare word without / . or ~ is very likely a
    # package name and must fall through to pkg.remove, not delete "./htop".
    if not any(ch in path for ch in "/.~"):
        return None
    return {"path": path}


def _core_remove(path_str: str) -> tuple[list[PlannedStep], UndoPlan, Tier]:
    tier, resolved = _destination_tier(path_str)
    root = tier is Tier.T2
    if resolved.is_dir() and not resolved.is_symlink():
        raise SafetyRefusal(
            f"refusing to delete directory {resolved}: fs.remove deletes single files "
            "only (directory removal is rmdir for empty dirs; recursive deletion is "
            "deliberately not in the catalog)"
        )
    steps = [
        PlannedStep(
            description=f"delete {resolved}",
            argv=("rm", "-f", str(resolved)),
            tier=tier,
            requires_root=root,
            timeout_s=30.0,
        )
    ]
    undo = UndoPlan(
        status=UndoStatus.UNAVAILABLE,
        reason=(
            "deletion is not reversible; use cautious mode for snapshots "
            "or copy the file aside first"
        ),
    )
    return steps, undo, tier


def _build_remove(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    steps, _undo, _tier = _core_remove(str(params["path"]))
    return steps


def _undo_remove(params: Params, profile: MachineProfile) -> UndoPlan:
    _steps, undo, _tier = _core_remove(str(params["path"]))
    return undo


def _match_link(text: str) -> Params | None:
    matched = _match_two_paths(text, ("symlink", "link"))
    if matched is None:
        m = re.match(r"^symlink (?P<src>.+) (?:as|to) (?P<dst>.+)$", text)
        if m is not None:
            matched = {"src": m.group("src"), "dst": m.group("dst")}
    if matched is None:
        matched = _match_two_token_paths(text, ("symlink", "link"))
    return matched


def _core_link(src_str: str, dst_str: str) -> tuple[list[PlannedStep], UndoPlan, Tier]:
    src = _clean_src(src_str)
    tier, dst = _destination_tier(dst_str)
    root = tier is Tier.T2
    dst_existed = dst.exists() or dst.is_symlink()
    steps = [
        PlannedStep(
            description=f"symlink {dst} -> {src}",
            argv=("ln", "-sfn", str(src), str(dst)),
            tier=tier,
            requires_root=root,
            timeout_s=30.0,
        )
    ]
    if dst_existed:
        undo = UndoPlan(
            status=UndoStatus.UNAVAILABLE,
            reason=f"{dst} already existed and was replaced; restore it from your own backup",
        )
    else:
        undo = UndoPlan(
            status=UndoStatus.AVAILABLE,
            reason=f"removes the created symlink {dst}",
            steps=(
                PlannedStep(
                    description=f"remove created symlink {dst}",
                    argv=("rm", "-f", str(dst)),
                    tier=Tier.T1,
                    requires_root=root,
                    timeout_s=30.0,
                ),
            ),
            verify_checks=(
                CheckSpec(
                    name="symlink absent after undo",
                    argv=("test", "-L", str(dst)),
                    expect_zero=False,
                ),
            ),
            params={"path": str(dst)},
        )
    return steps, undo, tier


def _build_link(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    steps, _undo, _tier = _core_link(str(params["src"]), str(params["dst"]))
    return steps


def _undo_link(params: Params, profile: MachineProfile) -> UndoPlan:
    _steps, undo, _tier = _core_link(str(params["src"]), str(params["dst"]))
    return undo


FILE_PLAYBOOKS: tuple[Playbook, ...] = (
    Playbook(
        id="fs.mkdir",
        description="create a directory (parents allowed; undo removes it if still empty)",
        tier=Tier.T1,
        match=_match_mkdir,
        build=_build_mkdir,
        verify=verify_ran,
        undo=_undo_mkdir,
    ),
    Playbook(
        id="fs.touch",
        description="create an empty file (or update timestamps; undo only for created files)",
        tier=Tier.T1,
        match=_match_touch,
        build=_build_touch,
        verify=verify_ran,
        undo=_undo_touch,
    ),
    Playbook(
        id="fs.copy",
        description="copy a file (protected destinations escalate to T2)",
        tier=Tier.T1,
        match=_match_copy,
        build=_build_copy,
        verify=verify_ran,
        undo=_undo_copy,
    ),
    Playbook(
        id="fs.move",
        description="move/rename a file or directory (undo moves it back)",
        tier=Tier.T1,
        match=_match_move,
        build=_build_move,
        verify=verify_ran,
        undo=_undo_move,
    ),
    Playbook(
        id="fs.remove",
        description="delete a single file (single files only; deletion has no undo)",
        tier=Tier.T1,
        match=_match_remove,
        build=_build_remove,
        verify=verify_ran,
        undo=_undo_remove,
    ),
    Playbook(
        id="fs.link",
        description="create a symbolic link (undo removes the link if newly created)",
        tier=Tier.T1,
        match=_match_link,
        build=_build_link,
        verify=verify_ran,
        undo=_undo_link,
    ),
)
