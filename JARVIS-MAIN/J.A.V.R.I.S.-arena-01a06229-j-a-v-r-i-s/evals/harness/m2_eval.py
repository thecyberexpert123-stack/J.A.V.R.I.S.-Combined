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
        --results evals/results/m2-local.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from m1_eval import annotate  # shared annotation helper

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


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS M2 planner eval driver")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--results", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))

    results: list[dict[str, Any]] = []
    failures = 0
    print("== JARVIS M2 planner eval ==")
    for case in catalog["cases"]:
        stub = StubLLM()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root / "src")
        env["JARVIS_STATE_DIR"] = f"/tmp/jarvis-m2-eval-{case['id']}"
        env["JARVIS_REMOTE_LLM"] = "0"
        env["JARVIS_LOCAL_MODEL"] = "eval-model"
        if case.get("no_local"):
            env["OLLAMA_HOST"] = "127.0.0.1:1"
        else:
            env["OLLAMA_HOST"] = stub.url
        for response in case.get("stub_responses", []):
            stub.enqueue(response, status=case.get("stub_status", 200))

        started = time.monotonic()
        proc = subprocess.run(
            ["python3", "-m", "jarvis", "--json", "ask", "--dry-run", *case["request"].split()],
            capture_output=True,
            text=True,
            timeout=TASK_TIMEOUT_S,
            env=env,
            cwd=repo_root,
        )
        elapsed = time.monotonic() - started
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"status": "driver_error", "error": proc.stdout[:200]}

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
        failures += 0 if ok else 1
        mark = "PASS" if ok else "FAIL"
        print(
            f"  [{mark}] {case['id']:<32} status={payload.get('status')!s:<9} "
            f"llm_reqs={stub.requests} {elapsed:5.1f}s"
        )
        if not ok:
            detail = "; ".join(problems)
            print(f"         -> {detail}")
            print(f"         -> error: {str(payload.get('error'))[:200]}")
            annotate("error", f"m2-eval {case['id']}", detail)
        results.append(
            {
                "id": case["id"],
                "ok": ok,
                "detail": "; ".join(problems) or "ok",
                "status": payload.get("status"),
                "llm_requests": stub.requests,
            }
        )
        stub.close()

    total = len(results)
    passed = total - failures
    summary = {
        "catalog": catalog["name"],
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "total": total,
        "passed": passed,
        "failed": failures,
        "schema_valid_plans": sum(1 for r in results if r["status"] in ("succeeded", "dry_run")),
        "cases": results,
    }
    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"== summary: {passed}/{total} passed -> {results_path} ==")
    annotate("notice", "m2-eval", f"{passed}/{total} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
