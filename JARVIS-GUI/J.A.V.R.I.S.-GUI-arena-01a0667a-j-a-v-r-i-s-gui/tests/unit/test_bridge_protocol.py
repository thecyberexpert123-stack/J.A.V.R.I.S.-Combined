"""Wire-protocol tests for the JARVIS kernel bridge.

The frames asserted here were captured from a live ``jarvis mcp serve`` at
kernel 1.10.2 (contract ``javris-frontend/1``), so these are conformance tests
rather than tests against an imagined server.

The security-relevant properties -- that consent is never synthesised, that a
refusal is never mistaken for a failure, and that tier-3 is never offered as
approvable -- are asserted directly.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from javris.bridge import protocol
from javris.bridge.protocol import OutcomeKind

# -- captured frames -------------------------------------------------------

INITIALIZE_RESULT: dict[str, Any] = {
    "protocolVersion": "2025-03-26",
    "serverInfo": {"name": "jarvis", "version": "1.10.2"},
}


def tool_response(payload: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    """Wrap a payload the way the kernel wraps it on the wire."""
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "isError": is_error,
            "content": [{"type": "text", "text": json.dumps(payload)}],
        },
    }


#: Verbatim shape of a tier-2 refusal, as captured from the live kernel.
REFUSAL_PAYLOAD = {
    "outcome": {
        "status": "refused",
        "tier": 2,
        "hint": (
            'review the plan with jarvis_preview, then re-call jarvis_do with "allow": '
            "true to consent explicitly"
        ),
    }
}

#: Verbatim shape of a successful jarvis_explain, as captured.
EXPLAIN_PAYLOAD = {
    "status": "ok",
    "claim": "The running kernel reports its type as 'Linux' via /proc/sys/kernel/ostype.",
    "sources": ["kb://facts/ostype"],
}


# -- framing ---------------------------------------------------------------


def test_every_frame_is_exactly_one_line() -> None:
    # The transport is newline-delimited, so an embedded newline would split
    # one logical frame into two malformed ones.
    frames = [
        protocol.build_initialize(1),
        protocol.build_initialized_notification(),
        protocol.build_tools_list(2),
        protocol.build_tool_call(3, "jarvis_explain", {"question": "a\nb"}),
    ]
    for frame in frames:
        assert frame.endswith("\n")
        assert frame.count("\n") == 1, f"frame spans multiple lines: {frame!r}"


def test_initialize_requests_the_documented_protocol_version() -> None:
    frame = json.loads(protocol.build_initialize(1))
    assert frame["method"] == "initialize"
    assert frame["params"]["protocolVersion"] == protocol.PROTOCOL_VERSION


def test_initialized_notification_carries_no_id() -> None:
    # A notification with an id would make the server try to answer it.
    frame = json.loads(protocol.build_initialized_notification())
    assert "id" not in frame


def test_server_version_is_read_from_the_handshake() -> None:
    assert protocol.server_version(INITIALIZE_RESULT) == "1.10.2"


def test_server_version_absent_is_none_not_a_guess() -> None:
    assert protocol.server_version({}) is None
    assert protocol.server_version({"serverInfo": "nonsense"}) is None


# -- consent invariants ----------------------------------------------------


def test_allow_is_absent_unless_explicitly_requested() -> None:
    frame = json.loads(protocol.build_tool_call(1, "jarvis_do", {"request": "install htop"}))
    assert "allow" not in frame["params"]["arguments"], "the default call must never carry consent"


def test_allow_is_present_only_when_asked_for() -> None:
    frame = json.loads(protocol.build_tool_call(1, "jarvis_do", {"request": "upgrade"}, allow=True))
    assert frame["params"]["arguments"]["allow"] is True


def test_consent_cannot_be_attached_to_a_read_only_tool() -> None:
    # Sending allow to a read-only tool would misrepresent the caller's intent
    # and suggests the call site has confused its paths.
    with pytest.raises(ValueError):
        protocol.build_tool_call(1, "jarvis_explain", {"question": "x"}, allow=True)


def test_unknown_tools_are_refused_before_reaching_the_wire() -> None:
    with pytest.raises(ValueError):
        protocol.build_tool_call(1, "jarvis_rm_rf", {})


def test_the_published_tool_set_is_what_we_implement() -> None:
    published = frozenset(
        {
            "jarvis_status",
            "jarvis_facts",
            "jarvis_explain",
            "jarvis_suggest",
            "jarvis_preview",
            "jarvis_do",
        }
    )
    known = protocol.KNOWN_TOOLS
    consent = protocol.CONSENT_TOOLS
    read_only = protocol.READ_ONLY_TOOLS
    assert known == published
    # Exactly one tool can change the machine, and it is the one gated by
    # consent. If this ever grows, the consent UI must grow with it.
    assert consent == frozenset({"jarvis_do"})
    assert read_only == published - consent


# -- outcome classification ------------------------------------------------


def test_refusal_is_not_reported_as_a_failure() -> None:
    # The kernel sets isError on a refusal. Treating that as a malfunction
    # would present the safety kernel working correctly as a crash.
    outcome = protocol.classify_outcome(tool_response(REFUSAL_PAYLOAD, is_error=True))
    assert outcome.kind is OutcomeKind.REFUSED
    assert outcome.tier == 2
    assert outcome.consent_required is True
    assert "consent" in outcome.text.lower()
    assert "jarvis_preview" in outcome.hint


def test_tier_three_refusal_is_never_offered_for_approval() -> None:
    # T3 is refused unconditionally by the kernel. Showing an approve button
    # would promise the owner an authority they do not have.
    payload = {"outcome": {"status": "refused", "tier": 3, "hint": ""}}
    outcome = protocol.classify_outcome(tool_response(payload, is_error=True))
    assert outcome.kind is OutcomeKind.REFUSED
    assert outcome.consent_required is False
    assert "never" in outcome.text.lower()


def test_success_is_classified_and_summarised() -> None:
    outcome = protocol.classify_outcome(tool_response(EXPLAIN_PAYLOAD, is_error=False))
    assert outcome.kind is OutcomeKind.OK
    assert "Linux" in outcome.text


def test_genuine_failure_is_reported_as_failure() -> None:
    payload = {"outcome": {"status": "failed", "error": "exit code 100"}}
    outcome = protocol.classify_outcome(tool_response(payload, is_error=True))
    assert outcome.kind is OutcomeKind.FAILED
    assert "100" in outcome.text


def test_jsonrpc_error_is_a_protocol_error() -> None:
    message = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no such method"}}
    outcome = protocol.classify_outcome(message)
    assert outcome.kind is OutcomeKind.PROTOCOL_ERROR


def test_malformed_payload_is_a_protocol_error_not_a_crash() -> None:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"isError": False, "content": [{"type": "text", "text": "not json"}]},
    }
    assert protocol.classify_outcome(message).kind is OutcomeKind.PROTOCOL_ERROR


def test_result_without_content_is_a_protocol_error() -> None:
    assert (
        protocol.classify_outcome({"jsonrpc": "2.0", "id": 1, "result": {}}).kind
        is OutcomeKind.PROTOCOL_ERROR
    )


# -- parsing robustness ----------------------------------------------------


@pytest.mark.parametrize("line", ["", "   ", "not json", "[1,2,3]", "null", '"a string"'])
def test_noise_lines_are_skipped_rather_than_fatal(line: str) -> None:
    # One malformed line must not be able to take the connection down.
    assert protocol.parse_line(line) is None


def test_valid_object_lines_parse() -> None:
    assert protocol.parse_line('{"a":1}') == {"a": 1}


def test_kernel_text_is_length_capped() -> None:
    # The kernel is trusted but not unbounded: a huge payload would block the
    # UI thread in the log renderer.
    payload = {"claim": "x" * (protocol.MAX_TEXT_LENGTH * 3)}
    outcome = protocol.classify_outcome(tool_response(payload, is_error=False))
    assert len(outcome.text) < protocol.MAX_TEXT_LENGTH * 2
    assert "truncated" in outcome.text


def test_spawn_argv_is_fixed_and_shell_free() -> None:
    # The single documented process spawn. A shell metacharacter here would
    # mean the argv was being composed rather than pinned.
    assert protocol.SPAWN_ARGV == ("jarvis", "mcp", "serve")
    for token in protocol.SPAWN_ARGV:
        assert not any(char in token for char in ";|&$`><\n")


# -- refusal-to-guess versus consent refusal --------------------------------

#: Verbatim shape of an unmatched jarvis_do, captured from kernel 1.20.0. The
#: kernel reports status "refused" with tier 0 and the <unmatched> sentinel.
UNMATCHED_PAYLOAD = {
    "outcome": {
        "status": "refused",
        "tier": 0,
        "playbook": "<unmatched>",
        "error": (
            "I cannot map this request to a known playbook and I will not "
            "guess (anti-hallucination policy)."
        ),
        "hint": "Known playbooks: fs.list, fs.read, fs.head, sys.uptime",
        "snapshot": None,
    }
}


def test_refusal_to_guess_is_not_a_consent_refusal() -> None:
    # The kernel answers an unmappable request with status "refused" and
    # tier 0. Keyed off the tier alone that renders as "this tier-0 action
    # needs your consent" -- a prompt for an action that does not exist, where
    # approving re-sends the request and earns the identical refusal.
    outcome = protocol.classify_outcome(tool_response(UNMATCHED_PAYLOAD, is_error=True))
    assert outcome.kind is OutcomeKind.UNMATCHED
    assert outcome.consent_required is False
    # The kernel's own sentence, not a manufactured consent sentence.
    assert "will not guess" in outcome.text
    assert "consent" not in outcome.text.lower()


def test_unmatched_is_detected_without_the_sentinel_field() -> None:
    # Older or partial payloads may omit "playbook". The prose fallback keeps
    # the classification correct rather than falling back to a consent prompt.
    payload = {
        "outcome": {
            "status": "refused",
            "tier": 0,
            "error": "I cannot map this request to a known playbook.",
        }
    }
    outcome = protocol.classify_outcome(tool_response(payload, is_error=True))
    assert outcome.kind is OutcomeKind.UNMATCHED
    assert outcome.consent_required is False


def test_genuine_consent_refusal_is_still_offered_for_approval() -> None:
    # The guard must not swallow real consent refusals: a T2 action carries no
    # <unmatched> sentinel and must still reach the owner as a decision.
    outcome = protocol.classify_outcome(tool_response(REFUSAL_PAYLOAD, is_error=True))
    assert outcome.kind is OutcomeKind.REFUSED
    assert outcome.consent_required is True


def test_unmatched_keeps_the_playbook_hint_for_the_owner() -> None:
    # The list of things the kernel *can* do is the useful part of a
    # refusal-to-guess, so it must survive classification.
    outcome = protocol.classify_outcome(tool_response(UNMATCHED_PAYLOAD, is_error=True))
    assert "sys.uptime" in outcome.hint
