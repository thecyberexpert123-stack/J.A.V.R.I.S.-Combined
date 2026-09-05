"""Persisted circuit breaker for LLM providers (ADR-0014 D1).

A CLI process dies between commands, so breaker state lives on disk: a hung
or failing model must not re-impose its full request timeout on every
invocation, forever. The state file is operational, not policy — it persists
as a ``.state`` file (the M9d charter precedent) and sits deliberately
OUTSIDE the M9c integrity scope: a tripped breaker is an observation about
the world, not a decision about authority. Nothing here can execute, consent,
or widen anything — it only says whether the next provider call may be
attempted, and remembers why previous ones failed.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from jarvis.journal.sqlite import _utcnow, state_dir
from jarvis.providers.base import Provider, ProviderError

DEFAULT_THRESHOLD = 3
DEFAULT_COOLDOWN_S = 300.0


def _as_int(value: object, default: int) -> int:
    return int(value) if isinstance(value, (int, float)) else default


def _as_float(value: object, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def default_breaker_path(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "ai" / "breaker.state"


class ProviderBreaker:
    """Three-state (closed/open/half-open) breaker persisted across processes.

    Wall-clock cooldown so the state survives process boundaries (JARVIS is
    process-per-command); a corrupted state file resets cleanly and says so.
    Half-open admits exactly one probe per process; concurrent processes may
    probe concurrently (accepted, documented in ADR-0014).
    """

    def __init__(
        self,
        path: Path,
        *,
        threshold: int = DEFAULT_THRESHOLD,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._records: dict[str, dict[str, object]] = self._load()
        self._probing: set[str] = set()

    # -- persistence -------------------------------------------------------
    def _load(self) -> dict[str, dict[str, object]]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return {}
        try:
            data = json.loads(raw)
            providers = data["providers"]
            if not isinstance(providers, dict):
                raise ValueError("providers must be an object")
            return {str(k): dict(v) for k, v in providers.items() if isinstance(v, dict)}
        except (ValueError, KeyError, TypeError):
            print(
                "jarvis ai-breaker: state file unreadable; resetting breaker state",
                file=sys.stderr,
            )
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        document = {"version": 1, "providers": self._records}
        self._path.write_text(json.dumps(document, sort_keys=True, indent=2), encoding="utf-8")

    # -- decisions ---------------------------------------------------------
    def allow(self, name: str) -> tuple[bool, str]:
        """May the next call to *name* be attempted? Returns (allowed, note)."""
        record = self._records.get(name)
        if not record:
            return True, "closed (no recorded failures)"
        failures = _as_int(record.get("failures", 0), 0)
        opened_at = _as_float(record.get("opened_at", 0.0), 0.0)
        if opened_at <= 0.0:
            return True, f"closed ({failures} consecutive failure(s))"
        age = self._clock() - opened_at
        if age >= self._cooldown_s:
            if name in self._probing:
                return False, f"half-open probe already in flight for {name}"
            self._probing.add(name)
            return True, f"half-open: probing {name} after {age:.0f}s cooldown"
        remaining = self._cooldown_s - age
        return (
            False,
            f"circuit breaker OPEN for {name} (last failure: "
            f"{record.get('last_reason', 'unknown')} at {record.get('last_utc', '?')}; "
            f"retry in ~{remaining:.0f}s, or run with --no-ai to skip the AI path)",
        )

    def release_probe(self, name: str) -> None:
        """Clear the half-open probe mark (single-process bookkeeping)."""
        self._probing.discard(name)

    def record_success(self, name: str) -> None:
        if self._records.pop(name, None) is not None:
            self._save()
        self._probing.discard(name)

    def record_failure(self, name: str, kind: str, detail: str) -> None:
        record = self._records.get(name) or {}
        failures = _as_int(record.get("failures", 0), 0) + 1
        opened_at = _as_float(record.get("opened_at", 0.0), 0.0)
        if failures >= self._threshold:
            opened_at = self._clock()
        self._records[name] = {
            "failures": failures,
            "opened_at": opened_at,
            "last_reason": kind[:80],
            "last_utc": _utcnow(),
        }
        del detail  # kept out of the persisted record on purpose (may embed model output)
        self._save()
        self._probing.discard(name)

    def views(self) -> dict[str, dict[str, object]]:
        """Snapshot for `status`/`doctor` disclosure — reads, never writes."""
        now = self._clock()
        out: dict[str, dict[str, object]] = {}
        for name, record in self._records.items():
            failures = _as_int(record.get("failures", 0), 0)
            opened_at = _as_float(record.get("opened_at", 0.0), 0.0)
            if opened_at > 0.0 and now - opened_at < self._cooldown_s:
                state = "open"
            elif opened_at > 0.0:
                state = "half-open"
            else:
                state = "closed"
            out[name] = {
                "state": state,
                "failures": failures,
                "last_reason": str(record.get("last_reason", "")),
                "last_utc": str(record.get("last_utc", "")),
            }
        return out


def guarded_complete(
    provider: Provider,
    system: str,
    user: str,
    breaker: ProviderBreaker | None = None,
    *,
    timeout_s: float = 90.0,
    schema: dict[str, object] | None = None,
) -> str:
    """`provider.complete` behind the breaker (ADR-0014 D1/D2).

    Raises ProviderError(kind=BREAKER_OPEN) without touching the network when
    the breaker is open. Success/failure *recording* stays with the caller —
    only the caller can distinguish a malformed-output failure from an honest
    "unexpressible" answer (the latter must not trip the breaker).
    """
    if breaker is not None:
        allowed, note = breaker.allow(provider.name)
        if not allowed:
            raise ProviderError(note, kind="breaker-open")
    try:
        return provider.complete(system, user, timeout_s=timeout_s, schema=schema)
    finally:
        if breaker is not None:
            breaker.release_probe(provider.name)
