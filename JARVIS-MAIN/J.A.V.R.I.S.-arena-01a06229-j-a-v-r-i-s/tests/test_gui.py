"""GUI control tests: detection, matrix, backends, policy, service, wizard, CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FakeRunner, StubHTTPServer
from jarvis.execution.runner import ExecResult
from jarvis.gui import backends
from jarvis.gui.backends import GuiBackendError
from jarvis.gui.capabilities import available
from jarvis.gui.detect import probe
from jarvis.gui.service import (
    GuiPolicyError,
    GuiService,
    GuiUnavailable,
    validate_combo,
    validate_launch_tokens,
    validate_text,
)
from jarvis.gui.vision import VisionUnavailable, describe_image, vision_model
from jarvis.gui.wizard import report as wizard_report
from jarvis.gui.wizard import run_checks
from jarvis.journal.sqlite import Journal
from jarvis.planner.playbooks import match_intent
from jarvis.safety.approval import ApprovalPolicy, ApprovalRefused


def _which(names: tuple[str, ...]):  # type: ignore[no-untyped-def]
    return lambda name: f"/usr/bin/{name}" if name in names else None


def _result(stdout: str = "", exit_code: int = 0) -> ExecResult:
    return ExecResult(exit_code=exit_code, stdout_tail=stdout, stderr_tail="")


@pytest.fixture()
def journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "journal.db")


# -- detection ---------------------------------------------------------------


def test_probe_headless_is_honest() -> None:
    env = probe(env={}, which_fn=_which(()))
    assert env.session_type == "headless"
    assert env.headless
    assert env.tools == ()


def test_probe_x11_and_wayland() -> None:
    x11 = probe(env={"DISPLAY": ":0"}, which_fn=_which(()))
    assert x11.session_type == "x11"
    wayland = probe(
        env={"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"},
        which_fn=_which(()),
    )
    assert wayland.session_type == "wayland"


def test_probe_desktop_precedence() -> None:
    hypr = probe(
        env={
            "WAYLAND_DISPLAY": "w",
            "HYPRLAND_INSTANCE_SIGNATURE": "x",
            "XDG_CURRENT_DESKTOP": "Hyprland",
        },
        which_fn=_which(()),
    )
    assert hypr.desktop == "hyprland"
    i3 = probe(env={"DISPLAY": ":0", "I3SOCK": "/tmp/i3.sock"}, which_fn=_which(()))
    assert i3.desktop == "i3"
    gnome = probe(
        env={"WAYLAND_DISPLAY": "w", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"},
        which_fn=_which(()),
    )
    assert gnome.desktop == "gnome"


def test_probe_tool_inventory() -> None:
    env = probe(env={"DISPLAY": ":0"}, which_fn=_which(("xdotool", "wmctrl", "scrot")))
    assert env.has_tool("xdotool") and env.has_tool("wmctrl") and env.has_tool("scrot")
    assert not env.has_tool("ydotool")


# -- capability matrix ---------------------------------------------------------


def test_matrix_headless_all_unavailable() -> None:
    caps = available(probe(env={}, which_fn=_which(())))
    for cap in ("windows", "type_text", "screenshot", "launch", "close"):
        assert caps[cap].backend is None
        assert "headless" in caps[cap].reason


def test_matrix_x11_with_tools() -> None:
    caps = available(probe(env={"DISPLAY": ":0"}, which_fn=_which(("wmctrl", "xdotool", "scrot"))))
    assert caps["windows"].backend == "wmctrl"
    assert caps["type_text"].backend == "xdotool"
    assert caps["screenshot"].backend == "scrot"


def test_matrix_i3_prefers_ipc() -> None:
    caps = available(
        probe(env={"DISPLAY": ":0", "I3SOCK": "/s"}, which_fn=_which(("i3-msg", "xdotool")))
    )
    assert caps["windows"].backend == "i3-msg"
    assert caps["type_text"].backend == "xdotool"  # input stays X11


def test_matrix_wayland_input_needs_daemon_socket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import jarvis.gui.capabilities as caps_mod

    monkeypatch.setattr(caps_mod, "ydotool_socket", lambda: Path("/nonexistent-socket"))
    caps = available(probe(env={"WAYLAND_DISPLAY": "w"}, which_fn=_which(("ydotool",))))
    assert caps["type_text"].backend is None
    assert "ydotoold" in caps["type_text"].reason

    ready_socket = tmp_path / "ydotool.sock"
    ready_socket.write_bytes(b"")
    monkeypatch.setattr(caps_mod, "ydotool_socket", lambda: ready_socket)
    caps = available(
        probe(
            env={"WAYLAND_DISPLAY": "w", "XDG_CURRENT_DESKTOP": "Hyprland"},
            which_fn=_which(("ydotool", "hyprctl", "grim")),
        )
    )
    assert caps["windows"].backend == "hyprctl"
    assert caps["type_text"].backend == "ydotool"
    assert caps["screenshot"].backend == "grim"


# -- backends: parsing ---------------------------------------------------------


def test_wmctrl_list_parsing() -> None:
    runner = FakeRunner(
        default_stdout=(
            "0x03200007  0 lab xterm — jarvis-a\n0x03a00007  0 lab Mozilla Firefox\nbad-line\n"
        )
    )
    windows = backends.wmctrl_list(runner)
    assert [w.title for w in windows] == ["xterm — jarvis-a", "Mozilla Firefox"]
    assert windows[0].id == "0x03200007"


def test_i3_tree_walk_includes_floating_and_focused() -> None:
    tree = {
        "id": 1,
        "name": "root",
        "nodes": [
            {
                "id": 2,
                "name": "ws1",
                "nodes": [
                    {
                        "id": 3,
                        "window": 111,
                        "name": "xterm — jarvis-a",
                        "focused": False,
                        "nodes": [],
                        "floating_nodes": [],
                    },
                ],
                "floating_nodes": [
                    {
                        "id": 4,
                        "window": 222,
                        "name": "floating calc",
                        "focused": True,
                        "nodes": [],
                        "floating_nodes": [],
                    },
                ],
            },
        ],
        "floating_nodes": [],
    }
    runner = FakeRunner(script=[(("i3-msg", "-t", "get_tree"), _result(json.dumps(tree)))])
    windows = backends.i3_list(runner)
    assert {w.title for w in windows} == {"xterm — jarvis-a", "floating calc"}
    assert backends.i3_focused_title(runner) == "floating calc"


def test_hyprland_clients_parsing() -> None:
    payload = json.dumps(
        [
            {"address": "0x1", "title": "Firefox", "initialClass": "firefox"},
            {"address": "0x2", "title": "", "initialClass": ""},
        ]
    )
    runner = FakeRunner(script=[(("hyprctl", "-j", "clients"), _result(payload))])
    windows = backends.hyprland_list(runner)
    assert len(windows) == 2 and windows[0].title == "Firefox"


def test_setsid_launch_composition() -> None:
    assert backends.setsid_launch(("xterm", "-title", "t")) == (
        "setsid",
        "--fork",
        "xterm",
        "-title",
        "t",
    )


# -- policy --------------------------------------------------------------------


def test_validate_text_policy() -> None:
    assert validate_text("hello world") == "hello world"
    with pytest.raises(GuiPolicyError, match="nothing to type"):
        validate_text("   ")
    with pytest.raises(GuiPolicyError, match="control characters"):
        validate_text("line\nnewline")
    with pytest.raises(GuiPolicyError, match="too long"):
        validate_text("x" * 501)


def test_validate_combo_policy() -> None:
    assert validate_combo("ctrl+shift+t") == "ctrl+shift+t"
    with pytest.raises(GuiPolicyError):
        validate_combo("bad combo; rm -rf")
    with pytest.raises(GuiPolicyError):
        validate_combo("x" * 41)


def test_validate_launch_tokens_rejects_paths() -> None:
    assert validate_launch_tokens(("xterm", "-title", "t")) == ("xterm", "-title", "t")
    with pytest.raises(GuiPolicyError, match="PATH"):
        validate_launch_tokens(("/tmp/evil.sh",))
    with pytest.raises(GuiPolicyError):
        validate_launch_tokens(())


# -- service -------------------------------------------------------------------


def test_service_headless_refuses_injection(journal: Journal) -> None:
    service = GuiService(
        FakeRunner(),  # type: ignore[arg-type]
        ApprovalPolicy(yes=True),
        journal,
        env={},
    )
    with pytest.raises(GuiUnavailable, match="headless"):
        service.type_text("hi")
    with pytest.raises(GuiUnavailable):
        service.windows()


def test_service_consent_blocks_injection_without_approval(
    journal: Journal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    runner = FakeRunner(
        script=[
            (("xdotool", "getactivewindow", "getwindowname"), _result("xterm — focused")),
        ]
    )
    env = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}
    service = GuiService(
        runner,
        ApprovalPolicy(yes=False),
        journal,
        env=env,
        which_fn=_which(("xdotool",)),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO())  # non-tty -> ApprovalRefused
    with pytest.raises(ApprovalRefused):
        service.type_text("should never land")
    assert not any(call[0][:2] == ("xdotool", "type") for call in runner.calls), (
        "injection must never run without consent"
    )


def test_service_type_injects_and_journals_hash_only(
    journal: Journal,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    script = [
        (("xdotool", "getactivewindow", "getwindowname"), _result("xterm — target")),
        (("xdotool", "type", "--delay", "40", "--", "secret-payload"), _result()),
    ]
    service = GuiService(
        FakeRunner(script=script),
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool",)),
    )
    outcome = service.type_text("secret-payload")
    assert outcome.status == "done" and outcome.target == "xterm — target"
    task = journal.recent_tasks(limit=1)[0]
    steps = journal.steps_for_task(str(task["id"]))
    task_row = journal.get_task(str(task["id"]))
    assert task_row is not None
    argv_json = str(steps[0]["argv"])
    assert "secret-payload" not in argv_json  # typed text is NOT journalled
    params = str(task_row["params"])
    assert "secret-payload" not in params
    assert "sha256_16" in params


def test_service_type_requires_focused_window(journal: Journal) -> None:
    script = [(("xdotool", "getactivewindow", "getwindowname"), _result("", exit_code=1))]
    service = GuiService(
        FakeRunner(script=script),
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool",)),
    )
    with pytest.raises(GuiPolicyError, match="no focused window"):
        service.type_text("hi")


def test_service_focus_unique_and_ambiguous(journal: Journal) -> None:
    listing = "0x1  0 h xterm — alpha\n0x2  0 h xterm — alpha two\n"
    runner = FakeRunner(
        script=[
            (("wmctrl", "-l"), _result(listing)),
            (("wmctrl", "-i", "-a", "0x1"), _result()),
            (("xdotool", "getactivewindow", "getwindowname"), _result("xterm — alpha")),
        ]
    )
    service = GuiService(
        runner,
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("wmctrl", "xdotool")),
    )
    outcome = service.focus("alpha two")
    assert outcome.status == "done"
    with pytest.raises(GuiPolicyError, match="be more specific"):
        service.focus("alpha")


def test_service_screenshot_verifies_file(
    journal: Journal,
    tmp_path: Path,
) -> None:
    out = tmp_path / "shot.png"

    class TouchingRunner(FakeRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            result = super().run(argv, **kwargs)
            if argv[0] == "scrot" and result.ok:
                out.write_bytes(b"\x89PNG fake")
            return result

    service = GuiService(
        TouchingRunner(script=[(("scrot", "-o", "-q", "90", str(out)), _result())]),
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("scrot",)),
    )
    outcome = service.screenshot(out)
    assert outcome.status == "done" and out.stat().st_size > 0

    class LyingRunner(FakeRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            return _result()  # claims success, writes nothing

    service = GuiService(
        LyingRunner(),
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("scrot",)),
    )
    with pytest.raises(GuiBackendError, match="missing/empty"):
        service.screenshot(tmp_path / "never.png")


def test_service_status_reports_matrix(journal: Journal) -> None:
    service = GuiService(
        FakeRunner(),  # type: ignore[arg-type]
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
    )
    data = service.status()
    assert data["session"]["session_type"] == "x11"
    caps = data["capabilities"]
    assert isinstance(caps, dict) and "type_text" in caps


# -- wizard ----------------------------------------------------------------------


def test_wizard_ready_wayland() -> None:
    env_vars = {"WAYLAND_DISPLAY": "wayland-0", "XDG_CURRENT_DESKTOP": "GNOME"}
    checks = run_checks(
        env_vars=env_vars,
        which_fn=_which(("ydotool", "ydotoold")),
        exists=lambda p: True,
        in_input_group=lambda: True,
    )
    assert all(c.ok for c in checks)
    assert "READY" in wizard_report(checks)


def test_wizard_missing_daemon_suggests_service_fix() -> None:
    env_vars = {"WAYLAND_DISPLAY": "wayland-0", "XDG_CURRENT_DESKTOP": "GNOME"}
    checks = run_checks(
        env_vars=env_vars,
        which_fn=_which(("ydotool", "apt")),
        exists=lambda p: p.name == "uinput",
        in_input_group=lambda: True,
    )
    socket_check = next(c for c in checks if c.name == "ydotoold socket")
    assert not socket_check.ok
    assert "systemctl enable --now ydotool" in socket_check.fix
    assert "NOT ready" in wizard_report(checks)


def test_wizard_x11_branch_checks_xdotool() -> None:
    checks = run_checks(
        env_vars={"DISPLAY": ":0"},
        which_fn=_which(()),
        exists=lambda p: True,
        in_input_group=lambda: False,
    )
    names = [c.name for c in checks]
    assert "input backend (X11)" in names
    xdotool_check = next(c for c in checks if c.name == "input backend (X11)")
    assert not xdotool_check.ok and "apt install xdotool" in xdotool_check.fix


# -- vision ----------------------------------------------------------------------


def test_vision_describe_via_stub() -> None:
    server = StubHTTPServer()
    try:
        server.queue({"message": {"content": "A terminal window with JARVIS running."}})
        image = Path("/tmp/jarvis-vision-test.png")
        image.write_bytes(b"\x89PNG fake data")
        env = {"JARVIS_OLLAMA_URL": server.url, "JARVIS_VISION_MODEL": "llava-test"}
        assert vision_model(env) == "llava-test"
        text = describe_image(image, "what is this?", env=env)
        assert "terminal" in text
    finally:
        server.close()


def test_vision_unavailable_is_honest(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG")
    with pytest.raises(VisionUnavailable, match="no reachable Ollama"):
        describe_image(image, env={"JARVIS_OLLAMA_URL": "http://127.0.0.1:1"})


def test_vision_empty_file_refused(tmp_path: Path) -> None:
    image = tmp_path / "empty.png"
    image.write_bytes(b"")
    with pytest.raises(VisionUnavailable, match="empty"):
        describe_image(image, env={"JARVIS_OLLAMA_URL": "http://127.0.0.1:1"})


# -- playbook gui.launch ----------------------------------------------------------


def test_gui_launch_playbook_matches(debian_profile) -> None:  # type: ignore[no-untyped-def]
    matched = match_intent("open firefox")
    assert matched is not None and matched[0].id == "gui.launch"
    assert matched[1]["app"] == "firefox"
    steps = matched[0].build(matched[1], debian_profile)
    assert steps[0].argv == ("setsid", "--fork", "firefox")
    assert str(steps[0].tier.value) == "2"


def test_gui_launch_playbook_preserves_case(debian_profile) -> None:  # type: ignore[no-untyped-def]
    matched = match_intent("launch Code --new-window")
    assert matched is not None and matched[0].id == "gui.launch"
    steps = matched[0].build(matched[1], debian_profile)
    assert steps[0].argv == ("setsid", "--fork", "Code", "--new-window")


def test_gui_launch_playbook_rejects_paths_and_flags_first() -> None:
    assert match_intent("open /tmp/evil.sh") is None
    assert match_intent("open") is None
    assert match_intent("open ../../../etc/shadow") is None


# -- CLI surface ------------------------------------------------------------------


def test_cli_gui_status_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "gui", "status"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["session"]["session_type"] in ("headless", "x11", "wayland")
    assert "capabilities" in data


def test_cli_gui_type_refused_headless_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["gui", "type", "hello"]) == 2
    assert "unavailable" in capsys.readouterr().err


def test_cli_gui_wizard_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "gui", "wizard"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert any(c["name"] == "ydotool binary" for c in data)


def test_service_quiet_runner_keeps_stdout_pure(journal: Journal) -> None:
    """--json mode: no runner echo lines may pollute stdout (CI bug found by m5 eval)."""

    class EchoSpy(FakeRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs.get("echo") is False, "service must suppress echo in JSON mode"
            result = super().run(argv, **kwargs)
            if argv[0] == "scrot" and result.ok:
                Path("/tmp/x.png").write_bytes(b"\x89PNG")
            return result

    service = GuiService(
        EchoSpy(
            script=[
                (("scrot", "-o", "-q", "90", "/tmp/x.png"), _result()),
            ]
        ),
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("scrot",)),
        echo=False,
    )
    service.screenshot(Path("/tmp/x.png"))
    assert service._runner.__class__.__name__ == "_QuietRunner"


def test_i3_tree_skips_dockarea_bars() -> None:
    tree = {
        "id": 1,
        "name": "root",
        "type": "root",
        "nodes": [
            {
                "id": 2,
                "type": "dockarea",
                "name": "i3bar for output screen",
                "window": 999,
                "nodes": [],
                "floating_nodes": [],
            },
            {
                "id": 3,
                "type": "workspace",
                "name": "1",
                "nodes": [
                    {
                        "id": 4,
                        "type": "con",
                        "window": 111,
                        "name": "xterm — real",
                        "focused": True,
                        "nodes": [],
                        "floating_nodes": [],
                    },
                ],
                "floating_nodes": [],
            },
        ],
        "floating_nodes": [],
    }
    runner = FakeRunner(script=[(("i3-msg", "-t", "get_tree"), _result(json.dumps(tree)))])
    windows = backends.i3_list(runner)
    assert [w.title for w in windows] == ["xterm — real"]


def test_open_app_uses_detach_mode(journal: Journal) -> None:
    """gui open must not inherit runner pipes (CI hang found by m5 eval)."""

    class DetachSpy(FakeRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs.get("detach") is True, "detached spawns need DEVNULL stdios"
            return super().run(argv, **kwargs)

    service = GuiService(
        DetachSpy(),
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(()),
    )
    outcome = service.open_app(("xterm",))
    assert outcome.status == "done"
