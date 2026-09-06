"""ADR-0030: owner-authored, narrowing-only argument policy.

Owner decisions under test: A3 (integrity-scoped + lint hint), B2 (composite
plan lists every refusing part), U3+U1 (new undo artefacts carry origins and
are policy-checked; legacy artefacts skip), ship-empty default.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FakeRunner, make_profile, make_result
from jarvis.cli.app import build_parser, main
from jarvis.core.orchestrator import Orchestrator, _undo_payload
from jarvis.planner.models import TaskStatus, UndoPlan, UndoStatus
from jarvis.planner.playbooks import PLAYBOOKS, match_intent
from jarvis.safety import argpolicy
from jarvis.safety.approval import ApprovalPolicy
from jarvis.safety.argpolicy import (
    EXAMPLE_POLICY,
    Policy,
    PolicyCache,
    load_policy,
    parse_policy,
    policy_path,
)
from jarvis.safety.integrity import default_scope
from jarvis.safety.tiers import SafetyRefusal

KNOWN = frozenset(pb.id for pb in PLAYBOOKS)
KEYS = {"pkg.remove": frozenset({"names"}), "svc.restart": frozenset({"unit"})}


def _policy(rules: list[dict[str, object]], **kw: object) -> Policy:
    doc = {"schema": 1, "rules": rules}
    return parse_policy(json.dumps(doc), known_playbooks=KNOWN, known_keys=KEYS, **kw)  # type: ignore[arg-type]


def _write_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doc: object) -> Path:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    path = policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def _orch(journal, runner=None, *, yes: bool = True) -> Orchestrator:  # type: ignore[no-untyped-def]
    return Orchestrator(
        make_profile(is_root=True),
        journal,
        runner or FakeRunner(),
        ApprovalPolicy(yes=yes),
        echo=False,
    )


# --------------------------------------------------------------------------
# D1 — parsing + effects
# --------------------------------------------------------------------------


def test_example_policy_is_valid_and_binds_as_documented() -> None:
    policy = parse_policy(json.dumps(EXAMPLE_POLICY), known_playbooks=KNOWN)
    assert policy.state == "ok" and not policy.errors
    assert {r.id for r in policy.rules} == {
        "no-kernel-removal",
        "scratch-dirs-only",
        "never-touch-login-services",
    }
    assert policy.bound_playbooks() == {
        "pkg.remove",
        "fs.remove",
        "fs.move",
        "svc.stop",
        "svc.restart",
        "svc.disable",
    }


def test_deny_regex_refuses_only_matching_values() -> None:
    policy = _policy(
        [
            {
                "id": "no-kernel",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "deny_regex": "^linux-image",
                "reason": "boot-critical",
            }
        ]
    )
    policy.check("pkg.remove", {"names": ["htop"]}, tier=1)
    with pytest.raises(SafetyRefusal, match=r"no-kernel.*linux-image-6.8.*boot-critical"):
        policy.check("pkg.remove", {"names": ["htop", "linux-image-6.8"]}, tier=1)
    # the same rule does not bind to another playbook
    policy.check("pkg.install", {"names": ["linux-image-6.8"]}, tier=1)


def test_deny_regex_uses_search_semantics_as_documented() -> None:
    policy = _policy(
        [{"id": "r", "playbooks": ["pkg.remove"], "argument": "names[]", "deny_regex": "image"}]
    )
    with pytest.raises(SafetyRefusal):  # unanchored: matches mid-string
        policy.check("pkg.remove", {"names": ["linux-image-6.8"]}, tier=1)


def test_no_allow_rule_can_override_a_deny_regardless_of_order() -> None:
    policy = _policy(
        [
            {"id": "wide", "playbooks": ["pkg.remove"], "argument": "names[]", "allow_regex": ".*"},
            {
                "id": "narrow",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "deny_regex": "^grub",
            },
        ]
    )
    with pytest.raises(SafetyRefusal, match="narrow"):
        policy.check("pkg.remove", {"names": ["grub"]}, tier=1)
    policy = _policy(
        [
            {
                "id": "narrow",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "deny_regex": "^grub",
            },
            {"id": "wide", "playbooks": ["pkg.remove"], "argument": "names[]", "allow_regex": ".*"},
        ]
    )
    with pytest.raises(SafetyRefusal, match="narrow"):
        policy.check("pkg.remove", {"names": ["grub"]}, tier=1)


def test_allow_regex_refuses_everything_else() -> None:
    policy = _policy(
        [
            {
                "id": "curated",
                "playbooks": ["pkg.install"],
                "argument": "names[]",
                "allow_regex": "^(htop|tmux|ripgrep)$",
                "reason": "",
            }
        ]
    )
    policy.check("pkg.install", {"names": ["htop", "tmux"]}, tier=1)
    with pytest.raises(SafetyRefusal, match=r"does not match allow_regex"):
        policy.check("pkg.install", {"names": ["htop", "nmap"]}, tier=1)


def test_allow_prefixes_resolve_paths_before_comparing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    policy = _policy(
        [
            {
                "id": "scratch",
                "playbooks": ["fs.remove", "fs.move"],
                "argument": "path|src|dst",
                "allow_prefixes": ["~/Downloads/", "~/tmp/"],
                "reason": "scratch only",
            }
        ]
    )
    policy.check("fs.remove", {"path": "~/Downloads/x.iso"}, tier=1)
    policy.check("fs.move", {"src": "~/tmp/a", "dst": "~/Downloads/b"}, tier=1)
    with pytest.raises(SafetyRefusal, match=r"scratch.*outside allow_prefixes"):
        policy.check("fs.remove", {"path": "~/Downloads/../.ssh/id_rsa"}, tier=1)  # traversal
    with pytest.raises(SafetyRefusal):
        policy.check("fs.move", {"src": "~/tmp/a", "dst": "~/Documents/b"}, tier=1)  # one bad key
    with pytest.raises(SafetyRefusal):
        policy.check("fs.remove", {"path": "~/Downloadsx/y"}, tier=1)  # prefix is a directory


def test_star_binds_to_every_playbook_with_that_argument() -> None:
    policy = _policy(
        [
            {
                "id": "no-ssh-anywhere",
                "playbooks": ["*"],
                "argument": "unit",
                "deny_regex": "^ssh",
                "reason": "",
            }
        ]
    )
    for pb in ("svc.stop", "svc.restart", "svc.start", "svc.status"):
        with pytest.raises(SafetyRefusal):
            policy.check(pb, {"unit": "sshd"}, tier=2)
    policy.check("pkg.remove", {"names": ["sshd"]}, tier=1)  # no `unit` key → inert


def test_rules_never_grant_or_change_tier() -> None:
    """A rule can add refusals, never remove one: check() returns None or raises."""
    policy = _policy(
        [
            {
                "id": "permissive",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "allow_regex": ".*",
                "reason": "",
            }
        ]
    )
    assert policy.check("pkg.remove", {"names": ["anything"]}, tier=1) is None
    # no field in the schema can express a grant
    doc = {
        "schema": 1,
        "rules": [
            {
                "id": "grant",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "allow_regex": ".*",
                "tier": 0,
                "skip_consent": True,
            }
        ],
    }
    bad = parse_policy(json.dumps(doc), known_playbooks=KNOWN)
    assert bad.state == "malformed" and any("unknown field" in str(f) for f in bad.errors)


@pytest.mark.parametrize(
    ("rule", "needle"),
    [
        (
            {
                "id": "bad id!",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "deny_regex": "x",
            },
            "id must match",
        ),
        ({"id": "r", "playbooks": [], "argument": "names[]", "deny_regex": "x"}, "non-empty list"),
        (
            {"id": "r", "playbooks": ["pkg.remov"], "argument": "names[]", "deny_regex": "x"},
            "unknown playbook",
        ),
        (
            {"id": "r", "playbooks": ["pkg.remove"], "argument": "", "deny_regex": "x"},
            "argument must be",
        ),
        ({"id": "r", "playbooks": ["pkg.remove"], "argument": "names[]"}, "exactly one of"),
        (
            {
                "id": "r",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "deny_regex": "x",
                "allow_regex": "y",
            },
            "exactly one of",
        ),
        (
            {"id": "r", "playbooks": ["pkg.remove"], "argument": "names[]", "deny_regex": "("},
            "does not compile",
        ),
        (
            {"id": "r", "playbooks": ["pkg.remove"], "argument": "names[]", "deny_regex": "(a+)+$"},
            "nests quantifiers",
        ),
        (
            {
                "id": "r",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "deny_regex": "x" * 201,
            },
            "longer than",
        ),
        (
            {"id": "r", "playbooks": ["pkg.remove"], "argument": "names[]", "allow_prefixes": []},
            "non-empty list",
        ),
        (
            {
                "id": "r",
                "playbooks": ["pkg.remove"],
                "argument": "names[]",
                "deny_regex": "x",
                "reason": "a\nb",
            },
            "single line",
        ),
    ],
)
def test_lint_rejects_malformed_rules(rule: dict[str, object], needle: str) -> None:
    policy = _policy([rule])
    assert policy.state == "malformed"
    assert any(needle in str(f) for f in policy.errors), [str(f) for f in policy.findings]


def test_lint_warns_when_playbook_never_produces_the_argument() -> None:
    policy = _policy(
        [{"id": "r", "playbooks": ["svc.restart"], "argument": "names[]", "deny_regex": "x"}]
    )
    assert policy.state == "ok"  # warning only; the rule stays (inert for svc.restart)
    assert any("does not produce argument 'names'" in str(f) for f in policy.warnings)


def test_duplicate_rule_ids_fail_closed_for_their_scope() -> None:
    policy = _policy(
        [
            {"id": "same", "playbooks": ["pkg.remove"], "argument": "names[]", "deny_regex": "a"},
            {"id": "same", "playbooks": ["svc.restart"], "argument": "unit", "deny_regex": "b"},
        ]
    )
    assert policy.state == "malformed" and "svc.restart" in policy.broken_scope
    with pytest.raises(SafetyRefusal, match=r"invalid rule naming svc.restart"):
        policy.check("svc.restart", {"unit": "nginx"}, tier=2)
    with pytest.raises(
        SafetyRefusal, match=r"matches deny_regex"
    ):  # the first, valid rule still binds
        policy.check("pkg.remove", {"names": ["a"]}, tier=1)


# --------------------------------------------------------------------------
# D3 — failure semantics: closed per scope, never system-wide, never wider
# --------------------------------------------------------------------------


def test_absent_file_is_the_empty_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    policy = load_policy()
    assert policy.state == "absent" and policy.rules == ()
    policy.check("pkg.remove", {"names": ["linux-image-6.8"]}, tier=1)  # today's behaviour


def test_invalid_json_refuses_t1_plus_but_t0_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_policy(tmp_path, monkeypatch, "{not json")
    policy = load_policy()
    assert policy.state == "malformed" and policy.broken_all
    with pytest.raises(SafetyRefusal, match=r"malformed; refusing pkg.remove"):
        policy.check("pkg.remove", {"names": ["htop"]}, tier=1)
    policy.check("sys.uptime", {}, tier=0)  # read-only keeps working


def test_one_broken_rule_refuses_only_what_it_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_policy(
        tmp_path,
        monkeypatch,
        {
            "schema": 1,
            "rules": [
                {
                    "id": "ok",
                    "playbooks": ["pkg.remove"],
                    "argument": "names[]",
                    "deny_regex": "^linux-image",
                },
                {
                    "id": "broken",
                    "playbooks": ["svc.restart"],
                    "argument": "unit",
                    "deny_regex": "(",
                },
            ],
        },
    )
    policy = load_policy()
    assert policy.state == "malformed" and not policy.broken_all
    assert policy.broken_scope == {"svc.restart"}
    with pytest.raises(SafetyRefusal, match=r"invalid rule naming svc.restart"):
        policy.check("svc.restart", {"unit": "nginx"}, tier=2)
    policy.check("svc.stop", {"unit": "nginx"}, tier=2)  # not named → today's behaviour
    with pytest.raises(
        SafetyRefusal, match=r"'ok' refused pkg.remove"
    ):  # the valid rule still binds
        policy.check("pkg.remove", {"names": ["linux-image-1"]}, tier=1)


def test_cache_reloads_on_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_policy(tmp_path, monkeypatch, {"schema": 1, "rules": []})
    cache = PolicyCache(path=path)
    assert cache.current().state == "ok" and cache.current() is cache.current()
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "rules": [
                    {
                        "id": "r",
                        "playbooks": ["pkg.remove"],
                        "argument": "names[]",
                        "deny_regex": "^htop$",
                    }
                ],
            }
        )
    )
    # mtime granularity can be coarse; size changed, which is enough
    assert len(cache.current().rules) == 1
    path.unlink()
    assert cache.current().state == "absent"


# --------------------------------------------------------------------------
# D2 — enforcement at the three orchestrator sites
# --------------------------------------------------------------------------


def test_single_playbook_refused_by_rule_before_anything_runs(
    journal,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    _write_policy(tmp_path, monkeypatch, EXAMPLE_POLICY)
    runner = FakeRunner()
    outcome = _orch(journal, runner).run_intent(
        "uninstall grub"
    )  # not in the code-level protected set — the owner's rule adds it
    assert outcome.status is TaskStatus.REFUSED
    assert "no-kernel-removal" in outcome.error and "boot- and login-critical" in outcome.error
    assert runner.calls == []  # nothing executed
    assert not outcome.task_id  # same non-journaled path as a check_argv refusal


def test_single_playbook_unaffected_when_no_rule_matches(
    journal,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    _write_policy(tmp_path, monkeypatch, EXAMPLE_POLICY)
    runner = FakeRunner(
        script=[
            (("apt-get", "install"), make_result(0, "Setting up htop", "")),
            (("dpkg-query", "-W"), make_result(0, "ii  htop", "")),
        ]
    )
    outcome = _orch(journal, runner).run_intent("install htop")
    assert outcome.status is TaskStatus.SUCCEEDED
    # U3: the artefact now records its origin
    artifact = journal.get_undo(outcome.task_id)
    assert artifact is not None
    assert artifact["payload"]["origins"] == [
        {"playbook_id": "pkg.install", "params": {"names": ["htop"]}}
    ]


def test_plan_lists_every_refusing_part(
    journal, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    _write_policy(tmp_path, monkeypatch, EXAMPLE_POLICY)
    runner = FakeRunner()

    def part(text: str):  # type: ignore[no-untyped-def]
        matched = match_intent(text)
        assert matched is not None
        return matched

    outcome = _orch(journal, runner).run_plan(
        "clean up",
        [part("uninstall grub"), part("system info"), part("restart sshd")],
    )
    assert outcome.status is TaskStatus.REFUSED
    assert "plan part 1 (pkg.remove)" in outcome.error and "no-kernel-removal" in outcome.error
    assert (
        "plan part 3 (svc.restart)" in outcome.error
        and "never-touch-login-services" in outcome.error
    )
    assert "part 2" not in outcome.error
    assert runner.calls == []


def test_plan_artifact_records_every_part_as_origin(
    journal, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    runner = FakeRunner(
        script=[
            (("apt-get", "install"), make_result(0, "Setting up htop", "")),
            (("dpkg-query", "-W"), make_result(0, "ii  htop", "")),
            (("uname", "-a"), make_result(0, "Linux", "")),
            (("df", "-h"), make_result(0, "/", "")),
            (("free", "-h"), make_result(0, "Mem", "")),
        ]
    )
    parts = [match_intent("install htop"), match_intent("system info")]
    outcome = _orch(journal, runner).run_plan("monitoring", parts)  # type: ignore[arg-type]
    assert outcome.status is TaskStatus.SUCCEEDED
    origins = journal.get_undo(outcome.task_id)["payload"]["origins"]  # type: ignore[index]
    assert [o["playbook_id"] for o in origins] == ["pkg.install", "sys.info"]
    assert origins[0]["params"] == {"names": ["htop"]}


def test_undo_is_policy_checked_via_origins(
    journal, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """U3: a rule written AFTER the forward run still governs its undo."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    runner = FakeRunner(
        script=[
            (("systemctl", "start"), make_result(0)),
            (("systemctl", "is-active"), make_result(0, "active", "")),
        ]
    )
    outcome = _orch(journal, runner).run_intent("start ssh.service")
    assert outcome.status is TaskStatus.SUCCEEDED
    # now the owner forbids touching ssh
    _write_policy(
        tmp_path,
        monkeypatch,
        {
            "schema": 1,
            "rules": [
                {
                    "id": "hands-off-ssh",
                    "playbooks": ["svc.start"],
                    "argument": "unit",
                    "deny_regex": "^ssh",
                }
            ],
        },
    )
    undo_runner = FakeRunner()
    undo = _orch(journal, undo_runner).undo(outcome.task_id)
    assert undo.status is TaskStatus.REFUSED
    assert "undo refused by argument policy" in undo.error and "hands-off-ssh" in undo.error
    assert undo_runner.calls == []
    assert journal.get_undo(outcome.task_id)["status"] == "available"  # type: ignore[index]


def test_legacy_undo_artifact_without_origins_skips_the_policy(
    journal,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """U1 for artefacts written before 1.22: never guess what produced them."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    runner = FakeRunner(
        script=[
            (("systemctl", "start"), make_result(0)),
            (("systemctl", "is-active"), make_result(0, "active", "")),
        ]
    )
    outcome = _orch(journal, runner).run_intent("start ssh.service")
    payload = journal.get_undo(outcome.task_id)["payload"]  # type: ignore[index]
    del payload["origins"]  # make it look pre-1.22
    journal.store_undo(outcome.task_id, payload)
    _write_policy(
        tmp_path,
        monkeypatch,
        {
            "schema": 1,
            "rules": [
                {"id": "r", "playbooks": ["svc.start"], "argument": "unit", "deny_regex": "^ssh"}
            ],
        },
    )
    undo_runner = FakeRunner(
        script=[
            (("systemctl", "stop"), make_result(0)),
            (("systemctl", "is-active"), make_result(3, "inactive", "")),
        ]
    )
    undo = _orch(journal, undo_runner).undo(outcome.task_id)
    assert undo.status is TaskStatus.SUCCEEDED


def test_tampered_origins_are_refused_not_trusted(
    journal, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    runner = FakeRunner(
        script=[
            (("systemctl", "start"), make_result(0)),
            (("systemctl", "is-active"), make_result(0, "active", "")),
        ]
    )
    outcome = _orch(journal, runner).run_intent("start ssh.service")
    payload = journal.get_undo(outcome.task_id)["payload"]  # type: ignore[index]
    payload["origins"] = "not-a-list"
    journal.store_undo(outcome.task_id, payload)
    _write_policy(tmp_path, monkeypatch, {"schema": 1, "rules": []})
    undo = _orch(journal, FakeRunner()).undo(outcome.task_id)
    assert undo.status is TaskStatus.REFUSED and "origins" in undo.error


def test_undo_payload_origins_is_additive() -> None:
    plan = UndoPlan(status=UndoStatus.NONE_NEEDED, steps=(), verify_checks=(), reason="")
    assert "origins" not in _undo_payload(plan)
    assert _undo_payload(plan, [("pkg.install", {"names": ["x"]})])["origins"] == [
        {"playbook_id": "pkg.install", "params": {"names": ["x"]}}
    ]


# --------------------------------------------------------------------------
# A3 — integrity scope; D4 — CLI surface
# --------------------------------------------------------------------------


def test_policy_dir_is_in_the_integrity_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_policy(tmp_path, monkeypatch, EXAMPLE_POLICY)
    assert path in default_scope().entries()


def test_cli_policy_example_lint_show_explain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["policy", "lint"]) == 0
    assert "no policy file" in capsys.readouterr().out
    assert main(["policy", "example"]) == 0
    example = capsys.readouterr().out
    assert json.loads(example) == EXAMPLE_POLICY
    path = policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example)
    assert main(["policy", "lint"]) == 0
    out = capsys.readouterr().out
    assert "ok: 3 rule(s) bind to 6 playbook(s)" in out
    assert main(["policy", "show"]) == 0
    assert "no-kernel-removal" in capsys.readouterr().out
    assert main(["policy", "explain", "uninstall grub"]) == 1
    out = capsys.readouterr().out
    assert (
        "playbook : pkg.remove" in out
        and "verdict  : REFUSED" in out
        and "no-kernel-removal" in out
    )
    assert main(["policy", "explain", "remove htop"]) == 0
    assert "verdict  : allowed" in capsys.readouterr().out
    assert main(["policy", "explain", "sing me a song"]) == 1
    # a broken file: exit 1 and the finding is printed
    path.write_text("{bad")
    assert main(["policy", "lint"]) == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_cli_lint_hints_about_the_stale_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.safety import integrity

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    integrity.write_baseline(integrity.default_baseline_path())  # baseline without the file
    _write_policy(tmp_path, monkeypatch, EXAMPLE_POLICY)
    assert main(["policy", "lint"]) == 0
    out = capsys.readouterr().out
    assert "argument-policy.json is added relative to the integrity baseline" in out
    assert "jarvis doctor --write-baseline" in out


def test_doctor_reports_the_policy_and_fails_on_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.safety import integrity

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    _write_policy(tmp_path, monkeypatch, EXAMPLE_POLICY)
    integrity.write_baseline(integrity.default_baseline_path())
    assert main(["doctor"]) == 0
    assert "argument policy: 3 rule(s) over 6 playbook(s) (ok)" in capsys.readouterr().out
    policy_path().write_text("{bad")
    integrity.write_baseline(integrity.default_baseline_path())  # isolate: not a drift failure
    assert main(["--json", "doctor"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["clean"] is False and doc["argument_policy"]["state"] == "malformed"


def test_status_payloads_gain_one_additive_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.cli.mcp_server import _tool_status
    from jarvis.core.fingerprint import build_profile

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "status"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["argument_policy"] == {"state": "absent", "rules": 0}
    assert set(doc) - {"argument_policy"} == set(build_profile().to_dict())
    payload, is_error = _tool_status({})
    assert not is_error and payload["argument_policy"] == {"state": "absent", "rules": 0}  # type: ignore[index]


def test_parser_exposes_the_policy_verbs() -> None:
    parser = build_parser()
    assert parser.parse_args(["policy", "lint"]).policy_command == "lint"
    assert parser.parse_args(["policy", "explain", "remove htop"]).request == "remove htop"
    assert parser.parse_args(["policy"]).policy_command == "show"


def test_source_has_no_grant_path() -> None:
    """Belt and braces: the module cannot express an allow that overrides a deny."""
    source = Path(argpolicy.__file__).read_text(encoding="utf-8")
    assert "skip_consent" not in source and "tier_override" not in source
    assert "updatedInput" not in source
