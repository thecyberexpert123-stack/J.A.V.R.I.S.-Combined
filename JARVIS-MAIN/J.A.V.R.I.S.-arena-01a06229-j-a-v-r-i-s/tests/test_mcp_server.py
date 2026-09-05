"""MCP server surface (ADR-0013 M9a): protocol conformance + kernel fidelity.

Each test drives `MCPServer.handle_line` with newline-delimited JSON-RPC and
asserts on parsed responses. The kernel boundary is exercised for real:
consent refusals go through the genuine ApprovalPolicy (deterministic
non-tty stdin), execution through a scripted FakeRunner. Monkeypatching
replaces only process boundaries (profile source, journal/context paths,
runner construction) — never the code under test.
"""

from __future__ import annotations

import io
import json
from typing import Any

from conftest import FakeRunner, make_profile
from jarvis import __version__
from jarvis.cli import mcp_server
from jarvis.cli.app import _cmd_mcp_serve, build_parser
from jarvis.cli.mcp_server import MCPServer

EXPECTED_TOOLS = {
    "jarvis_status",
    "jarvis_facts",
    "jarvis_explain",
    "jarvis_suggest",
    "jarvis_preview",
    "jarvis_do",
}

INIT = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {"protocolVersion": "2025-03-26"},
}


def make_server(monkeypatch: Any, tmp_path: Any, runner: FakeRunner | None = None) -> MCPServer:
    profile = make_profile()
    monkeypatch.setenv(
        "JARVIS_STATE_DIR", str(tmp_path / "state")
    )  # canaries land here, not ~/.local
    monkeypatch.setattr(mcp_server, "build_profile", lambda: profile)
    monkeypatch.setattr(mcp_server, "default_db_path", lambda: tmp_path / "journal.sqlite3")
    monkeypatch.setattr(mcp_server, "default_context_path", lambda: tmp_path / "context.json")
    if runner is not None:
        monkeypatch.setattr(mcp_server, "LocalRunner", lambda: runner)
    return MCPServer(io.StringIO(), io.StringIO())


def call(
    server: MCPServer, mid: int, method: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    frame: dict[str, Any] = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        frame["params"] = params
    raw = server.handle_line(json.dumps(frame))
    assert raw is not None, f"request {method} produced no response"
    parsed = json.loads(raw)
    assert parsed["id"] == mid
    assert parsed["jsonrpc"] == "2.0"
    return parsed


def tool(server: MCPServer, name: str, arguments: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Invoke a tool; returns (is_error, decoded_text_payload)."""
    resp = call(server, 99, "tools/call", {"name": name, "arguments": arguments})
    assert "result" in resp, f"tool call protocol error: {resp}"
    content = resp["result"]["content"]
    assert content[0]["type"] == "text"
    return bool(resp["result"]["isError"]), json.loads(content[0]["text"])


# -- protocol ----------------------------------------------------------------


def test_initialize_echoes_version_and_identifies_server(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    resp = call(server, 1, "initialize", {"protocolVersion": "2025-03-26"})
    assert resp["result"]["protocolVersion"] == "2025-03-26"
    info = resp["result"]["serverInfo"]
    assert info["name"] == "jarvis"
    assert info["version"] == __version__
    assert "tools" in resp["result"]["capabilities"]
    assert "resources" in resp["result"]["capabilities"]


def test_initialize_falls_back_on_malformed_version(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    resp = call(server, 1, "initialize", {"protocolVersion": "not-a-date"})
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    resp2 = call(server, 2, "initialize")
    assert resp2["result"]["protocolVersion"] == "2024-11-05"


def test_ping_returns_empty_result(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    resp = call(server, 1, "ping")
    assert resp["result"] == {}


def test_tools_list_exposes_exactly_the_audited_six(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    resp = call(server, 1, "tools/list")
    tools = resp["result"]["tools"]
    assert {t["name"] for t in tools} == EXPECTED_TOOLS
    for t in tools:
        assert t["description"], f"{t['name']} missing description"
        assert t["inputSchema"]["type"] == "object"
    by_name = {t["name"]: t for t in tools}
    assert by_name["jarvis_do"]["inputSchema"]["required"] == ["request"]
    assert by_name["jarvis_do"]["inputSchema"]["properties"]["allow"] == {"type": "boolean"}


def test_notification_produces_no_response(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    raw = server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    assert raw is None
    raw = server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "no/such-notification"}))
    assert raw is None


def test_parse_error_returns_32700(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    parsed = json.loads(server.handle_line("{not json") or "{}")
    assert parsed["error"]["code"] == -32700
    assert parsed["id"] is None


def test_batch_array_is_rejected(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    parsed = json.loads(server.handle_line('[{"jsonrpc": "2.0"}]') or "{}")
    assert parsed["error"]["code"] == -32600


def test_unknown_method_returns_32601(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    parsed = json.loads(
        server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 7, "method": "prompts/list"}))
        or "{}"
    )
    assert parsed["error"]["code"] == -32601
    assert parsed["id"] == 7


def test_malformed_frame_returns_32600(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    for bad in ('{"jsonrpc": "1.0", "id": 1, "method": "ping"}', '{"jsonrpc": "2.0", "id": 2}'):
        parsed = json.loads(server.handle_line(bad) or "{}")
        assert parsed["error"]["code"] == -32600, bad


def test_resources_list_has_kb_and_journal(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    resp = call(server, 1, "resources/list")
    uris = {r["uri"] for r in resp["result"]["resources"]}
    assert uris == {"kb://facts", "journal://tasks"}


def test_resources_read_kb_and_journal(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    resp = call(server, 1, "resources/read", {"uri": "kb://facts"})
    contents = resp["result"]["contents"]
    assert contents[0]["uri"] == "kb://facts"
    payload = json.loads(contents[0]["text"])
    assert payload["count"] >= 12  # shipped KB
    resp2 = call(server, 2, "resources/read", {"uri": "journal://tasks"})
    assert json.loads(resp2["result"]["contents"][0]["text"]) == []  # fresh journal


def test_unknown_resource_uri_is_invalid_params(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    parsed = json.loads(
        server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "resources/read",
                    "params": {"uri": "file:///etc"},
                }
            )
        )
        or "{}"
    )
    assert parsed["error"]["code"] == -32602


def test_serve_loops_until_eof_with_newline_framing(monkeypatch: Any, tmp_path: Any) -> None:
    profile = make_profile()
    monkeypatch.setattr(mcp_server, "build_profile", lambda: profile)
    monkeypatch.setattr(mcp_server, "default_db_path", lambda: tmp_path / "journal.sqlite3")
    monkeypatch.setattr(mcp_server, "default_context_path", lambda: tmp_path / "context.json")
    frames = (
        json.dumps(INIT)
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"})
        + "\n"
    )
    out = io.StringIO()
    code = MCPServer(io.StringIO(frames), out).serve()
    assert code == 0
    lines = out.getvalue().splitlines()
    assert len(lines) == 3  # notification answered with silence
    assert json.loads(lines[0])["result"]["serverInfo"]["name"] == "jarvis"
    assert len(json.loads(lines[1])["result"]["tools"]) == 6
    assert json.loads(lines[2])["result"] == {}


# -- tools -------------------------------------------------------------------


def test_status_returns_fingerprint_payload(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    is_error, payload = tool(server, "jarvis_status", {})
    assert is_error is False
    assert payload["distro_id"] == "debian"
    assert payload["package_manager"] == "apt"


def test_facts_lists_cited_kb_and_filters_topic(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    is_error, payload = tool(server, "jarvis_facts", {})
    assert is_error is False
    assert payload["count"] >= 12
    first_topic = payload["facts"][0]["topic"]
    for fact in payload["facts"]:
        assert fact["sources"] >= 1  # citation is mandatory in the store
    is_error, filtered = tool(server, "jarvis_facts", {"topic": first_topic})
    assert is_error is False
    assert 0 < filtered["count"] <= payload["count"]
    assert {f["topic"] for f in filtered["facts"]} == {first_topic}


def test_explain_answers_with_citation(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    is_error, payload = tool(server, "jarvis_explain", {"question": "what is the kernel type"})
    assert is_error is False
    assert payload["fact_id"] == "kernel.ostype"
    assert payload["sources"]


def test_explain_refuses_outside_kb_without_guessing(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    is_error, payload = tool(
        server, "jarvis_explain", {"question": "who is the president of france"}
    )
    assert is_error is True
    assert payload["status"] == "refused"
    assert payload["claim"] == ""


def test_suggest_is_read_only(monkeypatch: Any, tmp_path: Any) -> None:
    runner = FakeRunner()
    server = make_server(monkeypatch, tmp_path, runner)
    is_error, payload = tool(server, "jarvis_suggest", {})
    assert is_error is False
    assert isinstance(payload["suggestions"], list)
    assert "read-only" in payload["note"]
    assert runner.calls == []  # suggestions never execute anything


def test_preview_plans_but_never_executes_or_consents(monkeypatch: Any, tmp_path: Any) -> None:
    runner = FakeRunner()
    server = make_server(monkeypatch, tmp_path, runner)
    is_error, payload = tool(server, "jarvis_preview", {"request": "install htop"})
    assert is_error is False
    preview = payload["preview"]
    assert preview["steps"], "dry-run plan should contain steps"
    radius = payload["blast_radius"]
    assert radius["max_tier"] >= 1
    assert runner.calls == []  # nothing executed, nothing asked


def test_do_t2_without_allow_refuses_and_executes_nothing(monkeypatch: Any, tmp_path: Any) -> None:
    runner = FakeRunner()
    server = make_server(monkeypatch, tmp_path, runner)
    is_error, payload = tool(server, "jarvis_do", {"request": "upgrade the whole system"})
    assert is_error is True
    outcome = payload["outcome"]
    assert outcome["status"] == "refused"
    assert "explicit approval" in outcome["error"]
    assert "allow" in outcome["hint"]  # refusal restated in MCP terms
    assert runner.calls == []  # the refusal happened before any step ran


def test_do_with_allow_true_executes_through_kernel(monkeypatch: Any, tmp_path: Any) -> None:
    runner = FakeRunner()
    server = make_server(monkeypatch, tmp_path, runner)
    is_error, payload = tool(server, "jarvis_do", {"request": "system info", "allow": True})
    assert is_error is False
    assert payload["outcome"]["status"] == "succeeded"
    assert runner.calls, "read-only playbook should have run its steps"


def test_do_unmatched_request_refused_not_guessed(monkeypatch: Any, tmp_path: Any) -> None:
    runner = FakeRunner()
    server = make_server(monkeypatch, tmp_path, runner)
    is_error, payload = tool(server, "jarvis_do", {"request": "say hello to my little friend"})
    assert is_error is True
    assert payload["outcome"]["status"] == "refused"
    assert "pkg.install" in payload["outcome"]["hint"]
    assert runner.calls == []


def test_do_maps_allow_onto_the_real_approval_policy(monkeypatch: Any, tmp_path: Any) -> None:
    seen: list[dict[str, bool]] = []
    real_policy = mcp_server.ApprovalPolicy

    class RecordingPolicy(real_policy):  # forwards to the genuine gate
        def __init__(self, yes: bool = False, silent: bool = False, stdin: Any = None) -> None:
            seen.append({"yes": yes, "silent": silent})
            super().__init__(yes=yes, silent=silent, stdin=stdin)

    monkeypatch.setattr(mcp_server, "ApprovalPolicy", RecordingPolicy)
    server = make_server(monkeypatch, tmp_path, FakeRunner())
    tool(server, "jarvis_do", {"request": "system info", "allow": True})
    tool(server, "jarvis_do", {"request": "system info"})
    assert seen == [{"yes": True, "silent": True}, {"yes": False, "silent": True}]


def test_do_rejects_non_boolean_allow(monkeypatch: Any, tmp_path: Any) -> None:
    runner = FakeRunner()
    server = make_server(monkeypatch, tmp_path, runner)
    is_error, payload = tool(server, "jarvis_do", {"request": "system info", "allow": "yes"})
    assert is_error is True
    assert "allow must be a boolean" in payload["error"]
    assert runner.calls == []


def test_tool_call_with_empty_request_is_invalid_params(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    parsed = json.loads(
        server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "jarvis_do", "arguments": {"request": "  "}},
                }
            )
        )
        or "{}"
    )
    assert "result" in parsed
    assert parsed["result"]["isError"] is True


def test_unknown_tool_is_invalid_params(monkeypatch: Any, tmp_path: Any) -> None:
    server = make_server(monkeypatch, tmp_path)
    parsed = json.loads(
        server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {"name": "jarvis_shell", "arguments": {"command": "id"}},
                }
            )
        )
        or "{}"
    )
    assert parsed["error"]["code"] == -32602
    assert "unknown tool" in parsed["error"]["message"]


# -- CLI wiring ----------------------------------------------------------------


def test_parser_wires_mcp_serve() -> None:
    args = build_parser().parse_args(["mcp", "serve"])
    assert args.func is _cmd_mcp_serve
    assert args.mcp_command == "serve"
