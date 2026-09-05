"""Hybrid residency: the opt-in resident doorway (ADR-0018).

`jarvis serve` is an availability feature, never an authority feature: a
loopback-only, token-authenticated HTTP surface that reuses the MCP tool
handlers verbatim (`cli/mcp_server.py`), so consent semantics are parity by
construction — `jarvis_do` needs the same per-call ``allow: true`` for T2,
refusals carry the same preview-then-allow hint, T3 is refused
unconditionally. There is no persistent yes anywhere: every consent arrives
with its request and is journaled as on the CLI.

`jarvis serve install [--with-gui]` writes a systemd **user** unit (and,
optionally, an XDG autostart entry for the GUI frontend if its command
exists). Packaging never enables residency; only the owner's typed command
does. `uninstall` returns the machine to pure on-demand.

Stdlib-only by design (ADR-0005). Hardening asserted by tests (ADR-0018 D2):
loopback bind, bearer token with constant-time compare, Host-header check,
method/path allowlists, 64 KiB body cap, JSON-only bodies, no CORS answers,
token never logged.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

from jarvis import __version__
from jarvis.cli.mcp_server import _TOOL_HANDLERS
from jarvis.journal.sqlite import state_dir
from jarvis.safety.tiers import SafetyRefusal

DEFAULT_PORT = 8777
MAX_BODY_BYTES = 64 * 1024
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_TOOL_PATH = re.compile(r"^/v1/tools/(jarvis_(?:status|facts|explain|suggest|preview|do))$")
UNIT_NAME = "jarvis-serve.service"
GUI_COMMAND = "jarvis-gui"


# --------------------------------------------------------------------------
# token
# --------------------------------------------------------------------------


def token_path(env: dict[str, str] | None = None) -> Path:
    """The doorway bearer token, under the JARVIS state dir (0600)."""
    return state_dir(env) / "serve" / "token"


def ensure_token(env: dict[str, str] | None = None) -> str:
    """Load or create the bearer token; never log it, never widen perms."""
    path = token_path(env)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    return token


# --------------------------------------------------------------------------
# HTTP surface (parity with the MCP tool handlers)
# --------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server_version = "jarvis-serve/" + __version__
    protocol_version = "HTTP/1.1"

    token: str = ""
    bound_port: int = DEFAULT_PORT

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt: str, *args: object) -> None:
        return  # stdlib per-request noise is replaced by _audit below

    def _audit(self, status: int) -> None:
        """One stderr line per request; never the token, never the body."""
        print(
            f"[jarvis-serve] {self.command} {self.path} -> {status}",
            file=sys.stderr,
            flush=True,
        )

    def _reply(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self._audit(status)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[len("Bearer ") :].strip(), self.token)

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        hostname = host.rsplit(":", 1)[0] if ":" in host else host
        return hostname in _LOOPBACK_HOSTS and host.endswith(f":{self.bound_port}")

    # -- routes ------------------------------------------------------------

    def do_GET(self) -> None:
        if self.path == "/v1/health":
            if not self._host_ok():
                self._reply(421, {"error": "host mismatch"})
                return
            self._reply(200, {"ok": True})
            return
        if _TOOL_PATH.match(self.path or ""):
            self._reply(405, {"error": "method not allowed"})
            return
        self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        match = _TOOL_PATH.match(self.path or "")
        if self.path == "/v1/health":
            self._reply(405, {"error": "method not allowed"})
            return
        if match is None:
            self._reply(404, {"error": "not found"})
            return
        if not self._host_ok():
            self._reply(421, {"error": "host mismatch"})
            return
        if not self._authorized():
            self._reply(401, {"error": "bearer token required"})
            return
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._reply(415, {"error": "content-type must be application/json"})
            return
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError:
            length = -1
        if length < 0:
            self._reply(400, {"error": "invalid Content-Length"})
            return
        if length > MAX_BODY_BYTES:
            self._reply(413, {"error": "body too large"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._reply(400, {"error": "body must be valid JSON"})
            return
        if not isinstance(body, dict):
            self._reply(400, {"error": "body must be a JSON object"})
            return
        tool = match.group(1)
        assert isinstance(tool, str)
        # MCP parity: the handler is the SAME function the stdio server uses;
        # tool-level errors ride in-band as isError (never transport errors).
        payload, is_error = _TOOL_HANDLERS[tool](body)
        self._reply(200, {"result": payload, "isError": is_error})

    def do_OPTIONS(self) -> None:
        # No CORS answers, ever: browsers cannot preflight, so cross-origin
        # web pages cannot drive the doorway even from the same machine.
        self._reply(501, {"error": "no CORS on a loopback safety boundary"})


def build_server(host: str, port: int, token: str) -> ThreadingHTTPServer:
    """Build the doorway; refuse non-loopback binds outright."""
    if host not in _LOOPBACK_HOSTS:
        raise SafetyRefusal(f"refusing to bind {host!r}: the doorway serves localhost only")
    handler = cast(
        "type[_Handler]",
        type("BoundHandler", (_Handler,), {"token": token}),
    )
    server = ThreadingHTTPServer((host, port), handler)
    # the Host check must match the BOUND port (port 0 = ephemeral)
    handler.bound_port = server.server_address[1]
    return server


def run_server(host: str, port: int, token: str) -> int:
    server = build_server(host, port, token)
    done = threading.Event()

    def _stop(signum: int, _frame: object) -> None:
        print(f"[jarvis-serve] signal {signum}: shutting down", file=sys.stderr, flush=True)
        threading.Thread(target=server.shutdown, daemon=True).start()
        done.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print(
        f"[jarvis-serve] listening on http://{host}:{port} "
        f"(token: {token_path()}; never logged, 0600)",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


# --------------------------------------------------------------------------
# residency: systemd user unit + optional GUI autostart (ADR-0018 D3/D4)
# --------------------------------------------------------------------------


def unit_content(python_exe: str, port: int) -> str:
    """The systemd user unit. Contains no secrets (the token file holds those)."""
    return (
        "[Unit]\n"
        "Description=JARVIS resident doorway (loopback-only, token-authed; ADR-0018)\n"
        "Documentation=https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.\n"
        "After=default.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={python_exe} -m jarvis serve --bind 127.0.0.1 --port {port}\n"
        "Restart=on-failure\n"
        "RestartSec=2\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def desktop_content() -> str:
    """XDG autostart entry for the GUI frontend (written only if it exists)."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name=JARVIS GUI\n"
        f"Exec={GUI_COMMAND}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Comment=JARVIS hybrid residency: frontend autostart (agent stays consent-gated)\n"
    )


def unit_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / UNIT_NAME


def desktop_path(home: Path) -> Path:
    return home / ".config" / "autostart" / "jarvis-gui.desktop"


def _systemctl_user_available() -> bool:
    return shutil.which("systemctl") is not None and bool(os.environ.get("XDG_RUNTIME_DIR"))


def _gui_on_path() -> str | None:
    return shutil.which(GUI_COMMAND)


def install(
    port: int,
    with_gui: bool,
    home: Path,
    env: dict[str, str] | None = None,
    systemctl_available: bool | None = None,
    gui_probe: bool | None = None,
) -> int:
    """Validate everything first, then write, then enable — disclose every skip."""
    gui_found = gui_probe if gui_probe is not None else (_gui_on_path() is not None)
    if with_gui and not gui_found:
        raise SafetyRefusal(
            f"--with-gui: {GUI_COMMAND!r} not found on PATH; install the GUI frontend "
            "first or drop the flag (the agent unit can still be installed without it)"
        )
    ensure_token(env)  # create/reuse the doorway token file (0600)
    unit_dir = unit_path(home).parent
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path(home).write_text(unit_content(sys.executable, port), encoding="utf-8")
    print(f"[jarvis] wrote {unit_path(home)} (port {port}, loopback only)")

    if with_gui:
        desktop_path(home).parent.mkdir(parents=True, exist_ok=True)
        desktop_path(home).write_text(desktop_content(), encoding="utf-8")
        print(f"[jarvis] wrote {desktop_path(home)} (launches {GUI_COMMAND})")

    available = (
        systemctl_available if systemctl_available is not None else _systemctl_user_available()
    )
    if available:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", UNIT_NAME],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"[jarvis] enabled + started {UNIT_NAME} (systemd --user)")
        else:
            print(
                f"[jarvis] unit written but enable failed: {result.stderr.strip()}; "
                f"manual: systemctl --user enable --now {UNIT_NAME}"
            )
    else:
        print(
            f"[jarvis] systemd --user unavailable here: unit written but NOT enabled. "
            f"Manual start: systemctl --user enable --now {UNIT_NAME}  (or run: jarvis serve)"
        )
    print(
        "[jarvis] disclosure: a local process holding the token file can reach the same "
        "six tools as the MCP surface (T2 still needs per-call allow:true; token at "
        f"{token_path(env)}, 0600). Remove anytime: jarvis serve uninstall"
    )
    return 0


def uninstall(
    home: Path,
    systemctl_available: bool | None = None,
    env: dict[str, str] | None = None,
) -> int:
    available = (
        systemctl_available if systemctl_available is not None else _systemctl_user_available()
    )
    if available:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", UNIT_NAME],
            check=False,
            capture_output=True,
            text=True,
        )
    removed: list[str] = []
    for path, label in (
        (unit_path(home), "unit"),
        (desktop_path(home), "GUI autostart"),
        (token_path(env), "token"),
    ):
        if path.exists():
            path.unlink()
            removed.append(label)
            print(f"[jarvis] removed {label}: {path}")
    if not removed:
        print("[jarvis] nothing to remove — residency was not installed")
    else:
        print("[jarvis] residency removed; the machine is back to pure on-demand")
    return 0


def status(home: Path, env: dict[str, str] | None = None) -> int:
    unit = unit_path(home)
    print(f"unit file : {'present' if unit.exists() else 'absent'} ({unit})")
    if _systemctl_user_available():
        result = subprocess.run(
            ["systemctl", "--user", "is-active", UNIT_NAME],
            check=False,
            capture_output=True,
            text=True,
        )
        print(f"systemd   : {result.stdout.strip() or 'unknown'}")
    else:
        print("systemd   : unavailable here (cannot query; unit file truth only)")
    token = token_path(env)
    print(f"token     : {'present (0600)' if token.exists() else 'absent'} ({token})")
    desktop = desktop_path(home)
    print(f"gui start : {'present' if desktop.exists() else 'absent'} ({desktop})")
    print("default   : on-demand only (nothing runs unless you run it)")
    return 0
