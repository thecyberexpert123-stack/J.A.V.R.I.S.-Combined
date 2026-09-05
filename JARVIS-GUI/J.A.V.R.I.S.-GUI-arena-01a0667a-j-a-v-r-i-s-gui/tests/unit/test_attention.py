"""Tests for the attention-escalation policy."""

from __future__ import annotations

import pytest

from javris.attention import (
    CLEAR_SAMPLES,
    ERROR_THRESHOLD,
    RAISE_SAMPLES,
    RELEASE_MARGIN,
    WARN_THRESHOLD,
    AttentionMonitor,
    MetricReading,
    Prominence,
    Severity,
    classify,
)


def reading(
    key: str = "memory",
    fraction: float | None = 0.95,
    prominence: Prominence = Prominence.PERIPHERAL,
) -> MetricReading:
    """Build a reading with sensible defaults for the field under test."""
    return MetricReading(
        key=key,
        label=key.title(),
        fraction=fraction,
        readout="--" if fraction is None else f"{fraction * 100:.1f}",
        unit="%",
        prominence=prominence,
        advice="advice",
    )


def drive(
    monitor: AttentionMonitor,
    readings: tuple[MetricReading, ...],
    times: int,
) -> None:
    """Feed the same sample repeatedly."""
    for _ in range(times):
        monitor.update(readings)


class TestClassify:
    def test_none_is_normal_not_a_problem(self) -> None:
        # Absence of data must never be reported as a fault.
        assert classify(None) is Severity.NORMAL

    def test_below_warn_is_normal(self) -> None:
        assert classify(WARN_THRESHOLD - 0.01) is Severity.NORMAL

    def test_warn_threshold_is_inclusive(self) -> None:
        assert classify(WARN_THRESHOLD) is Severity.WARN

    def test_error_threshold_is_inclusive(self) -> None:
        assert classify(ERROR_THRESHOLD) is Severity.CRITICAL

    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0, 2.0])
    def test_never_raises_on_any_finite_input(self, value: float) -> None:
        assert classify(value) in set(Severity)


class TestRaising:
    def test_no_alert_when_everything_is_calm(self) -> None:
        monitor = AttentionMonitor()
        assert monitor.update((reading(fraction=0.1),)) is None

    def test_requires_sustained_condition(self) -> None:
        monitor = AttentionMonitor()
        sample = (reading(fraction=0.95),)
        for _ in range(RAISE_SAMPLES - 1):
            assert monitor.update(sample) is None, "raised on a transient spike"
        assert monitor.update(sample) is not None

    def test_single_spike_does_not_raise(self) -> None:
        monitor = AttentionMonitor()
        monitor.update((reading(fraction=0.99),))
        monitor.update((reading(fraction=0.10),))
        drive(monitor, (reading(fraction=0.10),), RAISE_SAMPLES)
        assert monitor.active is None

    def test_unavailable_metric_is_never_escalated(self) -> None:
        # Escalating a metric with no reading would mean inventing a fault.
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=None),), RAISE_SAMPLES + 2)
        assert monitor.active is None

    def test_central_metric_is_not_escalated(self) -> None:
        # It is already occupying the main display; promoting it is a no-op
        # that would only hide the rest of the HUD for nothing.
        monitor = AttentionMonitor()
        drive(
            monitor,
            (reading(fraction=0.99, prominence=Prominence.CENTRAL),),
            RAISE_SAMPLES + 2,
        )
        assert monitor.active is None

    def test_alert_carries_the_reading_verbatim(self) -> None:
        monitor = AttentionMonitor()
        drive(monitor, (reading(key="swap", fraction=0.93),), RAISE_SAMPLES)
        alert = monitor.active
        assert alert is not None
        assert alert.key == "swap"
        assert alert.readout == "93.0"
        assert alert.unit == "%"
        assert alert.severity is Severity.CRITICAL


class TestPriority:
    def test_only_one_alert_at_a_time(self) -> None:
        monitor = AttentionMonitor()
        sample = (reading(key="a", fraction=0.95), reading(key="b", fraction=0.92))
        drive(monitor, sample, RAISE_SAMPLES)
        alert = monitor.active
        assert alert is not None
        assert alert.key in {"a", "b"}

    def test_critical_outranks_warning(self) -> None:
        monitor = AttentionMonitor()
        sample = (
            reading(key="warn", fraction=0.75),
            reading(key="crit", fraction=0.95),
        )
        drive(monitor, sample, RAISE_SAMPLES)
        alert = monitor.active
        assert alert is not None
        assert alert.key == "crit"

    def test_higher_fraction_breaks_a_tie_within_a_band(self) -> None:
        monitor = AttentionMonitor()
        sample = (reading(key="low", fraction=0.91), reading(key="high", fraction=0.97))
        drive(monitor, sample, RAISE_SAMPLES)
        alert = monitor.active
        assert alert is not None
        assert alert.key == "high"

    def test_selection_is_deterministic_for_identical_values(self) -> None:
        first = AttentionMonitor()
        second = AttentionMonitor()
        sample = (reading(key="b", fraction=0.95), reading(key="a", fraction=0.95))
        drive(first, sample, RAISE_SAMPLES)
        drive(second, tuple(reversed(sample)), RAISE_SAMPLES)
        assert first.active is not None
        assert second.active is not None
        assert first.active.key == second.active.key


class TestClearing:
    def test_clears_after_sustained_recovery(self) -> None:
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        assert monitor.active is not None
        drive(monitor, (reading(fraction=0.10),), CLEAR_SAMPLES)
        assert monitor.active is None

    def test_does_not_clear_on_a_single_good_sample(self) -> None:
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        monitor.update((reading(fraction=0.10),))
        assert monitor.active is not None

    def test_hysteresis_holds_inside_the_release_band(self) -> None:
        # Just under the warn threshold but inside the release margin: the
        # alert must not flap off and back on.
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        inside = WARN_THRESHOLD - RELEASE_MARGIN / 2
        drive(monitor, (reading(fraction=inside),), CLEAR_SAMPLES + 2)
        assert monitor.active is not None

    def test_releases_below_the_release_band(self) -> None:
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        below = WARN_THRESHOLD - RELEASE_MARGIN - 0.01
        drive(monitor, (reading(fraction=below),), CLEAR_SAMPLES)
        assert monitor.active is None

    def test_held_alert_never_reports_normal_severity(self) -> None:
        # Inside the band the raw classification is NORMAL; an alert that is
        # still on screen must not render with no severity.
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        monitor.update((reading(fraction=WARN_THRESHOLD - RELEASE_MARGIN / 2),))
        alert = monitor.active
        assert alert is not None
        assert alert.severity is Severity.WARN

    def test_becoming_central_releases_immediately(self) -> None:
        # The operator switched to a mode that shows this metric large and
        # central, so they are now looking straight at it. Hysteresis guards
        # against a value flapping, not against a mode change, so this must
        # not wait out the recovery streak.
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        assert monitor.active is not None
        monitor.update((reading(fraction=0.95, prominence=Prominence.CENTRAL),))
        assert monitor.active is None

    def test_becoming_unavailable_releases_immediately(self) -> None:
        # Holding the last known number on screen as a live alert would be a
        # fabricated reading.
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        monitor.update((reading(fraction=None),))
        assert monitor.active is None

    def test_disappearing_metric_releases_and_is_forgotten(self) -> None:
        # A filesystem can be unmounted between polls.
        monitor = AttentionMonitor()
        drive(monitor, (reading(key="disk:/mnt", fraction=0.99),), RAISE_SAMPLES)
        assert monitor.active is not None
        assert monitor.update(()) is None

    def test_reset_drops_everything(self) -> None:
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        monitor.reset()
        assert monitor.active is None
        monitor.update((reading(fraction=0.95),))
        assert monitor.active is None, "streak survived a reset"


class TestSeverityEscalationInPlace:
    def test_warning_can_become_critical_without_clearing(self) -> None:
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.75),), RAISE_SAMPLES)
        first = monitor.active
        assert first is not None
        assert first.severity is Severity.WARN

        monitor.update((reading(fraction=0.97),))
        second = monitor.active
        assert second is not None
        assert second.key == first.key
        assert second.severity is Severity.CRITICAL

    def test_readout_tracks_the_live_value(self) -> None:
        monitor = AttentionMonitor()
        drive(monitor, (reading(fraction=0.95),), RAISE_SAMPLES)
        monitor.update((reading(fraction=0.99),))
        alert = monitor.active
        assert alert is not None
        assert alert.readout == "99.0"
