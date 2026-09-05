"""ADR-0026: unknown-app control (guarded AT-SPI) + owner-taught app packs.

Covers the four new surfaces end to end:
- jarvis.gui.actions     — the guarded find/list/act/text API (walls first)
- jarvis.gui.appskill    — app-skill/1 packs: validate, install+receipt, load
- gui.app playbook       — match / build argv shapes / fail-closed verify
- jarvis.gui.action_exec — the fixed-argv module CLI (exit 0/2/3)
plus the D5 no-shadow rules against gui.launch and the hint exemption.

pyatspi is faked via sys.modules (duck-typed, index-protocol children —
the shape real pyatspi Accessible objects expose).
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

import pytest

from jarvis.gui import appskill
from jarvis.gui.actions import ActionRefused, do_named_action, find_node, set_node_text
from jarvis.planner.models import Tier
from jarvis.planner.playbooks import PLAYBOOKS, match_intent
from jarvis.safety.tiers import SafetyRefusal

# --------------------------------------------------------------------------
# stub AT-SPI tree (index-protocol children, like the real pyatspi binding)
# --------------------------------------------------------------------------


class _StubAction:
    def __init__(self, names: list[str]) -> None:
        self._names = names
        self.performed: list[str] = []

    def get_n_actions(self) -> int:
        return len(self._names)

    def getName(self, i: int) -> str:
        return self._names[i]

    def doAction(self, i: int) -> bool:
        self.performed.append(self._names[i])
        return True


class _StubEditable:
    def __init__(self) -> None:
        self.text = ""

    def setTextContents(self, text: str) -> bool:
        self.text = text
        return True


class _StubNode:
    def __init__(
        self,
        name: str,
        role: str,
        *,
        action: _StubAction | None = None,
        editable: _StubEditable | None = None,
        children: list[_StubNode] | None = None,
    ) -> None:
        self.name = name
        self._role = role
        self._action = action
        self._editable = editable
        self._children = children or []

    def getRoleName(self) -> str:
        return self._role

    def queryAction(self) -> _StubAction:
        if self._action is None:
            raise NotImplementedError("no Action interface")
        return self._action

    def queryEditableText(self) -> _StubEditable:
        if self._editable is None:
            raise NotImplementedError("no EditableText interface")
        return self._editable

    def get_child_count(self) -> int:
        return len(self._children)

    def get_child_at_index(self, i: int) -> _StubNode | None:
        return self._children[i] if 0 <= i < len(self._children) else None


class _StubDesktop:
    def __init__(self, apps: list[_StubNode]) -> None:
        self._apps = apps

    def get_child_count(self) -> int:
        return len(self._apps)

    def get_child_at_index(self, i: int) -> _StubNode | None:
        return self._apps[i] if 0 <= i < len(self._apps) else None


def _tree(**extras: _StubNode) -> _StubDesktop:
    """gedit-like tree; `extras` merged into the app subtree."""
    children = [
        _StubNode("Untitled 1", "frame"),
        _StubNode("Save", "push button", action=_StubAction(["click", "press"])),
        _StubNode("Find", "text", editable=_StubEditable()),
        *extras.values(),
    ]
    app = _StubNode("gedit", "application", children=children)
    return _StubDesktop([app, _StubNode("other", "application")])


# a tree whose subtrees explode if read — proves walls fire before any read
class _BoobyTrapApp(_StubNode):
    def get_child_count(self) -> int:
        raise AssertionError("blocked application subtree was read")

    def get_child_at_index(self, i: int) -> None:
        raise AssertionError("blocked application subtree was read")


class _TrapDesktop(_StubDesktop):
    def __init__(self) -> None:
        super().__init__([_BoobyTrapApp("keepassxc", "application")])


# --------------------------------------------------------------------------
# pack documents
# --------------------------------------------------------------------------


def _pack_document(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": "app-skill/1",
        "id": "gedit-save",
        "version": 1,
        "created": "2026-09-05",
        "description": "owner-taught: type into gedit, save via keyboard, click Save",
        "app": {"launch": ["gedit", "/home/owner/notes.txt"]},
        "steps": [
            {"type": {"app": "gedit", "role": "text", "name": "Find", "text": "hello"}},
            {"key": "ctrl-s"},
            {"action": {"app": "gedit", "role": "push button", "name": "Save", "action": "click"}},
        ],
        "phrases": ["save my gedit file", "gedit save the open file"],
    }
    doc.update(overrides)
    return doc


@pytest.fixture()
def state(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state"


@pytest.fixture()
def installed(state: Any) -> dict[str, Any]:
    result = appskill.install_pack(_pack_document())
    assert isinstance(result["pack"], dict)
    return result  # type: ignore[return-value]


# --------------------------------------------------------------------------
# validate gates (D4: every field bounded, nothing command-carrying)
# --------------------------------------------------------------------------


def test_schema_is_mandatory(state: Any) -> None:
    doc = _pack_document()
    del doc["schema"]
    with pytest.raises(SafetyRefusal, match="schema"):
        appskill.install_pack(doc)


def test_id_shape_is_bounded(state: Any) -> None:
    for bad in ("", "UPPER", "1abc", "a", "x" * 40, "with space"):
        with pytest.raises(SafetyRefusal):
            appskill.validate_pack(_pack_document(id=bad))


def test_launch_first_token_must_be_a_bare_command(state: Any) -> None:
    # path-based exec is smuggled through the FIRST token only
    with pytest.raises(SafetyRefusal, match="launch token"):
        appskill.validate_pack(_pack_document(app={"launch": ["/usr/bin/evil", "arg"]}))
    with pytest.raises(SafetyRefusal, match="launch token"):
        appskill.validate_pack(_pack_document(app={"launch": ["../evil"]}))


def test_launch_arguments_reject_shell_metacharacters(state: Any) -> None:
    with pytest.raises(SafetyRefusal, match="launch token"):
        appskill.validate_pack(_pack_document(app={"launch": ["gedit", "; rm -rf /"]}))
    with pytest.raises(SafetyRefusal, match="launch token"):
        appskill.validate_pack(_pack_document(app={"launch": ["gedit", "$(x)"]}))
    # but honest absolute-path arguments are fine
    ok = appskill.validate_pack(_pack_document())
    assert ok["app"] == {"launch": ["gedit", "/home/owner/notes.txt"]}  # type: ignore[index]


def test_blocked_app_refused_at_launch(state: Any) -> None:
    with pytest.raises(SafetyRefusal, match="blocked list"):
        appskill.validate_pack(_pack_document(app={"launch": ["keepassxc"]}))


def test_blocked_app_refused_in_steps_and_focus(state: Any) -> None:
    with pytest.raises(SafetyRefusal, match="blocked list"):
        appskill.validate_pack(
            _pack_document(
                steps=[
                    {
                        "action": {
                            "app": "seahorse",
                            "role": "push button",
                            "name": "OK",
                            "action": "click",
                        }
                    }
                ],
                phrases=["seahorse ok"],
            )
        )
    with pytest.raises(SafetyRefusal, match="blocked list"):
        appskill.validate_pack(
            _pack_document(steps=[{"focus": "KeepAssXC"}], phrases=["focus keepassx"])
        )


def test_password_role_is_refusable_at_action_layer_not_pack_layer(state: Any) -> None:
    # packs may NAME a password-text role (validation is static); the runtime
    # wall in actions.py refuses before any read — tested below.
    doc = appskill.validate_pack(
        _pack_document(
            steps=[{"type": {"app": "gedit", "role": "password text", "name": "pw", "text": "x"}}],
            phrases=["type pw"],
        )
    )
    assert doc["steps"]


def test_phrase_gates(state: Any) -> None:
    with pytest.raises(SafetyRefusal, match="phrases"):
        appskill.validate_pack(_pack_document(phrases=[]))
    with pytest.raises(SafetyRefusal, match="phrases"):
        appskill.validate_pack(_pack_document(phrases=[f"p{i}" for i in range(9)]))
    with pytest.raises(SafetyRefusal, match="single line"):
        appskill.validate_pack(_pack_document(phrases=["two\nlines"]))
    with pytest.raises(SafetyRefusal, match="valid regex"):
        appskill.validate_pack(_pack_document(phrases=["save (my file"]))
    # non-anchored phrases are auto-anchored
    ok = appskill.validate_pack(_pack_document(phrases=["save my gedit file"]))
    assert ok["phrases"] == ["^save my gedit file$"]  # type: ignore[index]


def test_step_gates(state: Any) -> None:
    with pytest.raises(SafetyRefusal, match="exactly one key"):
        appskill.validate_pack(_pack_document(steps=[{"key": "ctrl-s", "focus": "x"}]))
    with pytest.raises(SafetyRefusal, match="unknown kind"):
        appskill.validate_pack(_pack_document(steps=[{"shell": "rm -rf /"}]))
    with pytest.raises(SafetyRefusal, match="steps"):
        appskill.validate_pack(_pack_document(steps=[]))
    with pytest.raises(SafetyRefusal, match="steps"):
        appskill.validate_pack(_pack_document(steps=[{"key": "k"}] * 13))
    with pytest.raises(SafetyRefusal, match="combo"):
        appskill.validate_pack(_pack_document(steps=[{"key": "ctrl;alt"}]))
    with pytest.raises(SafetyRefusal, match="text"):
        appskill.validate_pack(
            _pack_document(
                steps=[
                    {"type": {"app": "gedit", "role": "text", "name": "Find", "text": "x" * 201}}
                ]
            )
        )


# --------------------------------------------------------------------------
# install + receipt (fail-closed load)
# --------------------------------------------------------------------------


def test_install_is_atomic_with_receipt(installed: dict[str, Any], state: Any) -> None:
    pack_file = state / "appskills" / "gedit-save.app-skill.json"
    receipt_file = state / "appskills" / "gedit-save.receipt.json"
    assert pack_file.exists() and receipt_file.exists()
    digest = hashlib.sha256(pack_file.read_bytes()).hexdigest()
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert receipt["sha256"] == digest == installed["sha256"]
    # deterministic canonical bytes: re-install yields identical digest
    again = appskill.install_pack(_pack_document())
    assert again["sha256"] == installed["sha256"]


def test_drifted_pack_fails_closed(installed: dict[str, Any]) -> None:
    path = appskill.pack_path("gedit-save")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["steps"][1] = {"key": "ctrl-q"}  # owner never approved this
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert appskill.load_pack("gedit-save") is None
    assert appskill.match_pack("save my gedit file") is None


def test_missing_receipt_fails_closed(installed: dict[str, Any]) -> None:
    appskill.receipt_path("gedit-save").unlink()
    assert appskill.load_pack("gedit-save") is None


def test_removal_abstains(installed: dict[str, Any]) -> None:
    assert appskill.remove_pack("gedit-save") == 2
    assert appskill.load_pack("gedit-save") is None
    assert appskill.remove_pack("gedit-save") == 0


def test_match_pack_is_anchored_and_collapsed(installed: dict[str, Any]) -> None:
    assert appskill.match_pack("save my gedit file") is not None
    assert appskill.match_pack("  save   my gedit file  ") is not None
    assert appskill.match_pack("please save my gedit file now") is None
    assert appskill.match_pack("save my gedit fil") is None


# --------------------------------------------------------------------------
# gui.app playbook: match, build shapes, verify
# --------------------------------------------------------------------------


def _gui_app() -> Any:
    return next(pb for pb in PLAYBOOKS if pb.id == "gui.app")


def test_gui_app_registered_before_gui_launch() -> None:
    ids = [pb.id for pb in PLAYBOOKS]
    assert ids.index("gui.app") < ids.index("gui.launch")


def test_gui_app_matches_pack_phrase(installed: dict[str, Any]) -> None:
    matched = match_intent("save my gedit file")
    assert matched is not None and matched[0].id == "gui.app"
    assert matched[1] == {"pack": "gedit-save"}


def test_gui_app_abstains_without_packs(state: Any) -> None:
    # D5: absent packs -> the matcher abstains (never guesses)
    assert match_intent("save my gedit file") is None


def test_no_shadow_gui_launch_phrases(state: Any, installed: dict[str, Any]) -> None:
    # gui.launch's own vocabulary is untouched even with a pack installed
    matched = match_intent("open firefox")
    assert matched is not None and matched[0].id == "gui.launch"


def test_gui_launch_still_wins_its_own_intent(state: Any) -> None:
    # with NO packs installed, a plain "run gedit" belongs to gui.launch
    matched = match_intent("run gedit")
    assert matched is not None and matched[0].id == "gui.launch"


def test_pack_phrase_beats_the_gui_launch_fallback(installed: dict[str, Any]) -> None:
    # "open gedit" alone is a gui.launch launch; the taught phrase routes to
    # the pack because gui.app is registered first and matches exactly
    assert match_intent("save my gedit file")[0].id == "gui.app"
    assert match_intent("open gedit")[0].id == "gui.launch"


def test_build_argv_shapes(installed: dict[str, Any]) -> None:
    steps = _gui_app().build({"pack": "gedit-save"}, None)  # type: ignore[arg-type]
    assert [s.tier for s in steps] == [Tier.T2] * 4
    # 1. detached launch
    assert steps[0].argv == ("setsid", "--fork", "gedit", "/home/owner/notes.txt")
    assert steps[0].detach is True
    # 2. API text write through the module CLI
    assert steps[1].argv[:6] == (
        sys.executable,
        "-m",
        "jarvis.gui.action_exec",
        "--app",
        "gedit",
        "--role",
    )
    assert "--text" in steps[1].argv and "hello" in steps[1].argv
    assert steps[1].timeout_s == 60.0
    # 3. keyboard last-resort
    assert steps[2].argv == ("ydotool", "key", "ctrl-s")
    # 4. published action by name
    assert steps[3].argv[-2:] == ("--action", "click")
    assert "Save" in steps[3].argv


def test_build_without_launch_omits_the_step(state: Any) -> None:
    appskill.install_pack(_pack_document(app=None))
    steps = _gui_app().build({"pack": "gedit-save"}, None)  # type: ignore[arg-type]
    assert all("setsid" not in s.argv for s in steps)


def test_build_fails_closed_on_drift(installed: dict[str, Any]) -> None:
    path = appskill.pack_path("gedit-save")
    path.write_text(path.read_text(encoding="utf-8").replace("ctrl-s", "ctrl-q"), encoding="utf-8")
    with pytest.raises(SafetyRefusal, match="drifted"):
        _gui_app().build({"pack": "gedit-save"}, None)  # type: ignore[arg-type]


def test_build_fails_closed_on_missing(state: Any) -> None:
    with pytest.raises(SafetyRefusal, match="missing or its receipt"):
        _gui_app().build({"pack": "never-taught"}, None)  # type: ignore[arg-type]


def test_verify_uses_the_last_pack_step(installed: dict[str, Any]) -> None:
    from jarvis.execution.runner import ExecResult

    pb = _gui_app()
    ok = pb.verify(
        {},
        None,
        None,
        [  # type: ignore[arg-type]
            ExecResult(exit_code=0, stdout_tail="ok", stderr_tail=""),
            ExecResult(exit_code=1, stdout_tail="", stderr_tail="boom"),
        ],
    )
    assert ok.ok is False
    assert "boom" in str(ok.checks)  # the failing step's stderr is disclosed


# --------------------------------------------------------------------------
# jarvis.gui.actions: walls before reads
# --------------------------------------------------------------------------


def test_find_node_resolves_role_and_name() -> None:
    found = find_node(_tree(), app="gedit", role="push button", name="Save")
    assert found.role == "push button"
    found = find_node(_tree(), app="GEDIT", role="Text", name=" find ")
    assert found.name == "find"


def test_find_node_blocked_app_is_refused_before_the_tree_is_read() -> None:
    with pytest.raises(ActionRefused, match="blocked list"):
        find_node(_TrapDesktop(), app="keepassxc", role="push button", name="OK")


def test_find_node_password_role_refused_before_name_read() -> None:
    # the password field sits BEFORE the target in the walk order: the wall
    # must fire before the walk reaches (and reads) anything past it
    tree = _StubDesktop(
        [
            _StubNode(
                "gedit",
                "application",
                children=[
                    _StubNode("secret", "password text"),
                    _StubNode("Save", "push button", action=_StubAction(["click"])),
                ],
            )
        ]
    )
    with pytest.raises(ActionRefused, match="password"):
        find_node(tree, app="gedit", role="push button", name="Save")


def test_find_node_not_found_is_honest() -> None:
    with pytest.raises(ActionRefused, match="no node matching"):
        find_node(_tree(), app="gedit", role="push button", name="Reload")


def test_find_node_depth_budget_holds() -> None:
    deep: _StubNode = _StubNode("leaf", "push button", action=_StubAction(["click"]))
    for _ in range(8):  # deeper than MAX_DEPTH (4)
        deep = _StubNode("w", "frame", children=[deep])
    tree = _StubDesktop([_StubNode("gedit", "application", children=[deep])])
    with pytest.raises(ActionRefused, match="no node matching"):
        find_node(tree, app="gedit", role="push button", name="leaf")


def test_list_and_do_actions_are_name_indexed() -> None:
    node = find_node(_tree(), app="gedit", role="push button", name="Save")
    action = node.node
    assert action is not None
    assert do_named_action(action, "CLICK") == "click"
    with pytest.raises(ActionRefused, match="not published"):
        do_named_action(action, "delete-everything")


def test_set_node_text_boundaries() -> None:
    node = find_node(_tree(), app="gedit", role="text", name="Find")
    target = node.node
    assert target is not None
    assert set_node_text(target, "hello world").startswith("text set")
    with pytest.raises(ActionRefused, match=r"1\.\.200"):
        set_node_text(target, "")
    with pytest.raises(ActionRefused, match=r"1\.\.200"):
        set_node_text(target, "x" * 201)
    with pytest.raises(ActionRefused, match="control characters"):
        set_node_text(target, "bad\x00text")


# --------------------------------------------------------------------------
# action_exec module CLI: fixed argv, one JSON line, exit 0/2/3
# --------------------------------------------------------------------------


@pytest.fixture()
def fake_pyatspi(monkeypatch: pytest.MonkeyPatch) -> list[_StubNode]:
    """Install a pyatspi module stub and return the app children."""
    extras: dict[str, _StubNode] = {}

    class _Registry:
        @staticmethod
        def getDesktop(i: int) -> _StubDesktop:
            return _tree(**extras)

    import types

    monkeypatch.setitem(sys.modules, "pyatspi", types.SimpleNamespace(Registry=_Registry))
    return extras


def test_action_exec_success_exit0(fake_pyatspi: Any, capsys: pytest.CaptureFixture[str]) -> None:
    from jarvis.gui.action_exec import main

    rc = main(["--app", "gedit", "--role", "push button", "--name", "Save", "--action", "click"])
    assert rc == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(line) == {"ok": True, "performed": "click"}


def test_action_exec_text_exit0(fake_pyatspi: Any, capsys: pytest.CaptureFixture[str]) -> None:
    from jarvis.gui.action_exec import main

    rc = main(["--app", "gedit", "--role", "text", "--name", "Find", "--text", "typed by the pack"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out.strip())["ok"] is True


def test_action_exec_not_found_exit3(fake_pyatspi: Any, capsys: pytest.CaptureFixture[str]) -> None:
    from jarvis.gui.action_exec import main

    rc = main(["--app", "gedit", "--role", "push button", "--name", "Nope", "--action", "click"])
    assert rc == 3
    assert json.loads(capsys.readouterr().out.strip())["ok"] is False


def test_action_exec_action_not_published_exit3(fake_pyatspi: Any) -> None:
    from jarvis.gui.action_exec import main

    rc = main(["--app", "gedit", "--role", "push button", "--name", "Save", "--action", "teleport"])
    assert rc == 3


def test_action_exec_blocked_app_exit2(
    fake_pyatspi: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.gui.action_exec import main

    class _TrapRegistry:
        @staticmethod
        def getDesktop(i: int) -> _StubDesktop:
            return _TrapDesktop()

    import types

    monkeypatch.setitem(sys.modules, "pyatspi", types.SimpleNamespace(Registry=_TrapRegistry))
    rc = main(["--app", "keepassxc", "--role", "push button", "--name", "OK", "--action", "click"])
    assert rc == 2
    assert json.loads(capsys.readouterr().out.strip())["refused"]


# --------------------------------------------------------------------------
# CLI: jarvis app-skill wizard | list | show | remove
# --------------------------------------------------------------------------


def _cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, str, str]:
    from jarvis.cli.app import _cmd_appskill

    class _NS:
        pass

    ns = _NS()
    ns.appskill_command = args[0]
    ns.file = args[1] if len(args) > 1 else ""
    ns.pack_id = args[1] if len(args) > 1 else ""
    rc = _cmd_appskill(ns)  # type: ignore[arg-type]
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_wizard_installs_and_prints_receipt(
    state: Any,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pack_file = tmp_path / "gedit.app-skill.json"
    pack_file.write_text(json.dumps(_pack_document()), encoding="utf-8")
    rc, out, err = _cli(monkeypatch, capsys, "wizard", str(pack_file))
    assert rc == 0, err
    assert "receipt sha256" in out and "4 step(s) constructed" in out
    # second teach = replacement notice
    rc, out, err = _cli(monkeypatch, capsys, "wizard", str(pack_file))
    assert rc == 0 and "replacing existing pack" in out


def test_cli_wizard_refuses_bad_pack(
    state: Any,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pack_file = tmp_path / "bad.json"
    pack_file.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    rc, _out, err = _cli(monkeypatch, capsys, "wizard", str(pack_file))
    assert rc == 2 and "refused" in err


def test_cli_wizard_bad_json_is_an_error_not_a_crash(
    state: Any,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pack_file = tmp_path / "broken.json"
    pack_file.write_text("{not json", encoding="utf-8")
    rc, _out, err = _cli(monkeypatch, capsys, "wizard", str(pack_file))
    assert rc == 2 and "error" in err


def test_cli_list_show_remove_roundtrip(
    state: Any,
    installed: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc, out, _ = _cli(monkeypatch, capsys, "list")
    assert rc == 0 and "gedit-save" in out
    rc, out, _ = _cli(monkeypatch, capsys, "show", "gedit-save")
    assert rc == 0 and '"id": "gedit-save"' in out
    rc, out, err = _cli(monkeypatch, capsys, "show", "missing-pack")
    assert rc == 2 and "drifted" in err
    rc, out, _ = _cli(monkeypatch, capsys, "remove", "gedit-save")
    assert rc == 0 and "removed" in out
    rc, out, _ = _cli(monkeypatch, capsys, "list")
    assert rc == 0 and "gedit-save" not in out
    rc, out, _ = _cli(monkeypatch, capsys, "remove", "gedit-save")
    assert rc == 0 and "nothing to remove" in out


# --------------------------------------------------------------------------
# D5: the hint catalog pins exactly 57 (gui.app exempt, owner-taught)
# --------------------------------------------------------------------------


def test_gui_app_has_no_static_hint() -> None:
    from jarvis.planner.intent_hints import INTENT_HINTS

    assert "gui.app" not in INTENT_HINTS
    assert len(INTENT_HINTS) == 57
