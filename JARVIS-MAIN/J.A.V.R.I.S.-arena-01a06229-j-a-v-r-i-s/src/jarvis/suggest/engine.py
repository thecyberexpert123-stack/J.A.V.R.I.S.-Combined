"""Suggestion engine (M8a, ADR-0012): evidence-backed, read-only proposals.

Every suggestion cites its evidence (journal records or KB facts with
sources) — cite-or-abstain applies to suggestions. The engine holds no
Runner and executes nothing; `accept` prints the exact command for the user
to run through the normal consent path. Handled suggestions (accepted or
rejected) are suppressed from future listings via the feedback ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from jarvis.knowledge.store import KnowledgeError, load_kb

if TYPE_CHECKING:
    from jarvis.context.store import ContextStore
    from jarvis.core.fingerprint import MachineProfile
    from jarvis.journal.sqlite import Journal

STALE_REFRESH_DAYS = 14
MAX_SUGGESTIONS = 5
SCAN_WINDOW = 200

_REFRESH_PLAYBOOKS = ("pkg.cache.refresh", "pkg.upgrade")

# KB pitfall suggestions relevant per distro (cite-or-abstain: each names its
# fact and the fact's sources). question must match the fact's patterns.
_PITFALLS: tuple[tuple[str, str, str, str], ...] = (
    (
        "arch",
        "pitfall.arch.partial-upgrade",
        "arch pacman partial upgrade warning",
        "reads the Arch partial-upgrade pitfall (cited)",
    ),
    (
        "debian",
        "pitfall.debian.noninteractive",
        "apt noninteractive best practice",
        "reads the DEBIAN_FRONTEND pitfall (cited)",
    ),
    (
        "ubuntu",
        "pitfall.debian.noninteractive",
        "apt noninteractive best practice",
        "reads the DEBIAN_FRONTEND pitfall (cited)",
    ),
)


@dataclass(frozen=True)
class Suggestion:
    id: str
    title: str
    detail: str
    command: str  # the exact command accept prints; the user runs it themselves
    priority: int  # lower sorts first
    evidence: tuple[dict[str, str], ...] = field(default_factory=tuple)
    sources: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "detail": self.detail,
            "command": self.command,
            "evidence": [dict(e) for e in self.evidence],
            "sources": [dict(s) for s in self.sources],
        }


def _parse_utc(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def generate_suggestions(
    profile: MachineProfile,
    journal: Journal,
    context: ContextStore,
    *,
    now: datetime | None = None,
) -> list[Suggestion]:
    """Deterministic, evidence-backed suggestions. Read-only by construction."""
    moment = now or datetime.now(timezone.utc)
    handled = context.decisions()
    out: list[Suggestion] = []

    try:
        tasks = journal.recent_tasks(limit=SCAN_WINDOW)
    except Exception:
        tasks = []

    # S1: failed/interrupted tasks whose undo artifact is still available.
    for task in tasks:
        task_id = str(task["id"])
        sid = f"undo:{task_id}"
        if sid in handled:
            continue
        if str(task.get("status")) not in ("failed", "interrupted"):
            continue
        raw_tier = task.get("tier", 0)
        tier_val = int(raw_tier) if isinstance(raw_tier, (int, float)) else 0
        if tier_val < 1:
            continue
        try:
            artifact = journal.get_undo(task_id)
        except Exception:
            artifact = None
        if artifact is None or artifact.get("status") != "available":
            continue
        out.append(
            Suggestion(
                id=sid,
                title=f"undo failed task {task_id}",
                detail=(
                    f"task {task_id} ({task.get('intent_text', '')!r}) ended "
                    f"'{task.get('status')}' and its undo artifact is available. Review "
                    f"with `jarvis undo {task_id} --dry-run`, then reverse it."
                ),
                command=f"jarvis undo {task_id}",
                priority=1,
                evidence=(
                    {
                        "kind": "journal",
                        "detail": (
                            f"task {task_id} status={task.get('status')} "
                            f"at {task.get('created_utc')}"
                        ),
                    },
                ),
            )
        )

    # S2: package index stale (no successful refresh/upgrade recently).
    sid = "refresh:stale"
    if sid not in handled:
        last_refresh: datetime | None = None
        for task in tasks:
            if (
                str(task.get("playbook_id")) in _REFRESH_PLAYBOOKS
                and str(task.get("status")) == "succeeded"
            ):
                parsed = _parse_utc(str(task.get("created_utc", "")))
                if parsed and (last_refresh is None or parsed > last_refresh):
                    last_refresh = parsed
        if last_refresh is None:
            out.append(
                Suggestion(
                    id=sid,
                    title="refresh the package index",
                    detail=(
                        "no successful package-index refresh is recorded in the journal; "
                        "a stale index makes installs unreliable."
                    ),
                    command='jarvis do "refresh the package index" --preview',
                    priority=2,
                    evidence=(
                        {
                            "kind": "journal",
                            "detail": "no pkg.cache.refresh/pkg.upgrade success found",
                        },
                    ),
                )
            )
        else:
            age_days = (moment - last_refresh).days
            if age_days > STALE_REFRESH_DAYS:
                out.append(
                    Suggestion(
                        id=sid,
                        title="refresh the package index",
                        detail=(
                            f"last successful refresh was {age_days} days ago "
                            f"({last_refresh.date()}); indexes older than "
                            f"{STALE_REFRESH_DAYS} days go stale."
                        ),
                        command='jarvis do "refresh the package index" --preview',
                        priority=2,
                        evidence=(
                            {
                                "kind": "journal",
                                "detail": (
                                    f"last refresh {last_refresh.isoformat()} ({age_days}d ago)"
                                ),
                            },
                        ),
                    )
                )

    # S3: distro-relevant pitfall from the cited KB.
    distro = str(profile.distro_id).lower().strip()
    try:
        kb = load_kb()
    except KnowledgeError:
        kb = None
    if kb is not None:
        for want_distro, fact_id, question, blurb in _PITFALLS:
            sid = f"pitfall:{fact_id}"
            if distro != want_distro or sid in handled:
                continue
            fact = next((f for f in kb.facts if f.id == fact_id), None)
            if fact is None:
                continue
            out.append(
                Suggestion(
                    id=sid,
                    title=f"pitfall briefing: {fact_id}",
                    detail=f"{fact.claim} — {blurb} with `jarvis explain`.",
                    command=f'jarvis explain "{question}"',
                    priority=3,
                    evidence=(
                        {"kind": "kb", "fact_id": fact.id, "claim": fact.claim},
                        {"kind": "machine", "detail": f"distro={distro}"},
                    ),
                    sources=tuple(
                        {"kind": s.kind, "ref": s.ref, **({"url": s.url} if s.url else {})}
                        for s in fact.sources
                    ),
                )
            )
            break  # one pitfall briefing at a time

    out.sort(key=lambda s: (s.priority, s.id))
    return out[:MAX_SUGGESTIONS]
