"""Tests for HudController and the telemetry sampler.

A QGuiApplication is not required: QObject, Signal and QTimer work under a
plain QCoreApplication, so these run headless with no display and no GL.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from javris.attention import RAISE_SAMPLES
from javris.bridge.protocol import classify_outcome
from javris.controller import (
    _MODES,
    HudController,
    format_bytes,
    format_duration,
    format_percent,
    format_rate,
)
from javris.state import AssistantState, InvalidTransitionError
from javris.telemetry.models import DiskUsage, MemorySnapshot, TelemetrySnapshot
from javris.telemetry.proc_reader import ProcReader
from javris.telemetry.service import MIN_INTERVAL_MS, TelemetrySampler

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def qt_app() -> QCoreApplication:
    app = QCoreApplication.instance() or QCoreApplication([])
    return app


class FakeClock:
    """A monotonic clock the test advances explicitly."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def sampler() -> TelemetrySampler:
    reader = ProcReader(proc_root=FIXTURES / "proc", sys_root=FIXTURES / "sys")
    return TelemetrySampler(reader=reader, clock=FakeClock())


@pytest.fixture
def controller(sampler: TelemetrySampler) -> HudController:
    return HudController(sampler=sampler)


# -- formatting ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "--"),
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KiB"),
        (1024 * 1024, "1.0 MiB"),
        (1024**3 * 2.5, "2.5 GiB"),
    ],
)
def test_format_bytes(value: float | None, expected: str) -> None:
    assert format_bytes(value) == expected


def test_format_rate() -> None:
    assert format_rate(None) == "--"
    assert format_rate(2048) == "2.0 KiB/s"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "--"),
        (-5, "--"),
        (0, "00h 00m"),
        (3_661, "01h 01m"),
        (90_061, "1d 01h 01m"),
    ],
)
def test_format_duration(seconds: float | None, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_format_percent() -> None:
    assert format_percent(None) == "--"
    assert format_percent(42.5) == "42.5"
    assert format_percent(0.0) == "0.0"
    assert format_percent(100.0) == "100.0"


# -- sampler ---------------------------------------------------------------


def test_first_sample_has_no_rate_metrics(sampler: TelemetrySampler) -> None:
    """Rates need two samples; the first must report unknown, not zero."""
    snapshot = sampler.sample()
    assert snapshot.cpu_total_percent is None
    assert snapshot.net_rx_bytes_per_sec is None
    assert snapshot.memory is not None  # absolute values are available at once


def test_second_sample_produces_rates(sampler: TelemetrySampler) -> None:
    sampler.sample()
    clock = sampler._clock
    clock.now += 1.0
    snapshot = sampler.sample()
    # The fixture is static, so counters have not moved: 0% busy, 0 B/s.
    # That is a true measurement, unlike the None of the first sample.
    assert snapshot.cpu_total_percent is None or snapshot.cpu_total_percent == 0.0
    assert snapshot.net_rx_bytes_per_sec == 0.0


def test_sampler_records_degraded_sources(tmp_path: Path) -> None:
    empty = TelemetrySampler(reader=ProcReader(proc_root=tmp_path, sys_root=tmp_path))
    snapshot = empty.sample()
    assert snapshot.is_degraded
    for source in ("cpu", "memory", "loadavg", "uptime", "thermal", "storage", "network"):
        assert source in snapshot.degraded_sources


def test_sampler_never_raises_on_missing_tree(tmp_path: Path) -> None:
    empty = TelemetrySampler(reader=ProcReader(proc_root=tmp_path / "x", sys_root=tmp_path / "x"))
    assert empty.sample() is not None


def test_healthy_fixture_is_not_degraded(sampler: TelemetrySampler) -> None:
    snapshot = sampler.sample()
    for source in ("cpu", "memory", "loadavg", "uptime", "thermal", "network"):
        assert source not in snapshot.degraded_sources


# -- controller state ------------------------------------------------------


def test_controller_starts_booting(controller: HudController) -> None:
    assert controller.state == AssistantState.BOOTING.value


def test_legal_transition_emits_signal(controller: HudController) -> None:
    seen: list[str] = []
    controller.stateChanged.connect(lambda: seen.append(controller.state))
    controller.set_state(AssistantState.STANDBY)
    assert controller.state == "STANDBY"
    assert seen == ["STANDBY"]


def test_redundant_transition_emits_nothing(controller: HudController) -> None:
    controller.set_state(AssistantState.STANDBY)
    seen: list[str] = []
    controller.stateChanged.connect(lambda: seen.append(controller.state))
    controller.set_state(AssistantState.STANDBY)
    assert seen == []


def test_illegal_transition_raises(controller: HudController) -> None:
    with pytest.raises(InvalidTransitionError):
        controller.set_state(AssistantState.SPEAKING)


def test_request_state_reports_failure_instead_of_raising(controller: HudController) -> None:
    assert controller.requestState("SPEAKING") is False
    assert controller.state == "BOOTING"
    assert any("Illegal" in line for line in controller.log)


def test_request_state_rejects_unknown_name(controller: HudController) -> None:
    assert controller.requestState("TELEPORTING") is False
    assert any("Unknown state" in line for line in controller.log)


def test_request_state_succeeds_on_legal_move(controller: HudController) -> None:
    assert controller.requestState("standby") is True
    assert controller.state == "STANDBY"


# -- controller commands and log -------------------------------------------


def test_submit_command_echoes_and_responds(controller: HudController) -> None:
    controller.submitCommand("status")
    assert any("> status" in line for line in controller.log)
    assert any(line.startswith("OK") for line in controller.log)


def test_mode_command_changes_mode(controller: HudController) -> None:
    seen: list[str] = []
    controller.modeChanged.connect(lambda: seen.append(controller.mode))
    controller.submitCommand("mode monitor")
    assert controller.mode == "MONITOR"
    assert seen == ["MONITOR"]


def test_clear_command_empties_log(controller: HudController) -> None:
    controller.submitCommand("status")
    controller.submitCommand("clear")
    assert controller.log == []


def test_cycle_mode_visits_every_mode_then_wraps(controller: HudController) -> None:
    first = controller.mode
    seen = [first]
    for _ in range(len(_MODES) - 1):
        controller.cycleMode()
        assert controller.mode not in seen, "cycling must not repeat a mode early"
        seen.append(controller.mode)

    assert set(seen) == set(_MODES), "every mode must be reachable by cycling"

    controller.cycleMode()
    assert controller.mode == first, "cycling must wrap round to the start"


def test_shutdown_command_emits_request(controller: HudController) -> None:
    fired: list[bool] = []
    controller.shutdownRequested.connect(lambda: fired.append(True))
    controller.submitCommand("shutdown")
    assert fired == [True]


def test_log_is_bounded(controller: HudController) -> None:
    from javris.commands.router import Severity
    from javris.controller import MAX_LOG_LINES

    for index in range(MAX_LOG_LINES + 50):
        controller.append_log(Severity.INFO, f"line {index}")
    assert len(controller.log) == MAX_LOG_LINES
    # The newest line survives; the oldest is discarded.
    assert "line 249" in controller.log[-1]


# -- controller telemetry properties ---------------------------------------


def test_properties_expose_unknown_as_sentinel(controller: HudController) -> None:
    """Before any sample, numeric properties must read as unavailable."""
    assert controller.cpuPercent == -1.0
    assert controller.memoryFraction == -1.0
    assert controller.cpuText == "--"
    assert controller.memoryText == "--"
    assert controller.uptimeText == "--"
    assert controller.temperatureText == "--"
    assert controller.networkRxText == "--"


def test_properties_populate_after_poll(controller: HudController) -> None:
    controller._poll()
    assert controller.memoryText != "--"
    assert controller.uptimeText != "--"
    assert controller.temperatureText == "45.0"
    assert controller.loadText == "0.52  0.61  0.58"
    assert 0.0 <= controller.memoryFraction <= 1.0


def test_degradation_is_logged_once(tmp_path: Path) -> None:
    reader = ProcReader(proc_root=tmp_path, sys_root=tmp_path)
    broken = HudController(sampler=TelemetrySampler(reader=reader))
    broken._poll()
    broken._poll()
    warnings = [line for line in broken.log if "Telemetry unavailable" in line]
    assert len(warnings) == 1
    assert broken.degraded is True
    assert broken.degradedText


def test_interval_is_floored_to_minimum() -> None:
    controller = HudController(interval_ms=1)
    assert controller._timer.interval() == MIN_INTERVAL_MS


def test_disks_property_shape(controller: HudController) -> None:
    controller._poll()
    for disk in controller.disks:
        assert set(disk) == {"mount", "fraction", "text"}
        assert 0.0 <= float(disk["fraction"]) <= 1.0


# -- attention escalation ---------------------------------------------------


class StubSampler:
    """A sampler returning a snapshot the test dictates."""

    def __init__(self, snapshot: TelemetrySnapshot) -> None:
        self.snapshot = snapshot

    def sample(self) -> TelemetrySnapshot:
        return self.snapshot


def snapshot_with(
    cpu: float | None = 1.0,
    memory_used_fraction: float = 0.05,
    disks: tuple[DiskUsage, ...] = (),
) -> TelemetrySnapshot:
    """Build a snapshot with the memory fraction the caller asks for."""
    total = 1_000_000
    return TelemetrySnapshot(
        monotonic_time=0.0,
        cpu_total_percent=cpu,
        memory=MemorySnapshot(
            total=total,
            available=int(total * (1.0 - memory_used_fraction)),
            swap_total=0,
            swap_free=0,
        ),
        disks=disks,
    )


def poll(controller: HudController, times: int) -> None:
    """Drive the controller's polling loop directly, without a timer."""
    for _ in range(times):
        controller._poll()  # Private on purpose: this is the polling path.


class TestAttentionIntegration:
    def test_calm_system_escalates_nothing(self) -> None:
        controller = HudController(sampler=StubSampler(snapshot_with()))
        poll(controller, RAISE_SAMPLES + 2)
        assert controller.alertActive is False
        assert controller.alertSeverity == ""
        assert controller.alertFraction == pytest.approx(-1.0)

    def test_sustained_memory_pressure_is_escalated(self) -> None:
        # Memory is peripheral in MONITOR mode, so it is escalatable there.
        controller = HudController(sampler=StubSampler(snapshot_with(memory_used_fraction=0.96)))
        controller.cycleMode()
        assert controller.mode == "MONITOR"
        poll(controller, RAISE_SAMPLES)
        assert controller.alertActive is True
        assert controller.alertLabel == "Memory pressure"
        assert controller.alertSeverity == "CRITICAL"
        assert controller.alertUnit == "%"
        assert controller.alertFraction == pytest.approx(0.96, abs=1e-3)

    def test_metric_central_in_this_mode_is_not_escalated(self) -> None:
        # DIAGNOSTICS shows memory as a large central gauge already.
        controller = HudController(sampler=StubSampler(snapshot_with(memory_used_fraction=0.96)))
        assert controller.mode == "DIAGNOSTICS"
        poll(controller, RAISE_SAMPLES + 2)
        assert controller.alertActive is False

    def test_switching_mode_reevaluates_immediately(self) -> None:
        controller = HudController(sampler=StubSampler(snapshot_with(memory_used_fraction=0.96)))
        controller.cycleMode()
        poll(controller, RAISE_SAMPLES)
        assert controller.alertActive is True

        # Back to DIAGNOSTICS, where memory is central: released on the spot,
        # without waiting for another poll. There is now a third mode in the
        # cycle, so keep cycling until we arrive back.
        while controller.mode != "DIAGNOSTICS":
            controller.cycleMode()
        assert controller.alertActive is False

    def test_escalation_announces_itself_on_the_console(self) -> None:
        controller = HudController(sampler=StubSampler(snapshot_with(memory_used_fraction=0.96)))
        controller.cycleMode()
        poll(controller, RAISE_SAMPLES)
        assert any("Memory pressure at" in line for line in controller.log)

    def test_console_is_not_flooded_while_the_alert_persists(self) -> None:
        controller = HudController(sampler=StubSampler(snapshot_with(memory_used_fraction=0.96)))
        controller.cycleMode()
        poll(controller, RAISE_SAMPLES + 20)
        announcements = [line for line in controller.log if "Memory pressure at" in line]
        assert len(announcements) == 1

    def test_a_full_filesystem_is_escalated(self) -> None:
        full = DiskUsage(mount_point="/", total=1_000, free=10)
        controller = HudController(sampler=StubSampler(snapshot_with(disks=(full,))))
        poll(controller, RAISE_SAMPLES)
        assert controller.alertActive is True
        assert controller.alertLabel == "Storage /"

    def test_alert_signal_is_emitted(self) -> None:
        controller = HudController(sampler=StubSampler(snapshot_with(memory_used_fraction=0.96)))
        controller.cycleMode()
        emissions: list[int] = []
        controller.alertChanged.connect(lambda: emissions.append(1))
        poll(controller, RAISE_SAMPLES)
        assert emissions, "alertChanged never fired for an escalated condition"

    def test_unavailable_memory_escalates_nothing(self) -> None:
        empty = TelemetrySnapshot(monotonic_time=0.0, degraded_sources=("memory",))
        controller = HudController(sampler=StubSampler(empty))
        controller.cycleMode()
        poll(controller, RAISE_SAMPLES + 2)
        assert controller.alertActive is False


# -- refusal-to-guess must never become a consent prompt --------------------

#: The kernel's answer to an unmappable jarvis_do, captured from 1.20.0.
_UNMATCHED_DO = {
    "outcome": {
        "status": "refused",
        "tier": 0,
        "playbook": "<unmatched>",
        "error": (
            "I cannot map this request to a known playbook and I will not "
            "guess (anti-hallucination policy)."
        ),
        "hint": "Known playbooks: fs.list, fs.read, sys.uptime",
    }
}


def _do_response(payload: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "isError": True,
            "content": [{"type": "text", "text": json.dumps(payload)}],
        },
    }


def test_unmatched_do_raises_no_consent_prompt_under_kernel_only(
    controller: HudController,
) -> None:
    # Under KERNEL_ONLY the GUI skips the preview and calls jarvis_do
    # directly, so the plan.unmatched guard never runs. The classifier has to
    # carry the distinction on its own, or the owner is asked to approve a
    # request the kernel never understood -- and approving it would simply
    # earn the identical refusal.
    assert controller.setConfirmPolicy("KERNEL_ONLY") is True
    controller._last_do_request = "clean up disk space"
    controller._on_kernel_completed("do", classify_outcome(_do_response(_UNMATCHED_DO)))

    assert controller.pendingConsent == ""
    assert controller.consentGate == ""
    joined = " ".join(controller.log).lower()
    assert "will not guess" in joined
    # The consent sentence must not appear for a request that cannot be run.
    assert "needs your explicit consent" not in joined


def test_unmatched_do_lists_what_the_kernel_can_do(controller: HudController) -> None:
    assert controller.setConfirmPolicy("KERNEL_ONLY") is True
    controller._on_kernel_completed("do", classify_outcome(_do_response(_UNMATCHED_DO)))
    joined = " ".join(controller.log)
    assert "sys.uptime" in joined


def test_genuine_consent_refusal_still_prompts(controller: HudController) -> None:
    # The counterweight: a real T2 refusal must still reach the owner as a
    # decision point, or the fix above would have disabled the consent gate.
    payload = {
        "outcome": {
            "status": "refused",
            "tier": 2,
            "hint": 're-call jarvis_do with "allow": true to consent explicitly',
        }
    }
    controller._last_do_request = "upgrade the whole system"
    controller._on_kernel_completed("do", classify_outcome(_do_response(payload)))

    assert controller.pendingConsent == "upgrade the whole system"
    assert controller.consentGate == "KERNEL_CONSENT"
