#!/usr/bin/env bash
#
# The project's quality gate. Every check must pass before a change is
# considered complete. Run from the repository root:
#
#     ./tools/check.sh
#
# In a minimal container without libGL/libEGL/libdbus/libxkbcommon, set
# JAVRIS_GL_STUBS=1 to generate and use the sandbox stub libraries first.
# See tools/sandbox_gl_stubs.py for what that is and why it exists.

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
    PYTHON="python3"
fi

# pyside6-qmllint lives next to the interpreter in a virtualenv, or on PATH.
QMLLINT="$(dirname "${PYTHON}")/pyside6-qmllint"
if [[ ! -x "${QMLLINT}" ]]; then
    QMLLINT="pyside6-qmllint"
fi

if [[ "${JAVRIS_GL_STUBS:-0}" == "1" ]]; then
    echo "==> Generating sandbox GL stubs (development containers only)"
    "${PYTHON}" tools/sandbox_gl_stubs.py --output build/glstubs >/dev/null
    export LD_LIBRARY_PATH="${PWD}/build/glstubs:${LD_LIBRARY_PATH:-}"
fi

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-software}"

run() {
    echo
    echo "==> $1"
    shift
    "$@"
}

run "ruff (lint)"          "${PYTHON}" -m ruff check src tests tools
run "ruff (format)"        "${PYTHON}" -m ruff format --check src tests tools
run "mypy (strict)"        "${PYTHON}" -m mypy
run "pytest (unit)"        "${PYTHON}" -m pytest
# shellcheck disable=SC2046  # word splitting of the file list is intended
run "qmllint"              "${QMLLINT}" -I src $(find src -name '*.qml' | sort)
run "Qt Quick Test (QML)"  "${PYTHON}" tests/qml/run_qml_tests.py
run "headless render"      "${PYTHON}" tools/headless_render.py --output build/hud.png

echo
echo "All quality gates passed."
