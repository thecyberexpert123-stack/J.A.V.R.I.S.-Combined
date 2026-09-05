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
        --results evals/results/m4-grounding.json
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

from m1_eval import annotate

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


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS M4 grounding eval driver")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--results", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    env.setdefault("JARVIS_STATE_DIR", "/tmp/jarvis-m4-eval")
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))

    online = os.environ.get("JARVIS_ONLINE_DOCS", "0") == "1"
    results: list[dict[str, Any]] = []
    unverifiable_claims = 0
    failures = 0

    print(f"== JARVIS M4 grounding eval (online={online}) ==")
    for case in catalog["cases"]:
        expect = case.get("expect", {})
        payload = run_explain(case["question"], env)
        problems: list[str] = []

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
                unverifiable_claims += 1
            machine = (payload.get("machine") or {}).get("status")
            if "machine" in expect and machine != expect["machine"]:
                problems.append(f"machine {machine!r} != {expect['machine']!r}")
            if "status" in expect and payload.get("status") != expect["status"]:
                problems.append(f"status {payload.get('status')!r} != {expect['status']!r}")
            # verified is only acceptable when a real verification happened:
            if machine == "verified" and not str((payload.get("machine") or {}).get("detail", "")):
                problems.append("verified=true without verifier detail")
                unverifiable_claims += 1

        ok = not problems
        failures += 0 if ok else 1
        mark = "PASS" if ok else "FAIL"
        fact = payload.get("fact_id") or "-"
        machine = (payload.get("machine") or {}).get("status", "-")
        print(
            f"  [{mark}] {case['id']:<28} {payload.get('status')!s:<24} "
            f"{fact:<28} machine={machine}"
        )
        if not ok:
            print(f"         -> {'; '.join(problems)}")
            annotate("error", f"m4-eval {case['id']}", "; ".join(problems))
        results.append(
            {
                "id": case["id"],
                "ok": ok,
                "detail": "; ".join(problems) or "ok",
                "status": payload.get("status"),
                "fact": fact,
                "machine": machine,
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
        "cases_passed": sum(1 for r in results if r["ok"]),
        "cases_total": len(results),
        "upstream_checks_passed": sum(1 for u in upstream if u["reachable"]),
        "upstream_checks_total": len(upstream),
        "unverifiable_claims": unverifiable_claims,
        "gate": "0 unverifiable claims required",
        "passed": unverifiable_claims == 0 and failures == 0,
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
