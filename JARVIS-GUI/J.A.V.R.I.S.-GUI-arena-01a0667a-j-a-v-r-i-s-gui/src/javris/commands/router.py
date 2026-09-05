"""Allow-list command dispatch for the HUD console.

Security posture: this router **never** executes a shell, spawns a process,
opens a file or touches the network. It maps a fixed vocabulary of verbs onto
in-process handlers. Anything not in the vocabulary is rejected with a message.
Input is length-capped and control characters are stripped before parsing, so a
pasted terminal escape sequence cannot reach the log renderer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

#: Hard cap on accepted input length. Longer input is rejected outright rather
#: than truncated, so a command is never silently reinterpreted.
MAX_COMMAND_LENGTH = 200


class Severity(str, Enum):
    """Log severity, mapped to a distinct colour in the HUD."""

    INFO = "INFO"
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of dispatching one command line."""

    severity: Severity
    message: str
    #: Requested HUD mode, when the command asked for one; otherwise ``None``.
    mode: str | None = None
    #: True when the command asked the application to exit.
    shutdown: bool = False
    #: Agent bridge tool to invoke, when the verb maps to one; otherwise ``None``.
    agent_tool: str | None = None
    #: Free-text argument for :attr:`agent_tool`.
    agent_argument: str = ""
    #: True when the verb asks to close the agent connection.
    agent_disconnect: bool = False
    #: New GUI-side confirmation policy, when the command changes it. This
    #: never alters kernel authority -- only how much the GUI asks first.
    confirm_policy: str = ""


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """A single entry in the command vocabulary."""

    verb: str
    summary: str
    handler: Callable[[CommandRouter, tuple[str, ...]], CommandResult]


def _strip_control_characters(text: str) -> str:
    """Remove control characters, which have no legitimate place in a command."""
    return "".join(char for char in text if char.isprintable() or char == " ")


class CommandRouter:
    """Parses and dispatches console input against a fixed vocabulary.

    Args:
        modes: The HUD mode names that ``mode <name>`` may select.
    """

    def __init__(self, modes: tuple[str, ...] = ("DIAGNOSTICS", "MONITOR")) -> None:
        self._modes = modes
        self._specs: dict[str, CommandSpec] = {}
        for spec in (
            CommandSpec("help", "List available commands.", CommandRouter._cmd_help),
            CommandSpec("status", "Report current system status.", CommandRouter._cmd_status),
            CommandSpec(
                "mode",
                f"Switch HUD mode: {' | '.join(mode.lower() for mode in modes)}.",
                CommandRouter._cmd_mode,
            ),
            CommandSpec("clear", "Clear the console log.", CommandRouter._cmd_clear),
            CommandSpec("shutdown", "Close the HUD.", CommandRouter._cmd_shutdown),
            # Agent verbs, per javris-frontend/1 section 5. Each maps to
            # exactly one bridge call; none of them executes a shell.
            CommandSpec(
                "ask",
                "Ask the agent a question: ask <question>.",
                CommandRouter._cmd_ask,
            ),
            CommandSpec(
                "plan",
                "Show the agent's plan without running it: plan <request>.",
                CommandRouter._cmd_plan,
            ),
            CommandSpec(
                "do",
                "Ask the agent to carry out a request: do <request>.",
                CommandRouter._cmd_do,
            ),
            CommandSpec(
                "agent",
                "Agent connection: agent status | agent disconnect.",
                CommandRouter._cmd_agent,
            ),
            CommandSpec(
                "suggest",
                "Evidence-backed suggestions from the agent: suggest.",
                CommandRouter._cmd_suggest,
            ),
            CommandSpec(
                "confirm",
                "Confirmation policy: confirm irreversible | always | kernel-only.",
                CommandRouter._cmd_confirm,
            ),
        ):
            self._specs[spec.verb] = spec

    @property
    def verbs(self) -> tuple[str, ...]:
        """Every recognised verb, in alphabetical order."""
        return tuple(sorted(self._specs))

    def dispatch(self, line: str) -> CommandResult:
        """Parse and execute one command line.

        Never raises; every failure path returns a ``CommandResult`` the HUD can
        display, because an unparseable command is normal user input, not a bug.
        """
        if len(line) > MAX_COMMAND_LENGTH:
            return CommandResult(
                Severity.ERROR,
                f"Input rejected: exceeds {MAX_COMMAND_LENGTH} characters.",
            )

        cleaned = _strip_control_characters(line).strip()
        if not cleaned:
            return CommandResult(Severity.WARN, "Empty command ignored.")

        tokens = cleaned.split()
        verb = tokens[0].lower()
        spec = self._specs.get(verb)
        if spec is None:
            return CommandResult(
                Severity.ERROR,
                f"Unknown command '{verb}'. Type 'help' for the command list.",
            )
        return spec.handler(self, tuple(tokens[1:]))

    # -- handlers ----------------------------------------------------------

    def _cmd_help(self, _args: tuple[str, ...]) -> CommandResult:
        ordered = sorted(self._specs.values(), key=lambda spec: spec.verb)
        listing = "  ".join(f"{spec.verb} - {spec.summary}" for spec in ordered)
        return CommandResult(Severity.INFO, listing)

    def _cmd_status(self, _args: tuple[str, ...]) -> CommandResult:
        return CommandResult(Severity.OK, "All monitored subsystems reporting.")

    def _cmd_mode(self, args: tuple[str, ...]) -> CommandResult:
        if not args:
            return CommandResult(
                Severity.WARN,
                f"Usage: mode <{' | '.join(mode.lower() for mode in self._modes)}>",
            )
        requested = args[0].upper()
        if requested not in self._modes:
            return CommandResult(Severity.ERROR, f"Unknown mode '{args[0]}'.")
        return CommandResult(Severity.OK, f"Mode set to {requested}.", mode=requested)

    def _cmd_clear(self, _args: tuple[str, ...]) -> CommandResult:
        return CommandResult(Severity.INFO, "__CLEAR__")

    def _cmd_shutdown(self, _args: tuple[str, ...]) -> CommandResult:
        return CommandResult(Severity.WARN, "Shutting down.", shutdown=True)

    # -- agent verbs -------------------------------------------------------
    #
    # These do not talk to the kernel themselves. The router stays a pure
    # parser: it decides *which* tool a line means and hands that decision to
    # the controller, which owns the bridge. Keeping the parse side-effect-free
    # is what lets the whole vocabulary be tested without a subprocess.

    @staticmethod
    def _joined(args: tuple[str, ...]) -> str:
        return " ".join(args).strip()

    def _cmd_ask(self, args: tuple[str, ...]) -> CommandResult:
        question = self._joined(args)
        if not question:
            return CommandResult(Severity.WARN, "Usage: ask <question>")
        return CommandResult(
            Severity.INFO,
            f"Asking the agent: {question}",
            agent_tool="jarvis_explain",
            agent_argument=question,
        )

    def _cmd_plan(self, args: tuple[str, ...]) -> CommandResult:
        request = self._joined(args)
        if not request:
            return CommandResult(Severity.WARN, "Usage: plan <request>")
        return CommandResult(
            Severity.INFO,
            f"Requesting a plan for: {request}",
            agent_tool="jarvis_preview",
            agent_argument=request,
        )

    def _cmd_do(self, args: tuple[str, ...]) -> CommandResult:
        request = self._joined(args)
        if not request:
            return CommandResult(Severity.WARN, "Usage: do <request>")
        # Deliberately routed WITHOUT consent. The kernel decides whether this
        # request needs it, and only a subsequent explicit owner action may
        # send allow:true. The console can never pre-authorise anything.
        return CommandResult(
            Severity.INFO,
            f"Sending to the agent: {request}",
            agent_tool="jarvis_do",
            agent_argument=request,
        )

    def _cmd_suggest(self, args: tuple[str, ...]) -> CommandResult:
        if args:
            return CommandResult(Severity.WARN, "Usage: suggest")
        return CommandResult(
            Severity.INFO,
            "Asking the agent for suggestions.",
            agent_tool="jarvis_suggest",
        )

    #: Console spellings of the confirmation policies. Hyphenated for typing;
    #: mapped to the enum's names rather than guessed at by the controller.
    _CONFIRM_POLICIES: ClassVar[dict[str, str]] = {
        "irreversible": "IRREVERSIBLE",
        "always": "ALWAYS",
        "kernel-only": "KERNEL_ONLY",
        "kernel_only": "KERNEL_ONLY",
    }

    def _cmd_confirm(self, args: tuple[str, ...]) -> CommandResult:
        if not args:
            return CommandResult(
                Severity.WARN,
                "Usage: confirm irreversible | always | kernel-only",
            )
        policy = self._CONFIRM_POLICIES.get(args[0].lower())
        if policy is None:
            return CommandResult(
                Severity.ERROR,
                f"Unknown policy '{args[0]}'. Use: irreversible | always | kernel-only.",
            )
        return CommandResult(
            Severity.INFO,
            "Updating the confirmation policy.",
            confirm_policy=policy,
        )

    def _cmd_agent(self, args: tuple[str, ...]) -> CommandResult:
        if not args:
            return CommandResult(Severity.WARN, "Usage: agent status | agent disconnect")
        action = args[0].lower()
        if action == "status":
            return CommandResult(
                Severity.INFO,
                "Querying the agent.",
                agent_tool="jarvis_status",
            )
        if action == "disconnect":
            return CommandResult(
                Severity.WARN,
                "Disconnecting the agent.",
                agent_disconnect=True,
            )
        return CommandResult(
            Severity.ERROR,
            f"Unknown agent action '{args[0]}'. Use: status | disconnect.",
        )
