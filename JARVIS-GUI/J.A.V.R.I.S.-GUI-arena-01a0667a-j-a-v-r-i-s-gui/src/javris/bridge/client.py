"""QProcess client for the JARVIS kernel's stdio MCP server.

Spawns one child process with a fixed argv, speaks newline-delimited JSON-RPC
on its stdin/stdout, and emits Qt signals as results arrive. All protocol
decisions live in :mod:`javris.bridge.protocol`; this module owns only the
process lifecycle and the asynchronous plumbing.

Security posture. This is the GUI's single, documented extension of its "no
process execution" rule:

* one fixed argv (:data:`~javris.bridge.protocol.SPAWN_ARGV`), never composed
  from user input;
* spawned with :meth:`QProcess.start` taking a program and an argument list, so
  there is no shell and therefore no word-splitting or injection surface;
* stdin/stdout pipes only -- no sockets, no network, no credentials;
* ``allow`` is never set here. It arrives from :meth:`execute` as a parameter
  and the caller is responsible for having obtained an owner action first.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from . import protocol
from .protocol import Outcome, OutcomeKind

#: How long to wait for the handshake before declaring the kernel unreachable.
HANDSHAKE_TIMEOUT_MS = 10_000

#: How long any single tool call may take before it is abandoned.
#: Package operations are genuinely slow, so this is generous.
REQUEST_TIMEOUT_MS = 120_000


class KernelClient(QObject):
    """Owns the ``jarvis mcp serve`` child process and its request queue."""

    #: Connection reached the ready state; carries the kernel version string.
    connected = Signal(str)
    #: Connection ended or never started; carries a human-readable reason.
    disconnected = Signal(str)
    #: A tool call completed. Carries the request tag and the decided outcome.
    completed = Signal(str, object)
    #: A request began. Carries the request tag.
    started = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._buffer = ""
        self._next_id = 1
        self._pending: dict[int, str] = {}
        self._ready = False
        self._version = ""
        self._handshake_id: int | None = None

        self._handshake_timer = QTimer(self)
        self._handshake_timer.setSingleShot(True)
        self._handshake_timer.setInterval(HANDSHAKE_TIMEOUT_MS)
        self._handshake_timer.timeout.connect(self._on_handshake_timeout)

    # -- state -------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """True once the handshake has completed."""
        return self._ready

    @property
    def version(self) -> str:
        """Kernel version reported at handshake, or an empty string."""
        return self._version

    @staticmethod
    def executable() -> str | None:
        """Absolute path to the ``jarvis`` kernel, or None when absent.

        Two locations are searched, in order:

        1. ``PATH``, the normal case for a system-wide or user install.
        2. The bin directory of the running interpreter's environment. When the
           GUI is installed into a virtualenv alongside the kernel, that
           directory is frequently not on the bare ``PATH`` of the desktop
           session that launched us, yet it is unambiguously the same install.

        No other directory is searched. Guessing at kernel locations would mean
        the GUI could execute a binary the operator never pointed it at.
        """
        name = protocol.SPAWN_ARGV[0]
        found = shutil.which(name)
        if found is not None:
            return found
        sibling = Path(sys.executable).parent / name
        if sibling.is_file() and os.access(sibling, os.X_OK):
            return str(sibling)
        return None

    @staticmethod
    def available() -> bool:
        """True when the kernel can be located.

        Checked before spawning so a missing kernel becomes an honest OFFLINE
        state rather than a process-start failure the user cannot interpret.
        """
        return KernelClient.executable() is not None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Spawn the kernel and begin the handshake.

        Returns False when the kernel is absent or already running. The GUI
        treats False as "stay OFFLINE and keep showing telemetry", never as a
        reason to stop.
        """
        if self._process is not None:
            return False
        if not self.available():
            self.disconnected.emit(
                "jarvis kernel not found on PATH; agent features are unavailable."
            )
            return False

        process = QProcess(self)
        program = self.executable()
        if program is None:  # pragma: no cover - guarded by available() above
            return False
        _, *arguments = protocol.SPAWN_ARGV
        # Program and argument list are passed separately: QProcess does not
        # involve a shell, so nothing here can be word-split or injected.
        process.setProgram(program)
        process.setArguments(arguments)
        # The server's diagnostics go to stderr and must never be parsed as
        # protocol. Keeping the channels separate is part of the contract.
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._on_stdout)
        process.errorOccurred.connect(self._on_process_error)
        process.finished.connect(self._on_finished)

        self._process = process
        process.start()
        if not process.waitForStarted(3000):
            self._process = None
            self.disconnected.emit("The jarvis kernel failed to start.")
            return False

        self._handshake_id = self._send(
            protocol.build_initialize(self._take_id()), tag="__initialize__"
        )
        self._handshake_timer.start()
        return True

    def stop(self) -> None:
        """Terminate the child process and reset to a disconnected state.

        SIGTERM first, then a bounded wait, then SIGKILL. A kernel that ignores
        termination must not be able to keep the GUI alive after it closes.
        """
        self._handshake_timer.stop()
        process = self._process
        self._process = None
        self._ready = False
        self._version = ""
        self._pending.clear()
        self._buffer = ""

        if process is None:
            return
        process.readyReadStandardOutput.disconnect()
        process.finished.disconnect()
        process.errorOccurred.disconnect()
        if process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not process.waitForFinished(2000):
                process.kill()
                process.waitForFinished(1000)
        self.disconnected.emit("Agent disconnected.")

    # -- requests ----------------------------------------------------------

    def call(self, tool: str, arguments: dict[str, Any], *, tag: str) -> bool:
        """Issue a read-only tool call.

        Raises:
            ValueError: If ``tool`` requires consent. Consent-bearing calls go
                through :meth:`execute`, so the two paths cannot be confused at
                a call site.
        """
        if tool in protocol.CONSENT_TOOLS:
            raise ValueError(f"{tool!r} requires consent; use execute() instead of call().")
        return self._dispatch(tool, arguments, allow=False, tag=tag)

    def execute(self, request: str, *, allow: bool, tag: str) -> bool:
        """Issue ``jarvis_do``.

        Args:
            allow: Pass True **only** when the owner has just consented through
                an explicit UI action, and only once per call. Passing True
                because a previous call was refused would defeat the entire
                consent model.
        """
        return self._dispatch("jarvis_do", {"request": request}, allow=allow, tag=tag)

    def _dispatch(self, tool: str, arguments: dict[str, Any], *, allow: bool, tag: str) -> bool:
        if not self._ready or self._process is None:
            return False
        try:
            line = protocol.build_tool_call(self._take_id(), tool, arguments, allow=allow)
        except ValueError:
            # A programming error in the caller. Refuse to send rather than
            # emitting a malformed or over-privileged frame.
            return False
        # _take_id already advanced, so recover the id actually used.
        message_id = self._next_id - 1
        self._pending[message_id] = tag
        self._write(line)
        self.started.emit(tag)
        QTimer.singleShot(REQUEST_TIMEOUT_MS, lambda: self._expire(message_id))
        return True

    def _expire(self, message_id: int) -> None:
        """Abandon a request that never came back."""
        tag = self._pending.pop(message_id, None)
        if tag is None:
            return
        self.completed.emit(
            tag,
            Outcome(
                kind=OutcomeKind.PROTOCOL_ERROR,
                text="The kernel did not answer in time; the request was abandoned.",
            ),
        )

    # -- plumbing ----------------------------------------------------------

    def _take_id(self) -> int:
        message_id = self._next_id
        self._next_id += 1
        return message_id

    def _send(self, line: str, *, tag: str) -> int:
        message_id = self._next_id - 1
        self._pending[message_id] = tag
        self._write(line)
        return message_id

    def _write(self, line: str) -> None:
        if self._process is None:
            return
        self._process.write(line.encode("utf-8"))

    def _on_stdout(self) -> None:
        """Accumulate stdout and dispatch each complete line.

        Buffering is required: a pipe read can split a JSON object across two
        chunks, and parsing a partial line would corrupt the stream.
        """
        process = self._process
        if process is None:
            return
        # errors="replace": a malformed byte must degrade one character, not
        # raise inside a Qt slot where the exception has nowhere to go. The
        # bytes() call narrows PySide6's buffer union to a concrete type.
        raw = bytes(process.readAllStandardOutput().data())
        chunk = raw.decode("utf-8", errors="replace")
        self._buffer += chunk

        while "\n" in self._buffer:
            line, _, self._buffer = self._buffer.partition("\n")
            message = protocol.parse_line(line)
            if message is not None:
                self._handle(message)

    def _handle(self, message: dict[str, Any]) -> None:
        message_id = message.get("id")
        if not isinstance(message_id, int):
            # A notification from the server. Nothing in the contract requires
            # the client to act on one, so it is ignored rather than guessed at.
            return

        tag = self._pending.pop(message_id, None)
        if tag is None:
            return

        if tag == "__initialize__":
            self._complete_handshake(message)
            return

        self.completed.emit(tag, protocol.classify_outcome(message))

    def _complete_handshake(self, message: dict[str, Any]) -> None:
        self._handshake_timer.stop()
        result = message.get("result")
        if not isinstance(result, dict):
            self.stop()
            self.disconnected.emit("The kernel's handshake response was malformed.")
            return

        self._version = protocol.server_version(result) or "unknown"
        self._ready = True
        # Notification carries no id and expects no response.
        self._write(protocol.build_initialized_notification())
        self.connected.emit(self._version)

    def _on_handshake_timeout(self) -> None:
        self.stop()
        self.disconnected.emit("The kernel did not complete its handshake.")

    def _on_process_error(self, _error: QProcess.ProcessError) -> None:
        if self._process is None:
            return
        self._ready = False
        self.disconnected.emit("The kernel process reported an error.")

    def _on_finished(self, _code: int, _status: QProcess.ExitStatus) -> None:
        self._ready = False
        self._process = None
        self._pending.clear()
        self.disconnected.emit("The kernel process exited.")
