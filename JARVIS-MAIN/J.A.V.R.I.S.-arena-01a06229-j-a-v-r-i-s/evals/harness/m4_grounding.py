#!/usr/bin/env python3
"""M4 grounding eval: cite-or-abstain gate (ADR-0009).

Runs `jarvis --json explain` per catalog case and enforces the acceptance
gate: **0 unverifiable claims** —
- every answered case must carry >= 1 source (citation always present),
- `machine: verified` is only accepted when the fact's local verifier exists
  and passes on this host (the CLI derives this itself; we re-derive here),
- refusals must refuse (no invented claims),
- with JARVIS_ONLINE_DOCS=1 (set in CI), every kernel-doc citation is
  additionally verified to exist in torvalds/linux upstream.

Usage:
    python3 evals/harness/m4_grounding.py --catalog evals/catalog/m4.json \
        --results evals/results/m4-grounding.json [--runs K]

``--runs K`` (ADR-0027) asks every case K times; a case passes only if all K
runs pass and the summary reports the ``pass^1..pass^K`` curve. Unless the
caller pins ``JARVIS_STATE_DIR``, each run gets a fresh temporary state
directory so the ADR-0014 breaker cannot carry state between runs. K=1
(default) is today's single pass with identical console output.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from m1_eval import annotate
from passk import add_runs_argument, pass_hat_curve, render_curve

TASK_TIMEOUT_S = 120.0


def run_explain(question: str, env: dict[str, str]) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        ["python3", "-m", "jarvis", "--json", "explain", *question.split()],
        capture_output=True,
        text=True,
        timeout=TASK_TIMEOUT_S,
        env=env,
        cwd=repo_root,
    )
    try:
        payload: dict[str, Any] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"status": "driver_error", "error": proc.stdout[:200] or proc.stderr[:200]}
    payload["_exit"] = proc.returncode
    return payload


def run_case(
    case: dict[str, Any], env: dict[str, str], pinned_state_dir: str | None
) -> dict[str, Any]:
    """One run of one case; expectation checks are unchanged from the single-run driver.

    Without a pinned JARVIS_STATE_DIR the run's temporary directory is removed
    on pass and kept (path in the record) on failure.
    """
    run_env = dict(env)
    temp_dir: str | None = None
    if pinned_state_dir is None:
        temp_dir = tempfile.mkdtemp(prefix=f"jarvis-m4-eval-{case['id']}-")
        run_env["JARVIS_STATE_DIR"] = temp_dir
    expect = case.get("expect", {})
    payload = run_explain(case["question"], run_env)
    problems: list[str] = []
    unverifiable = 0

    if expect.get("refused"):
        if payload.get("status") != "refused":
            problems.append(f"expected refusal, got {payload.get('status')!r}")
    else:
        if payload.get("status") not in ("answered", "answered-unverified-here"):
            problems.append(f"unexpected status {payload.get('status')!r}")
        if "fact" in expect and payload.get("fact_id") != expect["fact"]:
            problems.append(f"fact {payload.get('fact_id')!r} != {expect['fact']!r}")
        sources = payload.get("sources") or []
        if not sources:
            problems.append("ANSWER WITHOUT CITATION (unverifiable claim)")
            unverifiable += 1
        machine = (payload.get("machine") or {}).get("status")
        if "machine" in expect and machine != expect["machine"]:
            problems.append(f"machine {machine!r} != {expect['machine']!r}")
        if "status" in expect and payload.get("status") != expect["status"]:
            problems.append(f"status {payload.get('status')!r} != {expect['status']!r}")
        # verified is only acceptable when a real verification happened:
        if machine == "verified" and not str((payload.get("machine") or {}).get("detail", "")):
            problems.append("verified=true without verifier detail")
            unverifiable += 1

    ok = not problems
    record: dict[str, Any] = {
        "ok": ok,
        "detail": "; ".join(problems) or "ok",
        "status": payload.get("status"),
        "fact": payload.get("fact_id") or "-",
        "machine": (payload.get("machine") or {}).get("status", "-"),
        "unverifiable": unverifiable,
    }
    if temp_dir is not None:
        if ok:
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            record["state_dir"] = temp_dir
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS M4 grounding eval driver")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--results", required=True)
    add_runs_argument(parser)
    args = parser.parse_args()
    runs: int = args.runs

    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    # An explicit JARVIS_STATE_DIR is honoured and never deleted; otherwise each
    # run gets its own temporary directory (ADR-0027 D4).
    pinned_state_dir = env.get("JARVIS_STATE_DIR")
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))

    online = os.environ.get("JARVIS_ONLINE_DOCS", "0") == "1"
    results: list[dict[str, Any]] = []
    unverifiable_claims = 0
    failures = 0

    header = f"== JARVIS M4 grounding eval (online={online}) =="
    print(header if runs == 1 else header.replace(") ==", f", runs={runs}) =="))
    for case in catalog["cases"]:
        runs_detail: list[dict[str, Any]] = []
        for run_index in range(1, runs + 1):
            record = run_case(case, env, pinned_state_dir)
            record = {"run": run_index, **record}
            runs_detail.append(record)
            unverifiable_claims += record["unverifiable"]
            mark = "PASS" if record["ok"] else "FAIL"
            run_tag = "" if runs == 1 else f" run {run_index}/{runs}"
            print(
                f"  [{mark}] {case['id']:<28} {record['status']!s:<24} "
                f"{record['fact']:<28} machine={record['machine']}{run_tag}"
            )
            if not record["ok"]:
                print(f"         -> {record['detail']}")
                if "state_dir" in record:
                    print(f"         -> state kept: {record['state_dir']}")
                annotate("error", f"m4-eval {case['id']}{run_tag}", record["detail"])
        passes = sum(1 for r in runs_detail if r["ok"])
        ok = passes == runs
        failures += 0 if ok else 1
        first = runs_detail[0]
        results.append(
            {
                "id": case["id"],
                "ok": ok,
                "detail": "; ".join(r["detail"] for r in runs_detail if not r["ok"]) or "ok",
                "status": first["status"],
                "fact": first["fact"],
                "machine": first["machine"],
                "passes": passes,
                "runs": runs,
                "runs_detail": runs_detail,
            }
        )

    # online verification of kernel-doc citations (torvalds/linux upstream)
    upstream: list[dict[str, Any]] = []
    if online:
        from jarvis.knowledge.fetch import verify_kernel_doc
        from jarvis.knowledge.store import load_kb

        kb = load_kb()
        for fact in kb.facts:
            for source in fact.sources:
                if source.kind == "kernel-doc":
                    check = verify_kernel_doc(source.repo, source.ref)
                    upstream.append(
                        {
                            "fact": fact.id,
                            "ref": f"{source.repo}:{source.ref}",
                            "reachable": check.reachable,
                            "detail": check.detail,
                        }
                    )
                    if not check.reachable:
                        failures += 1
                        annotate(
                            "error",
                            f"m4-upstream {fact.id}",
                            f"{source.repo}:{source.ref} unreachable: {check.detail}",
                        )
        for entry in upstream:
            mark = "PASS" if entry["reachable"] else "FAIL"
            print(f"  [{mark}] upstream {entry['ref']} ({entry['detail']})")

    total = len(results)
    passed = (
        total - (failures - sum(0 if u["reachable"] else 1 for u in upstream))
        if online
        else total - failures
    )
    # keep the arithmetic explicit and simple:
    passed = sum(1 for r in results if r["ok"]) + sum(1 for u in upstream if u["reachable"])
    total_checks = len(results) + len(upstream)
    summary = {
        "catalog": catalog["name"],
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "online_mode": online,
        "runs": runs,
        "cases_passed": sum(1 for r in results if r["ok"]),
        "cases_total": len(results),
        "upstream_checks_passed": sum(1 for u in upstream if u["reachable"]),
        "upstream_checks_total": len(upstream),
        "unverifiable_claims": unverifiable_claims,
        "gate": "0 unverifiable claims required",
        "passed": unverifiable_claims == 0 and failures == 0,
        "pass_hat": pass_hat_curve([r["passes"] for r in results], runs),
        "cases": results,
        "upstream": upstream,
    }
    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"== summary: {passed}/{total_checks} checks passed, "
        f"{unverifiable_claims} unverifiable claims -> {results_path} =="
    )
    if runs > 1:
        print(f"== {render_curve(summary['pass_hat'])} ==")
    annotate(
        "notice" if summary["passed"] else "error",
        "m4-grounding",
        f"{passed}/{total_checks} checks; {unverifiable_claims} unverifiable claims "
        f"(gate: 0); upstream {summary['upstream_checks_passed']}/"
        f"{summary['upstream_checks_total']}",
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
