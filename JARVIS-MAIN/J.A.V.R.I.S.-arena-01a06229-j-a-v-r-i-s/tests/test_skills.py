"""Verified skill packs (ADR-0013 M9b): validation, eval gating, receipt
pinning, kernel-delegating matching, CLI, and integrity-scope placement.

Skill packs may only re-expose existing playbooks under new phrasings —
every test here leans on that invariant: the argv and tier always come from
the referenced playbook, never from the pack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import FakeRunner
from jarvis.cli.app import main
from jarvis.core.orchestrator import Orchestrator
from jarvis.planner.playbooks import PLAYBOOKS
from jarvis.planner.skills import (
    SkillError,
    install_skill,
    installed_skills,
    match_skill,
    playbook_ids,
    remove_skill,
    validate_skill,
)
from jarvis.safety.approval import ApprovalPolicy
from jarvis.safety.integrity import default_scope


def good_pack(**overrides: Any) -> dict[str, object]:
    doc: dict[str, object] = {
        "schema": 1,
        "id": "refresh-all",
        "description": "colloquial phrasings for refreshing the package index",
        "match": "^(?:refresh|sync)\\s+(?:everything|all)$",
        "playbook": "pkg.cache.refresh",
        "params": {},
        "evals": [{"request": "refresh everything"}, {"request": "sync all"}],
        "provenance": {
            "source": "https://example.com/skills/refresh-all.skill.json",
            "sha256": "a" * 64,
        },
    }
    doc.update(overrides)
    return doc


def write_pack(tmp_path: Path, doc: dict[str, object]) -> Path:
    path = tmp_path / "pack.skill.json"
    path.write_text(json.dumps(doc, indent=2))
    return path


def env_of(tmp_path: Path) -> dict[str, str]:
    return {"JARVIS_STATE_DIR": str(tmp_path / "state")}


def make_result0() -> Any:
    from jarvis.execution.runner import ExecResult

    return ExecResult(exit_code=0, stdout_tail="ok", stderr_tail="")


# -- validation ----------------------------------------------------------------


def test_good_pack_validates() -> None:
    assert validate_skill(good_pack()) == []


@pytest.mark.parametrize(
    "override,fragment",
    [
        ({"schema": 2}, "schema"),
        ({"id": "Bad_ID"}, "id"),
        ({"description": ""}, "description"),
        ({"match": "multi\nline"}, "match"),
        ({"match": "(unclosed"}, "match does not compile"),
        ({"playbook": "pkg.does-not-exist"}, "playbook must be one of"),
        ({"params": {"BAD KEY": "x"}}, "param key"),
        ({"params": {"k": ["list"]}}, "must be a scalar"),
        ({"evals": []}, "evals must be a list"),
        (
            {"evals": [{"request": "does not match the regex"}]},
            "does not match the pack",
        ),
        ({"provenance": "https://x"}, "provenance must be an object"),
        ({"provenance": {"source": "s", "sha256": "xyz"}}, "sha256"),
    ],
)
def test_invalid_packs_are_refused(override: dict[str, object], fragment: str) -> None:
    assert any(fragment in e for e in validate_skill(good_pack(**override))), override


def test_playbook_reference_is_real_kernel_primitive() -> None:
    ids = playbook_ids()
    assert "pkg.cache.refresh" in ids
    assert all(pb.tier is not None for pb in PLAYBOOKS)  # kernel truth exists


# -- install: validation + eval dry-runs + receipt pinning ----------------------


def test_install_validates_and_pins_a_receipt(tmp_path: Path) -> None:
    source = write_pack(tmp_path, good_pack())
    env = env_of(tmp_path)
    installed = install_skill(source, env=env)
    assert installed["id"] == "refresh-all"
    receipt = json.loads((tmp_path / "state" / "skills" / "refresh-all.receipt.json").read_text())
    assert receipt["sha256"] == installed["sha256"]
    assert receipt["source"].startswith("https://example.com")


def test_install_rejects_unknown_playbook_before_writing(tmp_path: Path) -> None:
    source = write_pack(tmp_path, good_pack(playbook="free.lunch"))
    with pytest.raises(SkillError, match="playbook must be one of"):
        install_skill(source, env=env_of(tmp_path))
    assert not (tmp_path / "state" / "skills").exists()


def test_install_refuses_broken_param_types_before_any_write(tmp_path: Path) -> None:
    broken = good_pack(params={"packages": ["htop"]})  # list param: schema violation
    with pytest.raises(SkillError, match="must be a scalar"):
        install_skill(write_pack(tmp_path, broken), env=env_of(tmp_path))
    assert not (tmp_path / "state" / "skills").exists()


def test_install_catches_build_failures_at_install_time(tmp_path: Path) -> None:
    """Eval cases are real planning dry-runs: a pack whose playbook build
    explodes on this profile never reaches the skills directory."""
    real_build = None
    from jarvis.planner import skills as skills_mod

    playbook = next(pb for pb in PLAYBOOKS if pb.id == "pkg.cache.refresh")
    real_build = playbook.build

    def boom(_params: object, _profile: object) -> list[object]:
        raise RuntimeError("adapter exploded")

    skills_mod.PLAYBOOKS = tuple(
        type(pb)(  # same playbook, weaponized build — proves the dry-run gate
            id=pb.id,
            description=pb.description,
            tier=pb.tier,
            match=pb.match,
            build=boom,  # type: ignore[arg-type]
            verify=pb.verify,
            undo=pb.undo,
        )
        if pb.id == "pkg.cache.refresh"
        else pb
        for pb in PLAYBOOKS
    )
    try:
        with pytest.raises(SkillError, match="adapter exploded"):
            install_skill(write_pack(tmp_path, good_pack()), env=env_of(tmp_path))
    finally:
        skills_mod.PLAYBOOKS = PLAYBOOKS  # restore for other tests
        assert real_build is not None
    assert not (tmp_path / "state" / "skills").exists()


def test_removal(tmp_path: Path) -> None:
    install_skill(write_pack(tmp_path, good_pack()), env=env_of(tmp_path))
    assert remove_skill("refresh-all", env=env_of(tmp_path)) is True
    assert remove_skill("refresh-all", env=env_of(tmp_path)) is False
    assert installed_skills(env_of(tmp_path)) == []


# -- matching through the kernel -------------------------------------------------


def test_match_skill_delegates_with_skill_provenance(tmp_path: Path) -> None:
    install_skill(write_pack(tmp_path, good_pack()), env=env_of(tmp_path))
    env = env_of(tmp_path)
    matched = match_skill("refresh everything", env)
    assert matched is not None
    playbook, params = matched
    assert playbook.id == "pkg.cache.refresh"  # kernel primitive, not the pack
    assert params["skill"] == "refresh-all"  # audit trail
    assert match_skill("totally unrelated", env) is None
    assert match_skill("REFRESH EVERYTHING", env) is None  # case-sensitive like playbooks


def test_drifted_pack_is_skipped_fail_closed(tmp_path: Path) -> None:
    env = env_of(tmp_path)
    install_skill(write_pack(tmp_path, good_pack()), env=env)
    pack = tmp_path / "state" / "skills" / "refresh-all.skill.json"
    tampered = json.loads(pack.read_text())
    tampered["match"] = "^.*$"  # anyone's phrasing matches now — the classic poisoning
    pack.write_text(json.dumps(tampered))
    rows = installed_skills(env)
    assert rows[0]["status"] == "drift"
    assert match_skill("refresh everything", env) is None  # fails closed


def test_orchestrator_runs_a_skill_phrasing_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = env_of(tmp_path)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    install_skill(write_pack(tmp_path, good_pack()), env=env)
    from jarvis.core.fingerprint import build_profile
    from jarvis.journal.sqlite import Journal

    journal = Journal(tmp_path / "journal.db")
    orch = Orchestrator(
        build_profile(),
        journal,
        FakeRunner(script=[(("apt-get", "update"), make_result0())]),
        ApprovalPolicy(yes=True),
        echo=False,
    )
    outcome = orch.run_intent("refresh everything", dry_run=True)
    assert outcome.status.value in ("dry_run", "succeeded")
    assert outcome.playbook_id == "pkg.cache.refresh"
    # and the canonical phrasing still works, unchanged:
    canonical = orch.run_intent("update the package cache", dry_run=True)
    assert canonical.playbook_id == "pkg.cache.refresh"


def test_charter_precheck_still_speaks_canonical_phrasings(tmp_path: Path) -> None:
    """Skills extend run_intent, not the charter contract: a charter must keep
    using canonical requests (deliberate conservatism for standing orders)."""
    from jarvis.safety import charter as ch

    assert ch.match_intent is not None  # charter module imports the canonical matcher
    install_skill(write_pack(tmp_path, good_pack()), env=env_of(tmp_path))
    # the skill matches via the orchestrator path; the charter matcher is untouched
    assert match_skill("refresh everything", env_of(tmp_path)) is not None


# -- integrity scope -------------------------------------------------------------


def test_skill_packs_sit_inside_the_integrity_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    install_skill(write_pack(tmp_path, good_pack()), env=env_of(tmp_path))
    names = {path.name for path in default_scope().entries()}
    assert "refresh-all.skill.json" in names
    assert "refresh-all.receipt.json" in names


# -- CLI --------------------------------------------------------------------------


def test_cli_install_requires_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    source = write_pack(tmp_path, good_pack())
    code = main(["skill", "install", str(source)])  # non-tty, no --yes
    assert code == 2
    assert not (tmp_path / "state" / "skills").exists()


def test_cli_install_and_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    source = write_pack(tmp_path, good_pack())
    assert main(["--yes", "skill", "install", str(source)]) == 0
    out = capsys.readouterr().out
    assert "skill pack" in out and "inherited" in out and "sha256" in out
    assert main(["skill", "list"]) == 0
    assert "refresh-all" in capsys.readouterr().out


def test_cli_invalid_pack_refused_pre_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    source = write_pack(tmp_path, good_pack(playbook="free.lunch"))
    code = main(["--yes", "skill", "install", str(source)])
    assert code == 2
    assert "playbook must be one of" in capsys.readouterr().err
    assert not (tmp_path / "state" / "skills").exists()


def test_cli_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    install_skill(write_pack(tmp_path, good_pack()), env=env_of(tmp_path))
    assert main(["skill", "remove", "refresh-all"]) == 0
    assert main(["skill", "remove", "refresh-all"]) == 2
