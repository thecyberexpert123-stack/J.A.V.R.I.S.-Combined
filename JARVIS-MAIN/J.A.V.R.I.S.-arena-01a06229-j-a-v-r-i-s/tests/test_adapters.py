"""Adapter contract tests: exact argv per backend (the command surface)."""

from __future__ import annotations

import pytest

from jarvis.system.models import PackageManager
from jarvis.system.packages import get_adapter, installed_check_ok


@pytest.mark.parametrize(
    ("pm", "expected"),
    [
        (PackageManager.APT, ["apt-get", "update"]),
        (PackageManager.DNF, ["dnf", "-q", "makecache"]),
        (PackageManager.PACMAN, ["pacman", "-Sy"]),
        (PackageManager.ZYPPER, ["zypper", "refresh"]),
        (PackageManager.APK, ["apk", "update"]),
    ],
)
def test_refresh_argv(pm: PackageManager, expected: list[str]) -> None:
    assert get_adapter(pm).refresh_argv() == expected


@pytest.mark.parametrize(
    ("pm", "expected"),
    [
        (PackageManager.APT, ["apt-get", "install", "-y", "--", "htop", "curl"]),
        (PackageManager.DNF, ["dnf", "install", "-y", "--", "htop", "curl"]),
        (PackageManager.PACMAN, ["pacman", "-S", "--noconfirm", "--", "htop", "curl"]),
        (
            PackageManager.ZYPPER,
            ["zypper", "--non-interactive", "install", "--", "htop", "curl"],
        ),
        (PackageManager.APK, ["apk", "add", "htop", "curl"]),
    ],
)
def test_install_argv(pm: PackageManager, expected: list[str]) -> None:
    assert get_adapter(pm).install_argv(["htop", "curl"]) == expected


@pytest.mark.parametrize(
    ("pm", "expected"),
    [
        (PackageManager.APT, ["apt-get", "remove", "-y", "--", "htop"]),
        (PackageManager.DNF, ["dnf", "remove", "-y", "--", "htop"]),
        (PackageManager.PACMAN, ["pacman", "-Rs", "--noconfirm", "--", "htop"]),
        (PackageManager.ZYPPER, ["zypper", "--non-interactive", "remove", "--", "htop"]),
        (PackageManager.APK, ["apk", "del", "htop"]),
    ],
)
def test_remove_argv(pm: PackageManager, expected: list[str]) -> None:
    assert get_adapter(pm).remove_argv(["htop"]) == expected


@pytest.mark.parametrize(
    ("pm", "expected"),
    [
        (PackageManager.APT, ["apt-get", "upgrade", "-y"]),
        (PackageManager.DNF, ["dnf", "-q", "upgrade", "-y"]),
        (PackageManager.PACMAN, ["pacman", "-Syu", "--noconfirm"]),
        (PackageManager.ZYPPER, ["zypper", "--non-interactive", "update"]),
        (PackageManager.APK, ["apk", "upgrade"]),
    ],
)
def test_upgrade_argv(pm: PackageManager, expected: list[str]) -> None:
    assert get_adapter(pm).upgrade_argv() == expected


@pytest.mark.parametrize(
    ("pm", "expected"),
    [
        (PackageManager.APT, ["apt-cache", "search", "--", "text", "editor"]),
        (PackageManager.DNF, ["dnf", "-q", "search", "text", "editor"]),
        (PackageManager.PACMAN, ["pacman", "-Ss", "text", "editor"]),
        (PackageManager.ZYPPER, ["zypper", "search", "text", "editor"]),
        (PackageManager.APK, ["apk", "search", "-v", "text", "editor"]),
    ],
)
def test_search_argv(pm: PackageManager, expected: list[str]) -> None:
    assert get_adapter(pm).search_argv(["text", "editor"]) == expected


@pytest.mark.parametrize(
    ("pm", "expected"),
    [
        (PackageManager.APT, ["apt-cache", "show", "--", "htop"]),
        (PackageManager.DNF, ["dnf", "-q", "info", "htop"]),
        (PackageManager.PACMAN, ["pacman", "-Si", "htop"]),
        (PackageManager.ZYPPER, ["zypper", "info", "htop"]),
        (PackageManager.APK, ["apk", "search", "-v", "-x", "htop"]),
    ],
)
def test_info_argv(pm: PackageManager, expected: list[str]) -> None:
    assert get_adapter(pm).info_argv("htop") == expected


@pytest.mark.parametrize(
    ("pm", "expected"),
    [
        (PackageManager.APT, ["dpkg-query", "-W", "-f=${db:Status-Abbrev}", "--", "htop"]),
        (PackageManager.DNF, ["rpm", "-q", "--", "htop"]),
        (PackageManager.PACMAN, ["pacman", "-Q", "htop"]),
        (PackageManager.ZYPPER, ["rpm", "-q", "--", "htop"]),
        (PackageManager.APK, ["apk", "info", "-e", "htop"]),
    ],
)
def test_installed_check_argv(pm: PackageManager, expected: list[str]) -> None:
    assert get_adapter(pm).installed_check_argv("htop") == expected


def test_installed_check_ok_interpretation() -> None:
    # dpkg-query needs the 'ii' status abbreviation, not just exit 0.
    assert installed_check_ok("ii  htop", 0, PackageManager.APT)
    assert not installed_check_ok("un  htop", 0, PackageManager.APT)
    assert not installed_check_ok("rc  htop", 0, PackageManager.APT)
    assert not installed_check_ok("", 1, PackageManager.APT)
    # rpm/pacman/apk: exit 0 means installed.
    assert installed_check_ok("htop-3.3.0", 0, PackageManager.DNF)
    assert not installed_check_ok("", 1, PackageManager.PACMAN)
    assert installed_check_ok("", 0, PackageManager.APK)


def test_apt_mutating_env() -> None:
    assert get_adapter(PackageManager.APT).mutating_env["DEBIAN_FRONTEND"] == "noninteractive"
    assert get_adapter(PackageManager.DNF).mutating_env == {}
