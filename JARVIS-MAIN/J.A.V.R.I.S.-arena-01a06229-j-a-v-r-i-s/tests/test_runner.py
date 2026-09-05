"""LocalRunner behavior: sudo wrapping, real execution, timeout kill, tails."""

from __future__ import annotations

import time

import pytest

from jarvis.execution.runner import LocalRunner
from jarvis.system.models import PrivilegeError


def test_prepare_argv_wraps_sudo_for_non_root() -> None:
    runner = LocalRunner(sudo_binary="/usr/bin/sudo", euid=1000)
    final = runner._prepare_argv(["apt-get", "install", "--", "htop"], requires_root=True)
    assert final == ["/usr/bin/sudo", "-n", "--", "apt-get", "install", "--", "htop"]


def test_prepare_argv_no_sudo_when_root() -> None:
    runner = LocalRunner(sudo_binary="/usr/bin/sudo", euid=0)
    final = runner._prepare_argv(["apt-get", "install"], requires_root=True)
    assert final == ["apt-get", "install"]


def test_prepare_argv_missing_sudo_raises() -> None:
    runner = LocalRunner(sudo_binary="", euid=1000)  # "" disables autodetection
    with pytest.raises(PrivilegeError):
        runner._prepare_argv(["apt-get", "update"], requires_root=True)


def test_prepare_argv_rejects_bad_argv() -> None:
    runner = LocalRunner(sudo_binary=None, euid=0)
    with pytest.raises(ValueError):
        runner._prepare_argv([], requires_root=False)
    with pytest.raises(ValueError):
        runner._prepare_argv(["ok", ""], requires_root=False)


def test_real_run_success_and_failure() -> None:
    runner = LocalRunner(sudo_binary=None, euid=0)
    ok = runner.run(["true"], echo=False)
    assert ok.ok and ok.exit_code == 0
    fail = runner.run(["false"], echo=False)
    assert not fail.ok and fail.exit_code == 1


def test_real_run_captures_stdout_tail() -> None:
    runner = LocalRunner(sudo_binary=None, euid=0)
    res = runner.run(["printf", "hello\nworld\n"], echo=False)
    assert res.stdout_tail == "hello\nworld"


def test_real_run_timeout_kills_process_group() -> None:
    runner = LocalRunner(sudo_binary=None, euid=0)
    start = time.monotonic()
    res = runner.run(["sleep", "30"], timeout_s=0.5, echo=False)
    elapsed = time.monotonic() - start
    assert res.timed_out is True
    assert res.exit_code != 0
    assert elapsed < 10  # killed promptly, not after 30s


def test_real_run_sudo_prefix_not_invoked_without_root_flag() -> None:
    runner = LocalRunner(sudo_binary=None, euid=0)
    res = runner.run(["true"], requires_root=False, echo=False)
    assert res.ok
