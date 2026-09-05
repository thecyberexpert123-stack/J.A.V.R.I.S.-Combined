"""Periodic sampling of :class:`~javris.telemetry.proc_reader.ProcReader`.

Rate-derived metrics (CPU utilisation, network throughput) need two samples, so
the first poll after start deliberately reports ``None`` for them rather than
inventing a value from a single reading.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .models import CpuTimes, NetworkCounters, TelemetrySnapshot
from .proc_reader import ProcReader

#: Minimum sane polling interval, in milliseconds. Below this, jiffy deltas are
#: too small to be meaningful and the poll itself distorts the measurement.
MIN_INTERVAL_MS = 200


class TelemetrySampler:
    """Turns successive :class:`ProcReader` readings into snapshots.

    This class is deliberately free of any Qt dependency so it can be unit
    tested without an event loop or a display. :class:`TelemetryService` owns
    the Qt timer and delegates all measurement here.

    Args:
        reader: The source of kernel counters.
        clock: Monotonic time source, in seconds. Injectable for testing.
    """

    def __init__(
        self,
        reader: ProcReader | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reader = reader if reader is not None else ProcReader()
        self._clock = clock
        self._previous_cpu: CpuTimes | None = None
        self._previous_cores: tuple[CpuTimes, ...] = ()
        self._previous_net: NetworkCounters | None = None
        self._previous_time: float | None = None

    def sample(self) -> TelemetrySnapshot:
        """Take one reading of every source and return a snapshot.

        Never raises: any source that fails is reported as ``None`` and named
        in :attr:`TelemetrySnapshot.degraded_sources`.
        """
        now = self._clock()
        degraded: list[str] = []

        cpu_total, cpu_cores = self._reader.cpu_times()
        total_percent: float | None = None
        if cpu_total is None:
            degraded.append("cpu")
        elif self._previous_cpu is not None:
            fraction = ProcReader.utilisation(self._previous_cpu, cpu_total)
            total_percent = None if fraction is None else fraction * 100.0
        self._previous_cpu = cpu_total

        core_percents: list[float] = []
        if cpu_cores and len(cpu_cores) == len(self._previous_cores):
            for before, after in zip(self._previous_cores, cpu_cores, strict=True):
                fraction = ProcReader.utilisation(before, after)
                core_percents.append(0.0 if fraction is None else fraction * 100.0)
        self._previous_cores = cpu_cores

        memory = self._reader.memory()
        if memory is None:
            degraded.append("memory")

        load = self._reader.load_average()
        if load is None:
            degraded.append("loadavg")

        uptime = self._reader.uptime_seconds()
        if uptime is None:
            degraded.append("uptime")

        temperature = self._reader.temperature_celsius()
        if temperature is None:
            degraded.append("thermal")

        disks = self._reader.disks()
        if not disks:
            degraded.append("storage")

        # A machine with no battery is not degraded -- desktops and VMs simply
        # have none, so absence here is a fact about the host, not a failure.
        battery = self._reader.read_battery()

        rx_rate: float | None = None
        tx_rate: float | None = None
        net = self._reader.network_counters()
        if net is None:
            degraded.append("network")
        elif self._previous_net is not None and self._previous_time is not None:
            rates = ProcReader.throughput(self._previous_net, net, now - self._previous_time)
            if rates is not None:
                rx_rate, tx_rate = rates
        self._previous_net = net
        self._previous_time = now

        return TelemetrySnapshot(
            monotonic_time=now,
            cpu_total_percent=total_percent,
            cpu_core_percents=tuple(core_percents),
            memory=memory,
            load_average=load,
            uptime_seconds=uptime,
            temperature_celsius=temperature,
            disks=disks,
            net_rx_bytes_per_sec=rx_rate,
            net_tx_bytes_per_sec=tx_rate,
            battery=battery,
            degraded_sources=tuple(degraded),
        )
