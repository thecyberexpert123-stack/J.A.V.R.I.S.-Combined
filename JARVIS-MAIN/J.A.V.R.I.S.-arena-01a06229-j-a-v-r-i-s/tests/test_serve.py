"""ADR-0018 hybrid residency: loopback doorway, token auth, kernel parity, opt-in install.

The HTTP surface must be transport-only: every tool call below crosses the
same handlers (and therefore the same tiers/consent/journal) as the MCP stdio
surface and the CLI. Residency is opt-in and fully reversible; packaging
never enables it.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from jarvis.cli.serve import (
    build_server,
    desktop_content,
    desktop_path,
    ensure_token,
    install,
    status,
    token_path,
    uninstall,
    unit_content,
    unit_path,
)
from jarvis.safety.tiers import SafetyRefusal


@pytest.fixture()
def doorway():
    """A live doorway on an ephemeral loopback port; yields (base_url, token)."""
    token = "test-token-abcdef"
    server = build_server("127.0.0.1", 0, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield f"http://127.0.0.1:{port}", token
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# --------------------------------------------------------------------------
# transport hardening (ADR-0018 D2)
# --------------------------------------------------------------------------


def test_health_needs_no_auth_and_leaks_nothing(doorway) -> None:
    base, _ = doorway
    code, payload = _request(f"{base}/v1/health")
    assert code == 200 and payload == {"ok": True}


def test_tools_require_bearer_token(doorway) -> None:
    base, _ = doorway
    code, _ = _request(
        f"{base}/v1/tools/jarvis_status",
        method="POST",
        body=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert code == 401
    code, _ = _request(
        f"{base}/v1/tools/jarvis_status",
        method="POST",
        body=b"{}",
        headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
    )
    assert code == 401


def test_unknown_tool_is_404(doorway) -> None:
    base, token = doorway
    code, _ = _request(
        f"{base}/v1/tools/jarvis_exec",
        method="POST",
        body=b"{}",
        headers=_auth(token),
    )
    assert code == 404  # no exec tool exists — the doorway has no passthrough


def test_wrong_method_on_tool_path_is_405(doorway) -> None:
    base, _ = doorway
    code, _ = _request(f"{base}/v1/tools/jarvis_status")
    assert code == 405


def test_post_health_is_405(doorway) -> None:
    base, _ = doorway
    code, _ = _request(f"{base}/v1/health", method="POST", body=b"{}")
    assert code == 405


def test_wrong_host_header_is_refused(doorway) -> None:
    """DNS-rebinding defense: the Host must be loopback, not a rebound domain."""
    base, token = doorway
    code, _ = _request(
        f"{base}/v1/tools/jarvis_status",
        method="POST",
        body=b"{}",
        headers={"Host": "evil.example:8777", **_auth(token)},
    )
    assert code == 421


def test_oversize_body_is_413(doorway) -> None:
    base, token = doorway
    code, _ = _request(
        f"{base}/v1/tools/jarvis_explain",
        method="POST",
        body=b'{"question": "' + b"x" * (65 * 1024) + b'"}',
        headers=_auth(token),
    )
    assert code == 413


def test_bad_json_is_400(doorway) -> None:
    base, token = doorway
    code, _ = _request(
        f"{base}/v1/tools/jarvis_status",
        method="POST",
        body=b"{not json",
        headers=_auth(token),
    )
    assert code == 400


def test_non_json_content_type_is_415(doorway) -> None:
    """Text/plain simple requests are how browsers skip CORS preflight — refused."""
    base, token = doorway
    code, _ = _request(
        f"{base}/v1/tools/jarvis_status",
        method="POST",
        body=b"{}",
        headers={**_auth(token), "Content-Type": "text/plain"},
    )
    assert code == 415


def test_options_gets_no_cors_answer(doorway) -> None:
    base, _ = doorway
    code, _ = _request(f"{base}/v1/tools/jarvis_do", method="OPTIONS")
    assert code == 501  # no preflight, no cross-origin web usage


def test_non_loopback_bind_is_refused_never_sanitized() -> None:
    with pytest.raises(SafetyRefusal):
        build_server("0.0.0.0", 8777, "token")


def _auth(token: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# kernel parity through the doorway (same handlers as MCP stdio)
# --------------------------------------------------------------------------


def test_status_roundtrip(doorway) -> None:
    base, token = doorway
    code, payload = _request(
        f"{base}/v1/tools/jarvis_status",
        method="POST",
        body=b"{}",
        headers=_auth(token),
    )
    assert code == 200 and payload["isError"] is False
    result = payload["result"]
    assert isinstance(result, dict) and "distro_id" in result


def test_explain_outside_kb_is_an_in_band_refusal(doorway) -> None:
    base, token = doorway
    code, payload = _request(
        f"{base}/v1/tools/jarvis_explain",
        method="POST",
        body=json.dumps({"question": "what is the airspeed of an unladen swallow"}).encode(),
        headers=_auth(token),
    )
    assert code == 200 and payload["isError"] is True


def test_do_unmatched_request_is_refused_not_guessed(doorway) -> None:
    base, token = doorway
    code, payload = _request(
        f"{base}/v1/tools/jarvis_do",
        method="POST",
        body=json.dumps({"request": "shutdown now"}).encode(),
        headers=_auth(token),
    )
    assert code == 200
    outcome = payload["result"]["outcome"]
    assert outcome["status"] == "refused"


def test_do_t2_without_allow_is_refused_with_hint(doorway) -> None:
    base, token = doorway
    code, payload = _request(
        f"{base}/v1/tools/jarvis_do",
        method="POST",
        body=json.dumps({"request": "stop nginx"}).encode(),
        headers=_auth(token),
    )
    assert code == 200 and payload["isError"] is True
    result = payload["result"]
    assert result["outcome"]["status"] == "refused"
    error = str(result["outcome"].get("error") or "")
    if "approval" in error:  # approval-class refusal → MCP-parity hint present
        hint = str(result.get("hint") or result["outcome"].get("hint") or "")
        assert "allow" in hint
    else:  # environment-class refusal (e.g. no systemd here) — honest either way
        assert error


def test_preview_is_read_only_and_reports_blast_radius(doorway) -> None:
    base, token = doorway
    code, payload = _request(
        f"{base}/v1/tools/jarvis_preview",
        method="POST",
        body=json.dumps({"request": "list files in /tmp"}).encode(),
        headers=_auth(token),
    )
    assert code == 200 and payload["isError"] is False
    assert payload["result"]["preview"]["playbook"] == "fs.list"
    assert payload["result"]["blast_radius"] is not None


# --------------------------------------------------------------------------
# residency: opt-in install, honest status, complete uninstall (D3/D4)
# --------------------------------------------------------------------------


def test_unit_content_is_loopbound_and_secret_free() -> None:
    unit = unit_content("/usr/bin/python3", 8777)
    assert "--bind 127.0.0.1" in unit
    assert "WantedBy=default.target" in unit
    assert "Bearer" not in unit and "--token" not in unit  # no secret material


def test_desktop_content_launches_gui_contract_side() -> None:
    content = desktop_content()
    assert "Exec=jarvis-gui" in content
    assert content.startswith("[Desktop Entry]")


def test_install_writes_unit_and_protected_token(tmp_path: Path) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path / "state")}
    code = install(8777, with_gui=False, home=tmp_path, env=env, systemctl_available=False)
    assert code == 0
    unit = unit_path(tmp_path)
    assert unit.exists() and "127.0.0.1" in unit.read_text(encoding="utf-8")
    token = token_path(env)
    assert token.exists() and oct(token.stat().st_mode)[-3:] == "600"
    assert not desktop_path(tmp_path).exists()  # --with-gui absent → no desktop file


def test_install_with_gui_missing_frontend_refuses(tmp_path: Path) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path / "state")}
    with pytest.raises(SafetyRefusal):
        install(8777, with_gui=True, home=tmp_path, env=env, gui_probe=False)
    assert not unit_path(tmp_path).exists()  # validated BEFORE anything is written


def test_install_with_gui_present_writes_autostart(tmp_path: Path) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path / "state")}
    code = install(
        8777,
        with_gui=True,
        home=tmp_path,
        env=env,
        systemctl_available=False,
        gui_probe=True,
    )
    assert code == 0
    assert desktop_path(tmp_path).exists()


def test_uninstall_removes_every_piece(tmp_path: Path) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path / "state")}
    install(8777, with_gui=True, home=tmp_path, env=env, systemctl_available=False, gui_probe=True)
    code = uninstall(tmp_path, systemctl_available=False, env=env)
    assert code == 0
    assert not unit_path(tmp_path).exists()
    assert not desktop_path(tmp_path).exists()
    assert not token_path(env).exists()


def test_uninstall_without_install_is_honest(tmp_path: Path) -> None:
    assert uninstall(tmp_path, systemctl_available=False) == 0  # "nothing to remove"


def test_status_reports_absent_pieces(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path / "state")}
    assert status(tmp_path, env=env) == 0
    out = capsys.readouterr().out
    assert "absent" in out
    assert "on-demand" in out


def test_ensure_token_generates_once_and_reuses(tmp_path: Path) -> None:
    env = {"JARVIS_STATE_DIR": str(tmp_path)}
    first = ensure_token(env)
    assert first
    assert ensure_token(env) == first
    token_file = token_path(env)
    token_file.write_text("  \n", encoding="utf-8")  # corrupt → regenerated
    assert ensure_token(env) not in ("", first)
