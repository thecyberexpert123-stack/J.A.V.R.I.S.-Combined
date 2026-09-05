"""ADR-0022: guarded desktop awareness — the read-only tier, fail-closed."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest

from jarvis.desktop.guards import (
    BLOCKED_APPS,
    PASSWORD_ROLES,
    hygiene,
    is_blocked_app,
    is_sensitive_name,
)
from jarvis.desktop.read import (
    MAX_NODES,
    DesktopAudit,
    guarded_desktop_walk,
    guarded_titles,
    read_desktop,
)
from jarvis.safety.tiers import SafetyRefusal

# --------------------------------------------------------------------------
# stubs: duck-typed AT-SPI nodes with read/mutation accounting
# --------------------------------------------------------------------------


class _N:
    def __init__(self, role: str, name: str | None = None, children: list[_N] | None = None):
        self._role = role
        self._name = name
        self._children = children or []
        self.name_reads = 0
        self.mutation_calls = 0

    @property
    def name(self) -> str | None:
        self.name_reads += 1
        return self._name

    def getRoleName(self) -> str:
        return self._role

    def queryEditableText(self) -> Any:
        self.mutation_calls += 1
        raise RuntimeError("mutation attempted during a read-only walk")

    def __iter__(self) -> Any:
        return iter(self._children)


class _BoomRole:
    @property
    def name(self) -> str:
        raise AssertionError("name read on an unreadable node")

    def getRoleName(self) -> str:
        raise RuntimeError("bus died")

    def __iter__(self) -> Any:
        raise RuntimeError("bus died")


class _FakeRegistry:
    desktop_nodes: ClassVar[list[_N]] = []
    STATE_FOCUSED = 4242

    @classmethod
    def getDesktop(cls, _index: int) -> list[_N]:
        return cls.desktop_nodes


_FakeRegistry.Registry = _FakeRegistry


@pytest.fixture()
def fake_pyatspi(monkeypatch: pytest.MonkeyPatch) -> type[_FakeRegistry]:
    monkeypatch.setitem(sys.modules, "pyatspi", _FakeRegistry)  # type: ignore[dict-item]
    monkeypatch.setattr("jarvis.gui.atspi.atspi_available", lambda: True)
    _FakeRegistry.desktop_nodes = []
    return _FakeRegistry


# --------------------------------------------------------------------------
# walls: constants and pure predicates (ADR-0022 D2)
# --------------------------------------------------------------------------


def test_blocked_apps_pin() -> None:
    assert (
        frozenset(
            {
                "keepass",
                "bitwarden",
                "1password",
                "passwordsafe",
                "password safe",
                "dashlane",
                "lastpass",
                "enpass",
                "proton pass",
                "protonpass",
                "seahorse",
                "keyring",
                "kwallet",
                "polkit",
                "pkexec",
                "askpass",
                "gnome-terminal",
                "konsole",
                "xterm",
                "st",
                "urxvt",
                "alacritty",
                "kitty",
                "wezterm",
                "tilix",
                "terminator",
                "foot",
            }
        )
        == BLOCKED_APPS
    )


def test_password_roles_pin() -> None:
    assert frozenset({"password text"}) == PASSWORD_ROLES


def test_blocked_app_matching_is_case_insensitive_and_fail_closed() -> None:
    assert is_blocked_app("keepassxc")
    assert is_blocked_app("KeePassXC")
    assert is_blocked_app("org.gnomekeyring")
    assert is_blocked_app("st")  # exact: the suckless terminal
    assert is_blocked_app("gnome-terminal-server")
    assert not is_blocked_app("")
    assert not is_blocked_app("Files")
    assert not is_blocked_app("firefox")
    # the documented fail-closed bias: false-positive blocks are acceptable
    assert is_blocked_app("football manager")


def test_sensitive_names_word_boundary() -> None:
    for name in (
        "Enter your password",
        "API Key",
        "api_key",
        "Secret",
        "auth token",
        "private key",
        "CVV",
        "OTP code",
        "2FA",
        "card number",
        "PIN",
        "passphrase",
    ):
        assert is_sensitive_name(name), name
    for name in ("Author", "passport office", "Pinning tabs", "Files", "spin", "keyboard"):
        assert not is_sensitive_name(name), name


def test_hygiene_strips_controls_collapses_and_clamps() -> None:
    assert hygiene("a\x00b\t c  d") == "ab c d"  # controls stripped, not spaced
    assert hygiene("del\x7fete") == "delete"
    long = "x" * 300
    assert len(hygiene(long)) == 120
    assert hygiene(long).endswith("…")


# --------------------------------------------------------------------------
# the guarded walk (ADR-0022 D2/D3)
# --------------------------------------------------------------------------


def test_walk_blocks_apps_and_never_descends() -> None:
    hidden_child = _N("frame", name="Database Vault")
    files = _N("application", name="Files", children=[_N("frame", name="Home")])
    keepass = _N("application", name="KeePassXC", children=[hidden_child])
    result = guarded_desktop_walk([files, keepass])
    assert "[withheld: application 'KeePassXC' is on the blocked list]" in result.lines
    assert hidden_child.name_reads == 0 and hidden_child.getRoleName() == "frame"
    assert result.apps_blocked == ("KeePassXC",)
    assert result.nodes_read == 2  # Files + its frame only


def test_walk_withholds_password_fields_before_name_read() -> None:
    pw = _N("password text", name="hunter2")
    app = _N("application", name="Files", children=[_N("frame", name="Vault", children=[pw])])
    result = guarded_desktop_walk([app])
    assert "[withheld: password text field]" in result.lines
    assert pw.name_reads == 0  # wall 2: the name is never read
    assert result.roles_withheld == 1
    assert "hunter2" not in "\n".join(result.lines)


def test_walk_redacts_sensitive_names() -> None:
    field = _N("text", name="API key")
    app = _N("application", name="Files", children=[_N("frame", name="Form", children=[field])])
    result = guarded_desktop_walk([app])
    assert any("(redacted: sensitive field)" in line for line in result.lines)
    assert result.names_redacted == 1
    assert "API key" not in "\n".join(result.lines)


def test_walk_hygienes_names() -> None:
    app = _N("application", name="Files", children=[_N("frame", name="bad\x00title")])
    result = guarded_desktop_walk([app])
    assert any("badtitle" in line for line in result.lines)


def test_node_budget_truncates_honestly() -> None:
    # a WIDE tree: one app with more children than the budget (a deep chain
    # would only prove the depth cap, which has its own test above)
    app = _N("application", name="Files", children=[_N("text") for _ in range(MAX_NODES + 100)])
    result = guarded_desktop_walk([app])
    assert result.truncated is True
    assert result.nodes_read == MAX_NODES
    assert "[node budget exhausted — truncated]" in result.lines


def test_depth_cap_stops_the_descent() -> None:
    leaf = _N("text", name="deep secret")
    node = leaf
    for _ in range(10):
        node = _N("application", name="Files", children=[node])
    result = guarded_desktop_walk([node])
    assert leaf.name_reads == 0  # beyond depth 4: never visited
    assert result.nodes_read == 4  # app + three permitted levels


def test_unreadable_node_is_honest_and_walk_continues() -> None:
    app = _N("application", name="Files", children=[_N("frame", name="Home")])
    result = guarded_desktop_walk([_BoomRole(), app])
    assert "[unreadable application node]" in result.lines
    assert any("frame: Home" in line for line in result.lines)


def test_walk_is_read_only_by_construction() -> None:
    app = _N(
        "application",
        name="Files",
        children=[
            _N("frame", name="Home", children=[_N("password text", name="x"), _N("text", name="t")])
        ],
    )
    guarded_desktop_walk([app])
    for node in (app, *app._children, *app._children[0]._children):
        assert node.mutation_calls == 0


def test_read_result_is_frozen() -> None:
    result = guarded_desktop_walk([])
    with pytest.raises((AttributeError, TypeError)):
        result.nodes_read = 99  # type: ignore[misc]


# --------------------------------------------------------------------------
# guarded titles + the ADR-0010 contract rewire (ADR-0022 D5)
# --------------------------------------------------------------------------


def test_guarded_titles_excludes_blocked_and_redacts() -> None:
    files = _N("application", name="Files", children=[_N("frame", name="Home")])
    keepass = _N("application", name="KeePassXC", children=[_N("frame", name="Vault")])
    secret = _N("application", name="Editor", children=[_N("frame", name="Enter your password")])
    titles, reason = guarded_titles([files, keepass, secret])
    assert titles == ["Home", "(withheld: sensitive title)"]
    assert "1 application(s) withheld" in reason


def test_guarded_titles_ignores_non_windows_and_untitles() -> None:
    app = _N(
        "application",
        name="Files",
        children=[_N("menu", name="File"), _N("dialog", name="")],
    )
    titles, _reason = guarded_titles([app])
    assert titles == ["(untitled)"]


def test_desktop_window_titles_uses_the_guard(fake_pyatspi: type[_FakeRegistry]) -> None:
    from jarvis.gui.atspi import desktop_window_titles

    fake_pyatspi.desktop_nodes = [
        _N("application", name="Files", children=[_N("frame", name="Home")]),
        _N("application", name="keepassxc", children=[_N("frame", name="Vault")]),
    ]
    titles, reason = desktop_window_titles()
    assert titles == ["Home"]
    assert "guarded" in reason and "withheld" in reason


def test_desktop_window_titles_unavailable_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.gui import atspi as atspi_mod

    monkeypatch.setattr(atspi_mod, "atspi_available", lambda: False)
    titles, reason = atspi_mod.desktop_window_titles()
    assert titles is None and "pyatspi not installed" in reason


# --------------------------------------------------------------------------
# content-free audit (ADR-0022 D4)
# --------------------------------------------------------------------------


def test_audit_is_content_free(tmp_path: Path) -> None:
    app = _N(
        "application",
        name="Files",
        children=[_N("frame", name="SecretWindowTitle"), _N("password text", name="pw")],
    )
    result = guarded_desktop_walk([app])
    audit = DesktopAudit(tmp_path)
    audit.record_read(result, source="cli")
    raw = audit.path.read_text(encoding="utf-8")
    assert "SecretWindowTitle" not in raw
    assert "pw" not in raw
    entry = json.loads(raw.splitlines()[0])
    assert entry["kind"] == "read" and entry["source"] == "cli"
    assert entry["roles_withheld"] == 1 and entry["nodes_read"] == 3


def test_audit_source_validation(tmp_path: Path) -> None:
    audit = DesktopAudit(tmp_path)
    with pytest.raises(SafetyRefusal):
        audit.record_read(guarded_desktop_walk([]), source="agent")


def test_audit_stats_totals(tmp_path: Path) -> None:
    audit = DesktopAudit(tmp_path)
    app = _N("application", name="KeePassXC", children=[_N("frame", name="x")])
    audit.record_read(guarded_desktop_walk([app]), source="cli")
    audit.record_read(guarded_desktop_walk([]), source="gui")
    stats = audit.stats()
    assert stats["reads"] == 2
    assert stats["apps_blocked_total"] == 1
    assert stats["last_read"] is not None


# --------------------------------------------------------------------------
# read_desktop + CLI (ADR-0022 D5: on-demand, owner-issued)
# --------------------------------------------------------------------------


def test_read_desktop_unavailable_honest_and_unaudited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("jarvis.gui.atspi.atspi_available", lambda: False)
    result, reason = read_desktop()
    assert result is None and "pyatspi not installed" in reason
    assert not (tmp_path / "desktop" / "ledger.jsonl").exists()


def test_read_desktop_end_to_end_fake_pyatspi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_pyatspi: type[_FakeRegistry]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    fake_pyatspi.desktop_nodes = [
        _N("application", name="Files", children=[_N("frame", name="Home")]),
        _N("application", name="konsole", children=[_N("frame", name="shell")]),
    ]
    result, reason = read_desktop(source="cli")
    assert result is not None and reason == "guarded accessibility tree"
    assert result.apps_blocked == ("konsole",)
    entries = DesktopAudit(tmp_path).entries()
    assert len(entries) == 1 and entries[0]["apps_blocked"] == ["konsole"]


def test_cli_desktop_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_pyatspi: type[_FakeRegistry],
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    fake_pyatspi.desktop_nodes = [
        _N("application", name="Files", children=[_N("frame", name="Home")]),
        _N(
            "application",
            name="Editor",
            children=[_N("frame", name="Unlock", children=[_N("password text", name="x")])],
        ),
    ]
    assert main(["desktop", "read"]) == 0
    out = capsys.readouterr().out
    assert "frame: Home" in out
    assert "[withheld: password text field]" in out
    assert "guard summary: 0 app(s) withheld, 1 password field(s) withheld" in out
    assert "audit:" in out
    assert DesktopAudit(tmp_path).stats()["reads"] == 1


def test_cli_desktop_bare_is_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_pyatspi: type[_FakeRegistry],
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    fake_pyatspi.desktop_nodes = [_N("application", name="Files", children=[_N("frame", name="H")])]
    assert main(["desktop"]) == 0
    assert "application: Files" in capsys.readouterr().out


def test_cli_desktop_read_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("jarvis.gui.atspi.atspi_available", lambda: False)
    assert main(["desktop", "read"]) == 0
    out = capsys.readouterr().out
    assert "unavailable here" in out and "nothing was read" in out


def test_cli_desktop_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert main(["desktop", "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] is False
    assert payload["reads"] == 0 and "ledger" in payload
