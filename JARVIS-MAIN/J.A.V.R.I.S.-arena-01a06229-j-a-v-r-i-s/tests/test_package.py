"""Packaging-integrity smoke tests (M0).

Purpose: guarantee that the distribution metadata and the import package
never drift apart - the exact failure class that breaks release tooling
silently. These tests run in CI on Python 3.10-3.12.
"""

import re

import jarvis

DIST_NAME = "jarvis-agent"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_is_semver() -> None:
    assert SEMVER_RE.match(jarvis.__version__), (
        f"version {jarvis.__version__!r} is not MAJOR.MINOR.PATCH"
    )


def test_distribution_metadata_matches_package() -> None:
    from importlib import metadata

    dist_version = metadata.version(DIST_NAME)
    assert dist_version == jarvis.__version__, (
        f"distribution {DIST_NAME} reports {dist_version!r} "
        f"but package reports {jarvis.__version__!r}"
    )


def test_public_api_is_minimal() -> None:
    # M0 contract: the package root exposes only its version.
    # Expanded deliberately as modules land (M1+), never accidentally.
    assert jarvis.__all__ == ["__version__"]
