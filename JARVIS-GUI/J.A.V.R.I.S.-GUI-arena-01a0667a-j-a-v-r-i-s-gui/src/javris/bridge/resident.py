"""Resident-mode transport: the kernel's opt-in loopback doorway (ADR-0018).

The default remains the per-session spawn. This is the alternative for owners
who have run ``jarvis serve install`` and want the kernel reachable without the
GUI starting a process at all.

Two properties of the doorway shaped this client, and both were verified
against a running ``jarvis serve`` rather than taken from the ADR:

**The response envelope differs from stdio.** Over stdio the payload is
double-encoded -- ``result.content[0].text`` is a JSON *string* that must be
parsed again. Over HTTP the response is ``{"result": {...}, "isError": bool}``
with ``result`` already decoded. :func:`envelope_to_message` normalises the
HTTP shape into the stdio shape so that ``protocol.classify_outcome`` -- the
audited consent-classification path -- stays the single implementation. Two
parallel classifiers would be two places for the refusal/failure distinction to
drift, and that distinction is the one that must not drift.

**Consent semantics are identical.** Verified live: ``jarvis_do`` with a T2
request and no ``allow`` returns ``isError: true`` with
``outcome.status = "refused"`` and the same preview-then-allow hint. The
doorway holds no authority the stdio surface does not.

This client refuses to talk to anything that is not loopback. That is not
defence against an attacker who already controls the machine; it is a guard
against a misconfiguration silently turning a local doorway into a network
one, which is exactly what the kernel refuses to do on its own side.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

#: The doorway's default port, matching ``jarvis.cli.serve.DEFAULT_PORT``.
DEFAULT_PORT = 8777

#: Hosts this client will connect to. A non-loopback host is a configuration
#: error, not something to be helpful about.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: Bound on a token file. A real token is a few dozen characters; anything of
#: this size is not a token and should not be read into memory or sent.
MAX_TOKEN_BYTES = 4096

HEALTH_PATH = "/v1/health"
TOOL_PATH_PREFIX = "/v1/tools/"


class ResidentError(RuntimeError):
    """The doorway cannot be used as configured."""


def default_token_path(env: dict[str, str] | None = None) -> Path:
    """Where the kernel writes the doorway token.

    Mirrors ``jarvis.journal.sqlite.state_dir``: ``$JARVIS_STATE_DIR`` if set,
    otherwise ``$XDG_STATE_HOME/jarvis``, otherwise ``~/.local/state/jarvis``.
    Resolved independently rather than by importing the kernel, because the GUI
    must not depend on the backend package being importable in its own
    interpreter -- they are separate programs that share a wire contract.
    """
    source = os.environ if env is None else env
    explicit = source.get("JARVIS_STATE_DIR")
    if explicit:
        return Path(explicit) / "serve" / "token"
    xdg = source.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "jarvis" / "serve" / "token"


def read_token(path: Path) -> str:
    """Read the bearer token, refusing an unsafely-permissioned file.

    The kernel writes this 0600. If it is group- or world-readable then another
    account can already act as the owner, and the right response is to say so
    rather than to use it anyway.

    Raises:
        ResidentError: If the file is missing, too large, world/group readable,
            or empty.
    """
    try:
        info = path.stat()
    except OSError as exc:
        raise ResidentError(
            f"No doorway token at {path}. Run 'jarvis serve install' to enable resident mode."
        ) from exc

    if not stat.S_ISREG(info.st_mode):
        raise ResidentError(f"Doorway token at {path} is not a regular file.")

    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ResidentError(
            f"Doorway token at {path} is readable by other accounts "
            f"(mode {stat.S_IMODE(info.st_mode):04o}); refusing to use it. "
            "Restore it with: chmod 600 " + str(path)
        )

    if info.st_size > MAX_TOKEN_BYTES:
        raise ResidentError(f"Doorway token at {path} is implausibly large; refusing to read it.")

    token = path.read_text(encoding="utf-8", errors="strict").strip()
    if not token:
        raise ResidentError(f"Doorway token at {path} is empty.")
    return token


def validate_endpoint(host: str, port: int) -> None:
    """Reject any endpoint that is not loopback, or any out-of-range port.

    Raises:
        ResidentError: If the endpoint would send a bearer token off-machine.
    """
    if host not in LOOPBACK_HOSTS:
        raise ResidentError(
            f"Refusing to use {host!r}: the doorway is loopback-only, and sending "
            "the bearer token to another host would leak it."
        )
    if not 1 <= port <= 65535:
        raise ResidentError(f"Port {port} is out of range.")


def health_url(host: str, port: int) -> str:
    """URL of the unauthenticated health probe."""
    validate_endpoint(host, port)
    return f"http://{host}:{port}{HEALTH_PATH}"


def tool_url(host: str, port: int, tool: str) -> str:
    """URL for one tool, validating both endpoint and tool name."""
    from . import protocol

    validate_endpoint(host, port)
    if tool not in protocol.KNOWN_TOOLS:
        raise ValueError(f"Unknown tool {tool!r}.")
    return f"http://{host}:{port}{TOOL_PATH_PREFIX}{tool}"


def build_body(tool: str, arguments: dict[str, Any], *, allow: bool = False) -> bytes:
    """Serialise a tool-call body.

    Applies the same consent rule as the stdio framer: ``allow`` is never
    synthesised, and offering it to a read-only tool raises rather than being
    quietly dropped.

    Raises:
        ValueError: If the tool is unknown, or consent is offered to a
            read-only tool.
    """
    from . import protocol

    if tool not in protocol.KNOWN_TOOLS:
        raise ValueError(f"Unknown tool {tool!r}.")
    if allow and tool not in protocol.CONSENT_TOOLS:
        raise ValueError(f"{tool!r} is read-only; sending allow=True would misstate intent.")

    payload = dict(arguments)
    if allow:
        payload["allow"] = True
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def envelope_to_message(envelope: dict[str, Any]) -> dict[str, Any]:
    """Convert an HTTP ``{result, isError}`` envelope into the stdio shape.

    The point is to reuse ``protocol.classify_outcome`` verbatim. That function
    holds the refusal-versus-failure distinction, and having exactly one
    implementation of it is worth the small re-encode here.
    """
    inner = envelope.get("result")
    inner = inner if isinstance(inner, dict) else {}
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "isError": bool(envelope.get("isError")),
            "content": [{"type": "text", "text": json.dumps(inner)}],
        },
    }


def parse_envelope(raw: bytes) -> dict[str, Any]:
    """Decode a doorway response body.

    Raises:
        ResidentError: If the body is not a JSON object.
    """
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise ResidentError("Doorway returned a body that was not JSON.") from exc
    if not isinstance(parsed, dict):
        raise ResidentError("Doorway returned JSON that was not an object.")
    return parsed


def parse_server_header(value: str) -> str:
    """Extract the kernel version from the doorway's ``Server`` header.

    The doorway identifies itself as ``jarvis-serve/<version> Python/<x.y.z>``
    (verified against a running doorway at 1.20.0). This is the only place the
    HTTP surface reports its version, and reading it avoids inventing a version
    or leaving the owner with "unknown" for a link that is plainly working.

    Returns an empty string when the header is absent or in another form --
    unknown is reported as unknown.
    """
    for token in value.split():
        name, sep, version = token.partition("/")
        if sep and name == "jarvis-serve" and version:
            return version
    return ""


def describe_http_status(status: int) -> str:
    """Explain a doorway HTTP status in the operator's terms.

    Each of these was observed against a running doorway, so the explanations
    describe real behaviour rather than generic HTTP semantics.
    """
    if status == 401:
        return "The doorway rejected the token. Re-read it, or run 'jarvis serve install' again."
    if status == 403:
        return "The doorway refused the request."
    if status == 404:
        return "The doorway does not expose that tool."
    if status == 413:
        return "The request was larger than the doorway's 64 KiB limit."
    if status == 421:
        return "The doorway rejected the Host header; it only answers as loopback."
    if status >= 500:
        return f"The doorway reported an internal error (HTTP {status})."
    return f"The doorway returned HTTP {status}."
