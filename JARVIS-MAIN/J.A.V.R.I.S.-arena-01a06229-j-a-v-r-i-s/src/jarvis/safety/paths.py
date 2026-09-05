"""File-path policy for file-modifying operations (ADR-0008).

Rules are absolute, not advisory: symlinks are resolved before any check so a
link pointing at protected material is caught; authentication material and
kernel boot paths are refused outright; system trees require T2 consent.
"""

from __future__ import annotations

from pathlib import Path

from jarvis.safety.tiers import SafetyRefusal, Tier

FORBIDDEN_FILES: frozenset[str] = frozenset(
    {
        "/etc/passwd",
        "/etc/shadow",
        "/etc/gshadow",
        "/etc/sudoers",
    }
)
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "/etc/sudoers.d/",
    "/boot/",
    "/proc/",
    "/sys/",
    "/dev/",
)
T2_PREFIXES: tuple[str, ...] = ("/etc/", "/usr/", "/var/", "/opt/", "/srv/")

MAX_TEXT_CHARS = 500


def validate_edit_text(text: str) -> str:
    """A file edit payload must be one tame line."""
    if not text or not text.strip():
        raise SafetyRefusal("refusing to append empty text")
    if len(text) > MAX_TEXT_CHARS:
        raise SafetyRefusal(f"text too long for a single-line edit ({len(text)} chars)")
    if any(ch in text for ch in ("\n", "\r", "\x00", "\x1b")):
        raise SafetyRefusal("control characters are not allowed in edit text")
    return text.strip()


def classify_for_edit(path_str: str) -> tuple[Tier, Path]:
    """Classify a target path for a mutating edit.

    Returns (tier, resolved_path). Raises SafetyRefusal for protected or
    malformed targets. Refusal — never sanitization (ADR-0006).
    """
    if not path_str or path_str.strip() != path_str or "\x00" in path_str:
        raise SafetyRefusal(f"malformed path: {path_str!r}")
    raw = Path(path_str).expanduser()
    if not raw.is_absolute():
        raise SafetyRefusal(f"path must be absolute (after ~ expansion): {path_str!r}")
    resolved = raw.resolve(strict=False)
    as_posix = resolved.as_posix()

    if as_posix == "/":
        raise SafetyRefusal("refusing to operate on /")
    if as_posix in FORBIDDEN_FILES or any(
        as_posix.startswith(prefix) for prefix in FORBIDDEN_PREFIXES
    ):
        raise SafetyRefusal(
            f"refusing to modify {as_posix!r}: authentication material and "
            "boot/kernel paths are protected"
        )
    if any(as_posix == prefix.rstrip("/") or as_posix.startswith(prefix) for prefix in T2_PREFIXES):
        return Tier.T2, resolved
    return Tier.T1, resolved
