"""SENSE stage tests: os-release parsing, init + package-manager detection."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from jarvis.core.fingerprint import (
    build_profile,
    detect_init_system,
    detect_package_manager,
    read_os_release,
)
from jarvis.system.models import PackageManager

_DEBIAN = (
    'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
    'NAME="Debian GNU/Linux"\nID=debian\nVERSION_ID="12"\n'
)
_UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\nPRETTY_NAME="Ubuntu 24.04 LTS"\n'
_FEDORA = (
    'NAME="Fedora Linux"\nID=fedora\nVERSION_ID=42\n'
    'PRETTY_NAME="Fedora Linux 42 (Container Image)"\n'
)
_ARCH = 'NAME="Arch Linux"\nID=arch\nBUILD_ID=rolling\nPRETTY_NAME="Arch Linux"\n'
_ALPINE = 'NAME="Alpine Linux"\nID=alpine\nVERSION_ID=3.21.0\nPRETTY_NAME="Alpine Linux v3.21"\n'
_OPENSUSE = (
    'NAME="openSUSE Leap"\nID="opensuse-leap"\nVERSION_ID="16.0"\n'
    'PRETTY_NAME="openSUSE Leap 16.0"\n'
)

OS_RELEASE_SAMPLES = {
    "debian": _DEBIAN,
    "ubuntu": _UBUNTU,
    "fedora": _FEDORA,
    "arch": _ARCH,
    "alpine": _ALPINE,
    "opensuse": _OPENSUSE,
}

EXPECTED_IDS = {
    "debian": "debian",
    "ubuntu": "ubuntu",
    "fedora": "fedora",
    "arch": "arch",
    "alpine": "alpine",
    "opensuse": "opensuse-leap",  # real Leap ID (quoting handled by the parser)
}


def _write_os_release(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "os-release"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.parametrize("distro", sorted(OS_RELEASE_SAMPLES))
def test_read_os_release_parses_samples(tmp_path: Path, distro: str) -> None:
    parsed = read_os_release(_write_os_release(tmp_path, OS_RELEASE_SAMPLES[distro]))
    assert parsed["ID"] == EXPECTED_IDS[distro]
    assert "PRETTY_NAME" in parsed


def test_read_os_release_strips_single_quotes(tmp_path: Path) -> None:
    parsed = read_os_release(_write_os_release(tmp_path, "ID='odd-distro'\n"))
    assert parsed["ID"] == "odd-distro"


def test_read_os_release_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    body = "# a comment\n\nID=debian\nNO_EQUALS_SIGN\n"
    parsed = read_os_release(_write_os_release(tmp_path, body))
    assert parsed == {"ID": "debian"}


def test_read_os_release_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_os_release(tmp_path / "does-not-exist")


def test_detect_init_system_via_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run" / "systemd" / "system"
    run_dir.mkdir(parents=True)
    assert detect_init_system(tmp_path / "missing-comm", run_dir=run_dir) == "systemd"


def test_detect_init_system_without_run_dir(tmp_path: Path) -> None:
    absent_run = tmp_path / "no" / "systemd"
    comm = tmp_path / "comm"
    comm.write_text("init\n", encoding="utf-8")
    assert detect_init_system(comm, run_dir=absent_run) == "other:init"
    comm.write_text("systemd\n", encoding="utf-8")
    assert detect_init_system(comm, run_dir=absent_run) == "systemd"
    missing = tmp_path / "missing"
    assert detect_init_system(missing, run_dir=absent_run) == "unknown"


@pytest.mark.parametrize(
    ("distro", "expected"),
    [
        ("debian", PackageManager.APT),
        ("ubuntu", PackageManager.APT),
        ("fedora", PackageManager.DNF),
        ("arch", PackageManager.PACMAN),
        ("opensuse-leap", PackageManager.ZYPPER),
        ("alpine", PackageManager.APK),
        ("gentoo", None),  # not in the map and no backend binary present
    ],
)
def test_detect_package_manager_respects_binary_presence(
    distro: str, expected: PackageManager | None
) -> None:
    def which(binary: str) -> str | None:
        known = {"apt-get", "dnf", "pacman", "zypper", "apk"}
        return f"/usr/bin/{binary}" if binary in known and distro != "gentoo" else None

    assert detect_package_manager(distro, which=which) == expected


def test_detect_package_manager_prefers_distro_mapping() -> None:
    # The distro mapping wins over probe order: zypper present -> zypper chosen
    # even though apk also exists.
    def which(binary: str) -> str | None:
        return "/usr/bin/x" if binary in {"zypper", "apk"} else None

    assert detect_package_manager("opensuse-leap", which=which) == PackageManager.ZYPPER


def test_detect_package_manager_falls_back_to_probe() -> None:
    def which(binary: str) -> str | None:
        return "/usr/bin/dnf" if binary == "dnf" else None

    assert detect_package_manager("some-unknown-distro", which=which) == PackageManager.DNF


def test_build_profile_end_to_end(tmp_path: Path) -> None:
    os_release = _write_os_release(tmp_path, OS_RELEASE_SAMPLES["fedora"])

    def which(binary: str) -> str | None:
        return "/usr/bin/dnf" if binary == "dnf" else None

    profile = build_profile(os_release_path=os_release, which=which)
    assert profile.distro_id == "fedora"
    assert profile.version_id == "42"
    assert profile.package_manager is PackageManager.DNF
    assert profile.is_root == (os.geteuid() == 0)
    assert isinstance(profile.init_system, str)


def test_build_profile_survives_missing_os_release(tmp_path: Path) -> None:
    profile = build_profile(os_release_path=tmp_path / "absent", which=lambda _: None)
    assert profile.distro_id == "unknown"
    assert profile.distro_name == "unknown"
    assert profile.package_manager is None


def test_shutil_which_still_available() -> None:  # guards accidental import removal
    assert callable(shutil.which)
