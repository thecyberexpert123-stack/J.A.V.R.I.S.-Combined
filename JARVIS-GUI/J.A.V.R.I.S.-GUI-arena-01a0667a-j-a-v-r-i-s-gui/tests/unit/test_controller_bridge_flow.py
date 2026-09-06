"""State-machine behaviour of the controller across a request's lifetime.

These tests drive a real ``HudController`` with a scripted transport in place
of the kernel process, and assert what the header would show at each step. The
rule under test is that no request may leave the HUD in a state that lies
about what is in flight: every path -- a consent refusal, a declined prompt, a
handshake, a lost connection, a returned dictation -- must end in a state that
describes the HUD as it now is.

The refusal payloads are verbatim captures from kernel 1.20.0.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from javris.bridge.protocol import Outcome, classify_outcome
from javris.controller import HudController
from javris.state import AssistantState

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture(scope="session", autouse=True)
def qt_app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


class ScriptedTransport(QObject):
    """A transport double with the four bridge signals and a call log.

    ``ready`` is set by the test rather than by a handshake, so a scenario can
    begin in whichever connection state it needs.
    """

    connected = Signal(str)
    disconnected = Signal(str)
    completed = Signal(str, object)
    started = Signal(str)

    def __init__(self, *, ready: bool = True, version: str = "1.20.0") -> None:
        super().__init__()
        self.ready = ready
        self.version = version
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.executions: list[tuple[str, bool, str]] = []
        self.start_result = True

    def start(self) -> bool:
        return self.start_result

    def stop(self) -> None:
        self.ready = False
        self.disconnected.emit("Agent disconnected.")

    def call(self, tool: str, arguments: dict[str, Any], *, tag: str) -> bool:
        self.calls.append((tool, arguments, tag))
        self.started.emit(tag)
        return True

    def execute(self, request: str, *, allow: bool, tag: str) -> bool:
        self.executions.append((request, allow, tag))
        self.started.emit(tag)
        return True

    # -- scripted replies ----------------------------------------------------

    def reply(self, tag: str, payload: dict[str, Any], *, is_error: bool) -> None:
        message = {
            "jsonrpc": "2.0",
            "id": 9,
            "result": {
                "isError": is_error,
                "content": [{"type": "text", "text": json.dumps(payload)}],
            },
        }
        self.completed.emit(tag, classify_outcome(message))


@pytest.fixture
def ready() -> tuple[HudController, ScriptedTransport]:
    """A controller in STANDBY with a connected scripted transport."""
    controller = HudController()
    transport = ScriptedTransport()
    controller._transport = transport  # type: ignore[assignment]
    transport.connected.connect(controller._on_kernel_connected)
    transport.disconnected.connect(controller._on_kernel_disconnected)
    transport.completed.connect(controller._on_kernel_completed)
    transport.started.connect(controller._on_kernel_started)
    controller.set_state(AssistantState.STANDBY)
    return controller, transport


# -- captured kernel payloads ------------------------------------------------

APPROVAL_REFUSAL = {
    "outcome": {
        "status": "refused",
        "tier": 2,
        "playbook": "pkg.upgrade",
        "error": (
            "T2 (system-level) action requires explicit approval; "
            "re-run with --yes to consent non-interactively"
        ),
        "hint": (
            "review the plan with jarvis_preview, then re-call jarvis_do with "
            '"allow": true to consent explicitly'
        ),
    }
}

CAUTIOUS_REFUSAL = {
    "outcome": {
        "status": "refused",
        "tier": 2,
        "playbook": "pkg.upgrade",
        "error": (
            "cautious mode is ON (early-days guard): T2+ actions are blocked. "
            'Review the plan (jarvis do "..." --preview), then either pass '
            "--cautious-ok for this one action or turn the guard off: jarvis cautious off"
        ),
        "hint": "",
    }
}

PROTECTED_PATH_REFUSAL = {
    "outcome": {
        "status": "refused",
        "tier": 0,
        "playbook": "fs.remove",
        "error": (
            "refusing to modify '/etc/passwd': authentication material and "
            "boot/kernel paths are protected"
        ),
        "hint": "",
    }
}

DO_SUCCESS = {"outcome": {"status": "succeeded", "tier": 0, "playbook": "sys.uptime"}}

EXPLAIN_OK = {
    "status": "ok",
    "claim": "The running kernel reports its type as 'Linux' via /proc/sys/kernel/ostype.",
    "sources": ["kb://facts/ostype"],
}

EXPLAIN_ABSTAIN = {
    "status": "refused",
    "note": (
        "no cited fact matches this question; I will not guess "
        "(browse what I know: jarvis facts \u2014 12 facts, KB v1)"
    ),
    "claim": "",
    "ai_text": None,
    "sources": [],
}

PREVIEW_UNMATCHED = {
    "preview": {
        "status": "refused",
        "tier": 0,
        "playbook": "<unmatched>",
        "steps": [],
        "error": (
            "I cannot map this request to a known playbook and I will not "
            "guess (anti-hallucination policy)."
        ),
        "hint": "Known playbooks: fs.list, fs.read, sys.uptime",
    },
    "blast_radius": {"commands": [], "max_tier": 0, "network": False, "paths": {}},
}

PREVIEW_IRREVERSIBLE = {
    "preview": {
        "status": "dry_run",
        "tier": 1,
        "playbook": "fs.remove",
        "steps": [
            {
                "seq": 0,
                "argv": ["rm", "--", "~/scratch/old-notes.txt"],
                "description": "remove ~/scratch/old-notes.txt",
                "tier": 1,
                "requires_root": False,
                "status": "planned",
            }
        ],
        "undo": {"status": "unavailable", "reason": "deleted data is not recoverable"},
        "error": "",
        "hint": "",
    },
    "blast_radius": {"commands": ["rm"], "max_tier": 1, "network": False, "paths": {}},
}


def _state(controller: HudController) -> AssistantState:
    return AssistantState(controller.state)


# -- connection ----------------------------------------------------------------


def test_agent_connect_verb_reaches_connect_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = HudController()
    controller.set_state(AssistantState.STANDBY)
    reached: list[bool] = []
    monkeypatch.setattr(controller, "connectAgent", lambda: reached.append(True))
    controller.submitCommand("agent connect")
    assert reached == [True]


def test_agent_verbs_point_at_the_way_to_connect() -> None:
    controller = HudController()
    controller.set_state(AssistantState.STANDBY)
    controller.submitCommand("agent status")
    joined = " ".join(controller.log)
    assert "agent connect" in joined
    # The state was never touched: nothing was sent.
    assert _state(controller) is AssistantState.STANDBY


def test_handshake_settles_in_standby(ready: tuple[HudController, ScriptedTransport]) -> None:
    controller, transport = ready
    controller.set_state(AssistantState.PROCESSING)  # as connectAgent() leaves it
    transport.connected.emit("1.20.0")
    assert _state(controller) is AssistantState.STANDBY
    assert any("Agent connected" in line for line in controller.log)


def test_a_failed_connect_then_a_successful_retry_ends_in_standby(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    # First attempt: the transport cannot start, so the HUD is OFFLINE.
    controller.set_state(AssistantState.PROCESSING)
    controller.set_state(AssistantState.OFFLINE)
    # Retry: a request in flight, then a handshake.
    controller.set_state(AssistantState.PROCESSING)
    transport.connected.emit("1.20.0")
    assert _state(controller) is AssistantState.STANDBY


def test_disconnect_mid_request_settles_in_standby(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    controller.submitCommand("ask what kernel is this")
    assert _state(controller) is AssistantState.PROCESSING
    transport.stop()
    assert _state(controller) is AssistantState.STANDBY
    assert controller.pendingConsent == ""


# -- results -------------------------------------------------------------------


def test_a_read_only_answer_is_spoken_then_standby(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    seen: list[str] = []
    controller.stateChanged.connect(lambda: seen.append(controller.state))
    controller.submitCommand("ask what kernel is this")
    transport.reply("explain", EXPLAIN_OK, is_error=False)
    assert seen == ["PROCESSING", "SPEAKING", "STANDBY"]
    assert any("Linux" in line for line in controller.log)


def test_an_explain_abstention_is_an_answer_not_a_fault(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    controller.submitCommand("ask what is the meaning of life")
    transport.reply("explain", EXPLAIN_ABSTAIN, is_error=True)
    assert _state(controller) is AssistantState.STANDBY
    joined = " ".join(controller.log)
    assert "I will not guess" in joined
    assert "Request failed" not in joined


def test_a_completed_action_is_spoken_then_standby(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    assert controller.setConfirmPolicy("KERNEL_ONLY")
    controller.submitCommand("do show uptime")
    assert _state(controller) is AssistantState.EXECUTING
    transport.reply("do", DO_SUCCESS, is_error=False)
    assert _state(controller) is AssistantState.STANDBY
    assert any("succeeded" in line for line in controller.log)


def test_a_bare_plan_the_kernel_will_not_guess_is_not_a_fault(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    controller.submitCommand("plan dance the macarena")
    transport.reply("preview", PREVIEW_UNMATCHED, is_error=True)
    assert _state(controller) is AssistantState.STANDBY
    joined = " ".join(controller.log)
    assert "will not guess" in joined
    assert "sys.uptime" in joined
    assert "Request failed" not in joined


# -- refusals ------------------------------------------------------------------


def test_a_consent_refusal_prompts_and_stands_by(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    assert controller.setConfirmPolicy("KERNEL_ONLY")
    controller.submitCommand("do upgrade the whole system")
    transport.reply("do", APPROVAL_REFUSAL, is_error=True)
    assert controller.pendingConsent == "upgrade the whole system"
    assert controller.consentGate == "KERNEL_CONSENT"
    assert _state(controller) is AssistantState.STANDBY


@pytest.mark.parametrize("payload", [CAUTIOUS_REFUSAL, PROTECTED_PATH_REFUSAL])
def test_a_refusal_consent_cannot_lift_shows_the_reason_and_no_prompt(
    ready: tuple[HudController, ScriptedTransport], payload: dict[str, Any]
) -> None:
    controller, transport = ready
    assert controller.setConfirmPolicy("KERNEL_ONLY")
    controller.submitCommand("do upgrade the whole system")
    transport.reply("do", payload, is_error=True)
    # No prompt: approving would re-send the request and get the same answer.
    assert controller.pendingConsent == ""
    assert controller.consentGate == ""
    joined = " ".join(controller.log)
    assert payload["outcome"]["error"] in joined
    assert "needs your explicit consent" not in joined
    # And the HUD is not left spinning.
    assert _state(controller) is AssistantState.STANDBY


def test_approving_consent_passes_through_processing_to_executing(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    assert controller.setConfirmPolicy("KERNEL_ONLY")
    controller.submitCommand("do upgrade the whole system")
    transport.reply("do", APPROVAL_REFUSAL, is_error=True)
    seen: list[str] = []
    controller.stateChanged.connect(lambda: seen.append(controller.state))
    controller.approveConsent()
    assert seen == ["PROCESSING", "EXECUTING"]
    # allow=True originates here and nowhere else.
    assert transport.executions[-1] == ("upgrade the whole system", True, "do")


def test_declining_a_reversibility_prompt_returns_to_standby(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    controller.submitCommand("do delete ~/scratch/old-notes.txt")
    assert transport.calls[-1][0] == "jarvis_preview"
    transport.reply("preview-before-do", PREVIEW_IRREVERSIBLE, is_error=False)
    assert controller.consentGate == "REVERSIBILITY"
    assert _state(controller) is AssistantState.STANDBY
    controller.declineConsent()
    assert controller.pendingConsent == ""
    assert _state(controller) is AssistantState.STANDBY
    # Nothing was sent.
    assert transport.executions == []


# -- faults and recovery ---------------------------------------------------------


def test_a_new_command_acknowledges_a_prior_fault(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    controller.submitCommand("agent status")
    transport.reply("jarvis_status", {"error": "boom"}, is_error=True)
    assert _state(controller) is AssistantState.ERROR
    # The owner reads the fault and asks for something else: that is the
    # acknowledgement, and the new request must be representable.
    controller.submitCommand("ask what kernel is this")
    assert _state(controller) is AssistantState.PROCESSING


def test_a_protocol_error_is_still_a_fault(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, transport = ready
    controller.submitCommand("agent status")
    transport.completed.emit(
        "jarvis_status",
        Outcome(kind=classify_outcome({"jsonrpc": "2.0", "id": 1}).kind, text="garbled"),
    )
    assert _state(controller) is AssistantState.ERROR


# -- voice -------------------------------------------------------------------


def test_a_returned_dictation_settles_in_standby(
    ready: tuple[HudController, ScriptedTransport],
) -> None:
    controller, _ = ready
    controller._on_voice_listening()
    controller._on_voice_transcribing()
    assert _state(controller) is AssistantState.PROCESSING
    controller._on_voice_transcribed("show uptime")
    assert _state(controller) is AssistantState.STANDBY
    assert controller.dictation == "show uptime"
