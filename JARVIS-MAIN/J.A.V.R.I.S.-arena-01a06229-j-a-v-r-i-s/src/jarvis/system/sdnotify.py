"""Stdlib `sd_notify` client for the resident doorway (ADR-0029 D1).

The systemd notification protocol is a one-way stream of ``KEY=value`` lines
over an ``AF_UNIX``/``SOCK_DGRAM`` socket whose address arrives in
``$NOTIFY_SOCKET`` (a leading ``@`` means an abstract socket). systemd
documents the protocol as stable and ships a dependency-free Python client in
``sd_notify(3)``; this module follows it, adds the watchdog cadence from
``sd_watchdog_enabled(3)`` (ping at half of ``$WATCHDOG_USEC``) and keeps
every message inside the small set the doorway needs: ``READY=1``,
``STATUS=``, ``WATCHDOG=1``, ``STOPPING=1``.

Design points (each asserted by a test):

- **Inert outside systemd.** With ``$NOTIFY_SOCKET`` unset every method is a
  no-op; ``jarvis serve`` run by hand, in tests or in CI behaves exactly as
  before.
- **The environment is consumed.** The three variables are removed from
  ``os.environ`` at construction (the C API's ``unset_environment=1``), so
  playbook children spawned by the Runner — which copies ``os.environ`` —
  never inherit a notify socket or believe they are watchdog-supervised.
- **Pings only when addressed to us.** ``$WATCHDOG_PID``, when set, must equal
  our PID; otherwise the variables were meant for a process further up the
  tree and we neither ping nor claim supervision.
- **Never raises.** A failed send is logged once to stderr and swallowed: a
  status notification must never take the doorway down.
- **Never ``WATCHDOG=trigger``.** Policy failures (integrity drift, breaker
  open) mean *pause*, not restart-and-retry; this client cannot express a
  self-inflicted watchdog failure.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from collections.abc import Callable, MutableMapping

__all__ = ["SdNotify", "from_environment"]

_ENV_SOCKET = "NOTIFY_SOCKET"
_ENV_WATCHDOG_USEC = "WATCHDOG_USEC"
_ENV_WATCHDOG_PID = "WATCHDOG_PID"


def _sanitize_status(text: str) -> str:
    """One UTF-8 line, no control characters (the protocol is line-oriented)."""
    cleaned = "".join(ch if ch.isprintable() else " " for ch in text)
    return cleaned.strip()[:200]


class SdNotify:
    """A tiny, defensive sd_notify sender.

    ``address`` is the raw ``$NOTIFY_SOCKET`` value (``None`` → inert).
    ``watchdog_usec`` is the raw ``$WATCHDOG_USEC`` value if it applies to
    this process (``None`` → no pings). ``clock`` is injectable for tests.
    """

    def __init__(
        self,
        address: str | None,
        watchdog_usec: int | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._address = _socket_address(address) if address else None
        self._watchdog_usec = watchdog_usec if watchdog_usec and watchdog_usec > 0 else None
        self._clock = clock
        self._log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        self._last_ping: float | None = None
        self._failed_once = False

    # -- introspection -------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """True when a notify socket is present (we are under systemd)."""
        return self._address is not None

    @property
    def watchdog_enabled(self) -> bool:
        """True when systemd expects keep-alive pings from *this* process."""
        return self.enabled and self._watchdog_usec is not None

    @property
    def ping_interval_s(self) -> float | None:
        """Half of ``WATCHDOG_USEC`` in seconds (the documented convention)."""
        if self._watchdog_usec is None:
            return None
        return self._watchdog_usec / 2_000_000.0

    # -- the four messages the doorway uses --------------------------------

    def ready(self, status: str | None = None) -> None:
        """Start-up finished (``Type=notify`` waits for exactly this)."""
        lines = ["READY=1"]
        if status:
            lines.append(f"STATUS={_sanitize_status(status)}")
        self._send("\n".join(lines))

    def status(self, text: str) -> None:
        self._send(f"STATUS={_sanitize_status(text)}")

    def stopping(self) -> None:
        self._send("STOPPING=1")

    def watchdog(self, *, force: bool = False) -> bool:
        """Send ``WATCHDOG=1`` if the half-interval has elapsed.

        Returns True when a ping was sent. Cheap enough to call from the
        accept loop every ``poll_interval`` (one clock read when idle).
        """
        if not self.watchdog_enabled:
            return False
        now = self._clock()
        interval = self.ping_interval_s
        assert interval is not None
        if not force and self._last_ping is not None and now - self._last_ping < interval:
            return False
        self._last_ping = now
        self._send("WATCHDOG=1")
        return True

    # -- transport ----------------------------------------------------------

    def _send(self, message: str) -> None:
        if self._address is None:
            return
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
                sock.connect(self._address)
                sock.sendall(message.encode("utf-8"))
        except OSError as exc:
            if not self._failed_once:  # one line, then silence: never a log storm
                self._failed_once = True
                self._log(f"[jarvis-serve] sd_notify unavailable ({exc}); continuing without it")


def _socket_address(raw: str) -> str:
    """Translate ``$NOTIFY_SOCKET`` to a connect() address.

    A leading ``@`` denotes an abstract socket, which Python addresses with a
    leading NUL byte. Anything else must be an absolute path; systemd never
    sets a relative one, so a malformed value is treated as absent rather
    than guessed at.
    """
    if raw.startswith("@"):
        return "\0" + raw[1:]
    if raw.startswith("/"):
        return raw
    raise OSError(f"unsupported NOTIFY_SOCKET address {raw!r}")


def from_environment(
    env: MutableMapping[str, str] | None = None,
    *,
    pid: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] | None = None,
) -> SdNotify:
    """Build the client from (and consume) the systemd environment variables.

    Reads ``NOTIFY_SOCKET``, ``WATCHDOG_USEC`` and ``WATCHDOG_PID`` from ``env``
    (default: ``os.environ``) and **removes all three** so that children do
    not inherit them. Returns an inert client when the socket is unset or
    malformed, and a ping-less one when the watchdog variables address a
    different PID or do not parse.
    """
    mapping: MutableMapping[str, str] = os.environ if env is None else env
    address = mapping.pop(_ENV_SOCKET, None)
    raw_usec = mapping.pop(_ENV_WATCHDOG_USEC, None)
    raw_pid = mapping.pop(_ENV_WATCHDOG_PID, None)
    if address is not None:
        try:
            _socket_address(address)
        except OSError:
            address = None
    watchdog_usec: int | None = None
    if address is not None and raw_usec:
        try:
            watchdog_usec = int(raw_usec)
        except ValueError:
            watchdog_usec = None
        own_pid = os.getpid() if pid is None else pid
        if raw_pid and raw_pid.strip() != str(own_pid):
            watchdog_usec = None
    return SdNotify(address, watchdog_usec, clock=clock, log=log)
