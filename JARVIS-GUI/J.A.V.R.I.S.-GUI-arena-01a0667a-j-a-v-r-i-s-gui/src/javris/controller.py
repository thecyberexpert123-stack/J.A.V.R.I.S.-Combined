"""The single QML-facing object: state, telemetry properties and command entry.

QML reads from here and never mutates anything except through the explicit
``@Slot`` methods, keeping data flow one-directional (backend -> presentation).
All formatting for display lives here so QML stays free of business logic.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .attention import Alert, AttentionMonitor, MetricReading, Prominence
from .bridge.client import KernelClient
from .bridge.consent import (
    ConfirmPolicy,
    ConfirmRequest,
    Gate,
    needs_reversibility_confirmation,
    reversibility_summary,
)
from .bridge.plan import Plan, known_playbooks, parse_plan
from .bridge.protocol import Outcome, OutcomeKind
from .bridge.resident_client import ResidentClient
from .bridge.voice_client import VoiceClient
from .commands.router import CommandRouter, Severity
from .state import AssistantState, InvalidTransitionError, can_transition
from .telemetry.models import TelemetrySnapshot
from .telemetry.proc_reader import ProcReader
from .telemetry.service import MIN_INTERVAL_MS, TelemetrySampler

#: Duration of the boot sequence before the HUD settles into standby.
BOOT_DURATION_MS = 1800

#: Maximum console lines retained. Bounded so a long-running session cannot
#: grow the model without limit.
MAX_LOG_LINES = 200

_MODES = ("DIAGNOSTICS", "MONITOR", "ASSISTANT")

#: Which metrics each mode already presents as a large, central element.
#:
#: This table is the documented proxy for gaze direction used by
#: :mod:`javris.attention`; it must be kept in step with the mode QML. A metric
#: listed here is considered already-seen in that mode and is never escalated,
#: because escalation exists to move information the operator would otherwise
#: miss. DIAGNOSTICS foregrounds three large gauges; MONITOR foregrounds only
#: the reactor core, which encodes processor load.
_CENTRAL_METRICS: dict[str, frozenset[str]] = {
    "DIAGNOSTICS": frozenset({"cpu", "memory", "swap"}),
    "MONITOR": frozenset({"cpu"}),
    # ASSISTANT is a modal takeover: it deliberately shows almost no telemetry,
    # so nothing is "already central" and any breach is escalatable.
    "ASSISTANT": frozenset(),
}


def format_bytes(value: float | None) -> str:
    """Format a byte count with a binary unit suffix, or ``--`` when unknown."""
    if value is None:
        return "--"
    magnitude = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(magnitude) < 1024.0 or unit == "TiB":
            precision = 0 if unit == "B" else 1
            return f"{magnitude:.{precision}f} {unit}"
        magnitude /= 1024.0
    return f"{magnitude:.1f} TiB"


def format_rate(value: float | None) -> str:
    """Format a bytes-per-second rate, or ``--`` when unknown."""
    if value is None:
        return "--"
    return f"{format_bytes(value)}/s"


def format_duration(seconds: float | None) -> str:
    """Format a duration as ``NdNNh NNm``, or ``--`` when unknown."""
    if seconds is None or seconds < 0:
        return "--"
    total = int(seconds)
    days, remainder = divmod(total, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    return f"{hours:02d}h {minutes:02d}m"


def format_percent(value: float | None) -> str:
    """Format a percentage to one decimal place, or ``--`` when unknown."""
    return "--" if value is None else f"{value:.1f}"


class HudController(QObject):
    """Owns assistant state, drives telemetry polling and routes commands."""

    stateChanged = Signal()
    modeChanged = Signal()
    snapshotChanged = Signal()
    logChanged = Signal()
    alertChanged = Signal()
    shutdownRequested = Signal()

    def __init__(
        self,
        sampler: TelemetrySampler | None = None,
        interval_ms: int = 1000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._sampler = sampler if sampler is not None else TelemetrySampler()
        self._router = CommandRouter(_MODES)
        self._state = AssistantState.BOOTING
        self._mode = _MODES[0]
        self._snapshot = TelemetrySnapshot(monotonic_time=0.0)
        # Static host facts, read once: these cannot change while we run, so
        # polling them every frame would be waste.
        self._identity = ProcReader().read_host_identity()

        # -- agent bridge ---------------------------------------------------
        # Created but NOT started: connecting is an explicit act, and a HUD
        # that silently spawned a privileged agent on launch would be exactly
        # the kind of surprise this project avoids.
        self._kernel = KernelClient(self)
        self._resident = ResidentClient(self)
        #: The transport currently in use. Both expose the same signals, so
        #: everything downstream of here is transport-agnostic.
        self._transport: KernelClient | ResidentClient = self._kernel
        for client in (self._kernel, self._resident):
            client.connected.connect(self._on_kernel_connected)
            client.disconnected.connect(self._on_kernel_disconnected)
            client.completed.connect(self._on_kernel_completed)
            client.started.connect(self._on_kernel_started)

        #: Push-to-talk capture. Produces text for the console; never executes.
        self._voice = VoiceClient(self)
        self._voice.listening.connect(self._on_voice_listening)
        self._voice.transcribing.connect(self._on_voice_transcribing)
        self._voice.transcribed.connect(self._on_voice_transcribed)
        self._voice.failed.connect(self._on_voice_failed)
        #: Text handed back by the transcriber, for the console input to pick
        #: up. Never auto-submitted -- speech can mishear.
        self._dictation = ""

        #: The question currently in front of the owner, or None.
        self._confirm: ConfirmRequest | None = None
        #: How much GUI-side friction to add. The kernel's own gate applies
        #: under every setting; this only governs the reversibility gate.
        self._confirm_policy = ConfirmPolicy.IRREVERSIBLE
        #: Request text held between a gate-2 preview and its execution.
        self._staged_request = ""
        #: True while a resident connection attempt is outstanding. A stale
        #: token file outlives the doorway it belonged to, so a failed resident
        #: attempt falls back to spawning exactly once rather than leaving the
        #: owner stuck with a transport that cannot work.
        self._resident_attempt = False
        #: Subject of the most recent bare `plan` verb.
        self._last_preview_request = ""
        #: The most recent jarvis_do request text. Held so that a refusal can
        #: be re-sent verbatim after consent -- the owner must approve the
        #: exact request they were shown, never a reconstruction of it.
        self._last_do_request: str = ""
        #: The most recent plan, kept so the UI can show what was reviewed.
        self._last_plan: Plan | None = None
        #: The request text `_last_plan` describes. A plan is only ever shown
        #: beside the request it was computed for -- displaying a stale plan
        #: next to a different request would have the owner approving one
        #: thing while reading another.
        self._last_plan_request = ""
        self._log: list[str] = []
        self._windowed = False
        self._attention = AttentionMonitor()
        self._alert: Alert | None = None

        self._interval_ms = max(MIN_INTERVAL_MS, interval_ms)
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._poll)

        self._boot_timer = QTimer(self)
        self._boot_timer.setSingleShot(True)
        self._boot_timer.setInterval(BOOT_DURATION_MS)
        self._boot_timer.timeout.connect(self._finish_boot)

        self.append_log(Severity.INFO, "J.A.V.R.I.S. core initialising.")

    # -- lifecycle ---------------------------------------------------------

    @Slot()
    def start(self) -> None:
        """Begin the boot sequence and start telemetry polling."""
        self._poll()  # Prime the counters so the first visible sample has deltas.
        self._timer.start()
        self._boot_timer.start()

    @Slot()
    def stop(self) -> None:
        """Stop all timers. Safe to call more than once."""
        self._timer.stop()
        self._boot_timer.stop()

    def _finish_boot(self) -> None:
        if self._state is AssistantState.BOOTING:
            self.set_state(AssistantState.STANDBY)
            self.append_log(Severity.OK, "All systems nominal. Standing by.")

    # -- telemetry ---------------------------------------------------------

    def _poll(self) -> None:
        snapshot = self._sampler.sample()
        previously_degraded = self._snapshot.is_degraded
        self._snapshot = snapshot
        self.snapshotChanged.emit()

        # Report degradation once on the transition, not on every poll, so a
        # persistently missing sensor cannot flood the console.
        if snapshot.is_degraded and not previously_degraded:
            self.append_log(
                Severity.WARN,
                f"Telemetry unavailable: {', '.join(snapshot.degraded_sources)}.",
            )
        elif previously_degraded and not snapshot.is_degraded:
            self.append_log(Severity.OK, "All telemetry sources restored.")

        self._evaluate_attention()

    # -- attention escalation ---------------------------------------------

    def _metric_readings(self) -> tuple[MetricReading, ...]:
        """Describe every escalatable metric for the current mode.

        Only metrics with a meaningful saturation point appear here. Uptime,
        throughput and load average are excluded: they have no ceiling against
        which "how full is it" could be judged, so a fraction would be invented.
        """
        central = _CENTRAL_METRICS.get(self._mode, frozenset())

        def prominence(key: str) -> Prominence:
            return Prominence.CENTRAL if key in central else Prominence.PERIPHERAL

        cpu = self._snapshot.cpu_total_percent
        memory = self._snapshot.memory

        readings = [
            MetricReading(
                key="cpu",
                label="Processor load",
                fraction=None if cpu is None else cpu / 100.0,
                readout=format_percent(cpu),
                unit="%",
                prominence=prominence("cpu"),
                advice="Sustained processor saturation.",
            ),
            MetricReading(
                key="memory",
                label="Memory pressure",
                fraction=None if memory is None else memory.used_fraction,
                readout=("--" if memory is None else format_percent(memory.used_fraction * 100.0)),
                unit="%",
                prominence=prominence("memory"),
                advice="Physical memory near capacity.",
            ),
            MetricReading(
                key="swap",
                label="Swap pressure",
                fraction=None if memory is None else memory.swap_used_fraction,
                readout=(
                    "--" if memory is None else format_percent(memory.swap_used_fraction * 100.0)
                ),
                unit="%",
                prominence=prominence("swap"),
                advice="Swap in heavy use; expect stalls.",
            ),
        ]
        readings.extend(
            MetricReading(
                key=f"disk:{disk.mount_point}",
                label=f"Storage {disk.mount_point}",
                fraction=disk.used_fraction,
                readout=format_percent(disk.used_fraction * 100.0),
                unit="%",
                prominence=Prominence.PERIPHERAL,
                advice=f"Filesystem {disk.mount_point} is filling up.",
            )
            for disk in self._snapshot.disks
        )
        return tuple(readings)

    def _evaluate_attention(self) -> None:
        """Run the escalation policy and announce any change on the console."""
        previous = self._alert
        current = self._attention.update(self._metric_readings())
        self._alert = current

        if previous is None and current is None:
            return

        changed = (
            previous is None
            or current is None
            or previous.key != current.key
            or previous.severity is not current.severity
        )
        if not changed:
            # The readout moves every poll; the UI rebinds, but re-announcing an
            # unchanged condition on the console would just be noise.
            self.alertChanged.emit()
            return

        if current is None and previous is not None:
            self.append_log(Severity.OK, f"{previous.label} back within limits.")
        elif current is not None:
            severity = Severity.ERROR if current.severity.value == "CRITICAL" else Severity.WARN
            self.append_log(
                severity,
                f"{current.label} at {current.readout}{current.unit}. {current.advice}",
            )
        self.alertChanged.emit()

    # -- state -------------------------------------------------------------

    def set_state(self, target: AssistantState) -> None:
        """Transition to ``target``.

        Raises:
            InvalidTransitionError: If the transition is not permitted.
        """
        if not can_transition(self._state, target):
            raise InvalidTransitionError(self._state, target)
        if target is self._state:
            return
        self._state = target
        self.stateChanged.emit()

    @Slot(str, result=bool)
    def requestState(self, name: str) -> bool:  # noqa: N802 - QML naming convention
        """Attempt a transition by name, returning success rather than raising.

        QML has no exception contract, so illegal transitions requested from the
        UI are reported as a logged refusal instead of crashing the engine.
        """
        try:
            target = AssistantState(name.upper())
        except ValueError:
            self.append_log(Severity.ERROR, f"Unknown state '{name}'.")
            return False
        try:
            self.set_state(target)
        except InvalidTransitionError as error:
            self.append_log(Severity.ERROR, str(error))
            return False
        return True

    # -- commands ----------------------------------------------------------

    @Slot(str)
    def submitCommand(self, line: str) -> None:  # noqa: N802 - QML naming convention
        """Dispatch a console command and reflect its result in the HUD."""
        self.append_log(Severity.INFO, f"> {line.strip()}")
        result = self._router.dispatch(line)

        if result.message == "__CLEAR__":
            self._log.clear()
            self.logChanged.emit()
            return

        self.append_log(result.severity, result.message)
        if result.mode is not None and result.mode != self._mode:
            self._set_mode(result.mode)
        if result.confirm_policy:
            self.setConfirmPolicy(result.confirm_policy)
        if result.agent_disconnect:
            self._disconnect_agent()
        if result.agent_tool is not None:
            self._dispatch_agent(result.agent_tool, result.agent_argument)
        if result.shutdown:
            self.stop()
            self.shutdownRequested.emit()

    @Slot()
    def cycleMode(self) -> None:  # noqa: N802 - QML naming convention
        """Advance to the next HUD mode."""
        index = (_MODES.index(self._mode) + 1) % len(_MODES)
        self._set_mode(_MODES[index])
        self.append_log(Severity.OK, f"Mode set to {self._mode}.")

    def _set_mode(self, mode: str) -> None:
        """Switch mode and immediately re-run the escalation policy.

        Prominence is mode-dependent, so a mode change can make an escalated
        metric central (releasing the alert) or push a central one into the
        periphery. Re-evaluating here means the HUD is correct on the next
        frame rather than up to one poll interval later.
        """
        self._mode = mode
        self.modeChanged.emit()
        self._evaluate_attention()

    def append_log(self, severity: Severity, message: str) -> None:
        """Append one bounded, severity-tagged line to the console log."""
        self._log.append(f"{severity.value}\u001f{message}")
        if len(self._log) > MAX_LOG_LINES:
            del self._log[: len(self._log) - MAX_LOG_LINES]
        self.logChanged.emit()

    # -- properties exposed to QML ----------------------------------------

    def set_windowed(self, value: bool) -> None:
        """Choose windowed rather than full-screen presentation.

        Must be called before QML loads: the window flags it drives cannot be
        changed after the window has been created, which is why the QML-facing
        property is declared constant.
        """
        self._windowed = bool(value)

    @Property(bool, constant=True)
    def windowed(self) -> bool:
        """True when the HUD should open in a normal window, not full screen."""
        return self._windowed

    @Property(str, notify=stateChanged)
    def state(self) -> str:
        """Current assistant state name."""
        return self._state.value

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        """Current HUD mode name."""
        return self._mode

    @Property(list, notify=logChanged)
    def log(self) -> list[str]:
        """Console lines, each ``SEVERITY\\x1fmessage``, oldest first."""
        return list(self._log)

    @Property(float, notify=snapshotChanged)
    def cpuPercent(self) -> float:  # noqa: N802
        """Aggregate CPU utilisation; -1.0 when not yet measurable."""
        value = self._snapshot.cpu_total_percent
        return -1.0 if value is None else value

    @Property(str, notify=snapshotChanged)
    def cpuText(self) -> str:  # noqa: N802
        """Aggregate CPU utilisation, formatted for display."""
        return format_percent(self._snapshot.cpu_total_percent)

    @Property(list, notify=snapshotChanged)
    def coreLoads(self) -> list[float]:  # noqa: N802
        """Per-core utilisation as 0.0-1.0 fractions."""
        return [percent / 100.0 for percent in self._snapshot.cpu_core_percents]

    @Property(float, notify=snapshotChanged)
    def memoryFraction(self) -> float:  # noqa: N802
        """Physical memory usage as a 0.0-1.0 fraction; -1.0 when unknown."""
        memory = self._snapshot.memory
        return -1.0 if memory is None else memory.used_fraction

    @Property(str, notify=snapshotChanged)
    def memoryText(self) -> str:  # noqa: N802
        """Memory usage as ``used / total``."""
        memory = self._snapshot.memory
        if memory is None:
            return "--"
        return f"{format_bytes(memory.used)} / {format_bytes(memory.total)}"

    @Property(float, notify=snapshotChanged)
    def swapFraction(self) -> float:  # noqa: N802
        """Swap usage as a 0.0-1.0 fraction; -1.0 when unknown."""
        memory = self._snapshot.memory
        return -1.0 if memory is None else memory.swap_used_fraction

    @Property(str, notify=snapshotChanged)
    def loadText(self) -> str:  # noqa: N802
        """Load averages over 1, 5 and 15 minutes."""
        load = self._snapshot.load_average
        if load is None:
            return "--"
        return f"{load.one:.2f}  {load.five:.2f}  {load.fifteen:.2f}"

    @Property(str, notify=snapshotChanged)
    def uptimeText(self) -> str:  # noqa: N802
        """System uptime, formatted for display."""
        return format_duration(self._snapshot.uptime_seconds)

    @Property(str, notify=snapshotChanged)
    def temperatureText(self) -> str:  # noqa: N802
        """CPU package temperature in Celsius, or ``--`` when no sensor exists."""
        value = self._snapshot.temperature_celsius
        return "--" if value is None else f"{value:.1f}"

    @Property(str, notify=snapshotChanged)
    def networkRxText(self) -> str:  # noqa: N802
        """Inbound network throughput."""
        return format_rate(self._snapshot.net_rx_bytes_per_sec)

    @Property(str, notify=snapshotChanged)
    def networkTxText(self) -> str:  # noqa: N802
        """Outbound network throughput."""
        return format_rate(self._snapshot.net_tx_bytes_per_sec)

    @Property(list, notify=snapshotChanged)
    def disks(self) -> list[dict[str, object]]:
        """Per-filesystem usage records for the storage panel."""
        return [
            {
                "mount": disk.mount_point,
                "fraction": disk.used_fraction,
                "text": f"{format_bytes(disk.used)} / {format_bytes(disk.total)}",
            }
            for disk in self._snapshot.disks
        ]

    @Property(bool, notify=snapshotChanged)
    def degraded(self) -> bool:
        """True when any telemetry source is unavailable."""
        return self._snapshot.is_degraded

    @Property(str, notify=snapshotChanged)
    def degradedText(self) -> str:  # noqa: N802
        """Comma-separated names of unavailable telemetry sources."""
        return ", ".join(self._snapshot.degraded_sources)

    # -- attention properties ---------------------------------------------

    @Property(bool, notify=alertChanged)
    def alertActive(self) -> bool:  # noqa: N802
        """True when a condition has been escalated to the main display."""
        return self._alert is not None

    @Property(str, notify=alertChanged)
    def alertLabel(self) -> str:  # noqa: N802
        """Name of the escalated condition; empty when none is active."""
        return "" if self._alert is None else self._alert.label

    @Property(str, notify=alertChanged)
    def alertReadout(self) -> str:  # noqa: N802
        """Formatted value of the escalated condition."""
        return "" if self._alert is None else self._alert.readout

    @Property(str, notify=alertChanged)
    def alertUnit(self) -> str:  # noqa: N802
        """Unit suffix for :attr:`alertReadout`."""
        return "" if self._alert is None else self._alert.unit

    @Property(str, notify=alertChanged)
    def alertAdvice(self) -> str:  # noqa: N802
        """One-line explanation of the escalated condition."""
        return "" if self._alert is None else self._alert.advice

    @Property(str, notify=alertChanged)
    def alertSeverity(self) -> str:  # noqa: N802
        """``WARN``, ``CRITICAL``, or empty when no alert is active."""
        return "" if self._alert is None else self._alert.severity.value

    @Property(float, notify=alertChanged)
    def alertFraction(self) -> float:  # noqa: N802
        """Normalised 0.0-1.0 value of the escalated condition; -1.0 when none."""
        return -1.0 if self._alert is None else self._alert.fraction

    # -- battery ------------------------------------------------------------

    @Property(bool, notify=snapshotChanged)
    def batteryPresent(self) -> bool:  # noqa: N802
        """True when this host actually has a battery.

        Desktops, virtual machines and containers have none. The UI hides the
        whole readout rather than showing an empty or full cell.
        """
        return self._snapshot.battery is not None

    @Property(float, notify=snapshotChanged)
    def batteryFraction(self) -> float:  # noqa: N802
        """Charge as a 0.0-1.0 fraction; -1.0 when absent or unreadable."""
        battery = self._snapshot.battery
        if battery is None or battery.percent is None:
            return -1.0
        return battery.percent / 100.0

    @Property(str, notify=snapshotChanged)
    def batteryText(self) -> str:  # noqa: N802
        """Charge percentage, formatted for display."""
        battery = self._snapshot.battery
        if battery is None or battery.percent is None:
            return "--"
        return f"{battery.percent:.0f} %"

    @Property(str, notify=snapshotChanged)
    def batteryState(self) -> str:  # noqa: N802
        """``CHARGING``, ``DISCHARGING``, or ``UNKNOWN``.

        An unknown kernel status is reported as unknown rather than guessed:
        showing "discharging" on a machine that is plugged in would be a lie
        about the one thing this readout exists to convey.
        """
        battery = self._snapshot.battery
        if battery is None or battery.charging is None:
            return "UNKNOWN"
        return "CHARGING" if battery.charging else "DISCHARGING"

    @Property(str, notify=snapshotChanged)
    def batteryRuntimeText(self) -> str:  # noqa: N802
        """Estimated time to empty, or an empty string when not measurable."""
        battery = self._snapshot.battery
        if battery is None or battery.seconds_remaining is None:
            return ""
        return format_duration(battery.seconds_remaining)

    # -- host identity -------------------------------------------------------

    @Property(list, constant=True)
    def hostFacts(self) -> list[str]:  # noqa: N802
        """Static machine facts as ``label\\x1fvalue`` rows.

        Only genuinely readable facts appear. A host that exposes no CPU model
        simply yields fewer rows -- there is no placeholder text, and nothing
        here is invented. This is the honest counterpart to a "PC SPECS" panel
        listing fictional hardware.
        """
        identity = self._identity
        rows: list[tuple[str, str | None]] = [
            ("HOST", identity.hostname),
            ("OS", identity.os_name),
            ("KERNEL", identity.kernel_release),
            ("PROCESSOR", identity.cpu_model),
            (
                "LOGICAL CORES",
                None if identity.cpu_cores is None else str(identity.cpu_cores),
            ),
            (
                "MEMORY",
                None
                if identity.memory_total_bytes is None
                else format_bytes(identity.memory_total_bytes),
            ),
        ]
        return [f"{label}\x1f{value}" for label, value in rows if value]

    # -- agent bridge ---------------------------------------------------------

    agentChanged = Signal()
    consentChanged = Signal()
    voiceChanged = Signal()
    planChanged = Signal()

    @Property(bool, notify=agentChanged)
    def agentConnected(self) -> bool:  # noqa: N802
        """True once the active transport is ready."""
        return self._transport.ready

    @Property(str, notify=agentChanged)
    def agentVersion(self) -> str:  # noqa: N802
        """Kernel version string, or empty when not connected."""
        return self._transport.version

    @Property(bool, notify=agentChanged)
    def agentAvailable(self) -> bool:  # noqa: N802
        """True when the kernel can be spawned on demand."""
        return KernelClient.available()

    @Property(bool, notify=agentChanged)
    def residentAvailable(self) -> bool:  # noqa: N802
        """True when a resident doorway is configured for this account.

        Only true once the owner has run ``jarvis serve install``; resident
        mode is never assumed.
        """
        return self._resident.available()

    @Property(str, notify=agentChanged)
    def agentTransport(self) -> str:  # noqa: N802
        """Which transport is active: ``RESIDENT`` or ``ON_DEMAND``."""
        return "RESIDENT" if self._transport is self._resident else "ON_DEMAND"

    # -- consent and confirmation ---------------------------------------------

    @Property(str, notify=consentChanged)
    def pendingConsent(self) -> str:  # noqa: N802
        """The request awaiting an owner decision, or an empty string.

        While this is non-empty the UI must show the prompt. For the kernel
        gate it is the only path by which ``allow: true`` can ever be sent.
        """
        return self._confirm.request if self._confirm else ""

    @Property(str, notify=consentChanged)
    def consentGate(self) -> str:  # noqa: N802
        """Which gate is asking: ``KERNEL_CONSENT`` or ``REVERSIBILITY``.

        The UI styles these differently on purpose. One grants the kernel
        authority it does not otherwise have; the other is the GUI pausing
        before something that cannot be undone. Presenting them identically
        would devalue the one that carries real authority.
        """
        return self._confirm.gate.value if self._confirm else ""

    @Property(str, notify=consentChanged)
    def consentHeadline(self) -> str:  # noqa: N802
        """One line stating what is being asked, and why."""
        return self._confirm.headline if self._confirm else ""

    @Property(str, notify=consentChanged)
    def consentHint(self) -> str:  # noqa: N802
        """The kernel's own next-step hint, when it supplied one."""
        return self._confirm.hint if self._confirm else ""

    @Property(str, notify=consentChanged)
    def confirmPolicy(self) -> str:  # noqa: N802
        """The active reversibility policy."""
        return self._confirm_policy.value

    @Slot(str, result=bool)
    def setConfirmPolicy(self, name: str) -> bool:  # noqa: N802
        """Change the GUI-side confirmation policy.

        Rejects an unknown name rather than silently falling back, because a
        typo that quietly disabled a safety prompt would be the worst possible
        failure mode for this setting.
        """
        try:
            policy = ConfirmPolicy(name.upper())
        except ValueError:
            self.append_log(Severity.ERROR, f"Unknown confirmation policy: {name}")
            return False
        self._confirm_policy = policy
        self.append_log(Severity.INFO, f"Confirmation policy: {policy.value}.")
        self.consentChanged.emit()
        return True

    # -- plan review -----------------------------------------------------------

    def _plan_for_prompt(self) -> Plan | None:
        """The plan to display beside the current prompt, if it matches it.

        Returns None when the cached plan describes a different request. Under
        the ``kernel-only`` policy no preview is run before a mutation, so a
        plan left over from an earlier command would otherwise be rendered
        beside an unrelated consent prompt -- the owner would be reading one
        command while approving another.
        """
        if self._last_plan is None:
            return None
        if self._confirm is not None and self._confirm.request != self._last_plan_request:
            return None
        return self._last_plan

    @Property(bool, notify=planChanged)
    def planAvailable(self) -> bool:  # noqa: N802
        """True when a previewed plan is ready to display."""
        plan = self._plan_for_prompt()
        return plan is not None and not plan.is_empty

    @Property(str, notify=planChanged)
    def planPlaybook(self) -> str:  # noqa: N802
        """The matched playbook id, or empty when nothing matched."""
        plan = self._plan_for_prompt()
        return plan.playbook if plan else ""

    @Property(int, notify=planChanged)
    def planTier(self) -> int:  # noqa: N802
        """The plan's safety tier, or -1 when unknown."""
        plan = self._plan_for_prompt()
        if plan is None or plan.tier is None:
            return -1
        return plan.tier

    @Property(bool, notify=planChanged)
    def planIrreversible(self) -> bool:  # noqa: N802
        """True when the kernel reports no way to undo this plan."""
        plan = self._plan_for_prompt()
        return plan.irreversible if plan else False

    @Property(str, notify=planChanged)
    def planUndoReason(self) -> str:  # noqa: N802
        """The kernel's own words about reversibility."""
        plan = self._plan_for_prompt()
        return reversibility_summary(plan) if plan else ""

    @Property(list, notify=planChanged)
    def planSteps(self) -> list[str]:  # noqa: N802
        """Plan steps as ``description\x1fargv\x1froot`` rows.

        Unit-separated for the same reason the log is: it cannot occur in the
        payload text, so no description can forge a column break.
        """
        plan = self._plan_for_prompt()
        if plan is None:
            return []
        return [
            f"{step.description}\x1f{step.command_line}\x1f{'1' if step.requires_root else '0'}"
            for step in plan.steps
        ]

    @Property(list, notify=planChanged)
    def planBlast(self) -> list[str]:  # noqa: N802
        """Blast-radius facts as ``label\x1fvalue`` rows, omitting the empty."""
        plan = self._plan_for_prompt()
        if plan is None:
            return []
        blast = plan.blast
        rows: list[tuple[str, str]] = []
        if blast.commands:
            rows.append(("COMMANDS", ", ".join(blast.commands)))
        rows.append(("ROOT", "required" if blast.requires_root else "not required"))
        rows.append(("NETWORK", "yes" if blast.network else "no"))
        if blast.paths:
            rows.append(("PATHS", ", ".join(blast.paths)))
        return [f"{label}\x1f{value}" for label, value in rows]

    # -- voice -----------------------------------------------------------------

    @Property(bool, notify=voiceChanged)
    def voiceAvailable(self) -> bool:  # noqa: N802
        """True when this machine can turn speech into text."""
        return self._voice.available()

    @Property(str, notify=voiceChanged)
    def voiceStatus(self) -> str:  # noqa: N802
        """Why voice is unavailable, or that it is available."""
        return self._voice.explain_unavailable()

    @Property(str, notify=voiceChanged)
    def dictation(self) -> str:
        """The last transcript, for the console input to adopt.

        Handed to the input field, never submitted. Speech is treated as a
        keyboard that can mishear.
        """
        return self._dictation

    @Slot()
    def startDictation(self) -> None:  # noqa: N802
        """Begin a push-to-talk capture."""
        self._voice.refresh()
        if not self._voice.available():
            self.append_log(Severity.WARN, self._voice.explain_unavailable())
            self.voiceChanged.emit()
            return
        self._voice.start()

    @Slot()
    def cancelDictation(self) -> None:  # noqa: N802
        """Abandon a capture in progress."""
        self._voice.cancel()

    def _on_voice_listening(self) -> None:
        self.append_log(Severity.INFO, "Listening...")
        self._request_state_quietly(AssistantState.LISTENING)
        self.voiceChanged.emit()

    def _on_voice_transcribing(self) -> None:
        self._request_state_quietly(AssistantState.PROCESSING)
        self.voiceChanged.emit()

    def _on_voice_transcribed(self, text: str) -> None:
        self._dictation = text
        # Logged as a quotation, and deliberately not run: the owner reads it
        # in the input field and decides. A misheard word must never become an
        # executed request.
        self.append_log(Severity.INFO, f'Heard: "{text}" - review it, then press Enter.')
        self._request_state_quietly(AssistantState.STANDBY)
        self.voiceChanged.emit()

    def _on_voice_failed(self, reason: str) -> None:
        self.append_log(Severity.WARN, reason)
        self._request_state_quietly(AssistantState.STANDBY)
        self.voiceChanged.emit()

    # -- connection ------------------------------------------------------------

    @Slot()
    def connectAgent(self) -> None:  # noqa: N802
        """Connect using the best available transport.

        Resident mode is preferred when the owner has installed it, because it
        means not spawning a process at all. Otherwise the kernel is spawned on
        demand. Either way it takes this explicit call.
        """
        if self._transport.ready:
            self.append_log(Severity.INFO, "Agent already connected.")
            return

        if self._resident.available():
            self._transport = self._resident
            self._resident_attempt = True
            self.append_log(
                Severity.INFO, f"Connecting to the resident kernel at {self._resident.endpoint}..."
            )
        else:
            self._transport = self._kernel
            self._resident_attempt = False
            self.append_log(Severity.INFO, "Starting the JARVIS kernel on demand...")

        self.agentChanged.emit()
        self._request_state_quietly(AssistantState.PROCESSING)
        if not self._transport.start():
            self._request_state_quietly(AssistantState.OFFLINE)

    @Slot()
    def approveConsent(self) -> None:  # noqa: N802
        """Answer the pending question affirmatively.

        What that means depends on which gate asked, and the difference is
        preserved exactly:

        * **Kernel gate** -- re-send the request with ``allow=True``. This is
          the *only* place that flag originates, and it is reachable only from
          a deliberate UI action.
        * **Reversibility gate** -- send the request *without* ``allow``. The
          owner has acknowledged that it cannot be undone; they have not
          granted the kernel any additional authority, and if the kernel then
          wants consent it will ask through the first gate.
        """
        pending = self._confirm
        if pending is None:
            return
        request = pending.request
        gate = pending.gate
        self._confirm = None
        self.consentChanged.emit()

        if gate is Gate.KERNEL_CONSENT:
            self.append_log(Severity.WARN, f"Consent given. Executing: {request}")
            self._request_state_quietly(AssistantState.EXECUTING)
            if not self._transport.execute(request, allow=True, tag="do"):
                self.append_log(Severity.ERROR, "The agent is not connected.")
                self._request_state_quietly(AssistantState.ERROR)
            return

        # Reversibility gate: acknowledged, but no authority is added here.
        self.append_log(Severity.INFO, f"Acknowledged. Running: {request}")
        self._last_do_request = request
        self._request_state_quietly(AssistantState.EXECUTING)
        if not self._transport.execute(request, allow=False, tag="do"):
            self.append_log(Severity.ERROR, "The agent is not connected.")
            self._request_state_quietly(AssistantState.ERROR)

    @Slot()
    def declineConsent(self) -> None:  # noqa: N802
        """Dismiss the prompt without acting."""
        if self._confirm is None:
            return
        self._confirm = None
        self._staged_request = ""
        self.consentChanged.emit()
        self.append_log(Severity.INFO, "Declined. Nothing was run.")
        self._request_state_quietly(AssistantState.STANDBY)

    def _disconnect_agent(self) -> None:
        self._transport.stop()

    def _dispatch_agent(self, tool: str, argument: str) -> None:
        """Send one tool call on behalf of a console verb."""
        if not self._transport.ready:
            self.append_log(
                Severity.ERROR,
                "The agent is not connected. Use the connect action first.",
            )
            return

        self._request_state_quietly(AssistantState.PROCESSING)
        if tool == "jarvis_do":
            # Gate 2: preview first so the kernel can tell us whether this can
            # be undone. The preview is read-only and changes nothing.
            if self._confirm_policy is ConfirmPolicy.KERNEL_ONLY:
                self._last_do_request = argument
                self._transport.execute(argument, allow=False, tag="do")
                return
            self._staged_request = argument
            self._transport.call("jarvis_preview", {"request": argument}, tag="preview-before-do")
        elif tool == "jarvis_explain":
            self._transport.call(tool, {"question": argument}, tag="explain")
        elif tool == "jarvis_preview":
            self._last_preview_request = argument
            self._transport.call(tool, {"request": argument}, tag="preview")
        else:
            self._transport.call(tool, {}, tag=tool)

    def _on_kernel_started(self, _tag: str) -> None:
        self._request_state_quietly(AssistantState.PROCESSING)

    def _on_kernel_connected(self, version: str) -> None:
        self._resident_attempt = False
        label = f"Kernel {version}." if version else "Kernel version unreported."
        transport = "resident" if self._transport is self._resident else "on-demand"
        self.append_log(Severity.OK, f"Agent connected ({transport}). {label}")
        self.agentChanged.emit()
        self._request_state_quietly(AssistantState.STANDBY)

    def _on_kernel_disconnected(self, reason: str) -> None:
        self.append_log(Severity.WARN, reason)
        self.agentChanged.emit()

        # A token file outlives the doorway that wrote it, so "resident is
        # configured" does not mean "resident is running". Fall back to
        # spawning once rather than leaving the owner on a dead transport.
        if self._resident_attempt and not self._kernel.ready:
            self._resident_attempt = False
            if KernelClient.available():
                self._transport = self._kernel
                self.append_log(Severity.INFO, "Falling back to starting the kernel on demand...")
                self.agentChanged.emit()
                self._request_state_quietly(AssistantState.PROCESSING)
                if not self._transport.start():
                    self._request_state_quietly(AssistantState.OFFLINE)
                return
        if self._confirm is not None:
            self._confirm = None
            self._staged_request = ""
            self.consentChanged.emit()
        # Telemetry keeps running: losing the agent must never take the HUD
        # down with it (honest degradation, never a faked agent).
        self._request_state_quietly(AssistantState.STANDBY)

    def _on_kernel_completed(self, tag: str, outcome: Outcome) -> None:
        """Render one tool result and move the state machine accordingly."""
        if tag in ("preview", "preview-before-do"):
            self._last_plan = parse_plan(outcome.payload)
            self._last_plan_request = (
                self._staged_request if tag == "preview-before-do" else self._last_preview_request
            )
            self.planChanged.emit()

        if tag == "preview-before-do":
            self._resolve_staged_request(outcome)
            return

        if outcome.kind is OutcomeKind.UNMATCHED:
            # No consent prompt: there is no action to authorise. Reported the
            # same way whether or not a preview happened to run first.
            self._report_unmatched(outcome.text, outcome.hint)
            self._request_state_quietly(AssistantState.STANDBY)
            return

        if outcome.kind is OutcomeKind.REFUSED:
            self.append_log(Severity.WARN, outcome.text)
            if outcome.hint:
                self.append_log(Severity.INFO, outcome.hint)
            if outcome.consent_required and tag == "do":
                # Hold the request so approveConsent() has something to send.
                # Storing the text is not authorisation; only the owner's
                # action is.
                self._confirm = ConfirmRequest(
                    gate=Gate.KERNEL_CONSENT,
                    request=self._last_do_request,
                    plan=self._last_plan
                    if self._last_plan_request == self._last_do_request
                    else None,
                    hint=outcome.hint,
                    tier=outcome.tier,
                )
                self.consentChanged.emit()
            self._request_state_quietly(AssistantState.STANDBY)
            return

        if outcome.kind in (OutcomeKind.FAILED, OutcomeKind.PROTOCOL_ERROR):
            self.append_log(Severity.ERROR, outcome.text)
            self._request_state_quietly(AssistantState.ERROR)
            return

        self._request_state_quietly(AssistantState.SPEAKING)
        self.append_log(Severity.OK, outcome.text)
        self._request_state_quietly(AssistantState.STANDBY)

    def _report_unmatched(self, error: str, hint: str) -> None:
        """Show the kernel's refusal-to-guess, and never a consent prompt.

        Shared by both routes into this state -- the previewed one and the
        direct ``jarvis_do`` under ``KERNEL_ONLY`` -- so the owner sees the
        same thing regardless of which gate policy is in force.
        """
        self.append_log(Severity.WARN, error or "The kernel could not map that request.")
        names = known_playbooks(hint)
        if names:
            self.append_log(
                Severity.INFO,
                f"{len(names)} known playbooks, including: " + ", ".join(names[:8]) + ".",
            )
        elif hint:
            self.append_log(Severity.INFO, hint)

    def _resolve_staged_request(self, outcome: Outcome) -> None:
        """Decide what to do with a `do` whose preview has just returned.

        Three outcomes, and the unmatched case is the one most easily got
        wrong: the kernel answers an unmappable request with ``isError`` and an
        anti-hallucination message. That is the kernel refusing to guess, which
        is a feature. Sending the request anyway would produce the identical
        refusal a second time, so it is reported and dropped.
        """
        request = self._staged_request
        self._staged_request = ""
        plan = self._last_plan

        if plan is not None and plan.unmatched:
            self._report_unmatched(plan.error, plan.hint)
            self._request_state_quietly(AssistantState.STANDBY)
            return

        if outcome.kind is OutcomeKind.PROTOCOL_ERROR:
            self.append_log(Severity.ERROR, outcome.text)
            self._request_state_quietly(AssistantState.ERROR)
            return

        if plan is not None and needs_reversibility_confirmation(plan, self._confirm_policy):
            self._confirm = ConfirmRequest(
                gate=Gate.REVERSIBILITY,
                request=request,
                plan=plan,
                hint=reversibility_summary(plan),
                tier=plan.tier,
            )
            self.consentChanged.emit()
            self._request_state_quietly(AssistantState.STANDBY)
            return

        # Reversible (or policy says don't ask): send it. The kernel's own gate
        # still applies and will refuse a T2 request without consent.
        self._last_do_request = request
        self._request_state_quietly(AssistantState.EXECUTING)
        self._transport.execute(request, allow=False, tag="do")

    def _request_state_quietly(self, target: AssistantState) -> None:
        """Move to ``target`` when the transition table permits it.

        Illegal transitions are skipped rather than logged as errors: the
        bridge reports what the kernel is doing, and the state table is the
        authority on which of those reports can be represented right now.
        """
        if can_transition(self._state, target):
            self.set_state(target)
