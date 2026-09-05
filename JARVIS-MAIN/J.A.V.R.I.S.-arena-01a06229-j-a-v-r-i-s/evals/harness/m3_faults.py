#!/usr/bin/env python3
"""M3 fault-injection gate driver.

Runs the injected-fault pytest suite in-process and publishes the verdict as
JSON + a GitHub check annotation. The suite itself is the authority; this
driver exists so CI has a first-class artifact and sandboxed readers get the
number through api.github.com (see ADR-0008 §4).

Usage:
    python3 evals/harness/m3_faults.py --results evals/results/m3-faults.json
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

from m1_eval import annotate

VERDICT_RE = re.compile(r"FAULT SUITE VERDICT: (\d+) vectors checked, (\d+) escapes")


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS M3 fault-injection driver")
    parser.add_argument("--results", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_fault_injection.py", "-q", "-s"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=repo_root,
    )
    match = VERDICT_RE.search(proc.stdout + proc.stderr)
    vectors = int(match.group(1)) if match else 0
    escapes = int(match.group(2)) if match else -1
    pytest_ok = proc.returncode == 0

    summary = {
        "catalog": "m3-fault-injection",
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "pytest_exit": proc.returncode,
        "vectors_checked": vectors,
        "escapes": escapes,
        "gate": "0 escapes required",
        "passed": pytest_ok and escapes == 0,
    }
    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    verdict = "PASS" if summary["passed"] else "FAIL"
    print(
        f"== m3 fault gate: {verdict} — {vectors} vectors, {escapes} escapes -> {results_path} =="
    )
    if not pytest_ok:
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
    annotate(
        "notice" if summary["passed"] else "error",
        "m3-fault-gate",
        f"{vectors} vectors checked, {escapes} escapes (gate: 0)",
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
