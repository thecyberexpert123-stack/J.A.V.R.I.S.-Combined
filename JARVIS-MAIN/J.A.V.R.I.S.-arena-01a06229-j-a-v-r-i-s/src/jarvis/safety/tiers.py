"""Action-tier classification and static safety analysis (pipeline stage APPROVE).

The tier model is the heart of "does not blindly do tasks" (owner point 2):
T0 read-only, T1 reversible user-scope, T2 system-level, T3 destructive —
see docs/PLAN.md §4.3 and ADR-0006. Static analysis here is the first of the
two reviewers (the LLM reviewer arrives with the planner in M2).

Design note: argv elements cannot contain whitespace (all user tokens are
validated against no-whitespace patterns), so a *space*-joined argv is safe
for pattern scanning and keeps `\\s`/`\b` anchors meaningful. Program-name
patterns are only enforced on argv[0] and on arguments passed to `-c` (shell
content) so that, e.g., installing a package literally named `init` is not a
false positive while `bash -c "shutdown -h now"` still is.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import IntEnum

from jarvis.system.models import InvalidInputError, is_protected_package


class Tier(IntEnum):
    """Safety tier of an action; higher = more dangerous."""

    T0 = 0  # read-only
    T1 = 1  # reversible, user scope (backup/undo available)
    T2 = 2  # system-level (explicit approval)
    T3 = 3  # destructive / irreversible — refused by policy


class SafetyRefusal(RuntimeError):
    """Static safety analysis refused the action. Never bypassed at runtime."""


# Valid user-supplied tokens (ADR-0006): refuse, never sanitize.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:@._-]*$")

# Programs JARVIS must never be the one to invoke directly (argv[0]).
_DANGEROUS_PROGRAMS: frozenset[str] = frozenset(
    {
        "shutdown",
        "halt",
        "poweroff",
        "reboot",
        "init",
        "telinit",
        "dd",
        "mkfs",
        "wipefs",
        "parted",
        "fdisk",
        "gdisk",
        "sgdisk",
    }
)

# Patterns for shell content (a `-c` argument or a space-joined argv scan).
# Anchored with (^|\s) so e.g. "initech" does not match.
_UNCONDITIONAL_BLOCKED: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat)
    for pat in (
        r":\(\)\s*\{.*\};",  # fork bomb
        r"(?:^|\s)rm\s+(-\w*\s+)*-?[rf]{1,2}\w*\s+(?:/|~)(?:\s|$)",
        r"(?:^|\s)chmod\s+-R\s+\S+\s+/(?:\s|$)",
        r"(?:^|\s)chown\s+-R\s+\S+\s+/(?:\s|$)",
        r">\s*/dev/(?:sd|nvme|vd)",
        r"(?:^|\s)dd\s+[^;|&]*\bof=/dev/",
        r"(?:^|\s)mkfs(?:\.\w+)?(?:\s|$)",
        r"(?:^|\s)(?:curl|wget)\s+[^;|&]*\|\s*(?:sudo\s+)?(?:ba)?sh\b",
        r">\s*/etc/(?:passwd|shadow|sudoers)\b",
        r"(?:^|\s)umask\s+000(?:\s|$)",
        r"\|\s*(?:sudo\s+)?(?:ba|z)?sh\b",  # any pipe into a shell
        r"(?:^|\s)chmod\s+777\s+/(?:\s|$)",
    )
)

# Patterns that additionally apply to shell content after `-c`.
_SHELL_ONLY_BLOCKED: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat)
    for pat in (r"(?:^|\s|[/;])(?:shutdown|halt|poweroff|reboot|init|telinit)(?:\s|$)",)
)


def validate_package_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise InvalidInputError(f"invalid package name: {name!r}")
    return name


def validate_unit_name(unit: str) -> str:
    if not _UNIT_RE.match(unit):
        raise InvalidInputError(f"invalid systemd unit name: {unit!r}")
    return unit


def validate_search_query(query: str) -> list[str]:
    """Split a free-text search into validated tokens (used as separate argv items)."""
    tokens = query.split()
    if not tokens:
        raise InvalidInputError("empty search query")
    for token in tokens:
        if not _NAME_RE.match(token):
            raise InvalidInputError(f"invalid search term: {token!r}")
    return tokens


def check_removal_allowed(name: str) -> None:
    """Refuse removal of boot-critical packages outright (ADR-0006)."""
    if is_protected_package(name):
        raise SafetyRefusal(
            f"refusing to remove {name!r}: it is boot-critical; "
            "manual action is required for packages in the protected set"
        )


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _scan_shell_content(content: str) -> None:
    for pattern in _UNCONDITIONAL_BLOCKED:
        if pattern.search(content):
            raise SafetyRefusal(f"argv matches blocked pattern {pattern.pattern!r}")
    for pattern in _SHELL_ONLY_BLOCKED:
        if pattern.search(content):
            raise SafetyRefusal(f"argv matches blocked pattern {pattern.pattern!r}")


def check_argv(argv: Sequence[str]) -> None:
    """Static defense-in-depth over a full argv (applied before every execution)."""
    if not argv:
        raise SafetyRefusal("empty argv")
    for arg in argv:
        if not isinstance(arg, str) or not arg or "\x00" in arg:
            raise SafetyRefusal(f"malformed argv element: {arg!r}")

    program = _basename(argv[0])
    if program in _DANGEROUS_PROGRAMS or program.startswith("mkfs."):
        raise SafetyRefusal(f"refusing to execute {program!r} directly")

    # Scan shell content passed via -c (e.g. ["bash", "-c", "..."]).
    for index, arg in enumerate(argv[:-1]):
        if arg in ("-c", "-lc"):
            _scan_shell_content(argv[index + 1])

    # Blanket scan with the unambiguous patterns (space-joined; see module note).
    joined = " ".join(argv)
    for pattern in _UNCONDITIONAL_BLOCKED:
        if pattern.search(joined):
            raise SafetyRefusal(f"argv matches blocked pattern {pattern.pattern!r}")

    # Elements after a "--" end-of-options marker are user-data positions:
    # enforce the token rule so a tampered journal cannot smuggle flags/files.
    seen_marker = False
    for arg in argv:
        if arg == "--":
            seen_marker = True
            continue
        if seen_marker and not (_NAME_RE.match(arg) or _UNIT_RE.match(arg)):
            raise SafetyRefusal(f"invalid token after '--': {arg!r}")
