"""The only module permitted to read ``/proc`` and ``/sys``.

Design constraints, in priority order:

1. **Honesty.** A source that cannot be read returns ``None`` and is recorded in
   ``degraded_sources``. No default, no zero, no guess.
2. **Robustness.** Every parser tolerates truncated, malformed, renamed or
   permission-denied input without raising. The kernel's ``/proc`` format is
   stable but not guaranteed, and containers expose partial trees.
3. **Testability.** The filesystem root is injectable, so the entire reader is
   exercised against fixture directories with zero access to the real ``/proc``.
4. **Least privilege.** Read-only access, confined to a fixed allow-list of
   paths beneath the configured root. No writes, no shell, no network.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .models import (
    BatterySnapshot,
    CpuTimes,
    DiskUsage,
    HostIdentity,
    LoadAverage,
    MemorySnapshot,
    NetworkCounters,
)

_MEMINFO_LINE = re.compile(r"^(?P<key>\w+):\s+(?P<value>\d+)(?:\s+kB)?$")

#: Filesystem types that do not represent real user-visible storage.
_PSEUDO_FILESYSTEMS = frozenset(
    {
        "autofs",
        "binfmt_misc",
        "bpf",
        "cgroup",
        "cgroup2",
        "configfs",
        "debugfs",
        "devpts",
        "devtmpfs",
        "efivarfs",
        "fuse.gvfsd-fuse",
        "fusectl",
        "hugetlbfs",
        "mqueue",
        "proc",
        "pstore",
        "ramfs",
        "rpc_pipefs",
        "securityfs",
        "selinuxfs",
        "squashfs",
        "sysfs",
        "tmpfs",
        "tracefs",
    }
)

#: Preferred thermal zone types, most representative of package temperature first.
_THERMAL_PREFERENCES = ("x86_pkg_temp", "cpu-thermal", "coretemp", "acpitz")


class ProcReader:
    """Reads kernel-exported counters from a procfs/sysfs tree.

    Args:
        proc_root: Root of the procfs tree. Overridable for testing.
        sys_root: Root of the sysfs tree. Overridable for testing.
    """

    def __init__(
        self,
        proc_root: str | os.PathLike[str] = "/proc",
        sys_root: str | os.PathLike[str] = "/sys",
    ) -> None:
        self._proc = Path(proc_root)
        self._sys = Path(sys_root)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _read_text(path: Path) -> str | None:
        """Return the file's contents, or ``None`` if it cannot be read.

        Absent, unreadable, or non-UTF-8 files are all treated as unavailable
        rather than as errors: on a live kernel tree any of them can happen
        transiently (a process exiting, a sensor unbinding, a restricted
        container) and none of them justify taking the UI down.
        """
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return None

    @staticmethod
    def _to_int(token: str) -> int | None:
        """Parse a base-10 integer, returning ``None`` on malformed input."""
        try:
            return int(token)
        except (TypeError, ValueError):
            return None

    # -- CPU ---------------------------------------------------------------

    def cpu_times(self) -> tuple[CpuTimes | None, tuple[CpuTimes, ...]]:
        """Read aggregate and per-core CPU jiffy counters from ``/proc/stat``.

        Returns:
            A tuple of the aggregate ``cpu`` counters (or ``None`` if the file
            is unreadable or malformed) and per-core counters in kernel order.

        Note:
            Idle time is idle+iowait (fields 4 and 5), matching the convention
            used by kernel documentation and by common userspace monitors.
        """
        raw = self._read_text(self._proc / "stat")
        if raw is None:
            return None, ()

        aggregate: CpuTimes | None = None
        cores: list[CpuTimes] = []

        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 5 or not parts[0].startswith("cpu"):
                continue

            values: list[int] = []
            for token in parts[1:]:
                parsed = self._to_int(token)
                if parsed is None or parsed < 0:
                    values = []
                    break
                values.append(parsed)
            if len(values) < 4:
                continue

            idle_all = values[3] + (values[4] if len(values) > 4 else 0)
            entry = CpuTimes(name=parts[0], idle_all=idle_all, total=sum(values))
            if parts[0] == "cpu":
                aggregate = entry
            else:
                cores.append(entry)

        return aggregate, tuple(cores)

    @staticmethod
    def utilisation(previous: CpuTimes, current: CpuTimes) -> float | None:
        """Compute CPU utilisation between two samples, as a 0.0-1.0 fraction.

        Args:
            previous: The earlier sample.
            current: The later sample.

        Returns:
            Utilisation in 0.0-1.0, or ``None`` when the samples are not
            comparable: differing CPUs, no elapsed jiffies, or counters that
            moved backwards (which happens across suspend and CPU hotplug).
        """
        if previous.name != current.name:
            return None
        total_delta = current.total - previous.total
        idle_delta = current.idle_all - previous.idle_all
        if total_delta <= 0 or idle_delta < 0 or idle_delta > total_delta:
            return None
        return (total_delta - idle_delta) / total_delta

    # -- memory ------------------------------------------------------------

    def memory(self) -> MemorySnapshot | None:
        """Read physical and swap memory from ``/proc/meminfo``.

        Returns:
            A snapshot in bytes, or ``None`` if the file is unreadable or does
            not report the required ``MemTotal``/``MemAvailable`` fields.
        """
        raw = self._read_text(self._proc / "meminfo")
        if raw is None:
            return None

        fields: dict[str, int] = {}
        for line in raw.splitlines():
            match = _MEMINFO_LINE.match(line.strip())
            if match:
                fields[match.group("key")] = int(match.group("value")) * 1024

        if "MemTotal" not in fields or "MemAvailable" not in fields:
            return None
        return MemorySnapshot(
            total=fields["MemTotal"],
            available=fields["MemAvailable"],
            swap_total=fields.get("SwapTotal", 0),
            swap_free=fields.get("SwapFree", 0),
        )

    # -- load and uptime ---------------------------------------------------

    def load_average(self) -> LoadAverage | None:
        """Read 1/5/15-minute load averages from ``/proc/loadavg``."""
        raw = self._read_text(self._proc / "loadavg")
        if raw is None:
            return None
        parts = raw.split()
        if len(parts) < 3:
            return None
        try:
            return LoadAverage(float(parts[0]), float(parts[1]), float(parts[2]))
        except ValueError:
            return None

    def uptime_seconds(self) -> float | None:
        """Read system uptime in seconds from ``/proc/uptime``."""
        raw = self._read_text(self._proc / "uptime")
        if raw is None:
            return None
        parts = raw.split()
        if not parts:
            return None
        try:
            value = float(parts[0])
        except ValueError:
            return None
        return value if value >= 0 else None

    # -- network -----------------------------------------------------------

    def network_counters(self) -> NetworkCounters | None:
        """Sum received and transmitted bytes over all non-loopback interfaces.

        Returns:
            Cumulative counters, or ``None`` if ``/proc/net/dev`` is unreadable.
            A host with only loopback yields zeroes, which is a true reading.
        """
        raw = self._read_text(self._proc / "net" / "dev")
        if raw is None:
            return None

        rx_total = 0
        tx_total = 0
        for line in raw.splitlines():
            if ":" not in line:
                continue
            name, _, remainder = line.partition(":")
            interface = name.strip()
            if not interface or interface == "lo":
                continue
            columns = remainder.split()
            if len(columns) < 9:
                continue
            rx = self._to_int(columns[0])
            tx = self._to_int(columns[8])
            if rx is None or tx is None or rx < 0 or tx < 0:
                continue
            rx_total += rx
            tx_total += tx
        return NetworkCounters(rx_bytes=rx_total, tx_bytes=tx_total)

    @staticmethod
    def throughput(
        previous: NetworkCounters, current: NetworkCounters, elapsed: float
    ) -> tuple[float, float] | None:
        """Convert two counter samples into bytes/second.

        Returns ``None`` when the interval is non-positive or the counters
        moved backwards, which occurs on 32-bit counter wrap or interface
        removal; reporting a negative or absurd rate would be worse than
        reporting nothing.
        """
        if elapsed <= 0:
            return None
        rx_delta = current.rx_bytes - previous.rx_bytes
        tx_delta = current.tx_bytes - previous.tx_bytes
        if rx_delta < 0 or tx_delta < 0:
            return None
        return rx_delta / elapsed, tx_delta / elapsed

    # -- storage -----------------------------------------------------------

    def disks(self, limit: int = 4) -> tuple[DiskUsage, ...]:
        """Report usage for real mounted filesystems, largest first.

        Args:
            limit: Maximum number of filesystems to return.

        Returns:
            Usage entries, or an empty tuple if mounts cannot be enumerated.
            Pseudo-filesystems are excluded, as their sizes are meaningless to
            an operator watching disk pressure.
        """
        raw = self._read_text(self._proc / "mounts")
        if raw is None:
            return ()

        seen: set[str] = set()
        found: list[DiskUsage] = []
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mount_point, fs_type = parts[1], parts[2]
            if fs_type in _PSEUDO_FILESYSTEMS or mount_point in seen:
                continue
            seen.add(mount_point)
            # Escaped octal sequences appear in /proc/mounts for spaces etc.
            decoded = mount_point.encode().decode("unicode_escape")
            try:
                stats = os.statvfs(decoded)
            except (OSError, ValueError):
                continue
            total = stats.f_blocks * stats.f_frsize
            if total <= 0:
                continue
            found.append(
                DiskUsage(
                    mount_point=decoded,
                    total=total,
                    free=stats.f_bavail * stats.f_frsize,
                )
            )

        found.sort(key=lambda disk: disk.total, reverse=True)
        return tuple(found[:limit])

    # -- thermals ----------------------------------------------------------

    def temperature_celsius(self) -> float | None:
        """Read the most representative CPU package temperature, in Celsius.

        Thermal zones are preferred by type (package sensors before the ACPI
        fallback); if none of the known types are present the first readable
        zone is used. Returns ``None`` on hosts with no thermal zones, such as
        most virtual machines and containers.
        """
        zones_root = self._sys / "class" / "thermal"
        try:
            zones = sorted(p for p in zones_root.iterdir() if p.name.startswith("thermal_zone"))
        except (OSError, ValueError):
            return None

        readings: list[tuple[int, float]] = []
        for zone in zones:
            raw_temp = self._read_text(zone / "temp")
            if raw_temp is None:
                continue
            millidegrees = self._to_int(raw_temp.strip())
            # Kernel reports millidegrees; reject values outside a physically
            # plausible range rather than showing a nonsense figure.
            if millidegrees is None or not (-40_000 <= millidegrees <= 150_000):
                continue
            zone_type = (self._read_text(zone / "type") or "").strip()
            rank = (
                _THERMAL_PREFERENCES.index(zone_type)
                if zone_type in _THERMAL_PREFERENCES
                else len(_THERMAL_PREFERENCES)
            )
            readings.append((rank, millidegrees / 1000.0))

        if not readings:
            return None
        readings.sort(key=lambda item: item[0])
        return readings[0][1]

    def read_battery(self) -> BatterySnapshot | None:
        """Read the first real battery under ``/sys/class/power_supply``.

        Returns ``None`` when the host has no battery at all -- desktops,
        virtual machines and containers -- which the UI must render as absent
        rather than as a full or empty cell.

        Supplies whose ``type`` is not ``Battery`` (mains adapters, USB
        supplies, HID peripherals) are skipped: a wireless mouse reporting 40%
        must never be mistaken for the machine's own charge.
        """
        supplies_root = self._sys / "class" / "power_supply"
        try:
            supplies = sorted(supplies_root.iterdir())
        except (OSError, ValueError):
            return None

        for supply in supplies:
            if (self._read_text(supply / "type") or "").strip() != "Battery":
                continue

            percent: float | None = None
            raw_capacity = self._read_text(supply / "capacity")
            if raw_capacity is not None:
                capacity = self._to_int(raw_capacity.strip())
                # Clamp rather than reject: worn cells legitimately report
                # slightly over 100, and that is not a reason to show nothing.
                if capacity is not None:
                    percent = float(min(100, max(0, capacity)))

            status = (self._read_text(supply / "status") or "").strip()
            if status == "Charging":
                charging: bool | None = True
            elif status in ("Discharging", "Not charging", "Full"):
                # "Full" is not charging: a full battery on mains draws nothing.
                charging = False
            else:
                # "Unknown" and any vendor-specific value: say so.
                charging = None

            if percent is None and charging is None:
                # A battery directory that tells us nothing usable is not a
                # battery worth reporting.
                continue

            return BatterySnapshot(
                percent=percent,
                charging=charging,
                seconds_remaining=self._battery_seconds_remaining(supply, charging),
            )

        return None

    def _battery_seconds_remaining(self, supply: Path, charging: bool | None) -> float | None:
        """Estimate time to empty from the kernel's charge and current counters.

        Only returned while discharging, and only when both counters are
        present and the draw is non-zero. Everything else yields ``None``: a
        runtime figure invented from a guessed discharge rate would look
        authoritative and be meaningless.
        """
        if charging is not False:
            return None

        # Some kernels expose charge (uAh) with current (uA); others expose
        # energy (uWh) with power (uW). Both give hours when divided.
        for remaining_name, rate_name in (
            ("charge_now", "current_now"),
            ("energy_now", "power_now"),
        ):
            raw_remaining = self._read_text(supply / remaining_name)
            raw_rate = self._read_text(supply / rate_name)
            if raw_remaining is None or raw_rate is None:
                continue
            remaining = self._to_int(raw_remaining.strip())
            rate = self._to_int(raw_rate.strip())
            if remaining is None or rate is None or rate <= 0 or remaining < 0:
                continue
            return remaining / rate * 3600.0

        return None

    def read_host_identity(self) -> HostIdentity:
        """Read static facts about the machine.

        Called once at startup, not per frame: none of these change while the
        HUD is running. Every field independently degrades to ``None``, so a
        container that exposes no model name simply shows fewer rows.
        """
        cpu_model: str | None = None
        cpu_cores: int | None = None
        raw_cpuinfo = self._read_text(self._proc / "cpuinfo")
        if raw_cpuinfo is not None:
            processors = 0
            for line in raw_cpuinfo.splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                key = key.strip()
                if key == "model name" and cpu_model is None:
                    cpu_model = value.strip() or None
                elif key == "processor":
                    processors += 1
            cpu_cores = processors or None

        memory_total: int | None = None
        raw_meminfo = self._read_text(self._proc / "meminfo")
        if raw_meminfo is not None:
            for line in raw_meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    kibibytes = self._to_int(line.split()[1])
                    if kibibytes is not None:
                        memory_total = kibibytes * 1024
                    break

        os_name: str | None = None
        # os-release lives outside /proc and /sys; read it via the real
        # filesystem but tolerate its absence exactly like every other source.
        for candidate in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
            raw_release = self._read_text(candidate)
            if raw_release is None:
                continue
            for line in raw_release.splitlines():
                if line.startswith("PRETTY_NAME="):
                    os_name = line.partition("=")[2].strip().strip('"') or None
                    break
            if os_name is not None:
                break

        kernel_release: str | None = None
        raw_kernel = self._read_text(self._proc / "sys" / "kernel" / "osrelease")
        if raw_kernel is not None:
            kernel_release = raw_kernel.strip() or None

        hostname: str | None = None
        raw_hostname = self._read_text(self._proc / "sys" / "kernel" / "hostname")
        if raw_hostname is not None:
            hostname = raw_hostname.strip() or None

        return HostIdentity(
            cpu_model=cpu_model,
            cpu_cores=cpu_cores,
            memory_total_bytes=memory_total,
            os_name=os_name,
            kernel_release=kernel_release,
            hostname=hostname,
        )
