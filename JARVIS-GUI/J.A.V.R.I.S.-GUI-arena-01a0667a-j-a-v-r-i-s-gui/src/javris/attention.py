"""Attention escalation: promote a critical peripheral metric into the centre.

Rationale (docs/RESEARCH.md, D9-D11). The reference design's own critique is
that small gauges "dancing around" in the periphery do not actually capture
attention, because the fovea covers only a narrow angle; a competent assistant
therefore *escalates* - it hides lower-priority data and shows the problem in
the main display. "Attention management is crisis management."

Two honesty constraints shape this module:

1. **No gaze tracking.** The film's system escalates when it detects Tony is
   not looking at the gauge. We have no eye tracker and will not pretend to.
   The documented proxy is :class:`Prominence`: whether the metric is currently
   rendered centrally or only in the peripheral rail for the active mode. A
   metric that is already large and central is not escalated, because it is
   already doing the job escalation exists to do.

2. **No fabricated readings.** A metric whose value is unknown is never
   escalated; ``fraction`` is ``None`` and it is skipped entirely.

Everything here is pure and synchronous so it can be tested without Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Fraction at or above which a metric is a warning. Mirrors Theme.loadColor so
#: the escalated alert and the small gauge never disagree about severity.
WARN_THRESHOLD = 0.7

#: Fraction at or above which a metric is critical.
ERROR_THRESHOLD = 0.9

#: How far a metric must fall below its trigger threshold before the alert is
#: released. Without this band a value hovering on the threshold would flap the
#: whole centre of the HUD on and off once per poll.
RELEASE_MARGIN = 0.05

#: Consecutive qualifying samples required before an alert is raised. At the
#: default 1000 ms poll interval this is three seconds of a genuinely sustained
#: condition, not a single scheduler spike.
RAISE_SAMPLES = 3

#: Consecutive non-qualifying samples required before an alert is cleared.
CLEAR_SAMPLES = 3


class Severity(str, Enum):
    """Escalation severity of a single metric."""

    NORMAL = "NORMAL"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


#: Ordering used to pick the most important of several qualifying metrics.
_RANK = {Severity.NORMAL: 0, Severity.WARN: 1, Severity.CRITICAL: 2}


class Prominence(str, Enum):
    """How prominently a metric is already presented in the active mode.

    This is the documented stand-in for gaze direction. ``CENTRAL`` means the
    metric already occupies a large element near the middle of the display;
    ``PERIPHERAL`` means it appears only as a small row in the side rail.
    """

    CENTRAL = "CENTRAL"
    PERIPHERAL = "PERIPHERAL"


@dataclass(frozen=True, slots=True)
class MetricReading:
    """One metric offered to the monitor for consideration.

    Attributes:
        key: Stable identifier, used to track state across samples.
        label: Human-readable name shown if this metric is escalated.
        fraction: Normalised 0.0-1.0 load, or ``None`` when unavailable.
        readout: Preformatted display value, e.g. ``"94.2"``.
        unit: Unit suffix for the readout, e.g. ``"%"``.
        prominence: How this metric is presented in the current mode.
        advice: One short line explaining what the condition means.
    """

    key: str
    label: str
    fraction: float | None
    readout: str
    unit: str
    prominence: Prominence
    advice: str

    @property
    def severity(self) -> Severity:
        """Severity implied by ``fraction`` alone, ignoring hysteresis."""
        return classify(self.fraction)


@dataclass(frozen=True, slots=True)
class Alert:
    """The single condition currently promoted to the main display."""

    key: str
    label: str
    fraction: float
    readout: str
    unit: str
    severity: Severity
    advice: str


def classify(fraction: float | None) -> Severity:
    """Map a normalised load to a severity.

    An unknown value is :attr:`Severity.NORMAL`: absence of data is not
    evidence of a problem, and inventing one would be a fabricated reading.

    Args:
        fraction: Normalised 0.0-1.0 load, or ``None`` when unavailable.

    Returns:
        The severity band the value falls into.
    """
    if fraction is None:
        return Severity.NORMAL
    if fraction >= ERROR_THRESHOLD:
        return Severity.CRITICAL
    if fraction >= WARN_THRESHOLD:
        return Severity.WARN
    return Severity.NORMAL


class AttentionMonitor:
    """Decides which, if any, metric deserves the centre of the display.

    The monitor is fed the full metric set on every telemetry poll and returns
    at most one :class:`Alert`. One at a time is deliberate: escalating two
    things at once recreates the very attention-splitting the mechanism exists
    to prevent.

    Args:
        raise_samples: Consecutive qualifying samples needed to raise an alert.
        clear_samples: Consecutive non-qualifying samples needed to clear it.
    """

    def __init__(
        self,
        raise_samples: int = RAISE_SAMPLES,
        clear_samples: int = CLEAR_SAMPLES,
    ) -> None:
        self._raise_samples = max(1, raise_samples)
        self._clear_samples = max(1, clear_samples)
        self._streaks: dict[str, int] = {}
        self._clear_streak = 0
        self._active: Alert | None = None

    @property
    def active(self) -> Alert | None:
        """The alert currently escalated, or ``None``."""
        return self._active

    def reset(self) -> None:
        """Drop all history and any active alert."""
        self._streaks.clear()
        self._clear_streak = 0
        self._active = None

    def update(self, readings: tuple[MetricReading, ...]) -> Alert | None:
        """Consume one sample of every metric and return the current alert.

        Args:
            readings: Every metric for this poll, in any order.

        Returns:
            The alert to display, or ``None`` when nothing warrants the centre
            of the screen.
        """
        by_key = {reading.key: reading for reading in readings}
        self._prune(by_key)

        for reading in readings:
            if self._qualifies(reading):
                self._streaks[reading.key] = self._streaks.get(reading.key, 0) + 1
            else:
                self._streaks[reading.key] = 0

        if self._active is not None:
            self._update_active(by_key)

        if self._active is None:
            self._maybe_raise(readings)

        return self._active

    # -- internals ---------------------------------------------------------

    def _prune(self, by_key: dict[str, MetricReading]) -> None:
        """Forget metrics that are no longer being reported at all."""
        for key in [key for key in self._streaks if key not in by_key]:
            del self._streaks[key]
        if self._active is not None and self._active.key not in by_key:
            self._active = None
            self._clear_streak = 0

    def _qualifies(self, reading: MetricReading) -> bool:
        """True when a reading is eligible to be escalated.

        A metric qualifies only if it is genuinely elevated *and* it is not
        already central. The second half is the whole point: escalation moves
        information from where it will be missed to where it will not.
        """
        if reading.fraction is None:
            return False
        if reading.prominence is Prominence.CENTRAL:
            return False
        return reading.severity is not Severity.NORMAL

    def _maybe_raise(self, readings: tuple[MetricReading, ...]) -> None:
        """Promote the worst metric that has sustained its condition."""
        ready = [
            reading
            for reading in readings
            if self._streaks.get(reading.key, 0) >= self._raise_samples and self._qualifies(reading)
        ]
        if not ready:
            return
        # Worst severity wins; the highest fraction breaks a tie. The key is the
        # final tiebreaker so the choice is deterministic for a given sample.
        worst = max(
            ready,
            key=lambda item: (
                _RANK[item.severity],
                item.fraction if item.fraction is not None else 0.0,
                item.key,
            ),
        )
        self._active = _to_alert(worst)
        self._clear_streak = 0

    def _update_active(self, by_key: dict[str, MetricReading]) -> None:
        """Refresh, or release, the alert that is currently escalated."""
        assert self._active is not None  # noqa: S101 - guarded by the caller
        current = by_key[self._active.key]

        # Two conditions release the alert at once, with no streak. Hysteresis
        # exists to stop a *value* flapping around a threshold; neither of
        # these is a value oscillation, and delaying them would leave the HUD
        # displaying something untrue.
        if current.fraction is None:
            # The sensor stopped reporting. Continuing to show the last known
            # number as a live alert would be a fabricated reading.
            self._active = None
            self._clear_streak = 0
            return
        if current.prominence is Prominence.CENTRAL:
            # The operator changed to a mode that shows this metric large and
            # central, so they are now looking straight at it. Escalation has
            # nothing left to achieve.
            self._active = None
            self._clear_streak = 0
            return

        if current.fraction >= WARN_THRESHOLD - RELEASE_MARGIN:
            self._clear_streak = 0
            self._active = _to_alert(current, severity=self._escalated_severity(current))
            return

        self._clear_streak += 1
        if self._clear_streak >= self._clear_samples:
            self._active = None
            self._clear_streak = 0

    def _escalated_severity(self, reading: MetricReading) -> Severity:
        """Severity for an already-active alert, held within the release band.

        Inside the hysteresis band the raw classification would read
        ``NORMAL``, which would render an alert with no severity. The alert is
        still up, so it is reported at its lowest real band instead.
        """
        severity = reading.severity
        return Severity.WARN if severity is Severity.NORMAL else severity


def _to_alert(reading: MetricReading, severity: Severity | None = None) -> Alert:
    """Build an :class:`Alert` from a reading known to have a value."""
    assert reading.fraction is not None  # noqa: S101 - guarded by callers
    return Alert(
        key=reading.key,
        label=reading.label,
        fraction=reading.fraction,
        readout=reading.readout,
        unit=reading.unit,
        severity=severity if severity is not None else reading.severity,
        advice=reading.advice,
    )
