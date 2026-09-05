"""Guarded command execution (pipeline stage EXECUTE).

Security properties (ADR-0006):
- argv-only: no shell is ever spawned (`shell=True` is nowhere in this codebase);
- per-step timeouts with process-group cleanup (SIGTERM -> SIGKILL);
- output capped at 16 KiB per stream (tails are what get echoed and journaled);
- privilege escalation only via `sudo -n` (non-interactive); a step that needs
  root without available non-interactive sudo fails with a clear error instead
  of prompting, hanging, or fishing for credentials.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jarvis.system.models import PrivilegeError

MAX_TAIL_BYTES = 16 * 1024
_KILL_GRACE_S = 5.0


@dataclass(frozen=True)
class ExecResult:
    """Outcome of one executed command."""

    exit_code: int  # negative values indicate termination by a signal
    stdout_tail: str
    stderr_tail: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def _tail(data: bytes) -> str:
    """Decode and keep the last MAX_TAIL_BYTES of a stream; normalize CR progress lines."""
    text = data[-MAX_TAIL_BYTES:].decode("utf-8", errors="replace").replace("\r", "\n")
    return text.strip("\n")


class Runner:
    """Execution interface; injectable for tests (fake runner)."""

    def run(
        self,
        argv: Sequence[str],
        *,
        requires_root: bool = False,
        timeout_s: float = 300.0,
        extra_env: Mapping[str, str] | None = None,
        echo: bool = True,
        stdin_text: str = "",
        detach: bool = False,
    ) -> ExecResult:  # pragma: no cover - interface
        raise NotImplementedError

    def terminate_current(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class LocalRunner(Runner):
    """Real subprocess execution on the local machine."""

    def __init__(self, sudo_binary: str | None = None, euid: int | None = None) -> None:
        self._sudo = sudo_binary if sudo_binary is not None else shutil.which("sudo")
        self._euid = os.geteuid() if euid is None else euid
        self._current: subprocess.Popen[bytes] | None = None

    # -- helpers ---------------------------------------------------------
    def _prepare_argv(self, argv: Sequence[str], requires_root: bool) -> list[str]:
        if not argv or any(
            (not isinstance(arg, str)) or (not arg) or "\x00" in arg for arg in argv
        ):
            raise ValueError("argv must be a non-empty sequence of non-empty strings")
        final = [str(arg) for arg in argv]
        if requires_root and self._euid != 0:
            if not self._sudo:
                raise PrivilegeError(
                    "this step requires root privileges, but no usable 'sudo' was found; "
                    "authenticate sudo for this user or re-run as root"
                )
            final = [self._sudo, "-n", "--", *final]
        return final

    def _kill_group(self, proc: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, sig)  # pid == pgid because start_new_session=True

    # -- API -------------------------------------------------------------
    def run(
        self,
        argv: Sequence[str],
        *,
        requires_root: bool = False,
        timeout_s: float = 300.0,
        extra_env: Mapping[str, str] | None = None,
        echo: bool = True,
        stdin_text: str = "",
        detach: bool = False,
    ) -> ExecResult:
        final = self._prepare_argv(argv, requires_root)
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)

        # detach: for spawns that outlive the command (GUI apps via setsid).
        # Child fds must NOT be our pipes, or communicate() blocks on EOF
        # until the detached process exits.
        if detach:
            proc = subprocess.Popen(
                final,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        else:
            proc = subprocess.Popen(
                final,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        self._current = proc
        if echo:
            print(f"    $ {' '.join(final)}", flush=True)
            if stdin_text:
                print(f"        < {stdin_text.rstrip()}", flush=True)
        timed_out = False
        try:
            out, err = proc.communicate(
                input=stdin_text.encode("utf-8") if stdin_text else None,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_group(proc, signal.SIGTERM)
            try:
                out, err = proc.communicate(timeout=_KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                self._kill_group(proc, signal.SIGKILL)
                out, err = proc.communicate()
        finally:
            self._current = None

        result = ExecResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout_tail=_tail(out or b""),
            stderr_tail=_tail(err or b""),
            timed_out=timed_out,
        )
        if echo and result.stdout_tail:
            print(result.stdout_tail, flush=True)
        if echo and result.stderr_tail:
            print(result.stderr_tail, file=sys.stderr, flush=True)
        if timed_out:
            print(f"[jarvis] step exceeded {timeout_s:.0f}s and was terminated", flush=True)
        return result

    def terminate_current(self) -> None:
        proc = self._current
        if proc is None or proc.poll() is not None:
            return
        self._kill_group(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            self._kill_group(proc, signal.SIGKILL)
            proc.wait(timeout=3.0)
