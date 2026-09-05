"""Immutable value objects describing a single telemetry observation.

These types are the contract between the reader layer (which touches ``/proc``)
and the presentation layer (which must never touch it). Every field that can be
absent on a given machine is explicitly ``None`` rather than a fabricated value,
so the UI can render an honest ``UNAVAILABLE`` state instead of a plausible lie.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CpuTimes:
    """Cumulative jiffy counters for one CPU line of ``/proc/stat``.

    Attributes:
        name: The CPU identifier, e.g. ``"cpu"`` for the aggregate or ``"cpu0"``.
        idle_all: Idle plus iowait jiffies.
        total: Sum of every reported jiffy field.
    """

    name: str
    idle_all: int
    total: int


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """Physical and swap memory usage, in bytes."""

    total: int
    available: int
    swap_total: int
    swap_free: int

    @property
    def used(self) -> int:
        """Bytes of physical memory in use (total minus available)."""
        return max(0, self.total - self.available)

    @property
    def used_fraction(self) -> float:
        """Physical memory usage in the range 0.0-1.0; 0.0 when total is unknown."""
        if self.total <= 0:
            return 0.0
        return min(1.0, self.used / self.total)

    @property
    def swap_used(self) -> int:
        """Bytes of swap in use."""
        return max(0, self.swap_total - self.swap_free)

    @property
    def swap_used_fraction(self) -> float:
        """Swap usage in the range 0.0-1.0; 0.0 when no swap is configured."""
        if self.swap_total <= 0:
            return 0.0
        return min(1.0, self.swap_used / self.swap_total)


@dataclass(frozen=True, slots=True)
class NetworkCounters:
    """Cumulative byte counters across all non-loopback interfaces."""

    rx_bytes: int
    tx_bytes: int


@dataclass(frozen=True, slots=True)
class DiskUsage:
    """Usage of a single mounted filesystem, in bytes."""

    mount_point: str
    total: int
    free: int

    @property
    def used(self) -> int:
        """Bytes in use on this filesystem."""
        return max(0, self.total - self.free)

    @property
    def used_fraction(self) -> float:
        """Filesystem usage in the range 0.0-1.0; 0.0 when total is unknown."""
        if self.total <= 0:
            return 0.0
        return min(1.0, self.used / self.total)


@dataclass(frozen=True, slots=True)
class LoadAverage:
    """Kernel load averages over 1, 5 and 15 minutes."""

    one: float
    five: float
    fifteen: float


@dataclass(frozen=True, slots=True)
class BatterySnapshot:
    """Charge state of one power supply, read from ``/sys/class/power_supply``.

    Attributes:
        percent: Charge remaining, 0-100, or ``None`` if unreadable.
        charging: True when charging, False when discharging, ``None`` when the
            status is unknown or the supply reports something else entirely.
        seconds_remaining: Time to empty at the present rate, or ``None``. Only
            populated when the kernel exposes both a charge and a current, so
            it is a measurement rather than a guess.
    """

    percent: float | None = None
    charging: bool | None = None
    seconds_remaining: float | None = None


@dataclass(frozen=True, slots=True)
class HostIdentity:
    """Static facts about the machine. Read once; these do not change at runtime.

    Every field is optional: a container may expose none of them, and an
    invented model name would be exactly the kind of decorative fiction this
    project refuses.
    """

    cpu_model: str | None = None
    cpu_cores: int | None = None
    memory_total_bytes: int | None = None
    os_name: str | None = None
    kernel_release: str | None = None
    hostname: str | None = None


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    """A complete, self-consistent reading of the machine at one instant.

    ``None`` on any field means the source was unreadable or unsupported on this
    host. Consumers must render that as unavailable, never as zero.
    """

    monotonic_time: float
    cpu_total_percent: float | None = None
    cpu_core_percents: tuple[float, ...] = ()
    memory: MemorySnapshot | None = None
    load_average: LoadAverage | None = None
    uptime_seconds: float | None = None
    temperature_celsius: float | None = None
    disks: tuple[DiskUsage, ...] = ()
    net_rx_bytes_per_sec: float | None = None
    net_tx_bytes_per_sec: float | None = None
    battery: BatterySnapshot | None = None
    degraded_sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_degraded(self) -> bool:
        """True when at least one telemetry source could not be read."""
        return bool(self.degraded_sources)
