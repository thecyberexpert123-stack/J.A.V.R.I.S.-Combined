"""Inferred routines (ADR-0012 M8b) — read-only, evidence-cited, never stored.

Routines are derived on demand from the local journal and shown with an
explicit confidence; nothing inferred is persisted (the journal itself is the
only record, so `jarvis context forget` cannot leave stale inference behind —
a deliberate, documented deviation from "stored routines" in the ADR sketch).
A routine never grants authority: at most it notes that a charter (M9d) might
fit the observed cadence, for the owner to consider.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jarvis.safety.charter import playbook_tiers


def infer_routines(journal: Any, *, window_days: int = 30) -> list[dict[str, object]]:
    """Group journaled tasks by playbook inside the window; estimate cadence."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    per_playbook: dict[str, list[str]] = {}
    for row in journal.recent_tasks(limit=1000):
        created = str(row.get("created_utc", ""))
        try:
            if datetime.fromisoformat(created) < datetime.fromisoformat(cutoff):
                continue
        except ValueError:
            continue  # unparseable timestamp: skip, never crash
        per_playbook.setdefault(str(row.get("playbook_id", "")), []).append(created)

    tiers = playbook_tiers()
    routines: list[dict[str, object]] = []
    for playbook_id, stamps in sorted(per_playbook.items()):
        count = len(stamps)
        if count < 2:
            continue  # one-off tasks are not routines
        if count >= 20:
            cadence, confidence = "~daily", "high"
        elif count >= 8:
            cadence, confidence = "~weekly", "high"
        elif count >= 3:
            cadence, confidence = "~weekly-or-less", "medium"
        else:
            cadence, confidence = "ad-hoc", "low"
        tier = tiers.get(playbook_id)
        hint = ""
        if count >= 3 and tier is not None and tier <= 2:
            hint = (
                f"recurring T{tier} task — a charter (jarvis charter install) could fit,"
                " if you want it automated"
            )
        routines.append(
            {
                "playbook_id": playbook_id,
                "runs_in_window": count,
                "window_days": window_days,
                "cadence": cadence,
                "confidence": confidence,
                "last_utc": max(stamps),
                "charter_hint": hint,
                "evidence": (
                    f"journal: {count} tasks on {playbook_id} in the last {window_days} days"
                ),
                "inferred": True,
            }
        )
    routines.sort(
        key=lambda r: (
            -int(r["runs_in_window"]) if isinstance(r["runs_in_window"], int) else 0,
            str(r["playbook_id"]),
        )
    )
    return routines
