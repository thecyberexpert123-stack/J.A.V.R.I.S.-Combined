"""Qt client for the kernel's resident loopback doorway (ADR-0018).

Presents the same signal surface as :class:`~javris.bridge.client.KernelClient`
-- ``connected``/``disconnected``/``started``/``completed`` with the same
payloads -- so the controller can hold either transport without branching on
which one it has. The differences between spawning a process and calling an
HTTP endpoint belong here, not in the UI.

Uses ``QNetworkAccessManager`` from PySide6-Essentials, so resident mode adds
no dependency.

Security notes, all enforced before a request leaves the process:

* the endpoint must be loopback (:func:`resident.validate_endpoint`);
* the token file must be 0600 and plausibly sized (:func:`resident.read_token`);
* the token is sent only as an ``Authorization`` header, never in a URL or a
  log line;
* ``allow`` is generated only when the caller passes it, exactly as on stdio.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import protocol, resident
from .protocol import Outcome, OutcomeKind

#: Health probe budget. The doorway is a local process; if loopback has not
#: answered in this long it is not running.
HEALTH_TIMEOUT_MS = 5_000

#: Tool-call budget, matching the stdio client so behaviour does not depend on
#: which transport the owner chose.
REQUEST_TIMEOUT_MS = 120_000


class ResidentClient(QObject):
    """Talks to ``jarvis serve`` over the loopback doorway."""

    #: Doorway answered its health probe. Carries the kernel version string.
    connected = Signal(str)
    #: Doorway is unusable or the owner disconnected. Carries a reason.
    disconnected = Signal(str)
    #: A tool call completed. Carries the request tag and the decided outcome.
    completed = Signal(str, object)
    #: A request began. Carries the request tag.
    started = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = resident.DEFAULT_PORT,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._manager = QNetworkAccessManager(self)
        self._token = ""
        self._ready = False
        self._version = ""
        self._inflight: dict[QNetworkReply, str] = {}

    # -- state -------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """True once the doorway has answered a health probe."""
        return self._ready

    @property
    def version(self) -> str:
        """Kernel version, or an empty string when not yet known."""
        return self._version

    @property
    def endpoint(self) -> str:
        """The configured endpoint, for display. Never includes the token."""
        return f"http://{self._host}:{self._port}"

    def available(self) -> bool:
        """True when a usable token exists.

        Cheap and side-effect free, so the UI can offer resident mode only when
        the owner has actually installed it. A false answer here is an honest
        "not configured", never an error.
        """
        try:
            resident.validate_endpoint(self._host, self._port)
            resident.read_token(resident.default_token_path())
        except (resident.ResidentError, OSError):
            return False
        return True

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Read the token and probe the doorway's health endpoint.

        Returns False when resident mode is not usable, having emitted
        :attr:`disconnected` with the reason. The GUI treats that as "stay
        offline", never as a fatal condition.
        """
        if self._ready:
            return False
        try:
            resident.validate_endpoint(self._host, self._port)
            self._token = resident.read_token(resident.default_token_path())
        except resident.ResidentError as exc:
            self.disconnected.emit(str(exc))
            return False
        except OSError as exc:
            self.disconnected.emit(f"Could not read the doorway token: {exc}")
            return False

        request = QNetworkRequest(QUrl(resident.health_url(self._host, self._port)))
        request.setTransferTimeout(HEALTH_TIMEOUT_MS)
        reply = self._manager.get(request)
        reply.finished.connect(lambda: self._on_health(reply))
        return True

    def stop(self) -> None:
        """Disconnect. The doorway is not ours to shut down.

        Unlike the spawned transport there is no child process to terminate:
        the resident kernel belongs to the owner's session, and a front-end
        closing must not take it away from anything else using it.
        """
        was_ready = self._ready
        self._ready = False
        self._version = ""
        # Drop the token from memory; it is re-read on the next connect.
        self._token = ""
        for reply in list(self._inflight):
            reply.abort()
        self._inflight.clear()
        if was_ready:
            self.disconnected.emit("Disconnected from the resident kernel.")

    # -- requests ----------------------------------------------------------

    def call(self, tool: str, arguments: dict[str, Any], *, tag: str) -> bool:
        """Invoke a read-only tool.

        Raises:
            ValueError: If asked for a consent-bearing tool. Those must go
                through :meth:`execute`, which is the only path that can carry
                consent -- the same rule as the stdio client.
        """
        if tool in protocol.CONSENT_TOOLS:
            raise ValueError(f"{tool!r} requires consent; use execute().")
        return self._dispatch(tool, arguments, allow=False, tag=tag)

    def execute(self, request: str, *, allow: bool, tag: str) -> bool:
        """Invoke ``jarvis_do``. The only path that may carry consent."""
        return self._dispatch("jarvis_do", {"request": request}, allow=allow, tag=tag)

    def _dispatch(self, tool: str, arguments: dict[str, Any], *, allow: bool, tag: str) -> bool:
        if not self._ready:
            return False
        try:
            url = resident.tool_url(self._host, self._port, tool)
            body = resident.build_body(tool, arguments, allow=allow)
        except (resident.ResidentError, ValueError) as exc:
            self.completed.emit(
                tag,
                Outcome(kind=OutcomeKind.PROTOCOL_ERROR, text=str(exc)),
            )
            return False

        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        # The token goes in the header and nowhere else.
        request.setRawHeader(b"Authorization", f"Bearer {self._token}".encode())
        request.setTransferTimeout(REQUEST_TIMEOUT_MS)

        reply = self._manager.post(request, QByteArray(body))
        self._inflight[reply] = tag
        reply.finished.connect(lambda: self._on_reply(reply))
        self.started.emit(tag)
        return True

    # -- replies -----------------------------------------------------------

    def _on_health(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.disconnected.emit(
                f"No resident kernel at {self.endpoint}. "
                "Start it with 'jarvis serve run', or connect on demand instead."
            )
            return

        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if not isinstance(status, int) or status != 200:
            self.disconnected.emit(
                resident.describe_http_status(status if isinstance(status, int) else 0)
            )
            return

        # The doorway reports its version in the Server header; an absent or
        # unrecognised header leaves the version honestly empty.
        # bytes(...) then decode: str() on a QByteArray yields its Python
        # repr ("b'jarvis-serve/1.18.0'"), which parses to nothing.
        header = bytes(reply.rawHeader("Server").data()).decode("ascii", errors="replace")
        self._version = resident.parse_server_header(header)
        self._ready = True
        self.connected.emit(self._version)

    def _on_reply(self, reply: QNetworkReply) -> None:
        tag = self._inflight.pop(reply, "")
        reply.deleteLater()

        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return

        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        raw = bytes(reply.readAll().data())

        if isinstance(status, int) and status != 200:
            outcome = Outcome(
                kind=OutcomeKind.PROTOCOL_ERROR,
                text=resident.describe_http_status(status),
            )
            self._emit(tag, outcome)
            if status == 401:
                # The token is no longer accepted; staying "connected" would
                # misreport the state of the link.
                self.stop()
                self.disconnected.emit("The doorway rejected the token.")
            return

        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._emit(
                tag,
                Outcome(
                    kind=OutcomeKind.PROTOCOL_ERROR,
                    text=f"Doorway request failed: {reply.errorString()}",
                ),
            )
            return

        try:
            envelope = resident.parse_envelope(raw)
        except resident.ResidentError as exc:
            self._emit(tag, Outcome(kind=OutcomeKind.PROTOCOL_ERROR, text=str(exc)))
            return

        # Normalised into the stdio shape so the audited classifier is reused.
        outcome = protocol.classify_outcome(resident.envelope_to_message(envelope))
        self._emit(tag, outcome)

    def _emit(self, tag: str, outcome: Outcome) -> None:
        """Deliver an outcome to whoever asked for it."""
        self.completed.emit(tag, outcome)
