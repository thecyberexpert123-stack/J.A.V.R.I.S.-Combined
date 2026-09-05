"""Domain models shared across JARVIS modules.

This module sits at the bottom of the dependency graph: it must import no
other `jarvis` module (PLAN §4.2 — `system` knows nothing about planners,
LLMs, or execution policy).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum


class PackageManager(Enum):
    """Package-manager backends JARVIS can drive (Tier-1 set, PLAN FR-1)."""

    APT = "apt"
    DNF = "dnf"
    PACMAN = "pacman"
    ZYPPER = "zypper"
    APK = "apk"


class UnsupportedError(RuntimeError):
    """The requested operation has no implementation on this machine."""


class PrivilegeError(RuntimeError):
    """A step needs elevated privileges but none are available non-interactively."""


class InvalidInputError(ValueError):
    """User-supplied input failed validation (ADR-0006: refuse, never sanitize)."""


# Boot-critical packages that must never be removed through JARVIS, not even
# via undo artifacts (journal files are user-editable, so this set is enforced
# at every execution boundary, not just at plan time). Exact names and glob
# patterns per ADR-0006.
PROTECTED_PACKAGE_EXACT: frozenset[str] = frozenset(
    {
        "glibc",
        "libc6",
        "libc-bin",
        "coreutils",
        "bash",
        "dash",
        "dpkg",
        "apt",
        "dnf",
        "pacman",
        "zypper",
        "apk-tools",
        "rpm",
        "systemd",
        "dbus",
        "sudo",
        "util-linux",
        "mount",
        "passwd",
        "login",
        "sysvinit",
        "openrc",
    }
)
PROTECTED_PACKAGE_PATTERNS: tuple[str, ...] = (
    "linux-image-*",
    "linux-headers-*",
    "linux-firmware-*",
    "systemd-*",
    "apt-*",
    "glibc-*",
    "dbus-*",
)


def is_protected_package(name: str) -> bool:
    """True if *name* is boot-critical and must never be removed by JARVIS."""
    if name in PROTECTED_PACKAGE_EXACT:
        return True
    return any(fnmatch.fnmatchcase(name, pat) for pat in PROTECTED_PACKAGE_PATTERNS)


@dataclass(frozen=True)
class MachineProfile:
    """Fingerprint of the machine JARVIS is running on (pipeline stage SENSE)."""

    distro_id: str
    distro_name: str
    version_id: str | None
    init_system: str  # "systemd" | "none" | "unknown"
    package_manager: PackageManager | None
    session_type: str | None  # XDG_SESSION_TYPE, if any (GUI work, M5)
    is_root: bool
    sudo_available: bool
    python_version: str
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "distro_id": self.distro_id,
            "distro_name": self.distro_name,
            "version_id": self.version_id,
            "init_system": self.init_system,
            "package_manager": self.package_manager.value if self.package_manager else None,
            "session_type": self.session_type,
            "is_root": self.is_root,
            "sudo_available": self.sudo_available,
            "python_version": self.python_version,
            "extra": dict(self.extra),
        }
