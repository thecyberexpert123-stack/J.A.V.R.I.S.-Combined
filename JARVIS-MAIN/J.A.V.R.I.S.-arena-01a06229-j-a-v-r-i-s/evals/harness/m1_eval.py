#!/usr/bin/env python3
"""M1 execution-eval driver.

Runs the task catalog against the local machine through the real CLI
(``python3 -m jarvis``) and checks every expectation. Designed to run inside
distro containers: stdlib only, no pip installs. Exit code 0 = all
expectations met; 1 = one or more failed (never silently).

Usage:
    python3 evals/harness/m1_eval.py \
        --catalog evals/catalog/m1.json \
        --distro-name debian12 \
        --results evals/results/debian12.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

TASK_TIMEOUT_S = 1800.0


def _gh_escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotate(kind: str, title: str, message: str) -> None:
    """Emit a GitHub check-run annotation when running inside Actions.

    Annotations are served through api.github.com, which makes eval evidence
    readable even where artifact/log blob hosts are unreachable (e.g. sandboxed
    environments). Outside Actions this is a no-op.
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    print(f"::{kind} title={_gh_escape(title)}::{_gh_escape(message)}", flush=True)


def run_cli(args: list[str], env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.run(
        ["python3", "-m", "jarvis", *args],
        capture_output=True,
        text=True,
        timeout=TASK_TIMEOUT_S,
        env=env,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "driver_error",
            "error": f"non-JSON CLI output: {proc.stdout[:400]!r} / {proc.stderr[:400]!r}",
        }
    payload["_exit"] = proc.returncode
    return payload


def check(expect: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    if "status" in expect and payload.get("status") != expect["status"]:
        problems.append(f"status: expected {expect['status']!r}, got {payload.get('status')!r}")
    if "playbook" in expect and payload.get("playbook") != expect["playbook"]:
        problems.append(
            f"playbook: expected {expect['playbook']!r}, got {payload.get('playbook')!r}"
        )
    if expect.get("verify_ok") is True:
        verification = payload.get("verification")
        if not isinstance(verification, dict) or verification.get("ok") is not True:
            problems.append(f"verification did not pass: {verification!r}")
    if "error_contains" in expect:
        error = str(payload.get("error", ""))
        if expect["error_contains"] not in error:
            problems.append(f"error {error!r} does not contain {expect['error_contains']!r}")
    expected_exit = {"succeeded": 0, "dry_run": 0}.get(str(expect.get("status")))
    if expected_exit is not None and payload.get("_exit") != expected_exit:
        problems.append(f"exit code: expected {expected_exit}, got {payload.get('_exit')}")
    return (not problems, "; ".join(problems) or "ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS M1 execution-eval driver")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--distro-name", required=True)
    parser.add_argument("--results", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    env.setdefault("JARVIS_STATE_DIR", "/tmp/jarvis-eval-state")

    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    task_ids: dict[str, str | None] = {}
    results: list[dict[str, Any]] = []
    failures = 0

    print(f"== JARVIS M1 eval on {args.distro_name} ==")
    for task in catalog["tasks"]:
        started = time.monotonic()
        if task["type"] == "do":
            payload = run_cli(["--json", "--yes", "do", *task["intent"]], env)
        elif task["type"] == "undo":
            target = task_ids.get(task["of"])
            if not target:
                payload = {
                    "status": "driver_error",
                    "error": f"referenced task {task['of']!r} produced no id",
                }
                payload["_exit"] = 1
            else:
                payload = run_cli(["--json", "--yes", "undo", target], env)
        else:
            raise SystemExit(f"unknown task type: {task['type']!r}")

        if payload.get("task_id"):
            task_ids[task["id"]] = str(payload["task_id"])

        ok, detail = check(task.get("expect", {}), payload)
        failures += 0 if ok else 1
        elapsed = time.monotonic() - started
        mark = "PASS" if ok else "FAIL"
        print(
            f"  [{mark}] {task['id']:<28} status={payload.get('status')!s:<10} "
            f"playbook={payload.get('playbook')!s:<18} {elapsed:6.1f}s"
        )
        if not ok:
            print(f"         -> {detail}")
            print(f"         -> error: {str(payload.get('error'))[:300]}")
            annotate(
                "error",
                f"eval {args.distro_name}:{task['id']}",
                f"{detail} | error: {str(payload.get('error'))[:200]}",
            )
        results.append(
            {
                "id": task["id"],
                "intent": task.get("intent"),
                "ok": ok,
                "detail": detail,
                "status": payload.get("status"),
                "playbook": payload.get("playbook"),
                "task_id": payload.get("task_id"),
                "error": str(payload.get("error", ""))[:500],
                "elapsed_s": round(elapsed, 1),
            }
        )

    summary = {
        "distro": args.distro_name,
        "catalog": catalog["name"],
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "total": len(results),
        "passed": len(results) - failures,
        "failed": failures,
        "tasks": results,
    }
    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"== summary: {summary['passed']}/{summary['total']} passed -> {results_path} ==")
    annotate(
        "notice",
        f"eval {args.distro_name}",
        f"{summary['passed']}/{summary['total']} tasks passed",
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
