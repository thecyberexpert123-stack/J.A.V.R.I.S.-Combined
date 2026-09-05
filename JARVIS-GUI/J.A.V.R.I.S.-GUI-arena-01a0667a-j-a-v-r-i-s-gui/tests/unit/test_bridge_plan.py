"""Tests for plan and blast-radius parsing.

Every payload here was captured from a live ``jarvis mcp serve`` at kernel
1.18.0, so these are conformance tests against the real backend rather than
against an imagined one.
"""

from __future__ import annotations

from typing import Any

from javris.bridge import plan as plan_mod
from javris.bridge.plan import known_playbooks, parse_plan

#: A path appearing inside captured kernel payloads. These tests never
#: touch the filesystem; this is payload text, not a file they open.
SAMPLE_PATH = "/tmp/x"  # noqa: S108 - literal from a recorded kernel response

# -- captured payloads -----------------------------------------------------

#: `upgrade the whole system` -- tier 2, two steps, explicitly not undoable.
UPGRADE: dict[str, Any] = {
    "blast_radius": {
        "commands": ["apt-get"],
        "max_tier": 2,
        "network": True,
        "paths": {},
        "requires_root": True,
    },
    "preview": {
        "playbook": "pkg.upgrade",
        "status": "dry_run",
        "tier": 2,
        "steps": [
            {
                "argv": ["apt-get", "update"],
                "description": "refresh package index (pre-upgrade)",
                "requires_root": True,
                "seq": 0,
                "tier": 1,
            },
            {
                "argv": ["apt-get", "upgrade", "-y"],
                "description": "upgrade installed packages",
                "requires_root": True,
                "seq": 1,
                "tier": 2,
            },
        ],
        "undo": {
            "reason": "a system upgrade cannot be reversed automatically; restore from a"
            " snapshot/backup if rollback is needed",
            "status": "unavailable",
        },
    },
}

#: `remove the file /tmp/x` -- the case that motivated the reversibility gate:
#: tier 1, so the kernel runs it with no consent, yet it cannot be undone.
REMOVE: dict[str, Any] = {
    "blast_radius": {
        "commands": ["rm"],
        "max_tier": 1,
        "network": False,
        "paths": {"absolute": [SAMPLE_PATH]},
        "requires_root": False,
    },
    "preview": {
        "playbook": "fs.remove",
        "tier": 1,
        "steps": [
            {
                "argv": ["rm", "-f", SAMPLE_PATH],
                "description": "delete /tmp/x",
                "requires_root": False,
                "tier": 1,
            }
        ],
        "undo": {"reason": "deletion is not reversible", "status": "unavailable"},
    },
}

#: `restart the ssh service` -- tier 2 but idempotent, so nothing to undo.
RESTART: dict[str, Any] = {
    "blast_radius": {
        "commands": ["systemctl"],
        "max_tier": 2,
        "network": False,
        "paths": {},
        "requires_root": True,
    },
    "preview": {
        "playbook": "svc.restart",
        "tier": 2,
        "steps": [
            {
                "argv": ["systemctl", "restart", "ssh"],
                "description": "restart unit ssh",
                "requires_root": True,
                "tier": 2,
            }
        ],
        "undo": {"reason": "a restart is idempotent", "status": "none_needed"},
    },
}

#: `clean up disk space` -- nothing matched; the kernel refuses to guess.
UNMATCHED: dict[str, Any] = {
    "blast_radius": {
        "commands": [],
        "max_tier": 0,
        "network": False,
        "paths": {},
        "requires_root": False,
    },
    "preview": {
        "playbook": "<unmatched>",
        "tier": 0,
        "steps": [],
        "error": "I cannot map this request to a known playbook and I will not guess"
        " (anti-hallucination policy).",
        "hint": "Known playbooks: fs.list, fs.read, fs.head, sys.memory, pkg.upgrade.",
        "undo": None,
    },
}


# -- steps and argv --------------------------------------------------------


def test_steps_preserve_the_exact_argv() -> None:
    # The argv is the ground truth of what will run. If this is ever
    # paraphrased, the consent prompt stops being trustworthy.
    parsed = parse_plan(UPGRADE)
    assert len(parsed.steps) == 2
    assert parsed.steps[0].argv == ("apt-get", "update")
    assert parsed.steps[1].command_line == "apt-get upgrade -y"


def test_per_step_tier_and_root_are_kept() -> None:
    parsed = parse_plan(UPGRADE)
    assert parsed.steps[0].tier == 1
    assert parsed.steps[1].tier == 2
    assert all(step.requires_root for step in parsed.steps)


def test_a_step_without_a_description_falls_back_to_its_argv() -> None:
    # Better to show the command than to render an empty row.
    parsed = parse_plan({"preview": {"steps": [{"argv": ["ls", "-l"]}]}})
    assert parsed.steps[0].description == "ls -l"


def test_unusable_step_entries_are_dropped_not_rendered_blank() -> None:
    payload = {"preview": {"steps": [{}, "nonsense", {"argv": ["true"]}]}}
    assert len(parse_plan(payload).steps) == 1


def test_step_count_is_bounded() -> None:
    payload = {"preview": {"steps": [{"argv": ["true"]}] * (plan_mod.MAX_STEPS + 50)}}
    assert len(parse_plan(payload).steps) == plan_mod.MAX_STEPS


# -- reversibility ---------------------------------------------------------


def test_tier_one_deletion_is_irreversible() -> None:
    # The whole reason the reversibility gate exists: the kernel will run this
    # without asking, and it cannot be taken back.
    parsed = parse_plan(REMOVE)
    assert parsed.tier == 1
    assert parsed.irreversible is True


def test_idempotent_action_is_not_irreversible() -> None:
    # none_needed means "nothing to undo", not "cannot undo". Treating it as
    # dangerous would make the gate fire constantly and train it away.
    parsed = parse_plan(RESTART)
    assert parsed.undo_status == "none_needed"
    assert parsed.irreversible is False


def test_available_undo_is_not_irreversible() -> None:
    payload = {"preview": {"steps": [{"argv": ["x"]}], "undo": {"status": "available"}}}
    assert parse_plan(payload).irreversible is False


def test_unknown_undo_status_is_treated_as_irreversible() -> None:
    # Guessing optimistically about reversibility is the one error that cannot
    # be corrected after the fact.
    payload = {"preview": {"steps": [{"argv": ["x"]}], "undo": {"status": "who knows"}}}
    assert parse_plan(payload).irreversible is True


def test_missing_undo_object_is_treated_as_irreversible() -> None:
    payload = {"preview": {"steps": [{"argv": ["x"]}]}}
    assert parse_plan(payload).irreversible is True


def test_a_plan_with_no_steps_is_not_irreversible() -> None:
    # Nothing runs, so there is nothing to warn about.
    assert parse_plan(UNMATCHED).irreversible is False


# -- blast radius ----------------------------------------------------------


def test_blast_radius_is_read_from_the_kernel() -> None:
    blast = parse_plan(UPGRADE).blast
    assert blast.commands == ("apt-get",)
    assert blast.max_tier == 2
    assert blast.network is True
    assert blast.requires_root is True


def test_paths_are_flattened_across_their_kinds() -> None:
    # `paths` is an object keyed by kind, not a flat list.
    assert parse_plan(REMOVE).blast.paths == (SAMPLE_PATH,)


def test_missing_blast_radius_yields_empty_not_an_exception() -> None:
    blast = parse_plan({"preview": {}}).blast
    assert blast.commands == ()
    assert blast.network is False


# -- the unmatched case ----------------------------------------------------


def test_unmatched_request_is_flagged_and_keeps_the_kernel_message() -> None:
    parsed = parse_plan(UNMATCHED)
    assert parsed.unmatched is True
    assert "will not guess" in parsed.error
    assert parsed.steps == ()


def test_the_unmatched_sentinel_is_never_shown_as_a_playbook() -> None:
    # "<unmatched>" is the kernel's placeholder, not a name.
    assert parse_plan(UNMATCHED).playbook == ""


def test_a_matched_plan_is_not_flagged_unmatched() -> None:
    assert parse_plan(RESTART).unmatched is False


def test_known_playbooks_are_extracted_from_the_hint() -> None:
    names = known_playbooks(UNMATCHED["preview"]["hint"])
    assert names[:3] == ("fs.list", "fs.read", "fs.head")
    assert "pkg.upgrade" in names


def test_known_playbooks_returns_empty_for_an_unrelated_hint() -> None:
    # The caller then shows the hint verbatim rather than a mangled parse.
    assert known_playbooks("try something else") == ()


def test_known_playbooks_on_empty_input() -> None:
    assert known_playbooks("") == ()


# -- robustness ------------------------------------------------------------


def test_an_empty_payload_parses_to_an_empty_plan() -> None:
    parsed = parse_plan({})
    assert parsed.is_empty
    assert parsed.steps == ()
    assert parsed.playbook == ""


def test_wrongly_typed_fields_do_not_raise() -> None:
    # A malformed payload must degrade, never take the UI thread down.
    payload: dict[str, Any] = {
        "preview": {"steps": "not a list", "undo": 42, "tier": "two"},
        "blast_radius": [1, 2, 3],
    }
    parsed = parse_plan(payload)
    assert parsed.steps == ()
    assert parsed.tier is None
