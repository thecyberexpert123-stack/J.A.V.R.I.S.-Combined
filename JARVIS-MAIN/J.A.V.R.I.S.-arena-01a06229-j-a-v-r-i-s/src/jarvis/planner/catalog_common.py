"""Shared machinery for the command-catalog families (ADR-0016).

Every factory-built playbook gets the same guarantees: a pinned binary with a
fully fixed flag prefix, argument slots validated per kind (no user flags —
a leading dash is a refusal), an exit-code-plus-output verifier, and an honest
undo statement. This module deliberately duplicates ~10 lines from
planner.playbooks instead of importing it: playbooks.py imports the catalog
families, so the import edge must point one way only.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from jarvis.execution.runner import ExecResult, Runner
from jarvis.planner.models import UndoPlan, UndoStatus, Verification
from jarvis.safety.tiers import SafetyRefusal
from jarvis.system.models import MachineProfile

Params = dict[str, object]

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,253}$")
_GLOB = re.compile(r"^[A-Za-z0-9._*?[\]-]{1,80}$")
_MAX_ARG_CHARS = 200


def clean_arg(value: str, kind: str) -> str:
    """Validate one user argument slot. Refusal, never sanitization."""
    text = value.strip()
    if not text:
        raise SafetyRefusal("empty argument")
    if len(text) > _MAX_ARG_CHARS:
        raise SafetyRefusal(f"argument too long ({len(text)} chars)")
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in text):
        raise SafetyRefusal("control characters are not allowed in arguments")
    # shell metacharacters are refused in every argument slot: argv is executed
    # directly (no shell), so these are inert — refusing them keeps journal
    # entries, verify output, and human review unambiguous (ADR-0016 D2).
    if any(ch in text for ch in (";", "|", "&", "$", "`")):
        raise SafetyRefusal("shell metacharacters are not allowed in arguments")
    if text.startswith("-"):
        raise SafetyRefusal(f"refusing {text[:20]!r}: arguments must be values, never flags")
    if kind == "name" and not _TOKEN.match(text):
        raise SafetyRefusal(f"invalid name token: {text[:40]!r}")
    if kind == "host" and not _HOST.match(text):
        raise SafetyRefusal(f"invalid host: {text[:40]!r}")
    if kind == "glob" and ("/" in text or not _GLOB.match(text)):
        raise SafetyRefusal(f"invalid file-name pattern: {text[:40]!r}")
    if kind == "path" and "\x00" in text:  # unreachable after control-char check; belt & braces
        raise SafetyRefusal("NUL in path")
    return text


def path_arg(value: str) -> Path:
    """A path argument with ~ expansion; returns the resolved Path."""
    return Path(clean_arg(value, "path")).expanduser()


def verify_ran(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    """Standard verifier for read-only commands: exit 0 with output."""
    if not step_results or not step_results[0]:
        return Verification(ok=False, detail="no step result recorded")
    first = step_results[0]
    lines = len(first.stdout_tail.splitlines())
    if first.exit_code != 0:
        return Verification(
            ok=False,
            detail=f"command exited {first.exit_code}: {first.stderr_tail[:120]}",
        )
    return Verification(ok=True, detail=f"completed ({lines} line(s) of output)")


def no_undo(reason: str) -> UndoPlan:
    return UndoPlan(status=UndoStatus.NONE_NEEDED, reason=reason)
