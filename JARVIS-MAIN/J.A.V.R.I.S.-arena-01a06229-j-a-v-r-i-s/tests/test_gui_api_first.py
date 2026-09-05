"""M9e: API-first GUI actions — AT-SPI EditableText before synthetic input.

The path disclosure (api/wm/injection) is part of the capability matrix;
consent tiers and the TOCTOU guard are identical on both paths. pyatspi is
faked via sys.modules so the action-layer logic is tested without the real
accessibility bus.
"""

from __future__ import annotations

import io
import sys
from typing import Any, ClassVar

import pytest

from conftest import FakeRunner
from jarvis.execution.runner import ExecResult
from jarvis.gui import capabilities as caps_mod
from jarvis.gui.atspi import set_focused_text
from jarvis.gui.capabilities import available
from jarvis.gui.detect import probe
from jarvis.gui.service import GuiBackendError, GuiService
from jarvis.journal.sqlite import Journal
from jarvis.safety.approval import ApprovalPolicy, ApprovalRefused


def _which(names: tuple[str, ...]):  # type: ignore[no-untyped-def]
    return lambda name: f"/usr/bin/{name}" if name in names else None


def _result(stdout: str = "", exit_code: int = 0) -> ExecResult:
    return ExecResult(exit_code=exit_code, stdout_tail=stdout, stderr_tail="")


@pytest.fixture()
def journal(tmp_path: Any) -> Journal:
    return Journal(tmp_path / "journal.db")


@pytest.fixture()
def x11_env() -> Any:
    return probe(env={"DISPLAY": ":0"}, which_fn=_which(("xdotool", "wmctrl")))


# -- matrix path disclosure ----------------------------------------------------


def test_type_text_is_api_first_when_pyatspi_present(
    x11_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: True)
    matrix = available(x11_env)
    binding = matrix["type_text"]
    assert binding.backend == "atspi-editable"
    assert binding.path == "api"
    assert "no synthetic keys" in binding.reason


def test_type_text_falls_to_injection_honestly(
    x11_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: False)
    binding = available(x11_env)["type_text"]
    assert binding.backend == "xdotool"
    assert binding.path == "injection"
    assert "python3-pyatspi" in binding.reason  # the API path is named, not hidden


def test_key_is_injection_only_and_says_why(x11_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: True)
    binding = available(x11_env)["key"]
    assert binding.path == "injection"
    assert "no honest API path" in binding.reason


def test_wm_and_api_backends_disclose_paths(x11_env: Any) -> None:
    matrix = available(x11_env)
    assert matrix["focus"].path == "wm"
    assert matrix["close"].path == "wm"
    assert matrix["launch"].path == "api"
    assert matrix["screenshot"].path == "api"
    assert matrix["describe"].path == "api"


def test_service_status_includes_paths(journal: Journal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: False)
    service = GuiService(
        FakeRunner(),  # type: ignore[arg-type]
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool", "wmctrl")),
    )
    caps = service.status()["capabilities"]
    assert isinstance(caps, dict)
    type_binding = caps["type_text"]
    assert isinstance(type_binding, dict)
    assert type_binding["path"] == "injection"


# -- the API action path through the service -----------------------------------


def test_type_via_atspi_no_injection_argv_and_journals_hash(
    journal: Journal, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(
        "jarvis.gui.atspi.set_focused_text",
        lambda text: calls.append(text) or (True, "set via AT-SPI EditableText (test)"),
    )
    runner = FakeRunner(
        script=[(("xdotool", "getactivewindow", "getwindowname"), _result("gedit — x"))]
    )
    service = GuiService(
        runner,
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool", "wmctrl")),
    )
    outcome = service.type_text("typed-via-api")
    assert outcome.status == "done" and "AT-SPI" in outcome.detail
    assert calls == ["typed-via-api"]
    assert not any(call[0][:2] == ("xdotool", "type") for call in runner.calls), (
        "the API path must never synthesize keystrokes"
    )
    task = journal.recent_tasks(limit=1)[0]
    row = journal.get_task(str(task["id"]))
    assert row is not None
    params = str(row["params"])
    assert "typed-via-api" not in params and "sha256_16" in params
    assert "atspi-editable" in params


def test_api_path_still_requires_consent(
    journal: Journal, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: True)
    called = {"api": 0}
    monkeypatch.setattr(
        "jarvis.gui.atspi.set_focused_text",
        lambda text: called.__setitem__("api", called["api"] + 1) or (True, "set"),
    )
    runner = FakeRunner(
        script=[(("xdotool", "getactivewindow", "getwindowname"), _result("gedit — x"))]
    )
    service = GuiService(
        runner,
        ApprovalPolicy(yes=False),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool", "wmctrl")),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO())  # non-tty: refuse instead of ask
    with pytest.raises(ApprovalRefused):
        service.type_text("must not land")
    assert called["api"] == 0  # the gate holds on the API path too


def test_api_path_keeps_the_toctou_guard(
    journal: Journal, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from jarvis.gui.service import GuiPolicyError

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: True)
    monkeypatch.setattr("jarvis.gui.atspi.set_focused_text", lambda text: (True, "set"))
    runner = FakeRunner()
    service = GuiService(
        runner,
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool", "wmctrl")),
    )
    titles = iter(["gedit — x", "something-else — y"])
    monkeypatch.setattr(service, "focused_title", lambda: next(titles))
    with pytest.raises(GuiPolicyError, match="TOCTOU"):
        service.type_text("hi")
    assert runner.calls == []  # and nothing was executed


def test_api_failure_falls_back_disclosed(
    journal: Journal, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """ADR-0013 ordering: API preferred, synthetic input as the *disclosed*
    fallback under the same consent — the journal names both attempts."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: True)
    monkeypatch.setattr(
        "jarvis.gui.atspi.set_focused_text",
        lambda text: (False, "no focused editable-text object found"),
    )
    runner = FakeRunner(
        script=[
            (("xdotool", "getactivewindow", "getwindowname"), _result("xterm — t")),
            (("xdotool", "type", "--delay", "40", "--", "fallback-text"), _result()),
        ]
    )
    service = GuiService(
        runner,
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("xdotool", "wmctrl")),
    )
    outcome = service.type_text("fallback-text")
    assert outcome.status == "done"
    assert "fell back to injection via xdotool" in outcome.detail
    assert "AT-SPI unavailable" in outcome.detail
    assert any(call[0][:2] == ("xdotool", "type") for call in runner.calls)
    task = journal.recent_tasks(limit=1)[0]
    row = journal.get_task(str(task["id"]))
    assert row is not None
    params = str(row["params"])
    assert "api_attempt" in params and "fallback-text" not in params


def test_api_failure_without_injection_tool_is_honest(
    journal: Journal, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "st"))
    monkeypatch.setattr(caps_mod, "atspi_available", lambda: True)
    monkeypatch.setattr(
        "jarvis.gui.atspi.set_focused_text",
        lambda text: (False, "no focused editable-text object found"),
    )
    service = GuiService(
        FakeRunner(),  # type: ignore[arg-type]
        ApprovalPolicy(yes=True),
        journal,
        env={"DISPLAY": ":0"},
        which_fn=_which(("wmctrl",)),  # no xdotool, no ydotool
    )
    monkeypatch.setattr(service, "focused_title", lambda: "xterm — w")  # focus without injection
    with pytest.raises(GuiBackendError, match="no synthetic-input backend"):
        service.type_text("hi")


# -- atspi action layer (fake pyatspi module) ----------------------------------


class _FakeState:
    def __init__(self, focused: bool) -> None:
        self._focused = focused

    def contains(self, _flag: int) -> bool:
        return self._focused


class _FakeEditableText:
    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def setTextContents(self, text: str) -> None:
        self._sink.append(text)


class _FakeQueryCache:
    def __init__(self, sink: list[str] | None) -> None:
        self._editable = _FakeEditableText(sink) if sink is not None else None

    def queryEditableText(self) -> _FakeEditableText:
        if self._editable is None:
            raise NotImplementedError("not editable")
        return self._editable


class _FakeNode:
    def __init__(
        self,
        focused: bool,
        editable_sink: list[str] | None,
        children: list[_FakeNode] | None = None,
    ) -> None:
        self._state = _FakeState(focused)
        self._queries = _FakeQueryCache(editable_sink)
        self._children = children or []

    def getState(self) -> _FakeState:
        return self._state

    def queryEditableText(self) -> _FakeEditableText:
        return self._queries.queryEditableText()

    def __iter__(self) -> Any:
        return iter(self._children)


class _FakeRegistry:
    desktop_nodes: ClassVar[list[_FakeNode]] = []
    STATE_FOCUSED = 4242
    Registry: type[_FakeRegistry]  # fake module shape: pyatspi.Registry.getDesktop

    @classmethod
    def getDesktop(cls, _index: int) -> list[_FakeNode]:
        return cls.desktop_nodes


_FakeRegistry.Registry = _FakeRegistry


@pytest.fixture()
def fake_pyatspi(monkeypatch: pytest.MonkeyPatch) -> type[_FakeRegistry]:
    monkeypatch.setitem(sys.modules, "pyatspi", _FakeRegistry)  # type: ignore[dict-item]
    monkeypatch.setattr("jarvis.gui.atspi.atspi_available", lambda: True)
    return _FakeRegistry


def test_set_focused_text_edits_the_focused_editable(fake_pyatspi: Any) -> None:
    sink: list[str] = []
    fake_pyatspi.desktop_nodes = [
        _FakeNode(False, None, [_FakeNode(True, None, [_FakeNode(True, sink)])])
    ]
    ok, detail = set_focused_text("hello")
    assert ok is True and "EditableText" in detail
    assert sink == ["hello"]


def test_set_focused_text_no_focused_editable_is_honest(fake_pyatspi: Any) -> None:
    fake_pyatspi.desktop_nodes = [_FakeNode(False, None, [_FakeNode(False, None)])]
    ok, detail = set_focused_text("hello")
    assert ok is False and "no focused editable" in detail


def test_set_focused_text_reports_bus_errors(fake_pyatspi: Any) -> None:
    class Boom:
        def __iter__(self) -> Any:
            raise RuntimeError("bus died")

    fake_pyatspi.desktop_nodes = [Boom()]  # type: ignore[list-item]
    ok, detail = set_focused_text("hello")
    assert ok is False and "failed" in detail
