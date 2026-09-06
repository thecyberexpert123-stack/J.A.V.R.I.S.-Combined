"""ADR-0027: ``pass^k`` estimator + ``--runs K`` contract of the eval drivers.

The estimator is pinned against the τ-bench definition (arXiv:2406.12045 §3),
including the identity that makes the change backward compatible: at n=1,
pass^1 equals the plain pass rate the drivers always reported.

The driver tests execute the real harness scripts as subprocesses against a
two-case catalog: one deterministic pass, one case whose expectation is wrong
on purpose. They pin the JSON contract (old fields identical, new fields
additive), the keep-on-fail state-directory rule, and the fact that per-run
state isolation keeps the ADR-0014 breaker from tripping across runs (the
defect that motivated D4). ``TMPDIR`` is redirected into pytest's ``tmp_path``
so nothing is left behind on the host.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "evals" / "harness"
sys.path.insert(0, str(HARNESS))

from passk import (  # noqa: E402  (harness module, not a package)
    add_runs_argument,
    pass_hat_curve,
    pass_hat_k,
    positive_int,
    render_curve,
    suite_pass_hat,
)

# --- estimator ---------------------------------------------------------------


def test_pass_hat_1_is_the_plain_pass_rate() -> None:
    # n=1: pass^1 == passed/total — the pre-ADR summary numbers, exactly.
    assert suite_pass_hat([1, 1, 0, 1], runs=1, k=1) == pytest.approx(0.75)
    assert pass_hat_curve([1, 1, 1], runs=1) == {"1": 1.0}
    assert pass_hat_curve([0, 0], runs=1) == {"1": 0.0}


def test_pass_hat_k_matches_tau_bench_binomial_formula() -> None:
    # C(c,k)/C(n,k): 2 of 3 runs passed -> pass^1 = 2/3, pass^2 = 1/3, pass^3 = 0
    assert pass_hat_k(2, 3, 1) == pytest.approx(2 / 3)
    assert pass_hat_k(2, 3, 2) == pytest.approx(1 / 3)
    assert pass_hat_k(2, 3, 3) == 0.0
    # all runs pass -> 1.0 at every k; none pass -> 0.0 at every k
    assert all(pass_hat_k(5, 5, k) == 1.0 for k in range(1, 6))
    assert all(pass_hat_k(0, 5, k) == 0.0 for k in range(1, 6))


def test_pass_hat_is_monotone_non_increasing_in_k() -> None:
    curve = pass_hat_curve([4, 5, 3, 5, 2], runs=5)
    values = [curve[str(k)] for k in range(1, 6)]
    assert values == sorted(values, reverse=True)
    assert values[0] == pytest.approx(19 / 25, abs=1e-4)


def test_pass_hat_rejects_impossible_inputs() -> None:
    with pytest.raises(ValueError):
        pass_hat_k(1, 0, 1)
    with pytest.raises(ValueError):
        pass_hat_k(1, 3, 4)
    with pytest.raises(ValueError):
        pass_hat_k(4, 3, 1)
    assert suite_pass_hat([], runs=3, k=1) == 0.0  # empty suite claims nothing


def test_render_curve_and_runs_argument() -> None:
    assert render_curve({"1": 1.0, "2": 0.6667}) == "pass^1=1.0000 pass^2=0.6667"
    parser = argparse.ArgumentParser()
    add_runs_argument(parser)
    assert parser.parse_args([]).runs == 1
    assert parser.parse_args(["--runs", "4"]).runs == 4
    for bad in ("0", "-2", "x"):
        with pytest.raises(argparse.ArgumentTypeError):
            positive_int(bad)


# --- drivers -----------------------------------------------------------------


def _run_driver(script: str, argv: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["TMPDIR"] = str(tmp_path)
    env.pop("JARVIS_STATE_DIR", None)
    env.pop("GITHUB_ACTIONS", None)
    return subprocess.run(
        [sys.executable, str(HARNESS / script), *argv],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        cwd=ROOT,
    )


def _m2_two_case_catalog(tmp_path: Path) -> Path:
    full = json.loads((ROOT / "evals" / "catalog" / "m2.json").read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in full["cases"]}
    # `malformed-json-refused` records one breaker failure per run — the case
    # that tripped the breaker on the 4th invocation with a fixed state dir.
    good = by_id["malformed-json-refused"]
    bad = dict(by_id["engine-fast-path-no-llm"], id="wrong-on-purpose")
    bad["expect"] = {"status": "refused"}
    catalog = {"name": "m2-passk-test", "cases": [good, bad]}
    path = tmp_path / "m2-two.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


def test_m2_driver_default_runs_is_single_pass(tmp_path: Path) -> None:
    catalog = _m2_two_case_catalog(tmp_path)
    out = tmp_path / "m2-1.json"
    proc = _run_driver("m2_eval.py", ["--catalog", str(catalog), "--results", str(out)], tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr  # the wrong case fails
    assert "== JARVIS M2 planner eval ==" in proc.stdout  # unchanged header
    assert "run 1/1" not in proc.stdout  # no run tags at K=1
    assert "pass^" not in proc.stdout  # no curve line at K=1
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["runs"] == 1
    assert summary["pass_hat"] == {"1": 0.5}
    assert (summary["total"], summary["passed"], summary["failed"]) == (2, 1, 1)
    good, bad = summary["cases"]
    # pre-ADR per-case fields, unchanged meaning:
    assert {k: good[k] for k in ("id", "ok", "detail", "status", "llm_requests")} == {
        "id": "malformed-json-refused",
        "ok": True,
        "detail": "ok",
        "status": "refused",
        "llm_requests": 1,
    }
    assert bad["ok"] is False and "status 'dry_run' != 'refused'" in bad["detail"]
    # additive fields:
    assert (good["passes"], good["runs"], len(good["runs_detail"])) == (1, 1, 1)
    assert "state_dir" not in good["runs_detail"][0]  # passing run cleans up
    kept = Path(bad["runs_detail"][0]["state_dir"])  # failing run keeps evidence
    assert kept.is_dir() and (kept / "journal.db").exists()
    assert kept.parent == tmp_path
    assert str(kept) in proc.stdout


def test_m2_driver_runs_5_isolates_state_and_reports_curve(tmp_path: Path) -> None:
    catalog = _m2_two_case_catalog(tmp_path)
    out = tmp_path / "m2-5.json"
    proc = _run_driver(
        "m2_eval.py", ["--catalog", str(catalog), "--results", str(out), "--runs", "5"], tmp_path
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "(runs=5)" in proc.stdout
    assert "run 5/5" in proc.stdout
    summary = json.loads(out.read_text(encoding="utf-8"))
    good, bad = summary["cases"]
    # 5 refusals in a row: with a shared state dir the breaker (threshold 3)
    # would have opened on run 4 and turned refusals into BREAKER_OPEN failures.
    assert (good["passes"], good["runs"]) == (5, 5)
    assert all(r["status"] == "refused" for r in good["runs_detail"])
    assert (bad["passes"], bad["runs"]) == (0, 5)
    assert summary["pass_hat"] == {str(k): 0.5 for k in range(1, 6)}
    assert proc.stdout.rstrip().endswith(
        "== pass^1=0.5000 pass^2=0.5000 pass^3=0.5000 pass^4=0.5000 pass^5=0.5000 =="
    )
    # every failing run kept its own directory; every passing run removed its own
    kept = {r["state_dir"] for r in bad["runs_detail"]}
    assert len(kept) == 5 and all(Path(p).is_dir() for p in kept)
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("jarvis-m2-eval-")]
    assert len(leftovers) == 5


def test_m4_driver_runs_and_pinned_state_dir(tmp_path: Path) -> None:
    full = json.loads((ROOT / "evals" / "catalog" / "m4.json").read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in full["cases"]}
    catalog = {
        "name": "m4-passk-test",
        "cases": [by_id["refuse-nonsense"], dict(by_id["refuse-out-of-kb"], expect={"fact": "x"})],
    }
    path = tmp_path / "m4-two.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    out = tmp_path / "m4-2.json"
    proc = _run_driver(
        "m4_grounding.py", ["--catalog", str(path), "--results", str(out), "--runs", "2"], tmp_path
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "runs=2)" in proc.stdout
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["runs"] == 2
    assert summary["pass_hat"] == {"1": 0.5, "2": 0.5}
    assert (summary["cases_passed"], summary["cases_total"]) == (1, 2)
    good, bad = summary["cases"]
    assert good["ok"] and good["passes"] == 2 and "state_dir" not in good["runs_detail"][0]
    assert not bad["ok"] and Path(bad["runs_detail"][1]["state_dir"]).is_dir()
    assert "== pass^1=0.5000 pass^2=0.5000 ==" in proc.stdout

    # An explicit JARVIS_STATE_DIR is honoured for every run and never deleted.
    pinned = tmp_path / "pinned-state"
    pinned.mkdir()
    env = dict(os.environ)
    env["TMPDIR"] = str(tmp_path)
    env["JARVIS_STATE_DIR"] = str(pinned)
    env.pop("GITHUB_ACTIONS", None)
    proc2 = subprocess.run(
        [
            sys.executable,
            str(HARNESS / "m4_grounding.py"),
            "--catalog",
            str(path),
            "--results",
            str(tmp_path / "m4-pinned.json"),
            "--runs",
            "2",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        cwd=ROOT,
    )
    assert proc2.returncode == 1
    pinned_summary = json.loads((tmp_path / "m4-pinned.json").read_text(encoding="utf-8"))
    assert pinned.is_dir()
    assert all("state_dir" not in r for c in pinned_summary["cases"] for r in c["runs_detail"])


def test_drivers_reject_invalid_runs(tmp_path: Path) -> None:
    for script in ("m2_eval.py", "m4_grounding.py"):
        proc = _run_driver(
            script,
            ["--catalog", "unused.json", "--results", str(tmp_path / "x.json"), "--runs", "0"],
            tmp_path,
        )
        assert proc.returncode == 2
        assert "expected an integer >= 1" in proc.stderr
