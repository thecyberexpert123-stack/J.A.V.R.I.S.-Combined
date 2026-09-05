"""SENSE stage: fingerprint the machine from primary sources.

Everything here reads ground truth from the system itself (`/etc/os-release`,
`/proc`, PATH lookups). Nothing is guessed from the distro name alone: a
distro-id mapping is only accepted when the corresponding binary actually
exists on PATH.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from jarvis.system.models import MachineProfile, PackageManager

OS_RELEASE_PATH = Path("/etc/os-release")

# Preferred backend per distro family; only used when the binary is present.
_DISTRO_PM: dict[str, PackageManager] = {
    "debian": PackageManager.APT,
    "ubuntu": PackageManager.APT,
    "linuxmint": PackageManager.APT,
    "fedora": PackageManager.DNF,
    "rhel": PackageManager.DNF,
    "centos": PackageManager.DNF,
    "rocky": PackageManager.DNF,
    "almalinux": PackageManager.DNF,
    "arch": PackageManager.PACMAN,
    "manjaro": PackageManager.PACMAN,
    "opensuse-leap": PackageManager.ZYPPER,
    "opensuse-tumbleweed": PackageManager.ZYPPER,
    "opensuse": PackageManager.ZYPPER,
    "sles": PackageManager.ZYPPER,
    "alpine": PackageManager.APK,
    "postmarketos": PackageManager.APK,
}

_PM_BINARY: dict[PackageManager, str] = {
    PackageManager.APT: "apt-get",
    PackageManager.DNF: "dnf",
    PackageManager.PACMAN: "pacman",
    PackageManager.ZYPPER: "zypper",
    PackageManager.APK: "apk",
}

# Fallback probe order when the distro id is unknown to the map above.
_PM_PROBE_ORDER: tuple[PackageManager, ...] = (
    PackageManager.APT,
    PackageManager.DNF,
    PackageManager.PACMAN,
    PackageManager.ZYPPER,
    PackageManager.APK,
)


def read_os_release(path: Path = OS_RELEASE_PATH) -> dict[str, str]:
    """Parse an os-release file (man 5 os-release) into a dict.

    Handles the shell-ish quoting the format allows. Raises FileNotFoundError
    if the file does not exist (e.g. exotic minimal containers).
    """
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def detect_init_system(
    proc_comm_path: Path = Path("/proc/1/comm"),
    run_dir: Path = Path("/run/systemd/system"),
) -> str:
    """Best-effort init detection; honest 'unknown' when undeterminable."""
    if run_dir.is_dir():
        return "systemd"
    try:
        comm = proc_comm_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "unknown"
    if comm == "systemd":
        return "systemd"
    if comm:
        return f"other:{comm}"
    return "unknown"


def detect_package_manager(
    distro_id: str,
    which: object | None = None,
) -> PackageManager | None:
    """Resolve the package-manager backend for this machine.

    The distro-id mapping is only trusted when the backend binary actually
    exists; otherwise the probe order decides. Returns None when no supported
    backend exists on PATH (reported honestly to the user, never guessed).
    `which` is a shutil.which-compatible callable (injectable for tests).
    """
    lookup = which if which is not None else shutil.which
    assert callable(lookup)

    preferred = _DISTRO_PM.get(distro_id.lower().strip())
    candidates: list[PackageManager] = []
    if preferred is not None:
        candidates.append(preferred)
    candidates.extend(pm for pm in _PM_PROBE_ORDER if pm not in candidates)

    for pm in candidates:
        if lookup(_PM_BINARY[pm]):
            return pm
    return None


def build_profile(
    os_release_path: Path = OS_RELEASE_PATH,
    which: object | None = None,
) -> MachineProfile:
    """Collect the machine fingerprint (pipeline stage SENSE)."""
    lookup = which if which is not None else shutil.which
    assert callable(lookup)

    try:
        osr = read_os_release(os_release_path)
    except FileNotFoundError:
        osr = {}

    distro_id = osr.get("ID", "").lower().strip()
    pm = detect_package_manager(distro_id, which=lookup)

    return MachineProfile(
        distro_id=distro_id or "unknown",
        distro_name=osr.get("PRETTY_NAME") or osr.get("NAME") or "unknown",
        version_id=osr.get("VERSION_ID") or None,
        init_system=detect_init_system(),
        package_manager=pm,
        session_type=os.environ.get("XDG_SESSION_TYPE") or None,
        is_root=os.geteuid() == 0,  # POSIX only; this project targets Linux
        sudo_available=bool(lookup("sudo")),
        python_version=sys.version.split()[0],
        extra={"ID_LIKE": osr["ID_LIKE"]} if osr.get("ID_LIKE") else {},
    )
