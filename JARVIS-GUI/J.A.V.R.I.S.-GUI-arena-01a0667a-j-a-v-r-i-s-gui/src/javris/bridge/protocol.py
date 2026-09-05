"""Pure JSON-RPC 2.0 framing and payload interpretation for the JARVIS kernel.

This module is deliberately free of Qt and of any I/O: it turns Python values
into wire lines and wire lines into decided outcomes, and nothing else. That
keeps the part of the bridge that must be *exactly* right -- consent handling
and error classification -- testable without spawning a process.

The wire contract is ``javris-frontend/1``, published by ``jarvis mcp describe``
and documented in the kernel repository at ``docs/integration/JAVRIS-GUI.md``.
Verified against a live ``jarvis mcp serve`` at kernel 1.10.2.

Security posture (see ADR-0013 M9a in the kernel repo): the front-end never
widens authority. ``allow`` is never synthesised here; :func:`build_tool_call`
requires the caller to pass it explicitly, and :func:`classify_outcome` reports
a refusal as a refusal rather than retrying.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Wire contract this client implements. Compared against the server's
#: descriptor so a future incompatible revision is noticed rather than assumed.
CONTRACT = "javris-frontend/1"

#: Protocol version this client requests. The server echoes the client's date
#: version; the documented fallback is 2024-11-05.
PROTOCOL_VERSION = "2025-03-26"

#: Fixed argv. One spawn, no shell, no network -- the single documented
#: extension of the GUI's "no process execution" posture.
SPAWN_ARGV: tuple[str, ...] = ("jarvis", "mcp", "serve")

#: Tools that need no owner action.
READ_ONLY_TOOLS = frozenset(
    {
        "jarvis_status",
        "jarvis_facts",
        "jarvis_explain",
        "jarvis_suggest",
        "jarvis_preview",
    }
)

#: Tools that may mutate the machine and therefore require per-call consent.
CONSENT_TOOLS = frozenset({"jarvis_do"})

#: Every tool this client knows how to call.
KNOWN_TOOLS = READ_ONLY_TOOLS | CONSENT_TOOLS

#: Hard cap on text taken from the kernel before it reaches the log renderer.
#: The kernel is trusted, but "trusted" is not "unbounded": a multi-megabyte
#: payload would freeze the UI thread just as effectively as a hostile one.
MAX_TEXT_LENGTH = 4000


class OutcomeKind(str, Enum):
    """What a tool call actually resulted in.

    Distinguishing these is the whole point of the module: a *refusal* is the
    safety kernel working correctly and must be shown to the owner as a
    decision point, whereas a *failure* is something that went wrong and a
    *protocol error* means the transport itself is unreliable.
    """

    OK = "OK"
    #: T2 work declined for want of explicit consent. Not an error.
    REFUSED = "REFUSED"
    #: The kernel could not map the request to a playbook and declined to
    #: guess. Also a refusal, but one no consent can resolve: there is no
    #: action to authorise. Kept distinct from REFUSED so the UI cannot offer
    #: an approval that would do nothing.
    UNMATCHED = "UNMATCHED"
    #: The kernel ran something and it did not succeed.
    FAILED = "FAILED"
    #: Malformed frame, unknown id, or unparseable payload.
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


@dataclass(frozen=True, slots=True)
class Outcome:
    """A decided result, ready for the UI to render without further parsing."""

    kind: OutcomeKind
    #: Human-readable text, already length-capped.
    text: str
    #: The kernel's own next-step hint, when it supplied one.
    hint: str = ""
    #: Safety tier, when the kernel reported one.
    tier: int | None = None
    #: True when re-calling with ``allow=True`` is the documented next step.
    consent_required: bool = False
    #: The raw payload, for callers that need a field this class does not model.
    payload: dict[str, Any] = field(default_factory=dict)


def _cap(text: str) -> str:
    """Bound text before it reaches the renderer, marking any truncation."""
    if len(text) <= MAX_TEXT_LENGTH:
        return text
    return text[:MAX_TEXT_LENGTH] + f" [... truncated at {MAX_TEXT_LENGTH} characters]"


def build_initialize(message_id: int) -> str:
    """Frame the opening ``initialize`` request."""
    return _frame(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION},
        }
    )


def build_initialized_notification() -> str:
    """Frame ``notifications/initialized``, which takes no response."""
    return _frame({"jsonrpc": "2.0", "method": "notifications/initialized"})


def build_tools_list(message_id: int) -> str:
    """Frame a ``tools/list`` request."""
    return _frame({"jsonrpc": "2.0", "id": message_id, "method": "tools/list"})


def build_tool_call(
    message_id: int,
    tool: str,
    arguments: dict[str, Any],
    *,
    allow: bool = False,
) -> str:
    """Frame a ``tools/call`` request.

    Args:
        message_id: Correlation id; must be unique for the connection.
        tool: One of :data:`KNOWN_TOOLS`.
        arguments: Tool arguments, per the published input schema.
        allow: Consent flag. **Only** ever True as the direct result of an
            explicit owner action in the UI.

    Raises:
        ValueError: If the tool is unknown, or if consent is offered to a
            read-only tool. Both indicate a programming error in the caller,
            and failing loudly here is far better than sending a malformed or
            over-privileged frame to the kernel.
    """
    if tool not in KNOWN_TOOLS:
        raise ValueError(f"Unknown tool {tool!r}; the contract publishes {sorted(KNOWN_TOOLS)}.")
    if allow and tool not in CONSENT_TOOLS:
        raise ValueError(
            f"{tool!r} is read-only; sending allow=True would misstate the caller's intent."
        )

    payload = dict(arguments)
    if allow:
        payload["allow"] = True

    return _frame(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": payload},
        }
    )


def _frame(obj: dict[str, Any]) -> str:
    """Serialise one object as a single newline-terminated line.

    ``ensure_ascii`` keeps the frame to one line even when a request contains
    characters whose UTF-8 form might otherwise be mangled by an intermediate
    layer, and separators trim needless whitespace from the pipe.
    """
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n"


def parse_line(line: str) -> dict[str, Any] | None:
    """Parse one wire line, or return ``None`` if it is not a JSON object.

    Blank lines and non-object JSON are treated as noise rather than as
    failures: the transport promises objects, and anything else is skipped so
    one malformed line cannot take the connection down.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def server_version(initialize_result: dict[str, Any]) -> str | None:
    """Extract ``serverInfo.version`` from an ``initialize`` result."""
    info = initialize_result.get("serverInfo")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    return str(version) if isinstance(version, str) else None


def classify_outcome(message: dict[str, Any]) -> Outcome:
    """Turn a ``tools/call`` response into a decided :class:`Outcome`.

    The important distinction is between a refusal and a failure. The kernel
    signals both with ``isError: true``, so a client that only checked that
    flag would show the safety kernel's correct behaviour as a malfunction --
    and, worse, might invite a retry loop. Refusals are identified by
    ``payload.outcome.status == "refused"`` and surfaced as a consent decision.
    """
    if "error" in message:
        error = message["error"]
        detail = error.get("message") if isinstance(error, dict) else str(error)
        return Outcome(
            kind=OutcomeKind.PROTOCOL_ERROR,
            text=_cap(f"Kernel protocol error: {detail}"),
        )

    result = message.get("result")
    if not isinstance(result, dict):
        return Outcome(
            kind=OutcomeKind.PROTOCOL_ERROR,
            text="Kernel response contained no result object.",
        )

    payload = _extract_payload(result)
    if payload is None:
        return Outcome(
            kind=OutcomeKind.PROTOCOL_ERROR,
            text="Kernel response payload was not decodable JSON.",
        )

    is_error = bool(result.get("isError"))
    outcome = payload.get("outcome")
    outcome = outcome if isinstance(outcome, dict) else {}
    status = str(outcome.get("status", "")).lower()
    tier = outcome.get("tier")
    tier = tier if isinstance(tier, int) else None
    hint = str(outcome.get("hint") or "")

    if status == "refused" and _is_unmatched(outcome):
        # The kernel's refusal-to-guess. It carries a tier (0), so keying off
        # the tier alone would render it as "this tier-0 action needs your
        # consent" -- a consent prompt for a request that was never understood,
        # where approving re-sends it and gets the identical refusal. Surface
        # the kernel's own sentence instead; it is the honest one.
        return Outcome(
            kind=OutcomeKind.UNMATCHED,
            text=_cap(
                str(outcome.get("error") or "").strip()
                or "The kernel could not map that request to a known playbook."
            ),
            hint=_cap(hint),
            tier=tier,
            consent_required=False,
            payload=payload,
        )

    if status == "refused":
        return Outcome(
            kind=OutcomeKind.REFUSED,
            text=_cap(_refusal_text(outcome, tier)),
            hint=_cap(hint),
            tier=tier,
            # T3 is refused unconditionally: offering consent for it would be a
            # lie about what the owner is able to authorise.
            consent_required=tier is not None and tier < 3,
            payload=payload,
        )

    if is_error:
        return Outcome(
            kind=OutcomeKind.FAILED,
            text=_cap(str(outcome.get("error") or payload.get("error") or "Request failed.")),
            hint=_cap(hint),
            tier=tier,
            payload=payload,
        )

    return Outcome(
        kind=OutcomeKind.OK,
        text=_cap(summarise_success(payload)),
        tier=tier,
        payload=payload,
    )


#: The kernel's sentinel in ``outcome.playbook`` when nothing matched. Defined
#: in ``plan.py`` too, but duplicated rather than imported: ``protocol`` is the
#: lower layer and must not depend on the plan model.
_UNMATCHED_SENTINEL = "<unmatched>"


def _is_unmatched(outcome: dict[str, Any]) -> bool:
    """Whether this refusal is "I will not guess" rather than "I need consent".

    The structured sentinel is the primary signal; the prose check is a
    fallback for the case where the field is absent, and is deliberately
    narrow. Getting this wrong in the *safe* direction means showing a consent
    prompt that does nothing, so the test errs toward treating a refusal as a
    consent refusal unless the kernel is clearly declining to guess.
    """
    if str(outcome.get("playbook") or "").strip() == _UNMATCHED_SENTINEL:
        return True
    error = str(outcome.get("error") or "").lower()
    return "cannot map this request" in error


def _refusal_text(outcome: dict[str, Any], tier: int | None) -> str:
    """Compose the sentence shown when the kernel declines to act."""
    if tier is not None and tier >= 3:
        return "Refused: this is a tier-3 action, which the safety kernel never performs."
    label = f"tier-{tier} " if tier is not None else ""
    return f"Refused: this {label}action needs your explicit consent before it can run."


def _extract_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    """Decode ``result.content[0].text`` into the tool's JSON payload."""
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return None
    first = content[0]
    if not isinstance(first, dict):
        return None
    text = first.get("text")
    if not isinstance(text, str):
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def summarise_success(payload: dict[str, Any]) -> str:
    """Render a successful payload as one console line.

    Each tool returns a different shape, so this picks the field that carries
    the answer. Anything unrecognised falls back to compact JSON rather than
    being dropped -- showing the raw truth beats showing nothing.
    """
    for key in ("ai_text", "claim", "answer", "text", "summary"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    preview = payload.get("preview")
    if isinstance(preview, dict):
        steps = preview.get("steps")
        if isinstance(steps, list) and steps:
            lines = []
            for index, step in enumerate(steps, start=1):
                if isinstance(step, dict):
                    lines.append(f"{index}. {step.get('description') or step.get('argv')}")
            if lines:
                return "Plan: " + " | ".join(lines)

    outcome = payload.get("outcome")
    if isinstance(outcome, dict):
        status = outcome.get("status")
        if isinstance(status, str) and status:
            return f"Completed: {status}."

    # jarvis_suggest: each entry is evidence-backed, and the evidence is the
    # point. Titles alone would present the kernel's reasoning as a bare
    # opinion, so the supporting detail is kept with each one.
    suggestions = payload.get("suggestions")
    if isinstance(suggestions, list):
        if not suggestions:
            return "No suggestions: nothing in the journal or context warrants one."
        lines = []
        for entry in suggestions[:8]:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or entry.get("id") or "").strip()
            detail = str(entry.get("detail") or "").strip()
            if title:
                lines.append(f"{title} - {detail}" if detail else title)
        if lines:
            return "Suggestions: " + " | ".join(lines)

    # jarvis_status: a flat machine description. Rendered as key=value pairs
    # rather than raw JSON so it reads as a status line.
    if "distro_name" in payload:
        interesting = ("distro_name", "package_manager", "init_system", "python_version")
        parts = [
            f"{key.replace('_', ' ')}: {payload[key]}"
            for key in interesting
            if isinstance(payload.get(key), str)
        ]
        if parts:
            return " | ".join(parts)

    return json.dumps(payload, separators=(",", ":"))
