#!/usr/bin/env python3
"""M5 GUI eval driver: end-to-end tasks through the real CLI on a real X stack.

Modes:
  --xvfb     start Xvfb :99 + i3, then run every task in the catalog
             (needs: Xvfb, i3-wm, xterm, xdotool, wmctrl, scrot).
  --headless no display: run only the catalog's headless_subset (honesty checks).

Gate: >=98% within the catalog (15 tasks => 0 failures allowed).

Usage:
  python3 evals/harness/m5_gui.py --catalog evals/catalog/m5.json \
      --results evals/results/m5-gui-ci.json [--xvfb | --headless]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from m1_eval import annotate

TASK_TIMEOUT_S = 60.0


# -- expectation engine ---------------------------------------------------------


def _dig(payload: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    node: Any = payload
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _poll_window(title: str, env: dict[str, str], *, want: bool, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["wmctrl", "-l"], capture_output=True, text=True, env=env, timeout=10
        )
        found = title in result.stdout
        if found == want:
            return True
        time.sleep(0.4)
    return False


def _poll_file_contains(path: str, needle: str, env: dict[str, str], seconds: float) -> bool:
    del env
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if needle in Path(path).read_text(encoding="utf-8"):
                return True
        except OSError:
            pass
        time.sleep(0.4)
    return False


def run_task(task: dict[str, Any], env: dict[str, str], repo_root: Path) -> tuple[bool, str]:
    expect = task.get("expect", {})
    use_yes = not task.get("no_yes", False)
    argv = ["python3", "-m", "jarvis", "--json"]
    if use_yes:
        argv.append("--yes")
    argv += task["run"]
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=TASK_TIMEOUT_S,
        env=env,
        cwd=repo_root,
    )
    problems: list[str] = []
    if "exit" in expect and proc.returncode != expect["exit"]:
        problems.append(
            f"exit {proc.returncode} != {expect['exit']} (stderr: {proc.stderr.strip()[:120]})"
        )
    if "stderr_contains" in expect and expect["stderr_contains"] not in proc.stderr:
        problems.append(f"stderr missing {expect['stderr_contains']!r}")
    payload: dict[str, Any] = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            problems.append("stdout is not JSON")

    if "json_path" in expect:
        found, value = _dig(payload, expect["json_path"])
        if not found:
            problems.append(f"json path {expect['json_path']} missing")
        elif "equals" in expect and value != expect["equals"]:
            problems.append(f"{expect['json_path']}={value!r} != {expect['equals']!r}")
        elif expect.get("nonempty") and not str(value):
            problems.append(f"{expect['json_path']} is empty")

    if "poll_window_contains" in expect and not _poll_window(
        expect["poll_window_contains"],
        env,
        want=True,
        seconds=float(expect.get("poll_seconds", 15)),
    ):
        problems.append(f"window {expect['poll_window_contains']!r} never appeared")
    if "poll_window_absent" in expect and not _poll_window(
        expect["poll_window_absent"],
        env,
        want=False,
        seconds=float(expect.get("poll_seconds", 10)),
    ):
        problems.append(f"window {expect['poll_window_absent']!r} still present")
    if "file_contains" in expect and not _poll_file_contains(
        expect["file_contains"],
        expect["value"],
        env,
        float(expect.get("poll_seconds", 10)),
    ):
        problems.append(f"{expect['file_contains']} never contained {expect['value']!r}")
    if "file_starts" in expect:
        target = Path(expect["file_starts"])
        ok = target.exists() and target.stat().st_size > 0
        if ok and "magic" in expect:
            ok = target.read_bytes()[:4] == expect["magic"].encode("latin-1")
        if not ok:
            problems.append(f"{target} missing/empty/wrong magic")
    return (not problems), ("; ".join(problems) or "ok")


# -- X stack management -----------------------------------------------------------


def _wait_for(path: Path, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.2)
    return False


def _read_tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no output captured)"


def start_x_stack(env: dict[str, str]) -> list[subprocess.Popen[bytes]]:
    procs: list[subprocess.Popen[bytes]] = []
    xdisplay = ":99"
    xlock = Path("/tmp/.X99-lock")
    if xlock.exists():
        xlock.unlink()
    xvfb_log = Path("/tmp/jarvis-m5-xvfb.log")
    i3_log = Path("/tmp/jarvis-m5-i3.log")
    xvfb = subprocess.Popen(
        ["Xvfb", xdisplay, "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=xvfb_log.open("w"),
    )
    procs.append(xvfb)
    env["DISPLAY"] = xdisplay
    if not _wait_for(Path("/tmp/.X11-unix/X99"), 15):
        detail = f"Xvfb socket never appeared; Xvfb alive={xvfb.poll() is None};\n" + _read_tail(
            xvfb_log
        )
        annotate("error", "m5-gui-startup", detail[:400])
        raise RuntimeError(detail)

    conf = Path("/tmp/jarvis-m5-i3.conf")
    conf.write_text(
        "font pango:monospace 10\n"
        "default_orientation horizontal\n"
        "focus_follows_mouse no\n"
        "bar { mode invisible }\n",
        encoding="utf-8",
    )
    i3 = subprocess.Popen(
        ["i3", "-c", str(conf)],
        stdout=subprocess.DEVNULL,
        stderr=i3_log.open("w"),
        env=env,
    )
    procs.append(i3)
    socket_path = ""
    probe_rc = -1
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not socket_path:
        probe = subprocess.run(["i3", "--get-socketpath"], capture_output=True, text=True, env=env)
        probe_rc = probe.returncode
        if probe.returncode == 0 and probe.stdout.strip():
            socket_path = probe.stdout.strip()
        else:
            time.sleep(0.3)
    if not socket_path:
        detail = (
            f"i3 IPC socket never appeared; i3 alive={i3.poll() is None}; "
            f"get-socketpath rc={probe_rc};\n" + _read_tail(i3_log)
        )
        annotate("error", "m5-gui-startup", detail[:400])
        raise RuntimeError(detail)
    env["I3SOCK"] = socket_path
    time.sleep(1.0)  # let i3 finish its first pass
    annotate(
        "notice",
        "m5-gui-startup",
        f"Xvfb+{Path(socket_path).name} up; Xvfb pid={xvfb.pid}, i3 pid={i3.pid}",
    )
    return procs


def stop_x_stack(procs: list[subprocess.Popen[bytes]]) -> None:
    for proc in reversed(procs):
        proc.terminate()
    for proc in reversed(procs):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# -- main ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS M5 GUI eval driver")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--results", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--xvfb", action="store_true", help="drive a fresh Xvfb+i3 stack")
    mode.add_argument("--headless", action="store_true", help="verify honest headless refusal")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    env.setdefault("JARVIS_STATE_DIR", "/tmp/jarvis-m5-eval")
    Path(env["JARVIS_STATE_DIR"]).mkdir(parents=True, exist_ok=True)

    if args.headless:
        tasks = catalog.get("headless_subset", [])
        label = "headless-honesty"
    else:
        for binary in ("Xvfb", "i3", "xterm", "xdotool", "wmctrl", "scrot"):
            if shutil.which(binary) is None:
                print(f"missing required binary for --xvfb mode: {binary}")
                annotate("error", "m5-gui", f"missing binary: {binary}")
                return 1
        tasks = catalog["tasks"]
        label = "xvfb-i3"

    failures = 0
    details: list[dict[str, Any]] = []
    procs: list[subprocess.Popen[bytes]] = []
    print(f"== JARVIS M5 GUI eval ({label}) — {len(tasks)} task(s) ==")
    try:
        if args.xvfb:
            procs = start_x_stack(env)
        for task in tasks:
            try:
                ok, detail = run_task(task, env, repo_root)
            except Exception as exc:
                ok, detail = False, f"harness exception: {exc.__class__.__name__}: {exc}"
            failures += 0 if ok else 1
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {task['id']:<38} {detail}")
            if not ok:
                annotate("error", f"m5-gui {task['id']}", detail)
            details.append({"id": task["id"], "ok": ok, "detail": detail})
    finally:
        if procs:
            stop_x_stack(procs)

    passed_gate = failures <= len(tasks) - int(-(-len(tasks) * 98 // 100))
    # >=98% of N: allowed failures = N - ceil(N*0.98); for N=15 => 0
    summary = {
        "catalog": catalog["name"],
        "mode": label,
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tasks_passed": len(tasks) - failures,
        "tasks_total": len(tasks),
        "failures": failures,
        "gate": ">=98% within catalog",
        "passed": failures == 0 if len(tasks) == 15 else passed_gate,
        "tasks": details,
    }
    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"GUI SUITE VERDICT: {summary['tasks_passed']}/{len(tasks)} tasks, "
        f"{failures} failures (gate: >=98%)"
    )
    annotate(
        "notice" if summary["passed"] else "error",
        "m5-gui",
        f"{summary['tasks_passed']}/{len(tasks)} GUI tasks ({label}); "
        f"gate >=98% {'met' if summary['passed'] else 'MISSED'}",
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
