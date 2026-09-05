"""Guard constants and pure predicates for desktop awareness (ADR-0022 D2).

Fail-closed by design: a false-positive block costs a slice of a read-only
capability; a false-negative read of a secret-bearing surface costs privacy.
The lists are frozen constants, pinned by tests, and shared by every reader
(the CLI and the GUI service alike) so drift is a CI failure.
"""

from __future__ import annotations

import re

# Password managers, keyrings/secret services, polkit/askpass agents, and
# terminal emulators — matched case-insensitively by exact name or substring.
BLOCKED_APPS: frozenset[str] = frozenset(
    {
        # password managers
        "keepass",
        "bitwarden",
        "1password",
        "passwordsafe",
        "password safe",
        "dashlane",
        "lastpass",
        "enpass",
        "proton pass",
        "protonpass",
        # keyrings / secret services
        "seahorse",
        "keyring",
        "kwallet",
        # privilege / polkit / ssh askpass agents
        "polkit",
        "pkexec",
        "askpass",
        # terminal emulators: shell content is out of scope for a read-only agent
        "gnome-terminal",
        "konsole",
        "xterm",
        "st",
        "urxvt",
        "alacritty",
        "kitty",
        "wezterm",
        "tilix",
        "terminator",
        "foot",
    }
)

# AT-SPI RoleName for secure text entry. Withheld BEFORE the node's name is
# ever read (ADR-0022 D2 wall 2).
PASSWORD_ROLES: frozenset[str] = frozenset({"password text"})

_SENSITIVE_NAME_RE = re.compile(
    r"(?i)("
    r"\bpass(word|phrase|code)?s?\b"
    r"|\bsecrets?\b"
    r"|\btokens?\b"
    r"|\bcredentials?\b"
    r"|\bapi[-_ ]?keys?\b"
    r"|\bauth[-_ ]?(key|token)s?\b"
    r"|\bprivate[-_ ]?keys?\b"
    r"|\botp\b|\b2fa\b|\btotp\b"
    r"|\bcvv\b|\bcvc\b|\bcsc\b"
    r"|\b(card|account)[-_ ]?(number|no)\b"
    r"|\bpin\b"
    r")"
)

WITHHELD_APP = "[withheld: application '{name}' is on the blocked list]"
WITHHELD_PASSWORD = "[withheld: password text field]"
REDACTED_NAME = "(redacted: sensitive field)"


def is_blocked_app(name: str) -> bool:
    """Case-insensitive exact-or-substring blocklist match (fail-closed)."""
    lowered = name.strip().lower()
    if not lowered:
        return False
    return lowered in BLOCKED_APPS or any(token in lowered for token in BLOCKED_APPS)


def is_password_role(role: str) -> bool:
    return role.strip().lower() in PASSWORD_ROLES


def is_sensitive_name(name: str) -> bool:
    return _SENSITIVE_NAME_RE.search(name) is not None


def hygiene(text: str, limit: int = 120) -> str:
    """Strip control characters, collapse whitespace, clamp length."""
    cleaned = "".join(ch for ch in text if ord(ch) >= 32 and ord(ch) != 127)
    collapsed = " ".join(cleaned.split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return collapsed
