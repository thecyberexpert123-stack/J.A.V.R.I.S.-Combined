"""Charters: circuit-broken standing orders (ADR-0013 M9d; hardened M8c design).

A charter is a versioned, revocable contract that pre-authorizes exactly one
natural-language request — resolvable to an allowlisted playbook at or under a
tier ceiling (< T3, hard) — on a schedule. The field research (OpenClaw
heartbeats, AutoGPT loops) shows recurring autonomy fails through drift,
endless retries, and absent budgets, so every charter carries circuit
breakers: failure policy = pause (a failed firing stops the charter until the
owner resumes), per-run step cap, monthly run budget (counted from the
journal, conservatively), and a systemd ``TimeoutStartSec`` wall-clock bound.
Every firing is a normal journaled task through the same Orchestrator —
charters add *scheduling*, never a new authority path. Charter contracts are
policy-relevant state: they sit inside the M9c integrity scope, so byte
drift trips ``jarvis doctor``.

Anti-Ultron clause (ADR-0012) holds: a charter cannot modify charters, code,
or policy; it can only play its own allowlisted request.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jarvis.journal.sqlite import _utcnow, state_dir
from jarvis.planner.playbooks import PLAYBOOKS, match_intent

CHARTER_SCHEMA = 1
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_CALENDAR_RE = re.compile(r"^[A-Za-z0-9 .*:,/+-]{1,64}$")
_REQUEST_RE = re.compile(r"^[^\n\r]{1,200}$")
MAX_TIER_CEILING = 2  # T3 is refused by the kernel itself; charters never reach it
FAILURE_POLICY = "pause"  # the only policy in this release


class CharterError(ValueError):
    """A charter document violates its schema or invariants."""


def charters_dir(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "charters"


def charter_path(charter_id: str, env: dict[str, str] | None = None) -> Path:
    return charters_dir(env) / f"{charter_id}.json"


def state_path(charter_id: str, env: dict[str, str] | None = None) -> Path:
    # Deliberately NOT *.json: operational state must stay outside the
    # integrity scope's glob so pausing/resuming never trips jarvis doctor.
    return charters_dir(env) / f"{charter_id}.state"


def playbook_tiers() -> dict[str, int]:
    return {playbook.id: int(playbook.tier) for playbook in PLAYBOOKS}


def validate_charter(doc: dict[str, object]) -> list[str]:
    """Return all schema/invariant violations ([] means valid)."""
    errors: list[str] = []
    cid = doc.get("id")
    if not isinstance(cid, str) or not _ID_RE.fullmatch(cid):
        errors.append("id must match [a-z][a-z0-9-]{1,30}")
    request = doc.get("request")
    if not isinstance(request, str) or not _REQUEST_RE.fullmatch(request):
        errors.append("request must be one non-empty line of at most 200 chars")
    ceiling = doc.get("tier_ceiling")
    if (
        not isinstance(ceiling, int)
        or isinstance(ceiling, bool)
        or not 0 <= ceiling <= MAX_TIER_CEILING
    ):
        errors.append(
            f"tier_ceiling must be an integer 0..{MAX_TIER_CEILING} (T3 is never charterable)"
        )
    playbooks = doc.get("playbooks")
    tiers = playbook_tiers()
    if (
        not isinstance(playbooks, list)
        or not playbooks
        or any(not isinstance(p, str) for p in playbooks)
    ):
        errors.append("playbooks must be a non-empty list of playbook ids")
    else:
        for pid in playbooks:
            assert isinstance(pid, str)
            if pid not in tiers:
                errors.append(f"unknown playbook in allowlist: {pid}")
            elif isinstance(ceiling, int) and tiers[pid] > ceiling:
                errors.append(
                    f"playbook {pid} is T{tiers[pid]}, above the charter ceiling T{ceiling}"
                )
    steps = doc.get("max_steps_per_run")
    if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 64:
        errors.append("max_steps_per_run must be an integer 1..64")
    budget = doc.get("monthly_run_budget")
    if not isinstance(budget, int) or isinstance(budget, bool) or not 1 <= budget <= 1000:
        errors.append("monthly_run_budget must be an integer 1..1000")
    timeout = doc.get("timeout_start_sec")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 30 <= timeout <= 86400:
        errors.append("timeout_start_sec must be an integer 30..86400")
    calendar = doc.get("on_calendar")
    if calendar is not None and (
        not isinstance(calendar, str) or not _CALENDAR_RE.fullmatch(calendar)
    ):
        errors.append(
            "on_calendar must be a single-line systemd OnCalendar value (or null for manual)"
        )
    return errors


def write_charter(doc: dict[str, object], env: dict[str, str] | None = None) -> Path:
    errors = validate_charter(doc)
    if errors:
        raise CharterError("; ".join(errors))
    assert isinstance(doc["id"], str)
    path = charter_path(doc["id"], env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    state_path(doc["id"], env).write_text(
        json.dumps(
            {
                "status": "active",
                "failures": 0,
                "runs": 0,
                "last_run_utc": None,
                "paused_reason": "",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return path


def load_charter(charter_id: str, env: dict[str, str] | None = None) -> dict[str, object]:
    path = charter_path(charter_id, env)
    if not path.is_file():
        raise CharterError(f"no charter {charter_id!r} (list with: jarvis charter list)")
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict):
        raise CharterError(f"charter file for {charter_id!r} is not an object")
    errors = validate_charter(doc)
    if errors:
        raise CharterError(f"charter {charter_id!r} failed validation: {'; '.join(errors)}")
    return doc


def read_state(charter_id: str, env: dict[str, str] | None = None) -> dict[str, object]:
    path = state_path(charter_id, env)
    if not path.is_file():
        return {
            "status": "missing",
            "failures": 0,
            "runs": 0,
            "last_run_utc": None,
            "paused_reason": "",
        }
    state = json.loads(path.read_text())
    if not isinstance(state, dict):
        raise CharterError(f"charter state for {charter_id!r} is corrupt")
    return state


def write_state(
    charter_id: str, state: dict[str, object], env: dict[str, str] | None = None
) -> None:
    state_path(charter_id, env).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def set_status(
    charter_id: str, status: str, *, reason: str = "", env: dict[str, str] | None = None
) -> None:
    state = read_state(charter_id, env)
    state["status"] = status
    state["paused_reason"] = reason
    write_state(charter_id, state, env)


def count_recent_runs(journal: Any, allowlist: list[str], *, window_days: int = 30) -> int:
    """Journaled tasks on allowlisted playbooks inside the window (any status:
    conservative — owner-run tasks count too, which can only pause earlier)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    count = 0
    for row in journal.recent_tasks(limit=1000):
        created = str(row.get("created_utc", ""))
        playbook_id = str(row.get("playbook_id", ""))
        try:
            if playbook_id in allowlist and datetime.fromisoformat(
                created
            ) >= datetime.fromisoformat(cutoff):
                count += 1
        except ValueError:
            continue  # unparseable timestamp: skip rather than crash the check
    return count


def precheck(doc: dict[str, object], state: dict[str, object], journal: Any) -> tuple[str, str]:
    """All gates before any execution. Returns (playbook_id, "") or ("", reason)."""
    charter_id = str(doc.get("id", "?"))
    status = str(state.get("status", "missing"))
    if status != "active":
        reason = str(state.get("paused_reason", "")) or "no reason recorded"
        return "", f"charter {charter_id} is {status} ({reason}); owner action required"
    errors = validate_charter(doc)
    if errors:
        set_status(charter_id, "paused", reason="failed run-time validation")
        return "", f"charter {charter_id} failed run-time validation: {'; '.join(errors)}"
    request = str(doc.get("request", ""))
    allowlist = doc.get("playbooks")
    ceiling = doc.get("tier_ceiling")
    assert isinstance(allowlist, list) and isinstance(ceiling, int)
    matched = match_intent(request)
    if matched is None:
        set_status(charter_id, "paused", reason="request no longer matches any playbook")
        return "", f"charter {charter_id}: request matches no playbook; paused"
    playbook, _params = matched
    playbook_id = playbook.id
    if playbook_id not in allowlist:
        set_status(charter_id, "paused", reason=f"plan left the allowlist: {playbook_id}")
        return "", (
            f"charter {charter_id}: resolved playbook {playbook_id} is not allowlisted; paused"
        )
    tier_value = int(playbook.tier)
    if tier_value > ceiling:
        set_status(charter_id, "paused", reason=f"plan tier T{tier_value} above ceiling")
        return "", (
            f"charter {charter_id}: playbook {playbook_id} is T{tier_value},"
            f" above ceiling T{ceiling}; paused"
        )
    budget = doc.get("monthly_run_budget")
    assert isinstance(budget, int)
    used = count_recent_runs(journal, allowlist)
    if used >= budget:
        set_status(charter_id, "paused", reason=f"monthly budget exhausted ({used}/{budget})")
        return "", f"charter {charter_id}: monthly budget exhausted ({used}/{budget}); paused"
    return playbook_id, ""


def record_firing(
    charter_id: str, outcome_status: str, *, env: dict[str, str] | None = None
) -> dict[str, object]:
    """Circuit breaker: any non-success pauses the charter (failure policy)."""
    state = read_state(charter_id, env)
    state["last_run_utc"] = _utcnow()
    state["last_status"] = outcome_status
    runs = state.get("runs", 0)
    failures = state.get("failures", 0)
    if outcome_status == "succeeded":
        state["runs"] = (runs if isinstance(runs, int) else 0) + 1
        state["failures"] = 0
    else:
        state["failures"] = (failures if isinstance(failures, int) else 0) + 1
        state["status"] = "paused"
        state["paused_reason"] = f"failure policy ({FAILURE_POLICY}): firing ended {outcome_status}"
    write_state(charter_id, state, env)
    return state


# -- systemd user timers (best effort; honest degradation to manual) ----------


def unit_documents(doc: dict[str, object], jarvis_path: str) -> tuple[str, str]:
    """(service, timer) unit texts — pure string builders, unit-tested."""
    cid = str(doc["id"])
    calendar = doc.get("on_calendar")
    assert isinstance(calendar, str)
    service = (
        "[Unit]\n"
        f"Description=JARVIS charter: {cid}\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={jarvis_path} charter run {cid}\n"
        f"TimeoutStartSec={doc['timeout_start_sec']}\n"
    )
    timer = (
        "[Unit]\n"
        f"Description=JARVIS charter timer: {cid}\n"
        "\n"
        "[Timer]\n"
        f"OnCalendar={calendar}\n"
        "Persistent=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


def user_unit_dir() -> Path:
    home = Path.home()
    return home / ".config" / "systemd" / "user"


def systemctl_user(args: list[str]) -> tuple[bool, str]:
    """Best-effort systemctl --user; never raises. (ok, detail)."""
    binary = shutil.which("systemctl")
    if binary is None:
        return False, "systemctl not found"
    try:
        completed = subprocess.run(
            [binary, "--user", *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, (completed.stderr.strip() or f"exit {completed.returncode}")
    return True, "ok"
