"""Local verifiers: check KB facts against THIS machine (ADR-0009 layer 1).

Every verifier is honest three-ways: True (verified), False (checked and
contradicted), None (cannot check here). The answer layer reports which.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from jarvis.core.fingerprint import read_os_release

_VERIFIED = "verified"
_CONTRADICTED = "contradicted"
_UNVERIFIABLE = "unverifiable-here"


def verify_fact(spec: Mapping[str, object] | None) -> tuple[str, str]:
    """Run a fact verifier. Returns (status, detail)."""
    if spec is None:
        return _UNVERIFIABLE, "documentation-sourced (no local check defined)"
    kind = str(spec.get("kind", ""))
    if kind == "file_equals":
        path = Path(str(spec.get("path", "")))
        try:
            actual = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            return _UNVERIFIABLE, f"cannot read {path}: {exc}"
        expected = str(spec.get("value", ""))
        if actual == expected:
            return _VERIFIED, f"{path} == {expected!r}"
        return _CONTRADICTED, f"{path} is {actual!r}, expected {expected!r}"
    if kind == "file_exists":
        path = Path(str(spec.get("path", "")))
        if path.exists():
            return _VERIFIED, f"{path} exists"
        return _CONTRADICTED, f"{path} does not exist on this machine"
    if kind == "os_release_field":
        field = str(spec.get("field", ""))
        try:
            values = read_os_release()
        except OSError:
            return _UNVERIFIABLE, "/etc/os-release not readable"
        if field in values:
            return _VERIFIED, f"os-release {field}={values[field]!r}"
        return _CONTRADICTED, f"os-release has no {field!r} field"
    if kind == "binary_present":
        name = str(spec.get("name", ""))
        if shutil.which(name):
            return _VERIFIED, f"{name} found on PATH"
        return _CONTRADICTED, f"{name} not on PATH here"
    if kind == "command_ok":
        argv = spec.get("argv", [])
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            return _UNVERIFIABLE, "invalid argv in verifier"
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                timeout=15,
                env=dict(os.environ),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _UNVERIFIABLE, f"command failed: {exc}"
        if proc.returncode == 0:
            return _VERIFIED, f"{' '.join(argv)} exited 0"
        return _CONTRADICTED, f"{' '.join(argv)} exited {proc.returncode}"
    return _UNVERIFIABLE, f"unknown verifier kind {kind!r}"
