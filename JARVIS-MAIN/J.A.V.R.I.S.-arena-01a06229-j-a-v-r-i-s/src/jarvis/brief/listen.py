"""The opt-in signal listener, ``jarvis brief listen`` (ADR-0031 D8).

A small resident process — its own unit, ``jarvis-signals.service``, never
inside the doorway (ADR-0018's contract is untouched) — that subscribes to
four broadcast signals on the system bus through the stdlib client and has
exactly two powers:

1. **record**: ``PrepareForSleep`` / ``PrepareForShutdown`` (logind), the
   session's ``LockedHint`` and NetworkManager's ``Metered`` / ``Connectivity``
   changes become ``{"kind": "event"}`` rows in the briefing ledger;
2. **deliver late**: when a hold clears — the session unlocks or the machine
   resumes — the day's *held* briefing (composed earlier by the timer,
   withheld because the screen was locked or sleep was imminent) is delivered
   with the same ``notify-send`` line the timer would have used, once per
   briefing id.

It never composes a briefing, never touches the planner, never executes.
The only D-Bus frames it originates are ``Hello``, ``AddMatch`` and
``Properties.Get`` (to re-read ``LockedHint`` on the caller-relative
``session/auto`` object, which logind resolves to the owner's session — so
the listener never has to guess a session path). Without a bus it stays up
and retries with back-off; ``systemd`` supervision is the same ``sd_notify``
client the doorway uses (``READY``, ``WATCHDOG``, ``STATUS``, ``STOPPING``).
"""

from __future__ import annotations

import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.brief.engine import Briefing, BriefLedger, desktop_notify
from jarvis.brief.signals import (
    LOGIN1,
    LOGIN1_MANAGER,
    LOGIN1_SESSION,
    NM,
    NM_PATH,
    SESSION_AUTO,
    metered_from_enum,
)
from jarvis.system import dbus_client, sdnotify
from jarvis.system.dbus_client import BusConnection, BusError, Message, RemoteError, Variant

__all__ = ["MATCH_RULES", "Listener", "run_listener"]

MATCH_RULES: tuple[str, ...] = (
    dbus_client.match_rule(
        type="signal", sender=LOGIN1, interface=LOGIN1_MANAGER, member="PrepareForSleep"
    ),
    dbus_client.match_rule(
        type="signal", sender=LOGIN1, interface=LOGIN1_MANAGER, member="PrepareForShutdown"
    ),
    dbus_client.match_rule(
        type="signal",
        sender=LOGIN1,
        interface=dbus_client.PROPERTIES_IFACE,
        member="PropertiesChanged",
        path_namespace="/org/freedesktop/login1/session",
    ),
    dbus_client.match_rule(
        type="signal",
        sender=NM,
        interface=dbus_client.PROPERTIES_IFACE,
        member="PropertiesChanged",
        path=NM_PATH,
    ),
)

POLL_SECONDS = 1.0
BACKOFF_START = 2.0
BACKOFF_MAX = 60.0
MAX_EVENTS_PER_HOUR = 120
RETRY_DELIVERY_AFTER = 300.0


def _log(line: str) -> None:
    print(f"[jarvis-signals] {line}", file=sys.stderr, flush=True)


@dataclass
class Listener:
    """The event loop's state; ``handle()`` is pure enough to test with fake frames."""

    ledger: BriefLedger
    record_only: bool = False
    notify: Callable[[str], bool] = desktop_notify
    clock: Callable[[], float] = time.monotonic
    log: Callable[[str], None] = _log
    conn: BusConnection | None = None
    locked: bool | None = None
    events_this_hour: int = 0
    hour_started: float = 0.0
    attempted: dict[str, float] = field(default_factory=dict)
    delivered_total: int = 0
    events_total: int = 0

    # -- subscription -------------------------------------------------------------

    def subscribe(self, address: str | None = None) -> str:
        """Connect, Hello, one AddMatch per rule, read the initial LockedHint."""
        conn = BusConnection.connect(address)
        try:
            for rule in MATCH_RULES:
                conn.add_match(rule)
        except BusError:
            conn.close()
            raise
        self.conn = conn
        self.locked = self._poll_locked()
        self.record("bus", {"state": "connected", "locked": self.locked})
        return conn.unique_name or ""

    def disconnect(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # -- events -------------------------------------------------------------------

    def handle(self, message: Message) -> None:
        """Dispatch one SIGNAL frame; anything unexpected is ignored, never raised."""
        if message.kind != dbus_client.MESSAGE_SIGNAL:
            return
        if message.interface == LOGIN1_MANAGER and message.member == "PrepareForSleep":
            starting = bool(message.body[0]) if message.body else None
            if starting is None:
                return
            self.record("sleep" if starting else "resume", {})
            if not starting:
                self.locked = self._poll_locked()
                self.deliver_if_clear("resume")
        elif message.interface == LOGIN1_MANAGER and message.member == "PrepareForShutdown":
            if message.body and bool(message.body[0]):
                self.record("shutdown", {})
        elif message.interface == dbus_client.PROPERTIES_IFACE and (
            message.member == "PropertiesChanged"
        ):
            self._properties_changed(message)

    def _properties_changed(self, message: Message) -> None:
        if len(message.body) < 2 or not isinstance(message.body[1], dict):
            return
        iface = str(message.body[0])
        changed = message.body[1]
        if iface == LOGIN1_SESSION and "LockedHint" in changed:
            # A change on *some* session (maybe another user's): re-read ours.
            now_locked = self._poll_locked()
            if now_locked is None or now_locked == self.locked:
                self.locked = now_locked
                return
            previous, self.locked = self.locked, now_locked
            self.record("lock" if now_locked else "unlock", {"previous": previous})
            if not now_locked:
                self.deliver_if_clear("unlock")
        elif iface == NM and ("Metered" in changed or "Connectivity" in changed):
            detail: dict[str, object] = {}
            metered = changed.get("Metered")
            if isinstance(metered, Variant) and metered.signature == "u":
                detail["metered"] = metered_from_enum(metered.value)
            connectivity = changed.get("Connectivity")
            if isinstance(connectivity, Variant) and connectivity.signature == "u":
                detail["connectivity"] = connectivity.value
            if detail:
                self.record("network", detail)

    def _poll_locked(self) -> bool | None:
        if self.conn is None:
            return None
        try:
            value = self.conn.get_property(LOGIN1, SESSION_AUTO, LOGIN1_SESSION, "LockedHint")
        except RemoteError:
            return None  # no session resolvable for this caller (ASSUMED rare; see ADR)
        except BusError:
            self.disconnect()
            return None
        return value.value if value.signature == "b" and isinstance(value.value, bool) else None

    # -- the two powers -----------------------------------------------------------

    def record(self, event: str, detail: dict[str, object]) -> None:
        now = self.clock()
        if now - self.hour_started >= 3600:
            self.hour_started = now
            self.events_this_hour = 0
        self.events_this_hour += 1
        if self.events_this_hour > MAX_EVENTS_PER_HOUR:
            if self.events_this_hour == MAX_EVENTS_PER_HOUR + 1:
                self.ledger.record_event("event-limit", {"per_hour": MAX_EVENTS_PER_HOUR})
            return
        self.events_total += 1
        self.ledger.record_event(event, detail)

    def deliver_if_clear(self, trigger: str) -> bool:
        """Deliver today's held briefing if no hold remains; once per id."""
        if self.record_only or self.locked is True:
            return False
        held = self.ledger.held_undelivered()
        if held is None:
            return False
        briefing_id = str(held.get("id"))
        last = self.attempted.get(briefing_id)
        if last is not None and self.clock() - last < RETRY_DELIVERY_AFTER:
            return False
        self.attempted[briefing_id] = self.clock()
        reasons = held.get("reasons")
        items = tuple(str(r) for r in reasons) if isinstance(reasons, list) else ()
        line = Briefing(briefing_id=briefing_id, created=str(held.get("ts")), items=items)
        delivered = self.notify(line.notify_line())
        self.ledger.record_delivery(briefing_id, trigger=trigger, delivered=delivered)
        if delivered:
            self.delivered_total += 1
        self.log(
            f"held briefing {briefing_id} on {trigger}: "
            f"{'delivered' if delivered else 'desktop notification unavailable'}"
        )
        return delivered

    def status_line(self) -> str:
        bus = "subscribed" if self.conn is not None else "no bus (retrying)"
        return (
            f"{bus}; {self.events_total} event(s) recorded; "
            f"{self.delivered_total} late delivery(ies)"
            + ("; record-only" if self.record_only else "")
        )


def run_listener(
    *,
    record_only: bool = False,
    state: Path | None = None,
    address: str | None = None,
    once: bool = False,
) -> int:
    """The process entry point; returns when SIGTERM/SIGINT arrives (or after one pass)."""
    notifier = sdnotify.from_environment()
    listener = Listener(BriefLedger(state), record_only=record_only)
    stop = False

    def _stop(signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True
        _log(f"signal {signum}: shutting down")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    backoff = BACKOFF_START
    next_attempt = 0.0
    _log(
        "listening for PrepareForSleep / PrepareForShutdown / LockedHint / NetworkManager "
        "changes; powers: record" + ("" if record_only else " + deliver held briefing")
    )
    notifier.ready(listener.status_line())
    try:
        while not stop:
            notifier.watchdog()
            if listener.conn is None:
                now = time.monotonic()
                if now >= next_attempt:
                    try:
                        unique = listener.subscribe(address)
                        backoff = BACKOFF_START
                        _log(f"subscribed as {unique}")
                        notifier.status(listener.status_line())
                    except BusError as exc:
                        _log(f"bus unavailable ({exc}); retry in {backoff:g}s")
                        notifier.status(listener.status_line())
                        next_attempt = now + backoff
                        backoff = min(backoff * 2, BACKOFF_MAX)
                if listener.conn is None:
                    if once:
                        break
                    time.sleep(min(POLL_SECONDS, max(0.0, next_attempt - time.monotonic())))
                    continue
            assert listener.conn is not None
            try:
                message = listener.conn.next_signal(POLL_SECONDS)
            except BusError as exc:
                _log(f"bus connection lost ({exc}); reconnecting")
                listener.disconnect()
                listener.record("bus", {"state": "lost"})
                next_attempt = time.monotonic() + backoff
                continue
            if message is not None:
                listener.handle(message)
                notifier.status(listener.status_line())
            if once:
                break
    finally:
        notifier.stopping()
        listener.disconnect()
    return 0
