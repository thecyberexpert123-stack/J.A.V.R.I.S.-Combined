#!/usr/bin/env python3
"""Unit test gate: run pytest and publish each failure as a CI annotation.

Job logs are unreachable from some environments (blob endpoints blocked);
annotations are the evidence channel of record for this project.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_eval import annotate


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        capture_output=True,
        text=True,
    )
    tail = (proc.stdout + "\n" + proc.stderr)[-4000:]
    print(tail)
    failed = re.findall(r"FAILED ([^\s]+)", proc.stdout)
    for entry in failed:
        test_id, _, reason = entry.partition(" - ")
        annotate(
            "error",
            f"pytest {test_id.split('::')[0]}",
            (reason or test_id)[:280],
        )
    annotate(
        "notice" if proc.returncode == 0 else "error",
        "pytest-gate",
        f"exit {proc.returncode}; {len(failed)} failure(s)",
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
