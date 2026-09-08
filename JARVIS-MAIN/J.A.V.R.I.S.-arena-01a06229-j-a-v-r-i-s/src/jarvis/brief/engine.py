"""The briefing engine (ADR-0021): sense → compose → decide → deliver → ledger.

Zero subprocesses in composition: the journal is a local sqlite DB, the
suggestions engine is journal/context-only, disk pressure is `os.statvfs`.
Delivery is presentation only (a state-dir markdown file plus an optional
probed `notify-send` with fixed argv). Pure functions wherever testable.

Environment signals (ADR-0031): ``sense()`` runs *before* ``compose()`` and
hands it a frozen ``Signals`` value — battery / link / slept from sysfs,
metered / sleep-or-shutdown-imminent / locked from the system bus through the
stdlib client — still without a subprocess. Signals add lines (S1-S3) or
*hold* the desktop knock (S4/S5); nothing sensed ever reaches the planner or
triggers execution. ``--signals off`` skips sensing and keeps ``latest.md``
and stdout byte-identical to the pre-ADR engine.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

from jarvis.brief.signals import DEFAULT_BATTERY_LOW, MODES, Signals, sense
from jarvis.context.store import ContextStore, default_context_path
from jarvis.core.fingerprint import build_profile
from jarvis.journal.sqlite import Journal, state_dir
from jarvis.safety.tiers import SafetyRefusal
from jarvis.suggest.engine import generate_suggestions

statvfs: Callable[[str], object] = os.statvfs  # patched in tests

DEFAULT_DISK_FREE_PCT = 15.0
FAILURE_WINDOW_DAYS = 7
MAX_NOTIFY_LINE = 200
_LEDGER = "ledger.jsonl"
_LATEST = "latest.md"
_NOTIFY_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Briefing:
    """A composed candidate briefing plus the policy decision on it."""

    briefing_id: str
    created: str
    items: tuple[str, ...] = field(default_factory=tuple)
    decision: str = "silence"  # "notify" | "silence"
    reasons: tuple[str, ...] = field(default_factory=tuple)
    # ADR-0031 (additive, defaults keep every existing constructor call valid)
    holds: tuple[str, ...] = field(default_factory=tuple)
    signals: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    context: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "id": self.briefing_id,
            "created": self.created,
            "items": list(self.items),
            "decision": self.decision,
            "reasons": list(self.reasons),
            "holds": list(self.holds),
            "signals": dict(self.signals),
        }

    def markdown(self) -> str:
        lines = [f"# JARVIS briefing {self.briefing_id}", f"created: {self.created}", ""]
        lines += [f"- {item}" for item in self.items]
        lines += ["", f"decision: {self.decision} ({'; '.join(self.reasons) or 'n/a'})"]
        # only when something was sensed — byte-identical output in "off" mode
        if self.context:
            lines.append(f"context: {self.context}")
        if self.holds:
            lines.append(f"held: {', '.join(self.holds)} (desktop notification withheld)")
        return "\n".join(lines) + "\n"

    def replace(self, **changes: object) -> Briefing:
        """A copy with fields changed (frozen dataclass)."""
        return dc_replace(self, **changes)  # type: ignore[arg-type]

    def notify_line(self) -> str:
        """One hygiened line for the desktop notification."""
        text = "; ".join(self.items[:2]) or f"briefing {self.briefing_id}"
        text = " ".join(_NOTIFY_RE.sub(" ", text).split())
        return text[:MAX_NOTIFY_LINE]


# --------------------------------------------------------------------------
# composition (all local, zero subprocess)
# --------------------------------------------------------------------------


def disk_free_pct(mount: str = "/") -> float:
    stat = statvfs(mount)
    blocks = getattr(stat, "f_blocks", 0)
    free = getattr(stat, "f_bavail", 0)
    if blocks <= 0:
        return 100.0
    return (free / blocks) * 100.0


def compose(
    journal: Journal,
    context: ContextStore,
    profile: object,
    *,
    disk_free: float | None = None,
    now: datetime | None = None,
    signals: Signals | None = None,
    battery_low: int = DEFAULT_BATTERY_LOW,
) -> Briefing:
    """Gather items from the four local sources (+ sensed signals); no decision yet.

    ``signals`` is the frozen result of ``sense()`` — composition itself
    never senses, so it stays subprocess- and bus-free by construction.
    """
    moment = now or datetime.now(timezone.utc)
    stamp = moment.replace(microsecond=0).isoformat()
    items: list[str] = []

    failures = 0
    try:
        tasks = journal.recent_tasks(limit=50)
    except Exception:
        tasks = []
    cutoff = moment - timedelta(days=FAILURE_WINDOW_DAYS)
    for task in tasks:
        created = str(task.get("created_utc", ""))
        try:
            when = datetime.fromisoformat(created)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff and str(task.get("status")) in {"failed", "interrupted"}:
            failures += 1
    if failures:
        items.append(f"{failures} task(s) failed in the last {FAILURE_WINDOW_DAYS} days")

    try:
        suggestions = generate_suggestions(profile, journal, context, now=moment)  # type: ignore[arg-type]
    except Exception:
        suggestions = []
    if suggestions:
        items.append(f"{len(suggestions)} maintenance suggestion(s) waiting (jarvis suggest)")

    try:
        unknowns = journal.recent_unknown_requests(limit=10)
    except Exception:
        unknowns = []
    if unknowns:
        items.append(f"{len(unknowns)} unmapped request(s) to review (jarvis grow)")

    free = disk_free if disk_free is not None else disk_free_pct()
    if free < DEFAULT_DISK_FREE_PCT:
        items.append(f"low disk: {free:.1f}% free on /")

    sensed = signals if signals is not None else Signals()
    signal_items = sensed.items(battery_low)
    items.extend(signal_items)

    digest = f"{stamp}|{failures}|{len(suggestions)}|{len(unknowns)}|{free:.1f}"
    if signal_items:  # the id stays as before whenever no signal line was added
        digest += "|" + "|".join(signal_items)
    import hashlib

    briefing_id = hashlib.sha256(digest.encode("utf-8")).hexdigest()[:12]
    return Briefing(
        briefing_id=briefing_id,
        created=stamp,
        items=tuple(items),
        signals=MappingProxyType(sensed.to_json_dict() if sensed.mode != "off" else {}),
        context=sensed.context_line(),
        holds=sensed.holds(),
    )


# --------------------------------------------------------------------------
# policy (pure, deterministic, inspectable)
# --------------------------------------------------------------------------


def decide(briefing: Briefing) -> Briefing:
    """The v1 policy: notify iff any reason fires; otherwise silence + reason.

    Holds (ADR-0031 D3) do not change the decision vocabulary: a held
    briefing is still ``notify`` — composed, written to ``latest.md`` and
    ledgered — only the desktop knock is withheld by ``run_once``.
    """
    reasons = tuple(briefing.items)
    if reasons:
        return briefing.replace(decision="notify", reasons=reasons)
    return briefing.replace(items=(), decision="silence", reasons=("nothing to report",))


# --------------------------------------------------------------------------
# ledger (append-only jsonl) + delivery
# --------------------------------------------------------------------------


class BriefLedger:
    def __init__(self, state: Path | None = None) -> None:
        self._dir = (state_dir() if state is None else state) / "briefings"

    @property
    def directory(self) -> Path:
        return self._dir

    def record_run(self, briefing: Briefing, *, delivered: bool) -> None:
        record: dict[str, object] = {
            "ts": briefing.created,
            "kind": "run",
            "id": briefing.briefing_id,
            "decision": briefing.decision,
            "reasons": list(briefing.reasons),
            "delivered": delivered,
        }
        if briefing.holds:  # additive keys, present only when they carry information
            record["holds"] = list(briefing.holds)
        if briefing.signals:
            record["signals"] = dict(briefing.signals)
        self._append(record)

    def record_event(self, event: str, detail: Mapping[str, object] | None = None) -> None:
        """A sensed event from the listener (ADR-0031 D8): recorded, never acted on."""
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        record: dict[str, object] = {"ts": stamp, "kind": "event", "event": event}
        if detail:
            record.update(detail)
        self._append(record)

    def record_delivery(self, briefing_id: str, *, trigger: str, delivered: bool) -> None:
        """The listener delivered (or failed to deliver) a held briefing."""
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self._append(
            {
                "ts": stamp,
                "kind": "delivery",
                "id": briefing_id,
                "trigger": trigger,
                "delivered": delivered,
            }
        )

    def held_undelivered(self, *, now: datetime | None = None) -> dict[str, object] | None:
        """The most recent held ``run`` (today, UTC) with no later delivery record.

        ``now`` is injectable for tests; production callers use the wall clock.
        """
        latest: dict[str, object] | None = None
        delivered_ids: set[str] = set()
        for line in self._lines():
            record = json.loads(line)
            kind = record.get("kind")
            if kind == "run":
                if record.get("holds") and record.get("decision") == "notify":
                    latest = record
                else:
                    latest = None  # a newer, un-held run supersedes the held one
            elif kind == "delivery" and record.get("delivered"):
                delivered_ids.add(str(record.get("id")))
        if latest is None or str(latest.get("id")) in delivered_ids:
            return None
        today = (now or datetime.now(timezone.utc)).date().isoformat()
        if not str(latest.get("ts", "")).startswith(today):
            return None
        return latest

    def last_suspend(self) -> dict[str, object] | None:
        """The ``signals.suspend`` record of the most recent run, for the S6 delta."""
        for line in reversed(self._lines()):
            record = json.loads(line)
            if record.get("kind") != "run":
                continue
            signals = record.get("signals")
            if isinstance(signals, dict) and isinstance(signals.get("suspend"), dict):
                return dict(signals["suspend"])
            return None
        return None

    def record_feedback(self, briefing_id: str, verdict: str) -> None:
        if verdict not in {"accept", "dismiss"}:
            raise SafetyRefusal("verdict must be accept or dismiss")
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self._append({"ts": stamp, "kind": "feedback", "id": briefing_id, "verdict": verdict})

    def stats(self) -> dict[str, object]:
        runs = 0
        notified = 0
        held = 0
        accepts = 0
        dismisses = 0
        events = 0
        deliveries = 0
        last: dict[str, object] | None = None
        for line in self._lines():
            record = json.loads(line)
            kind = record.get("kind")
            if kind == "run":
                runs += 1
                if record.get("decision") == "notify":
                    notified += 1
                    if record.get("holds"):
                        held += 1  # a knock that was withheld, not merely a sensed hold
                last = record
            elif kind == "feedback":
                if record.get("verdict") == "accept":
                    accepts += 1
                elif record.get("verdict") == "dismiss":
                    dismisses += 1
            elif kind == "event":
                events += 1
            elif kind == "delivery" and record.get("delivered"):
                deliveries += 1
        return {
            "runs": runs,
            "notified": notified,
            "silenced": runs - notified,
            "silence_rate": round((runs - notified) / runs, 3) if runs else None,
            "accepted": accepts,
            "dismissed": dismisses,
            "last_run": last,
            # ADR-0031 (additive)
            "held": held,
            "events": events,
            "late_deliveries": deliveries,
        }

    def write_latest(self, briefing: Briefing) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / _LATEST
        path.write_text(briefing.markdown(), encoding="utf-8")
        return path

    def _append(self, payload: dict[str, object]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with (self._dir / _LEDGER).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def _lines(self) -> list[str]:
        path = self._dir / _LEDGER
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(line)
        return out


def desktop_notify(text: str, *, which: Callable[[str], str | None] = shutil.which) -> bool:
    """One hygiened notify-send line; False (honestly) when unavailable/failed."""
    if which("notify-send") is None:
        return False
    clean = " ".join(_NOTIFY_RE.sub(" ", text).split())[:MAX_NOTIFY_LINE]
    if not clean:
        return False
    try:
        result = subprocess.run(
            ["notify-send", "JARVIS", clean],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def run_once(
    *,
    quiet: bool = False,
    json_output: bool = False,
    no_desktop: bool = False,
    state: Path | None = None,
    journal: Journal | None = None,
    profile: object | None = None,
    disk_free: float | None = None,
    now: datetime | None = None,
    signals_mode: str = "sysfs",
    battery_low: int = DEFAULT_BATTERY_LOW,
    sysfs_root: Path = Path("/"),
    bus_address: str | None = None,
) -> dict[str, object]:
    """Sense → compose → decide → deliver → ledger. Returns the payload for --json/CLI.

    ``signals_mode`` ∈ ``off|sysfs|bus`` (ADR-0031 D2; the owner chose
    ``sysfs`` as the default). A hold (S4/S5) withholds the desktop knock
    only: ``latest.md`` and the ledger are written exactly as for a delivered
    briefing, with ``delivered=false`` and the ``holds`` list.
    """
    if signals_mode not in MODES:
        raise SafetyRefusal(f"--signals must be one of {', '.join(MODES)}")
    if not 0 <= battery_low <= 100:
        raise SafetyRefusal("--battery-low must be between 0 and 100")
    jn = journal if journal is not None else Journal(state_dir() / "journal.db")
    prof = profile if profile is not None else build_profile()
    context = ContextStore(default_context_path())
    ledger = BriefLedger(state)
    sensed = sense(
        signals_mode,
        root=sysfs_root,
        previous_suspend=ledger.last_suspend() if signals_mode != "off" else None,
        bus_address=bus_address,
    )
    candidate = compose(
        jn, context, prof, disk_free=disk_free, now=now, signals=sensed, battery_low=battery_low
    )
    briefing = decide(candidate)
    delivered = False
    if briefing.decision == "notify":
        ledger.write_latest(briefing)
        if not no_desktop and not briefing.holds:
            delivered = desktop_notify(briefing.notify_line())
        ledger.record_run(briefing, delivered=delivered)
    else:
        ledger.record_run(briefing, delivered=False)

    if json_output:
        payload = briefing.to_json_dict()
        payload["delivered"] = delivered
        return payload
    if briefing.decision == "notify":
        if not quiet:
            print(briefing.markdown(), end="")
            if briefing.holds:
                print(
                    f"(held: {', '.join(briefing.holds)}; written to briefings/latest.md, "
                    "no desktop notification)"
                )
            elif not delivered and not no_desktop:
                print("(desktop notification unavailable; written to briefings/latest.md)")
    elif not quiet:
        print("nothing to report (silence recorded)")
    return briefing.to_json_dict()
