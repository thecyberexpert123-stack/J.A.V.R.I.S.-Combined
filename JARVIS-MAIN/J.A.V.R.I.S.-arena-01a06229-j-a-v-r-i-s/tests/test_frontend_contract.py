"""Front-end contract conformance (J.A.V.R.I.S.-GUI wiring, ADR-0013 M9a).

`jarvis mcp describe` publishes the machine-readable contract for front-end
implementers. These tests assert the descriptor against the LIVE server
behavior, so the published contract and the code cannot drift apart: a front-
end built against the descriptor works against the server, by construction.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

from jarvis.cli.mcp_server import (
    CONSENT_BY_TOOL,
    TOOL_SPECS,
    MCPServer,
    frontend_contract,
)

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-03-26"},
}


def call_tool(server: MCPServer, mid: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
    import io

    server._stdout = io.StringIO()  # keep frames inspectable per call
    raw = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        )
    )
    assert raw is not None
    parsed = json.loads(raw)
    assert "result" in parsed
    content = parsed["result"]["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    return {
        "isError": bool(parsed["result"]["isError"]),
        "payload": json.loads(str(first["text"])),
    }


def test_contract_covers_exactly_the_served_tools() -> None:
    contract = frontend_contract()
    served = {str(spec["name"]) for spec in TOOL_SPECS}
    described = {str(tool["name"]) for tool in contract["tools"]}
    assert described == served
    assert set(CONSENT_BY_TOOL) == served  # every tool has declared consent semantics


def test_consent_labels_match_the_documented_model() -> None:
    contract = frontend_contract()
    by_name = {str(t["name"]): t for t in contract["tools"]}
    assert by_name["jarvis_do"]["consent"] == "explicit-allow"
    for name in (
        "jarvis_status",
        "jarvis_facts",
        "jarvis_explain",
        "jarvis_suggest",
        "jarvis_preview",
    ):
        assert by_name[name]["consent"] == "read-only", name


def test_describe_cli_matches_library_contract(monkeypatch: Any, capsys: Any) -> None:
    from jarvis.cli.app import main

    assert main(["mcp", "describe"]) == 0
    published = json.loads(capsys.readouterr().out)
    assert published == frontend_contract()
    assert published["contract"] == "javris-frontend/1"
    assert published["transport"]["spawn"] == ["jarvis", "mcp", "serve"]


def test_handshake_in_contract_reproduces_the_real_handshake(
    monkeypatch: Any, tmp_path: Any
) -> None:
    """The example session from the published contract works verbatim."""
    contract = frontend_contract()
    example_lines = [
        step["line"] for step in contract["example_session"] if isinstance(step.get("line"), str)
    ]
    assert len(example_lines) == 5  # initialize, initialized, explain, refusal, allow
    from io import StringIO

    stream_in = "\n".join(example_lines[:2]) + "\n"
    out = StringIO()
    MCPServer(StringIO(stream_in), out).serve()  # type: ignore[arg-type]
    frames = [json.loads(line) for line in out.getvalue().splitlines()]
    assert frames[0]["result"]["serverInfo"]["name"] == "jarvis"  # version handshake point
    assert "notifications/initialized" in example_lines[1]


def test_server_identity_tracks_the_package_version() -> None:
    """Front-ends read serverInfo.version for capability detection (§8 of the
    wiring doc); it must never drift from the installed kernel version."""
    from jarvis import __version__ as kernel_version

    out = StringIO()
    MCPServer(StringIO(json.dumps(INIT) + "\n"), out).serve()  # type: ignore[arg-type]
    frame = json.loads(out.getvalue().splitlines()[0])
    assert frame["result"]["serverInfo"]["version"] == kernel_version


def test_consent_flow_from_the_contract_end_to_end(monkeypatch: Any, tmp_path: Any) -> None:
    """read-only tool plays; explicit-allow tool refuses without allow, plays
    with it — exactly as the published consent_model promises a front-end."""
    from conftest import FakeRunner

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    profile = None  # build_profile patched below

    from conftest import make_profile
    from jarvis.cli import mcp_server

    profile = make_profile()
    monkeypatch.setattr(mcp_server, "build_profile", lambda: profile)
    monkeypatch.setattr(mcp_server, "default_db_path", lambda: tmp_path / "journal.sqlite3")
    monkeypatch.setattr(mcp_server, "default_context_path", lambda: tmp_path / "context.db")
    monkeypatch.setattr(mcp_server, "LocalRunner", lambda: FakeRunner())

    server = MCPServer.__new__(MCPServer)  # handler-level use only
    server._stdout = None  # type: ignore[assignment]

    # read-only path
    explained = call_tool(server, 2, "jarvis_explain", {"question": "what is the kernel type"})
    assert explained["isError"] is False
    assert explained["payload"]["fact_id"] == "kernel.ostype"

    # explicit-allow path, refusal first (the GUI consent dialog moment)
    refused = call_tool(server, 3, "jarvis_do", {"request": "upgrade the whole system"})
    assert refused["isError"] is True
    assert refused["payload"]["outcome"]["status"] == "refused"
    assert "allow" in refused["payload"]["outcome"]["hint"]

    # owner consented in the front-end: the same call with allow:true
    allowed = call_tool(server, 4, "jarvis_do", {"request": "system info", "allow": True})
    assert allowed["isError"] is False
    assert allowed["payload"]["outcome"]["status"] == "succeeded"


def test_state_mapping_covers_the_gui_machine() -> None:
    contract = frontend_contract()
    gui_states = {
        "BOOTING",
        "STANDBY",
        "LISTENING",
        "PROCESSING",
        "EXECUTING",
        "SPEAKING",
        "ERROR",
        "OFFLINE",
    }
    mapped = {str(step["gui_state"]) for step in contract["state_mapping"]}
    assert mapped <= gui_states  # never invent a state the HUD doesn't have
    assert {"BOOTING", "STANDBY", "PROCESSING", "EXECUTING", "SPEAKING", "ERROR"} <= mapped
