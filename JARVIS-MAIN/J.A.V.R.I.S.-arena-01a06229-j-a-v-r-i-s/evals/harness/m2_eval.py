#!/usr/bin/env python3
"""M2 planner eval: routing, proposal schema-validity, refusal honesty.

Runs the real CLI (``python3 -m jarvis ask --dry-run --json``) against a local
stub LLM server with scripted responses — deterministic, no network, no model
weights. Measures the schema-validity rate: every case that expects a plan
must produce a fully materialized deterministic plan (each step re-validated
by the playbook matchers), and every malformed/out-of-vocabulary proposal
must be refused.

Usage:
    python3 evals/harness/m2_eval.py \
        --catalog evals/catalog/m2.json \
        --results evals/results/m2-local.json [--runs K]

``--runs K`` (ADR-0027) executes every case K times against a fresh state
directory and a fresh stub server; a case passes only if all K runs pass and
the summary reports the ``pass^1..pass^K`` curve. K=1 (default) is today's
single pass with identical console output.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from m1_eval import annotate  # shared annotation helper
from passk import add_runs_argument, pass_hat_curve, render_curve

TASK_TIMEOUT_S = 300.0


class StubLLM:
    """Scripted stand-in for an OpenAI-compatible/Ollama backend."""

    def __init__(self) -> None:
        self._pending: list[tuple[int, object]] = []
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def do_GET(self) -> None:
                self._send(200, b"{}")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                outer.requests += 1
                if outer._pending:
                    status, body = outer._pending.pop(0)
                else:
                    status, body = 500, {"error": "no scripted response"}
                payload = (
                    json.dumps(body).encode("utf-8")
                    if isinstance(body, (dict, list))
                    else str(body).encode("utf-8")
                )
                self._send(status, payload)

            def _send(self, status: int, payload: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def enqueue(self, body: object, status: int = 200) -> None:
        self._pending.append((status, body))

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def run_case(case: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """One run of one case against a fresh stub server and a fresh state dir.

    The state directory is removed when the run passes and kept (path in the
    record) when it fails, so the journal remains available as evidence. A
    fresh directory per run is what keeps the ADR-0014 provider breaker from
    accumulating the refusal cases' deliberate failures across runs.
    """
    stub = StubLLM()
    state_dir = tempfile.mkdtemp(prefix=f"jarvis-m2-eval-{case['id']}-")
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root / "src")
        env["JARVIS_STATE_DIR"] = state_dir
        env["JARVIS_REMOTE_LLM"] = "0"
        env["JARVIS_LOCAL_MODEL"] = "eval-model"
        if case.get("no_local"):
            env["OLLAMA_HOST"] = "127.0.0.1:1"
        else:
            env["OLLAMA_HOST"] = stub.url
        for response in case.get("stub_responses", []):
            stub.enqueue(response, status=case.get("stub_status", 200))

        started = time.monotonic()
        try:
            proc = subprocess.run(
                ["python3", "-m", "jarvis", "--json", "ask", "--dry-run", *case["request"].split()],
                capture_output=True,
                text=True,
                timeout=TASK_TIMEOUT_S,
                env=env,
                cwd=repo_root,
            )
        except subprocess.TimeoutExpired:
            payload: dict[str, Any] = {
                "status": "driver_error",
                "error": f"CLI exceeded {TASK_TIMEOUT_S:.0f}s",
            }
        else:
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = {"status": "driver_error", "error": proc.stdout[:200]}
        elapsed = time.monotonic() - started

        expect = case.get("expect", {})
        problems: list[str] = []
        if "status" in expect and payload.get("status") != expect["status"]:
            problems.append(f"status {payload.get('status')!r} != {expect['status']!r}")
        if "playbook" in expect and payload.get("playbook") != expect["playbook"]:
            problems.append(f"playbook {payload.get('playbook')!r} != {expect['playbook']!r}")
        if "error_contains" in expect and expect["error_contains"] not in str(
            payload.get("error", "")
        ):
            problems.append(f"error missing {expect['error_contains']!r}")
        if "llm_requests" in expect and stub.requests != expect["llm_requests"]:
            problems.append(f"llm requests {stub.requests} != {expect['llm_requests']}")
        if "step_count" in expect and len(payload.get("steps", [])) != expect["step_count"]:
            problems.append(f"step count {len(payload.get('steps', []))} != {expect['step_count']}")
        if "undo_status" in expect:
            undo = payload.get("undo") or {}
            if undo.get("status") != expect["undo_status"]:
                problems.append(f"undo {undo.get('status')!r} != {expect['undo_status']!r}")

        ok = not problems
        error = payload.get("error")
        record: dict[str, Any] = {
            "ok": ok,
            "detail": "; ".join(problems) or "ok",
            "status": payload.get("status"),
            "llm_requests": stub.requests,
            "error": str(error)[:200] if error is not None else None,
            "elapsed_s": round(elapsed, 2),
        }
        if ok:
            shutil.rmtree(state_dir, ignore_errors=True)
        else:
            record["state_dir"] = state_dir
        return record
    finally:
        stub.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS M2 planner eval driver")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--results", required=True)
    add_runs_argument(parser)
    args = parser.parse_args()
    runs: int = args.runs

    repo_root = Path(__file__).resolve().parents[2]
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))

    results: list[dict[str, Any]] = []
    failures = 0
    print(
        "== JARVIS M2 planner eval =="
        if runs == 1
        else f"== JARVIS M2 planner eval (runs={runs}) =="
    )
    for case in catalog["cases"]:
        runs_detail: list[dict[str, Any]] = []
        for run_index in range(1, runs + 1):
            record = run_case(case, repo_root)
            record = {"run": run_index, **record}
            runs_detail.append(record)
            mark = "PASS" if record["ok"] else "FAIL"
            run_tag = "" if runs == 1 else f" run {run_index}/{runs}"
            print(
                f"  [{mark}] {case['id']:<32} status={record['status']!s:<9} "
                f"llm_reqs={record['llm_requests']} {record['elapsed_s']:5.1f}s{run_tag}"
            )
            if not record["ok"]:
                print(f"         -> {record['detail']}")
                print(f"         -> error: {record['error']!s}")
                print(f"         -> state kept: {record['state_dir']}")
                annotate("error", f"m2-eval {case['id']}{run_tag}", record["detail"])
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
                "llm_requests": first["llm_requests"],
                "passes": passes,
                "runs": runs,
                "runs_detail": runs_detail,
            }
        )

    total = len(results)
    passed = total - failures
    curve = pass_hat_curve([r["passes"] for r in results], runs)
    summary = {
        "catalog": catalog["name"],
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "runs": runs,
        "total": total,
        "passed": passed,
        "failed": failures,
        "schema_valid_plans": sum(
            1
            for r in results
            if all(run["status"] in ("succeeded", "dry_run") for run in r["runs_detail"])
        ),
        "pass_hat": curve,
        "cases": results,
    }
    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"== summary: {passed}/{total} passed -> {results_path} ==")
    if runs > 1:
        print(f"== {render_curve(curve)} ==")
    annotate("notice", "m2-eval", f"{passed}/{total} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
