"""M8d — supervised growth loop (ADR-0012): drafting validated against the
real KB store and the M9b skill machinery; proposals are inert data; the
kernel/policy stays outside the write scope; promotion is owner-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.cli.app import main
from jarvis.planner.grow import (
    GrowError,
    draft_fact,
    draft_skill,
    export_proposal,
    list_proposals,
    prune_proposal,
    show_proposal,
)
from jarvis.planner.skills import install_skill  # noqa: F401 (promotion is separate)
from jarvis.safety.integrity import default_scope


def fact_doc(**overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "id": "test.fact",
        "topic": "testing",
        "claim": "A test fact with a real citation so the store accepts it.",
        "patterns": ["test fact please"],
        "sources": [{"kind": "docs", "ref": "tests (local)", "url": "https://example.invalid"}],
    }
    doc.update(overrides)
    return doc


def env_of(tmp_path: Path) -> dict[str, str]:
    return {"JARVIS_STATE_DIR": str(tmp_path / "state")}


def write_pack(tmp_path: Path) -> Path:
    pack = {
        "schema": 1,
        "id": "grow-skill",
        "description": "a proposed alias pack",
        "match": "^(?:refresh|sync)\\s+(?:everything|all)$",
        "playbook": "pkg.cache.refresh",
        "params": {},
        "evals": [{"request": "refresh everything"}],
        "provenance": {
            "source": "https://example.invalid/pack",
            "sha256": "0" * 64,
        },
    }
    path = tmp_path / "grow.skill.json"
    path.write_text(json.dumps(pack, indent=2))
    return path


# -- fact drafting through the real citation-required store ----------------------


def test_draft_fact_accepted_by_real_store(tmp_path: Path) -> None:
    env = env_of(tmp_path)
    result = draft_fact(fact_doc(), env=env)
    assert result["kind"] == "fact"
    assert Path(str(result["path"])).is_file()
    assert len(list_proposals(env)) == 1


def test_draft_fact_uncited_is_refused_by_the_store(tmp_path: Path) -> None:
    with pytest.raises(GrowError, match="ADR-0009"):
        draft_fact(fact_doc(sources=[]), env=env_of(tmp_path))
    assert list_proposals(env_of(tmp_path)) == []


def test_draft_fact_bad_verifier_kind_refused(tmp_path: Path) -> None:
    with pytest.raises(GrowError, match=r"verify\.kind"):
        draft_fact(fact_doc(verify={"kind": "telepathy"}), env=env_of(tmp_path))


# -- skill proposals through the M9b machinery ------------------------------------


def test_draft_skill_validated(tmp_path: Path) -> None:
    env = env_of(tmp_path)
    result = draft_skill(write_pack(tmp_path), env=env)
    assert result["kind"] == "skill"
    assert "grow-skill" in show_proposal("grow-skill", env)


def test_draft_skill_rejects_bad_pack(tmp_path: Path) -> None:
    pack = json.loads(write_pack(tmp_path).read_text())
    pack["playbook"] = "free.lunch"
    path = tmp_path / "bad.skill.json"
    path.write_text(json.dumps(pack))
    with pytest.raises(GrowError, match="playbook must be one of"):
        draft_skill(path, env=env_of(tmp_path))


# -- lifecycle: list / show / prune / export ---------------------------------------


def test_show_and_prune(tmp_path: Path) -> None:
    env = env_of(tmp_path)
    draft_fact(fact_doc(), rationale="owner asked for it", env=env)
    assert "test.fact" in show_proposal("test.fact", env)
    assert prune_proposal("test.fact", env) is True
    assert prune_proposal("test.fact", env) is False
    with pytest.raises(GrowError, match="no proposal"):
        show_proposal("test.fact", env)


def test_export_fact_produces_owner_commands(tmp_path: Path) -> None:
    env = env_of(tmp_path)
    draft_fact(fact_doc(), env=env)
    out = tmp_path / "export"
    exported = export_proposal("test.fact", out, env=env)
    assert exported["kind"] == "fact"
    artifact = Path(str(exported["artifact"]))
    assert artifact.is_file()
    commands = exported["commands"]
    assert isinstance(commands, list)
    assert any("gh pr create" in str(c) for c in commands)
    assert any("YOU merge" in str(c) for c in commands)  # merge stays with the owner


def test_export_unknown_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(GrowError, match="no proposal"):
        export_proposal("nope", tmp_path / "x", env=env_of(tmp_path))


def test_proposals_stay_outside_the_integrity_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    draft_fact(fact_doc(), env=env_of(tmp_path))
    names = {path.name for path in default_scope().entries()}
    assert "test.fact.json" not in names  # inert data is not policy state


def test_drafting_never_touches_the_shipped_kb(tmp_path: Path) -> None:
    """The growth loop's hard boundary: the live store is unchanged."""
    from jarvis.knowledge.store import load_kb

    before = len(load_kb().facts)
    draft_fact(fact_doc(), env=env_of(tmp_path))
    assert len(load_kb().facts) == before


# -- CLI --------------------------------------------------------------------------


def test_cli_fact_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    argv = [
        "--json",
        "grow",
        "fact",
        "--id",
        "cli.fact",
        "--topic",
        "testing",
        "--claim",
        "A cited claim for the CLI path.",
        "--pattern",
        "cli fact, please test",
        "--sources",
        json.dumps([{"kind": "docs", "ref": "local tests"}]),
    ]
    assert main(argv) == 0
    assert main(["grow", "list"]) == 0
    assert "cli.fact" in capsys.readouterr().out


def test_cli_fact_uncited_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    argv = [
        "grow",
        "fact",
        "--id",
        "bad.fact",
        "--topic",
        "t",
        "--claim",
        "c",
        "--pattern",
        "p",
        "--sources",
        "[]",
    ]
    assert main(argv) == 2
    assert "ADR-0009" in capsys.readouterr().err


def test_cli_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    draft_fact(fact_doc(id="exp.fact"), env=env_of(tmp_path))
    assert main(["grow", "export", "exp.fact", "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "exported" in out and "owner actions" in out
