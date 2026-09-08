"""Environment signals for the briefing (ADR-0031 D1/D2): sensed, never acted on.

Six facts, each a *line* in the briefing or a *hold* on the desktop knock —
never a trigger, never an input to the planner:

- **S1** battery discharging at or below a threshold — sysfs, with the same
  ``type == Battery`` / clamp / status filter as the HUD's ``read_battery()``
- **S2** no network link — sysfs ``operstate`` (loopback excluded)
- **S3** metered connection — NetworkManager ``Metered`` ∈ {YES, GUESS_YES}
- **S4** sleep or shutdown imminent — logind ``PreparingForSleep`` /
  ``PreparingForShutdown`` → hold
- **S5** session locked — logind Session ``LockedHint`` → hold
- **S6** slept since the last briefing — ``/sys/power/suspend_stats/success``
  delta within one ``boot_id`` → recorded only

``sense(mode)`` is the only entry point: ``off`` senses nothing, ``sysfs``
reads S1/S2/S6 with ``open()`` on fixed paths, ``bus`` adds S3-S5 (and the
recorded ``IdleHint``) over one read-only connection from
``jarvis.system.dbus_client`` — no subprocess in any mode. Every value is
``None`` when *not sensed*; ``None`` never means "normal".
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jarvis.system import dbus_client
from jarvis.system.dbus_client import BusError, RemoteError, Variant

__all__ = [
    "BUS_PROPERTIES",
    "DEFAULT_BATTERY_LOW",
    "MODES",
    "Battery",
    "Signals",
    "SuspendCount",
    "holds_from_mapping",
    "metered_from_enum",
    "read_battery",
    "read_link",
    "read_suspend_count",
    "sense",
    "sense_bus",
]

MODES = ("off", "sysfs", "bus")
DEFAULT_BATTERY_LOW = 20
MAX_ATTR_BYTES = 256
ARPHRD_LOOPBACK = 772
BUS_CALL_TIMEOUT = 2.0
BUS_TOTAL_BUDGET = 6.0

LOGIN1 = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
LOGIN1_MANAGER = "org.freedesktop.login1.Manager"
LOGIN1_SESSION = "org.freedesktop.login1.Session"
SESSION_AUTO = "/org/freedesktop/login1/session/auto"
NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"

#: (key, destination, path, interface, property, expected signature)
BUS_PROPERTIES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("preparing_for_sleep", LOGIN1, LOGIN1_PATH, LOGIN1_MANAGER, "PreparingForSleep", "b"),
    ("preparing_for_shutdown", LOGIN1, LOGIN1_PATH, LOGIN1_MANAGER, "PreparingForShutdown", "b"),
    ("idle", LOGIN1, LOGIN1_PATH, LOGIN1_MANAGER, "IdleHint", "b"),
    ("locked", LOGIN1, SESSION_AUTO, LOGIN1_SESSION, "LockedHint", "b"),
    ("metered", NM, NM_PATH, NM, "Metered", "u"),
    ("connectivity", NM, NM_PATH, NM, "Connectivity", "u"),
)

# NMMetered: 0 UNKNOWN, 1 YES, 2 NO, 3 GUESS_YES, 4 GUESS_NO (nm-dbus-types)
_METERED_YES = {1, 3}
_METERED_NO = {2, 4}
_KNOWN_STATUS = {"Unknown", "Charging", "Discharging", "Not charging", "Full"}


@dataclass(frozen=True)
class Battery:
    percent: int | None
    status: str
    discharging: bool | None

    def to_json_dict(self) -> dict[str, object]:
        return {"percent": self.percent, "status": self.status, "discharging": self.discharging}


@dataclass(frozen=True)
class SuspendCount:
    boot_id: str
    success: int

    def to_json_dict(self) -> dict[str, object]:
        return {"boot_id": self.boot_id, "success": self.success}


@dataclass(frozen=True)
class Signals:
    """Everything sensed for one run; ``None`` = not sensed."""

    mode: str = "off"
    battery: Battery | None = None
    link: bool | None = None
    metered: bool | None = None
    connectivity: int | None = None
    locked: bool | None = None
    idle: bool | None = None
    preparing_for_sleep: bool | None = None
    preparing_for_shutdown: bool | None = None
    suspend: SuspendCount | None = None
    suspend_cycles: int | None = None
    bus: str = "off"

    @property
    def sensed(self) -> bool:
        """True when at least one fact was actually read (drives the context line)."""
        return any(
            value is not None
            for value in (
                self.battery,
                self.link,
                self.metered,
                self.connectivity,
                self.locked,
                self.idle,
                self.preparing_for_sleep,
                self.preparing_for_shutdown,
                self.suspend_cycles,
            )
        )

    def items(self, battery_low: int = DEFAULT_BATTERY_LOW) -> tuple[str, ...]:
        """S1-S3 as briefing lines. A fact that was not sensed never yields a line."""
        out: list[str] = []
        battery = self.battery
        if (
            battery is not None
            and battery.discharging is True
            and battery.percent is not None
            and battery.percent <= battery_low
        ):
            out.append(
                f"battery {battery.percent}% and discharging — not a moment for a long upgrade"
            )
        if self.link is False:
            out.append("no network link — package-index suggestions need a connection")
        if self.metered is True:
            out.append("on a metered link — a package refresh would spend it")
        return tuple(out)

    def holds(self) -> tuple[str, ...]:
        """S4/S5: only an explicit ``True`` holds — *not sensed* never does."""
        return holds_from_mapping(self.to_json_dict())

    def context_line(self) -> str | None:
        """One deterministic ``key: value`` line of what was sensed, or ``None``."""
        if not self.sensed:
            return None
        parts: list[str] = []
        if self.battery is not None:
            pct = "?" if self.battery.percent is None else f"{self.battery.percent}%"
            parts.append(f"battery {pct} ({self.battery.status.lower() or 'unknown'})")
        if self.link is not None:
            parts.append(f"link: {'up' if self.link else 'down'}")
        if self.metered is not None:
            parts.append(f"metered: {'yes' if self.metered else 'no'}")
        if self.connectivity is not None:
            parts.append(f"connectivity: {self.connectivity}")
        if self.locked is not None:
            parts.append(f"session: {'locked' if self.locked else 'unlocked'}")
        if self.idle is not None:
            parts.append(f"idle: {'yes' if self.idle else 'no'}")
        if self.preparing_for_sleep is not None:
            parts.append(f"sleep imminent: {'yes' if self.preparing_for_sleep else 'no'}")
        if self.preparing_for_shutdown is not None:
            parts.append(f"shutdown imminent: {'yes' if self.preparing_for_shutdown else 'no'}")
        if self.suspend_cycles is not None:
            parts.append(f"slept since last briefing: {self.suspend_cycles}")
        return "; ".join(parts)

    def to_json_dict(self) -> dict[str, object]:
        """The additive ``signals`` payload (ADR-0031 D4)."""
        return {
            "mode": self.mode,
            "battery": None if self.battery is None else self.battery.to_json_dict(),
            "network": {
                "link": self.link,
                "metered": self.metered,
                "connectivity": self.connectivity,
            },
            "session": {
                "locked": self.locked,
                "idle": self.idle,
                "preparing_for_sleep": self.preparing_for_sleep,
                "preparing_for_shutdown": self.preparing_for_shutdown,
            },
            "suspend": None if self.suspend is None else self.suspend.to_json_dict(),
            "suspend_cycles": self.suspend_cycles,
            "bus": self.bus,
        }


def holds_from_mapping(signals: Mapping[str, object]) -> tuple[str, ...]:
    """S4/S5 holds from a ``signals`` payload — only an explicit ``True`` holds."""
    session = signals.get("session")
    if not isinstance(session, Mapping):
        return ()
    holds: list[str] = []
    if session.get("preparing_for_sleep") is True:
        holds.append("sleep-imminent")
    if session.get("preparing_for_shutdown") is True:
        holds.append("shutdown-imminent")
    if session.get("locked") is True:
        holds.append("session-locked")
    return tuple(holds)


# --------------------------------------------------------------------------
# sysfs (zero subprocess; every failure = fact absent)
# --------------------------------------------------------------------------


def _read_attr(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_ATTR_BYTES)
    except (OSError, ValueError):
        return None
    return raw.decode("utf-8", errors="replace").strip()


def read_battery(root: Path = Path("/")) -> Battery | None:
    """The first real battery — the HUD's filter plus the kernel's ``scope``.

    Supplies whose ``type`` is not ``Battery`` are skipped (mains, USB, UPS),
    and so are batteries whose ``scope`` is ``Device``: the HID layer
    registers a wireless mouse's or keyboard's cell with
    ``POWER_SUPPLY_SCOPE_DEVICE`` precisely so user space can tell it from
    the machine's own (``System``) battery — a 40 % mouse must never read as
    a 40 % laptop, whatever the directory names sort to. ``capacity`` is
    clamped to 0-100 (worn cells report 101); ``status`` outside the
    documented set reads as unknown. A battery directory with neither a
    usable percentage nor a status is not a battery worth reporting.
    ``None`` = no battery (desktop, VM, container).
    """
    supplies_root = root / "sys" / "class" / "power_supply"
    try:
        supplies = sorted(supplies_root.iterdir())
    except (OSError, ValueError):
        return None
    for supply in supplies:
        if (_read_attr(supply / "type") or "") != "Battery":
            continue
        if _read_attr(supply / "scope") == "Device":
            continue
        percent: int | None = None
        raw_capacity = _read_attr(supply / "capacity")
        if raw_capacity is not None:
            try:
                percent = min(100, max(0, int(raw_capacity)))
            except ValueError:
                percent = None
        status = _read_attr(supply / "status") or ""
        if status not in _KNOWN_STATUS:
            status = "Unknown"
        discharging = None if status == "Unknown" else status == "Discharging"
        if percent is None and discharging is None:
            continue
        return Battery(percent=percent, status=status, discharging=discharging)
    return None


def read_link(root: Path = Path("/")) -> bool | None:
    """True when a non-loopback interface carries a link.

    ``operstate == "up"`` counts. So does ``unknown`` with ``carrier == 1``:
    the sysfs ABI says an ``unknown`` interface "must be considered for user
    data" because not every driver sets an operational state, and the
    kernel's carrier flag settles it (``carrier`` reads fail with EINVAL
    while the interface is administratively down, which reads as no link).
    ``None`` when there is no non-loopback interface to judge at all.
    """
    net_root = root / "sys" / "class" / "net"
    try:
        interfaces = sorted(net_root.iterdir())
    except (OSError, ValueError):
        return None
    judged = False
    for iface in interfaces:
        raw_type = _read_attr(iface / "type")
        try:
            if raw_type is not None and int(raw_type) == ARPHRD_LOOPBACK:
                continue
        except ValueError:
            pass
        operstate = _read_attr(iface / "operstate")
        if operstate is None:
            continue
        judged = True
        if operstate == "up":
            return True
        if operstate == "unknown" and _read_attr(iface / "carrier") == "1":
            return True
    return False if judged else None


def read_suspend_count(root: Path = Path("/")) -> SuspendCount | None:
    """``suspend_stats/success`` keyed by ``boot_id``; ``None`` on older kernels."""
    raw = _read_attr(root / "sys" / "power" / "suspend_stats" / "success")
    boot_id = _read_attr(root / "proc" / "sys" / "kernel" / "random" / "boot_id")
    if raw is None or not boot_id:
        return None
    try:
        return SuspendCount(boot_id=boot_id, success=int(raw))
    except ValueError:
        return None


def _suspend_cycles(current: SuspendCount | None, previous: object) -> int | None:
    if current is None or not isinstance(previous, Mapping):
        return None
    if previous.get("boot_id") != current.boot_id:
        return None
    before = previous.get("success")
    if not isinstance(before, int) or isinstance(before, bool):
        return None
    delta = current.success - before
    return delta if delta >= 0 else None


# --------------------------------------------------------------------------
# bus (read-only Properties.Get; a fact is absent on any error)
# --------------------------------------------------------------------------


def metered_from_enum(value: object) -> bool | None:
    """``NMMetered`` → metered? ``YES``/``GUESS_YES`` true, ``NO``/``GUESS_NO`` false,
    ``UNKNOWN`` (and anything undocumented) *not sensed* — never "no"."""
    if value in _METERED_YES:
        return True
    if value in _METERED_NO:
        return False
    return None


def _coerce(key: str, value: Variant, expected: str) -> object:
    if value.signature != expected:
        return None
    if key == "metered":
        return metered_from_enum(value.value)
    return value.value


def sense_bus(
    *,
    address: str | None = None,
    env: Mapping[str, str] | None = None,
    call_timeout: float = BUS_CALL_TIMEOUT,
    budget: float = BUS_TOTAL_BUDGET,
) -> dict[str, object]:
    """S3-S5 (+ idle) over one connection; returns ``{key: value…, "bus": status}``."""
    facts: dict[str, object] = {key: None for key, *_ in BUS_PROPERTIES}
    deadline = time.monotonic() + budget
    try:
        conn = dbus_client.BusConnection.connect(address, env=env, timeout=call_timeout)
    except BusError as exc:
        facts["bus"] = f"unavailable: {exc}"
        return facts
    with conn:
        for key, destination, path, interface, name, expected in BUS_PROPERTIES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                facts["bus"] = f"unavailable: budget of {budget:g}s exhausted"
                return facts
            try:
                variant = conn.get_property(
                    destination, path, interface, name, timeout=min(call_timeout, remaining)
                )
            except RemoteError:
                continue  # that service/property is absent; the fact stays None
            except BusError as exc:
                facts["bus"] = f"unavailable: {exc}"
                return facts
            facts[key] = _coerce(key, variant, expected)
    facts["bus"] = "ok"
    return facts


def sense(
    mode: str,
    *,
    root: Path = Path("/"),
    previous_suspend: object = None,
    bus_address: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Signals:
    """The one entry point; ``mode`` ∈ ``MODES``. ``off`` returns the empty value."""
    if mode not in MODES:
        raise ValueError(f"signals mode must be one of {', '.join(MODES)}, not {mode!r}")
    if mode == "off":
        return Signals()
    suspend = read_suspend_count(root)
    bus: dict[str, object] = {}
    if mode == "bus":
        bus = sense_bus(address=bus_address, env=env)
    return Signals(
        mode=mode,
        battery=read_battery(root),
        link=read_link(root),
        metered=_as_bool(bus.get("metered")),
        connectivity=_as_int(bus.get("connectivity")),
        locked=_as_bool(bus.get("locked")),
        idle=_as_bool(bus.get("idle")),
        preparing_for_sleep=_as_bool(bus.get("preparing_for_sleep")),
        preparing_for_shutdown=_as_bool(bus.get("preparing_for_shutdown")),
        suspend=suspend,
        suspend_cycles=_suspend_cycles(suspend, previous_suspend),
        bus=str(bus.get("bus", "off")),
    )


def _as_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
