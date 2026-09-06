#!/usr/bin/env python3
"""Run the Qt Quick Test suites in ``tests/qml``.

Qt Quick Test normally ships as a C++ ``qmltestrunner`` binary, which the
PySide6 wheels do not include; ``QUICK_TEST_MAIN`` is exposed to Python instead
via :func:`PySide6.QtQuickTest.QUICK_TEST_MAIN`. This script is the project's
equivalent of that runner.

Qt documents ``-platform offscreen`` as the way to run Quick tests without a
display, and this script defaults to it.

Usage:
    python tests/qml/run_qml_tests.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
QML_TEST_DIR = Path(__file__).resolve().parent

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Must be set before QGuiApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtQuickTest import QUICK_TEST_MAIN  # noqa: E402


def main() -> int:
    """Execute every ``tst_*.qml`` suite. Returns the number of failures."""
    argv = [
        "javris-qml-tests",
        "-input",
        str(QML_TEST_DIR),
        "-import",
        str(SRC_ROOT),
        *sys.argv[1:],
    ]
    return QUICK_TEST_MAIN("javris", argv)


if __name__ == "__main__":
    raise SystemExit(main())
