"""M8a suggestion engine: evidence-backed, read-only, suppression via ledger."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.context.store import ContextStore
from jarvis.core.fingerprint import build_profile
from jarvis.journal.sqlite import Journal
from jarvis.suggest.engine import MAX_SUGGESTIONS, generate_suggestions

NOW = datetime.now(timezone.utc)


def _journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "j.db")


def _task(
    journal: Journal,
    task_id: str,
    *,
    playbook: str = "pkg.install",
    status: str = "succeeded",
    tier: int = 1,
    intent: str = "do the thing",
    age_days: float = 0.0,
) -> None:
    journal.begin_task(task_id, intent, playbook, tier, {}, {"distro_id": "debian"})
    journal.finish_task(task_id, status)
    if age_days:
        # backdate by rewriting the row (journal is append-only by API)
        stamp = (NOW - timedelta(days=age_days)).isoformat(timespec="seconds")
        journal._conn.execute("UPDATE tasks SET created_utc = ? WHERE id = ?", (stamp, task_id))
        journal._conn.commit()


# -- S1: undo orphans ------------------------------------------------------------


def test_undo_orphan_suggested_with_evidence(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    _task(journal, "t1", status="failed", tier=2, intent="upgrade the system")
    journal.store_undo("t1", {"steps": [], "verify": [], "tier": 2})
    profile = build_profile()
    suggestions = generate_suggestions(profile, journal, context, now=NOW)
    match = [s for s in suggestions if s.id == "undo:t1"]
    assert match, "failed task with available undo must be suggested"
    s = match[0]
    assert s.command == "jarvis undo t1"
    assert s.evidence and s.evidence[0]["kind"] == "journal"
    assert "failed" in s.detail


def test_undo_orphan_excludes_clean_tasks_and_tier0(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    _task(journal, "ok", status="succeeded", tier=2)
    journal.store_undo("ok", {"steps": [], "verify": [], "tier": 2})
    _task(journal, "t0", status="failed", tier=0)
    journal.store_undo("t0", {"steps": [], "verify": [], "tier": 0})
    _task(journal, "noart", status="failed", tier=1)
    suggestions = generate_suggestions(build_profile(), journal, context, now=NOW)
    ids = [s.id for s in suggestions]
    assert "undo:ok" not in ids and "undo:t0" not in ids and "undo:noart" not in ids


# -- S2: stale package index ------------------------------------------------------


def test_stale_refresh_suggested_when_old_or_missing(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    _task(journal, "old", playbook="pkg.cache.refresh", age_days=20)
    suggestions = generate_suggestions(build_profile(), journal, context, now=NOW)
    match = [s for s in suggestions if s.id == "refresh:stale"]
    assert match and "20 days ago" in match[0].detail
    assert 'jarvis do "refresh the package index" --preview' in match[0].command


def test_fresh_refresh_not_suggested(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    _task(journal, "fresh", playbook="pkg.cache.refresh", age_days=1)
    suggestions = generate_suggestions(build_profile(), journal, context, now=NOW)
    assert all(s.id != "refresh:stale" for s in suggestions)


# -- S3: cited pitfall briefings ----------------------------------------------------


def test_pitfall_suggestion_cites_kb_sources(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    profile = build_profile()  # debian in this environment
    suggestions = generate_suggestions(profile, journal, context, now=NOW)
    pitfalls = [s for s in suggestions if s.id.startswith("pitfall:")]
    if profile.distro_id.lower() not in ("debian", "ubuntu", "arch"):
        assert not pitfalls
        return
    assert pitfalls
    s = pitfalls[0]
    assert s.sources, "pitfall suggestion must cite sources"
    assert any(src.get("url") for src in s.sources)


def test_pitfall_only_for_relevant_distro(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    profile = build_profile()
    suggestions = generate_suggestions(profile, journal, context, now=NOW)
    if profile.distro_id.lower() == "arch":
        assert any(s.id == "pitfall:pitfall.arch.partial-upgrade" for s in suggestions)
    elif profile.distro_id.lower() in ("debian", "ubuntu"):
        assert any(s.id == "pitfall:pitfall.debian.noninteractive" for s in suggestions)


# -- suppression / ledger / invariants -----------------------------------------------


def test_handled_suggestions_suppressed(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    _task(journal, "t1", status="failed", tier=1)
    journal.store_undo("t1", {"steps": [], "verify": [], "tier": 1})
    profile = build_profile()
    assert any(s.id == "undo:t1" for s in generate_suggestions(profile, journal, context, now=NOW))
    context.record_feedback("undo:t1", "rejected", reason="already handled it myself")
    context.record_feedback("refresh:stale", "accepted")
    remaining = generate_suggestions(profile, journal, context, now=NOW)
    ids = [s.id for s in remaining]
    assert "undo:t1" not in ids and "refresh:stale" not in ids


def test_engine_is_read_only_and_deterministic(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    _task(journal, "t1", status="failed", tier=1)
    journal.store_undo("t1", {"steps": [], "verify": [], "tier": 1})
    profile = build_profile()
    first = generate_suggestions(profile, journal, context, now=NOW)
    second = generate_suggestions(profile, journal, context, now=NOW)
    assert [s.to_json_dict() for s in first] == [s.to_json_dict() for s in second]
    # generation must not mutate the journal
    assert journal.get_task("t1") is not None
    assert len(journal.recent_tasks(limit=50)) == 1


def test_cap_and_priority_sort(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    context = ContextStore(tmp_path / "c.db")
    for i in range(8):
        _task(journal, f"t{i}", status="failed", tier=1)
        journal.store_undo(f"t{i}", {"steps": [], "verify": [], "tier": 1})
    suggestions = generate_suggestions(build_profile(), journal, context, now=NOW)
    assert len(suggestions) <= MAX_SUGGESTIONS
    priorities = [s.priority for s in suggestions]
    assert priorities == sorted(priorities)


def test_broken_journal_never_crashes_suggestions(tmp_path: Path) -> None:
    class Broken:
        def recent_tasks(self, limit: int = 20) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
            raise RuntimeError("db locked")

    context = ContextStore(tmp_path / "c.db")
    suggestions = generate_suggestions(build_profile(), Broken(), context, now=NOW)  # type: ignore[arg-type]
    assert isinstance(suggestions, list)


# -- CLI ---------------------------------------------------------------------------


def test_cli_suggest_list_and_accept_reject_flow(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "suggest"]) == 0
    docs = _json_docs(capsys.readouterr().out)
    assert any(d["id"] == "refresh:stale" for d in docs if isinstance(d, dict))

    assert main(["suggest", "accept", "refresh:stale"]) == 0
    accepted = capsys.readouterr().out
    assert 'jarvis do "refresh the package index" --preview' in accepted

    assert main(["suggest", "reject", "refresh:stale", "--reason", "dup"]) == 0
    assert main(["--json", "suggest"]) == 0
    after = _json_docs(capsys.readouterr().out)
    assert all(d.get("id") != "refresh:stale" for d in after if isinstance(d, dict))


def test_cli_suggest_reject_requires_reason(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["suggest", "reject", "refresh:stale"]) == 2


def test_cli_suggest_accept_unknown_id(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["suggest", "accept", "nope:404"]) == 2


def test_cli_context_show(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["context", "show"]) == 0
    assert "empty" in capsys.readouterr().out
    main(["suggest", "accept", "refresh:stale"])
    capsys.readouterr()
    assert main(["--json", "context", "show"]) == 0
    docs = [d for d in _json_docs(capsys.readouterr().out) if isinstance(d, dict)]
    assert docs and isinstance(docs[-1].get("feedback"), list)  # M8b: structured store view
    feedback = docs[-1]["feedback"]
    assert feedback and feedback[-1]["suggestion_id"] == "refresh:stale"


def _json_docs(text: str) -> list[object]:  # type: ignore[type-arg]
    decoder = json.JSONDecoder()
    docs: list[object] = []
    idx = text.find("{")
    while idx != -1:
        try:
            obj, end = decoder.raw_decode(text, idx)
            docs.append(obj)
            idx = text.find("{", end)
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
    return docs
