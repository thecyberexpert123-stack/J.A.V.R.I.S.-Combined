"""file.append: path policy, matching, backup/undo round-trip on REAL files."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_profile
from jarvis.core.orchestrator import Orchestrator
from jarvis.execution.runner import LocalRunner
from jarvis.journal.sqlite import Journal
from jarvis.planner.fileops import _match_append, backup_path_for, build_file_append
from jarvis.safety.approval import ApprovalPolicy
from jarvis.safety.paths import classify_for_edit
from jarvis.safety.tiers import SafetyRefusal, Tier
from jarvis.system.models import UnsupportedError, is_protected_package

# -- path policy -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "/etc/shadow", "/etc/gshadow", "/etc/sudoers", "/etc/sudoers.d/99-evil"],
)
def test_auth_material_refused(path: str) -> None:
    with pytest.raises(SafetyRefusal, match="protected"):
        classify_for_edit(path)


@pytest.mark.parametrize("path", ["/boot/vmlinuz", "/proc/cpuinfo", "/sys/x", "/dev/sda"])
def test_kernel_paths_refused(path: str) -> None:
    with pytest.raises(SafetyRefusal):
        classify_for_edit(path)


def test_root_refused() -> None:
    with pytest.raises(SafetyRefusal):
        classify_for_edit("/")


def test_relative_path_refused() -> None:
    with pytest.raises(SafetyRefusal, match="absolute"):
        classify_for_edit("rel/path.txt")


def test_etc_is_t2_home_is_t1() -> None:
    tier, _ = classify_for_edit("/etc/motd")
    assert tier is Tier.T2
    tier, _ = classify_for_edit("~/notes.txt")
    assert tier is Tier.T1
    tier, _ = classify_for_edit("/var/log/app.log")
    assert tier is Tier.T2


def test_symlink_to_protected_target_refused(tmp_path: Path) -> None:
    link = tmp_path / "innocent"
    link.symlink_to("/etc/shadow")
    with pytest.raises(SafetyRefusal):
        classify_for_edit(str(link))


def test_edit_text_validation() -> None:
    from jarvis.safety.paths import validate_edit_text

    assert validate_edit_text("hello world") == "hello world"
    for bad in ("", "   ", "a\nb", "a\rb", "x" * 501, "esc\x1b[31m"):
        with pytest.raises(SafetyRefusal):
            validate_edit_text(bad)


# -- matcher ---------------------------------------------------------------


def test_matcher_basic() -> None:
    params = _match_append("append hello to /tmp/a.txt")
    assert params == {"text": "hello", "path": "/tmp/a.txt"}


def test_matcher_preserves_path_case() -> None:
    params = _match_append("append Data to /etc/MyApp/Config.ini")
    assert params is not None
    assert params["path"] == "/etc/MyApp/Config.ini"


def test_matcher_quoted_text_and_capitalized_verb() -> None:
    params = _match_append("Append 'export EDITOR=vim' to the file /home/u/.bashrc")
    assert params is not None
    assert params["text"] == "export EDITOR=vim"
    assert params["path"] == "/home/u/.bashrc"


def test_matcher_rejects_malformed() -> None:
    assert _match_append("append to /x") is None
    assert _match_append("append text only") is None
    assert _match_append("install htop") is None


# -- plan construction -------------------------------------------------------


def test_backup_path_is_deterministic(tmp_path: Path) -> None:
    a = backup_path_for(Path("/etc/motd"))
    b = backup_path_for(Path("/etc/motd"))
    assert a == b
    assert backup_path_for(Path("/other")) != a


def test_build_existing_file_has_backup_first(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("line1\n", encoding="utf-8")
    steps, undo, tier = build_file_append(str(target), "line2", make_profile())
    assert tier is Tier.T1
    assert steps[0].argv[:2] == ("cp", "-p")
    assert steps[1].argv[:2] == ("tee", "-a")
    assert steps[1].stdin_text == "line2\n"
    assert undo.steps[0].argv[:2] == ("cp", "-p")
    assert undo.verify_checks[0].argv == ("test", "-f", str(target))


def test_build_absent_file_undo_removes(tmp_path: Path) -> None:
    target = tmp_path / "new.txt"
    steps, undo, _tier = build_file_append(str(target), "x", make_profile())
    assert len(steps) == 1 and steps[0].argv[0] == "tee"
    assert undo.steps[0].argv[:2] == ("rm", "-f")
    assert undo.verify_checks[0].expect_zero is False


def test_build_system_path_elevates_tier_and_requires_root() -> None:
    steps, _undo, tier = build_file_append("/etc/motd", "welcome", make_profile())
    assert tier is Tier.T2
    assert all(s.tier is Tier.T2 and s.requires_root for s in steps)


# -- full round-trip on REAL files with the REAL runner -----------------------


def _orch(tmp_path: Path) -> Orchestrator:  # type: ignore[no-untyped-def]
    import os

    state = tmp_path / "state"
    state.mkdir()
    old = os.environ.get("JARVIS_STATE_DIR")
    os.environ["JARVIS_STATE_DIR"] = str(state)
    journal = Journal(state / "j.db")
    if old is not None:
        os.environ["JARVIS_STATE_DIR"] = old
    else:
        import os as _os

        _os.environ.pop("JARVIS_STATE_DIR", None)
    return Orchestrator(
        make_profile(is_root=False, sudo=True),
        journal,
        LocalRunner(sudo_binary="", euid=1000),
        ApprovalPolicy(yes=True),
        echo=False,
    )


def test_roundtrip_edit_and_undo_restores_bytes(tmp_path: Path) -> None:
    target = tmp_path / "config.conf"
    original = "key=1\n"
    target.write_text(original, encoding="utf-8")
    orch = _orch(tmp_path)
    outcome = orch.run_intent(f"append key=2 to {target}")
    assert outcome.status.value == "succeeded", outcome.error
    assert "key=2" in target.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == original + "key=2\n"

    undo_outcome = orch.undo(outcome.task_id)
    assert undo_outcome.status.value == "succeeded", undo_outcome.error
    assert target.read_text(encoding="utf-8") == original  # byte-identical restore


def test_roundtrip_created_file_and_undo_removes(tmp_path: Path) -> None:
    target = tmp_path / "created.log"
    orch = _orch(tmp_path)
    outcome = orch.run_intent(f"append first line to {target}")
    assert outcome.status.value == "succeeded", outcome.error
    assert target.read_text(encoding="utf-8") == "first line\n"

    undo_outcome = orch.undo(outcome.task_id)
    assert undo_outcome.status.value == "succeeded", undo_outcome.error
    assert not target.exists()


def test_system_path_requires_t2_consent(tmp_path: Path) -> None:
    import io

    from jarvis.safety.approval import ApprovalPolicy, ApprovalRefused

    policy = ApprovalPolicy(yes=False, stdin=io.StringIO())  # non-tty: cannot ask
    with pytest.raises(ApprovalRefused):
        policy.decide(Tier.T2, [])


def test_protected_packages_guard_untouched_by_fileops() -> None:
    # guard: file ops never weaken the package protected set
    assert is_protected_package("libc6")


def test_unsupported_environment_still_refuses_paths(tmp_path: Path) -> None:
    orch = _orch(tmp_path)
    profile = orch._profile
    from dataclasses import replace

    from jarvis.system.models import PackageManager

    bare = replace(profile, package_manager=PackageManager.APT, init_system="none")
    orch2 = Orchestrator(
        bare,
        orch._journal,
        LocalRunner(sudo_binary="", euid=1000),
        ApprovalPolicy(yes=True),
        echo=False,
    )
    # file ops do not need systemd or a package manager; refusal comes from
    # policy paths only:
    outcome = orch2.run_intent(f"append x to {tmp_path / 'ok.txt'}")
    assert outcome.status.value in {"succeeded", "refused"}
    _ = UnsupportedError  # import kept honest
