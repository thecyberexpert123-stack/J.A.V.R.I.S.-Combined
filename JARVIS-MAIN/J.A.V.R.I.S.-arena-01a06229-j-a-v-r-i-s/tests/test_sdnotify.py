"""ADR-0029 D1/D2/D3: sd_notify client, supervised doorway, confined brief unit.

The systemd side is simulated with a bound abstract ``AF_UNIX`` datagram
socket — exactly what ``$NOTIFY_SOCKET`` names on a real system — so every
assertion here is about bytes systemd would actually receive. What cannot be
tested in this sandbox (a live user service manager restarting the unit) is
listed in the ADR as owner-machine verification.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.brief.install import HARDENING_DIRECTIVES, install_timer, service_content
from jarvis.cli.serve import WATCHDOG_SEC, build_server, unit_content
from jarvis.safety.tiers import SafetyRefusal
from jarvis.system import sdnotify

# --------------------------------------------------------------------------
# a fake systemd: abstract datagram socket, drained on demand
# --------------------------------------------------------------------------


class FakeSystemd:
    def __init__(self) -> None:
        self.name = f"@jarvis-test-notify-{os.getpid()}-{id(self)}"
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind("\0" + self.name[1:])
        self.sock.settimeout(2.0)

    def messages(self, expect: int) -> list[str]:
        out: list[str] = []
        for _ in range(expect):
            out.append(self.sock.recv(4096).decode("utf-8"))
        return out

    def drain(self) -> list[str]:
        self.sock.settimeout(0.2)
        out: list[str] = []
        try:
            while True:
                out.append(self.sock.recv(4096).decode("utf-8"))
        except TimeoutError:
            pass
        finally:
            self.sock.settimeout(2.0)
        return out

    def close(self) -> None:
        self.sock.close()


@pytest.fixture()
def systemd() -> Iterator[FakeSystemd]:
    fake = FakeSystemd()
    yield fake
    fake.close()


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


# --------------------------------------------------------------------------
# D1 — the client
# --------------------------------------------------------------------------


def test_inert_without_notify_socket() -> None:
    env: dict[str, str] = {"PATH": "/usr/bin"}
    client = sdnotify.from_environment(env, pid=1234)
    assert not client.enabled and not client.watchdog_enabled
    client.ready("x")
    client.status("y")
    assert client.watchdog() is False
    client.stopping()  # all no-ops, nothing raised
    assert env == {"PATH": "/usr/bin"}


def test_environment_is_consumed_so_children_never_inherit_it(systemd: FakeSystemd) -> None:
    env = {
        "NOTIFY_SOCKET": systemd.name,
        "WATCHDOG_USEC": "30000000",
        "WATCHDOG_PID": "4242",
        "HOME": "/home/x",
    }
    client = sdnotify.from_environment(env, pid=4242)
    assert client.enabled and client.watchdog_enabled
    assert env == {"HOME": "/home/x"}  # the three variables are gone


def test_real_children_do_not_inherit_the_notify_environment(
    monkeypatch: pytest.MonkeyPatch, systemd: FakeSystemd
) -> None:
    """The Runner copies os.environ into every playbook child (execution/runner.py)."""
    monkeypatch.setenv("NOTIFY_SOCKET", systemd.name)
    monkeypatch.setenv("WATCHDOG_USEC", "30000000")
    monkeypatch.setenv("WATCHDOG_PID", str(os.getpid()))
    client = sdnotify.from_environment()  # the doorway's call: default mapping = os.environ
    assert client.watchdog_enabled
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; print(sorted(k for k in os.environ if k[:8] in ('NOTIFY_S', 'WATCHDOG')))",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ),  # exactly what execution/runner.py does
    )
    assert probe.stdout.strip() == "[]"


def test_ready_status_and_stopping_reach_the_socket(systemd: FakeSystemd) -> None:
    client = sdnotify.from_environment({"NOTIFY_SOCKET": systemd.name}, pid=1)
    client.ready("listening on 127.0.0.1:8777; 0 request(s)")
    client.status("serving; 1 request(s); last: GET /v1/health -> 200")
    client.stopping()
    got = systemd.messages(3)
    assert got[0] == "READY=1\nSTATUS=listening on 127.0.0.1:8777; 0 request(s)"
    assert got[1] == "STATUS=serving; 1 request(s); last: GET /v1/health -> 200"
    assert got[2] == "STOPPING=1"


def test_watchdog_pings_at_half_interval_only(systemd: FakeSystemd) -> None:
    clock = FakeClock()
    client = sdnotify.from_environment(
        {"NOTIFY_SOCKET": systemd.name, "WATCHDOG_USEC": "30000000"}, pid=1, clock=clock
    )
    assert client.ping_interval_s == 15.0
    assert client.watchdog() is True  # first call pings immediately
    clock.now += 14.9
    assert client.watchdog() is False  # too early
    clock.now += 0.2
    assert client.watchdog() is True  # 15.1 s after the first
    assert systemd.messages(2) == ["WATCHDOG=1", "WATCHDOG=1"]
    assert systemd.drain() == []


def test_watchdog_pid_mismatch_means_no_pings(systemd: FakeSystemd) -> None:
    client = sdnotify.from_environment(
        {"NOTIFY_SOCKET": systemd.name, "WATCHDOG_USEC": "30000000", "WATCHDOG_PID": "1"},
        pid=99,
    )
    assert client.enabled  # READY/STATUS still flow …
    assert not client.watchdog_enabled  # … but the watchdog was meant for another process
    assert client.watchdog(force=True) is False
    client.ready()
    assert systemd.messages(1) == ["READY=1"]


@pytest.mark.parametrize("raw_usec", ["", "abc", "0", "-5"])
def test_unparseable_or_zero_watchdog_usec_disables_pings(
    systemd: FakeSystemd, raw_usec: str
) -> None:
    client = sdnotify.from_environment(
        {"NOTIFY_SOCKET": systemd.name, "WATCHDOG_USEC": raw_usec}, pid=1
    )
    assert client.enabled and not client.watchdog_enabled


def test_malformed_socket_address_is_treated_as_absent() -> None:
    env = {"NOTIFY_SOCKET": "relative/path", "WATCHDOG_USEC": "1000000"}
    client = sdnotify.from_environment(env, pid=1)
    assert not client.enabled and not client.watchdog_enabled
    assert env == {}  # still consumed: children must not see it either


def test_send_failure_is_logged_once_and_never_raised() -> None:
    lines: list[str] = []
    client = sdnotify.SdNotify("@jarvis-test-nobody-listens-here", 2_000_000, log=lines.append)
    client.ready()
    client.status("x")
    assert client.watchdog(force=True) is True  # the attempt is made
    client.stopping()
    assert len(lines) == 1 and "sd_notify unavailable" in lines[0]


def test_status_is_one_sanitized_line() -> None:
    assert sdnotify._sanitize_status("a\nb\tc\x00d  ") == "a b c d"
    assert len(sdnotify._sanitize_status("x" * 500)) == 200


def test_trigger_is_not_expressible() -> None:
    """Policy failures mean pause, never a self-inflicted watchdog restart."""
    assert not hasattr(sdnotify.SdNotify, "trigger")
    source = Path(sdnotify.__file__).read_text(encoding="utf-8")
    assert "WATCHDOG=trigger" not in source.replace("Never ``WATCHDOG=trigger``", "")


# --------------------------------------------------------------------------
# D1 wired into the doorway
# --------------------------------------------------------------------------


@pytest.fixture()
def supervised_doorway(systemd: FakeSystemd) -> Iterator[tuple[str, str, FakeClock, FakeSystemd]]:
    clock = FakeClock()
    notifier = sdnotify.from_environment(
        {"NOTIFY_SOCKET": systemd.name, "WATCHDOG_USEC": "2000000"}, pid=os.getpid(), clock=clock
    )
    token = "test-token-abcdef"
    server = build_server("127.0.0.1", 0, token, notifier)
    port = server.server_address[1]
    notifier.ready(f"listening on 127.0.0.1:{port}; 0 request(s)")
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", token, clock, systemd
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_doorway_conversation_ready_watchdog_status_stopping(
    supervised_doorway: tuple[str, str, FakeClock, FakeSystemd],
) -> None:
    base, token, clock, systemd = supervised_doorway
    # READY first, then the accept loop's first WATCHDOG=1 (service_actions).
    first = systemd.messages(2)
    assert first[0].startswith("READY=1\nSTATUS=listening on 127.0.0.1:")
    assert first[1] == "WATCHDOG=1"
    # A request produces a STATUS line that carries method/path/code only.
    request = urllib.request.Request(
        f"{base}/v1/tools/jarvis_status",
        data=b"{}",
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
        json.loads(response.read())
    status_line = systemd.messages(1)[0]
    assert status_line == "STATUS=serving; 1 request(s); last: POST /v1/tools/jarvis_status -> 200"
    assert token not in status_line
    # Advance the fake clock past the half interval: the loop pings again.
    clock.now += 1.1
    assert systemd.messages(1) == ["WATCHDOG=1"]


def test_doorway_shutdown_sends_stopping(systemd: FakeSystemd) -> None:
    notifier = sdnotify.from_environment({"NOTIFY_SOCKET": systemd.name}, pid=os.getpid())
    server = build_server("127.0.0.1", 0, "t", notifier)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert "STOPPING=1" in systemd.drain()


def test_hung_request_does_not_starve_the_ping(systemd: FakeSystemd) -> None:
    """The ping runs on the accept loop; a handler thread that blocks cannot stop it."""
    clock = FakeClock()
    notifier = sdnotify.from_environment(
        {"NOTIFY_SOCKET": systemd.name, "WATCHDOG_USEC": "2000000"}, pid=os.getpid(), clock=clock
    )
    server = build_server("127.0.0.1", 0, "t", notifier)
    gate = threading.Event()
    original = server.note_request

    def blocking_note(line: str) -> None:  # simulate a handler that never returns
        gate.wait(timeout=5)
        original(line)

    server.note_request = blocking_note  # type: ignore[method-assign]
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        systemd.messages(1)  # the loop's first WATCHDOG=1
        hung = threading.Thread(
            target=lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=10),
            daemon=True,
        )
        hung.start()
        clock.now += 1.1
        assert systemd.messages(1) == ["WATCHDOG=1"]  # arrives while the request is stuck
    finally:
        gate.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_build_server_without_notifier_is_inert_and_unchanged() -> None:
    server = build_server("127.0.0.1", 0, "t")
    try:
        assert not server.notifier.enabled
        server.service_actions()  # no socket, no exception
    finally:
        server.server_close()


# --------------------------------------------------------------------------
# D2 — the doorway unit: supervised, not confined
# --------------------------------------------------------------------------


def test_doorway_unit_is_supervised_not_confined() -> None:
    unit = unit_content("/usr/bin/python3", 8777)
    assert "Type=notify\n" in unit
    assert "NotifyAccess=main\n" in unit
    assert f"WatchdogSec={WATCHDOG_SEC}\n" in unit and WATCHDOG_SEC == 30
    assert "Restart=on-failure\n" in unit  # covers watchdog expiry; on-watchdog would drop crashes
    assert "Restart=on-watchdog" not in unit
    for forbidden in (
        "NoNewPrivileges",
        "ProtectSystem",
        "ProtectHome",
        "PrivateUsers",
        "SystemCallFilter",
        "UMask",
        "PrivateTmp",
        "CapabilityBoundingSet",
    ):
        assert forbidden not in unit, f"{forbidden} breaks sudo -n for T1/T2 (ADR-0029)"
    assert "--bind 127.0.0.1" in unit and "Bearer" not in unit


# --------------------------------------------------------------------------
# D3 — the brief unit: opt-in confinement
# --------------------------------------------------------------------------


def test_brief_unit_default_is_unchanged() -> None:
    unit = service_content("/usr/bin/python3")
    assert unit == (
        "[Unit]\n"
        "Description=JARVIS briefing (propose-only; ADR-0021)\n"
        "\n"
        "[Service]\n"
        "ExecStart=/usr/bin/python3 -m jarvis brief --quiet\n"
        "Type=oneshot\n"
    )
    for directive in HARDENING_DIRECTIVES:
        assert directive.split("=")[0] + "=" not in unit


def test_brief_unit_hardened_profile_is_complete_and_scoped(tmp_path: Path) -> None:
    state = tmp_path / "state"
    unit = service_content("/usr/bin/python3", harden=True, state=state)
    assert "ExecStart=/usr/bin/python3 -m jarvis brief --quiet\n" in unit
    assert "Type=oneshot\n" in unit
    for directive in HARDENING_DIRECTIVES:
        assert f"{directive}\n" in unit
    assert f"ReadWritePaths={state}\n" in unit
    # ordering that matters: PrivateUsers before the mount-namespace directives,
    # ReadWritePaths right after ProtectHome
    assert unit.index("PrivateUsers=yes") < unit.index("ProtectSystem=strict")
    assert unit.index("ProtectHome=read-only") < unit.index("ReadWritePaths=")
    # the doorway's forbidden list is exactly what this unit may take
    assert "NoNewPrivileges=yes\n" in unit and "RestrictAddressFamilies=AF_UNIX\n" in unit


def test_brief_hardened_uses_the_resolved_state_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "custom-state"))
    unit = service_content("/usr/bin/python3", harden=True)
    assert f"ReadWritePaths={tmp_path / 'custom-state'}\n" in unit


@pytest.mark.parametrize("bad", ["with space", 'quo"te', "back\\slash", "apos'trophe"])
def test_brief_hardened_refuses_unquotable_state_dir(tmp_path: Path, bad: str) -> None:
    with pytest.raises(SafetyRefusal, match="ReadWritePaths"):
        service_content("/usr/bin/python3", harden=True, state=tmp_path / bad)


def test_install_harden_validates_before_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("jarvis.brief.install._systemctl_available", lambda: False)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "has space"))
    with pytest.raises(SafetyRefusal):
        install_timer("daily", tmp_path, harden=True)
    assert not (tmp_path / ".config").exists()  # nothing half-written


def test_install_harden_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("jarvis.brief.install._systemctl_available", lambda: False)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert install_timer("weekly", tmp_path, harden=True) == 0
    unit = (tmp_path / ".config" / "systemd" / "user" / "jarvis-brief.service").read_text()
    assert "SystemCallFilter=@system-service\n" in unit
    assert f"ReadWritePaths={tmp_path / 'state'}\n" in unit
    out = capsys.readouterr().out
    assert "hardened (ADR-0029 D3)" in out and "journalctl --user -u jarvis-brief" in out
    # plain re-install reverts
    assert install_timer("weekly", tmp_path) == 0
    unit = (tmp_path / ".config" / "systemd" / "user" / "jarvis-brief.service").read_text()
    assert "SystemCallFilter" not in unit


def test_cli_brief_install_exposes_harden_flag() -> None:
    from jarvis.cli.app import build_parser

    args = build_parser().parse_args(["brief", "install", "--on", "daily", "--harden"])
    assert args.harden is True
    args = build_parser().parse_args(["brief", "install"])
    assert args.harden is False


# --------------------------------------------------------------------------
# offline analyser — the numbers the ADR quotes, re-measured when possible
# --------------------------------------------------------------------------


def _exposure(unit_text: str, tmp_path: Path, name: str) -> float | None:
    if shutil.which("systemd-analyze") is None:
        return None
    path = tmp_path / name
    path.write_text(unit_text, encoding="utf-8")
    result = subprocess.run(
        ["systemd-analyze", "security", "--offline=true", "--no-pager", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    # "→ Overall exposure level for x.service: 2.0 OK :-)" — take the first number after the colon
    for line in result.stdout.splitlines():
        if "Overall exposure level" in line:
            match = re.search(
                r":\s*([0-9]+(?:\.[0-9]+)?)", line.split("Overall exposure level", 1)[1]
            )
            return float(match.group(1)) if match else None
    return None


def test_offline_exposure_scores_match_the_adr(tmp_path: Path) -> None:
    hardened = _exposure(
        service_content("/usr/bin/python3", harden=True, state=tmp_path / "s"),
        tmp_path,
        "jarvis-brief.service",
    )
    if hardened is None:
        pytest.skip(
            "systemd-analyze not available or its output changed; ADR numbers not re-measured"
        )
    assert hardened <= 2.5, f"hardened brief unit scores {hardened}, ADR-0029 D3 promises <= 2.5"
    plain = _exposure(service_content("/usr/bin/python3"), tmp_path, "jarvis-brief-plain.service")
    doorway = _exposure(unit_content("/usr/bin/python3", 8777), tmp_path, "jarvis-serve.service")
    assert plain is not None and plain > hardened
    # honesty check: the doorway is supervised, not confined — its score does NOT improve
    assert doorway is not None and doorway >= 9.0
