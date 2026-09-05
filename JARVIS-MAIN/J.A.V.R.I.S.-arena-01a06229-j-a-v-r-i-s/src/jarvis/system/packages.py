"""Package-manager adapters: exact argv construction per backend.

Adapters own *how* to talk to a backend; they never decide *whether* to act
(PLAN §4.2). All argvs are built from validated tokens (safety.tiers) and are
unit-tested for exactness — the command surface is a contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jarvis.system.models import PackageManager, UnsupportedError


@dataclass(frozen=True)
class PMAdapter:
    """Command vocabulary for one package-manager backend."""

    pm: PackageManager

    @property
    def mutating_env(self) -> Mapping[str, str]:
        """Extra env for non-interactive mutation (apt needs the frontend hint)."""
        if self.pm is PackageManager.APT:
            return {"DEBIAN_FRONTEND": "noninteractive", "DEBIAN_PRIORITY": "critical"}
        return {}

    # -- repository index -------------------------------------------------
    def refresh_argv(self) -> list[str]:
        match self.pm:
            case PackageManager.APT:
                return ["apt-get", "update"]
            case PackageManager.DNF:
                return ["dnf", "-q", "makecache"]
            case PackageManager.PACMAN:
                return ["pacman", "-Sy"]
            case PackageManager.ZYPPER:
                return ["zypper", "refresh"]
            case PackageManager.APK:
                return ["apk", "update"]
        raise UnsupportedError(self.pm.value)  # pragma: no cover - exhaustive match

    # -- mutations --------------------------------------------------------
    def install_argv(self, names: Sequence[str]) -> list[str]:
        match self.pm:
            case PackageManager.APT:
                return ["apt-get", "install", "-y", "--", *names]
            case PackageManager.DNF:
                return ["dnf", "install", "-y", "--", *names]
            case PackageManager.PACMAN:
                return ["pacman", "-S", "--noconfirm", "--", *names]
            case PackageManager.ZYPPER:
                return ["zypper", "--non-interactive", "install", "--", *names]
            case PackageManager.APK:
                return ["apk", "add", *names]
        raise UnsupportedError(self.pm.value)  # pragma: no cover

    def remove_argv(self, names: Sequence[str]) -> list[str]:
        match self.pm:
            case PackageManager.APT:
                return ["apt-get", "remove", "-y", "--", *names]
            case PackageManager.DNF:
                return ["dnf", "remove", "-y", "--", *names]
            case PackageManager.PACMAN:
                # -Rs: also drop dependencies that become unneeded (Arch wiki).
                return ["pacman", "-Rs", "--noconfirm", "--", *names]
            case PackageManager.ZYPPER:
                return ["zypper", "--non-interactive", "remove", "--", *names]
            case PackageManager.APK:
                return ["apk", "del", *names]
        raise UnsupportedError(self.pm.value)  # pragma: no cover

    def upgrade_argv(self) -> list[str]:
        match self.pm:
            case PackageManager.APT:
                # Conservative upgrade: installs updates, never removes packages.
                return ["apt-get", "upgrade", "-y"]
            case PackageManager.DNF:
                return ["dnf", "-q", "upgrade", "-y"]
            case PackageManager.PACMAN:
                # -Syu: Arch requires index+upgrade together (no partial upgrades).
                return ["pacman", "-Syu", "--noconfirm"]
            case PackageManager.ZYPPER:
                return ["zypper", "--non-interactive", "update"]
            case PackageManager.APK:
                return ["apk", "upgrade"]
        raise UnsupportedError(self.pm.value)  # pragma: no cover

    # -- read-only queries ------------------------------------------------
    def search_argv(self, tokens: Sequence[str]) -> list[str]:
        match self.pm:
            case PackageManager.APT:
                return ["apt-cache", "search", "--", *tokens]
            case PackageManager.DNF:
                return ["dnf", "-q", "search", *tokens]
            case PackageManager.PACMAN:
                return ["pacman", "-Ss", *tokens]
            case PackageManager.ZYPPER:
                return ["zypper", "search", *tokens]
            case PackageManager.APK:
                return ["apk", "search", "-v", *tokens]
        raise UnsupportedError(self.pm.value)  # pragma: no cover

    def info_argv(self, name: str) -> list[str]:
        match self.pm:
            case PackageManager.APT:
                return ["apt-cache", "show", "--", name]
            case PackageManager.DNF:
                return ["dnf", "-q", "info", name]
            case PackageManager.PACMAN:
                return ["pacman", "-Si", name]
            case PackageManager.ZYPPER:
                return ["zypper", "info", name]
            case PackageManager.APK:
                return ["apk", "search", "-v", "-x", name]
        raise UnsupportedError(self.pm.value)  # pragma: no cover

    def installed_check_argv(self, name: str) -> list[str]:
        """Read-only probe: exit 0 iff *name* is installed."""
        match self.pm:
            case PackageManager.APT:
                return ["dpkg-query", "-W", "-f=${db:Status-Abbrev}", "--", name]
            case PackageManager.DNF:
                return ["rpm", "-q", "--", name]
            case PackageManager.PACMAN:
                return ["pacman", "-Q", name]
            case PackageManager.ZYPPER:
                return ["rpm", "-q", "--", name]
            case PackageManager.APK:
                return ["apk", "info", "-e", name]
        raise UnsupportedError(self.pm.value)  # pragma: no cover


def installed_check_ok(stdout_tail: str, exit_code: int, pm: PackageManager) -> bool:
    """Interpret an installed_check_argv result.

    rpm/pacman/apk: exit 0 simply means installed. dpkg-query exits 0 for
    known packages too, so the status abbreviation must say 'ii '.
    """
    if pm is PackageManager.APT:
        return exit_code == 0 and stdout_tail.strip().startswith("ii")
    return exit_code == 0


def get_adapter(pm: PackageManager) -> PMAdapter:
    return PMAdapter(pm)
