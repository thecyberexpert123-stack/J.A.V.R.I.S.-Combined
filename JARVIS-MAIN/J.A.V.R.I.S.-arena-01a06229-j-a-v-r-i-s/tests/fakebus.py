"""An in-process message bus for tests (ADR-0031 D6).

Speaks exactly what a real ``dbus-daemon``/``dbus-broker`` speaks on the
wire: the NUL byte, SASL ``AUTH EXTERNAL`` / ``OK`` / ``BEGIN``, then binary
messages parsed with the *same* codec the client uses — which is fine for
the handshake and framing (those were checked byte-for-byte against an
independent implementation), and lets every test assert what JARVIS *sent*
(flags, destinations, arguments) rather than what it printed.

Behaviour knobs cover the failure modes the ADR lists: reject the
authentication, hand back an error name, return the wrong signature, send a
malformed frame, oversize frame, or close mid-frame. Properties are served
from a ``{(bus_name, path, interface): {prop: Variant}}`` table.
"""

from __future__ import annotations

import contextlib
import os
import socket
import struct
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from jarvis.system.dbus_client import (
    BUS_IFACE,
    BUS_NAME,
    FIELD_DESTINATION,
    FIELD_ERROR_NAME,
    FIELD_INTERFACE,
    FIELD_MEMBER,
    FIELD_PATH,
    FIELD_REPLY_SERIAL,
    FIELD_SENDER,
    MESSAGE_ERROR,
    MESSAGE_METHOD_CALL,
    MESSAGE_METHOD_RETURN,
    MESSAGE_SIGNAL,
    PROPERTIES_IFACE,
    Message,
    Variant,
    decode_message,
    encode_message,
    frame_length,
)

__all__ = ["FakeBus", "Recorded"]


@dataclass
class Recorded:
    """One frame the client sent, decoded."""

    message: Message

    @property
    def member(self) -> str | None:
        return self.message.member

    @property
    def destination(self) -> str | None:
        value = self.message.fields.get(FIELD_DESTINATION)
        return None if value is None else str(value)

    @property
    def body(self) -> tuple[object, ...]:
        return self.message.body

    @property
    def flags(self) -> int:
        return self.message.flags


@dataclass
class FakeBus:
    properties: dict[tuple[str, str, str], dict[str, Variant]] = field(default_factory=dict)
    #: names that own nothing → Properties.Get answers ServiceUnknown, as a real bus does
    known_names: set[str] = field(default_factory=lambda: {BUS_NAME})
    reject_auth: bool = False
    hello_reply: str = ":1.42"
    # fault knobs
    error_for: dict[str, str] = field(default_factory=dict)  # member → error name
    wrong_signature_for: set[str] = field(default_factory=set)
    garbage_after_hello: bytes | None = None
    close_after_hello: bool = False
    oversize_after_hello: bool = False
    # observability
    sent: list[Recorded] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)
    auth_lines: list[bytes] = field(default_factory=list)
    on_call: Callable[[Message], bytes | None] | None = None

    def __post_init__(self) -> None:
        self._path = f"\0jarvis-fakebus-{os.getpid()}-{id(self)}"
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(self._path)
        self._listener.listen(4)
        self._serial = 1000
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    # -- test-facing API ----------------------------------------------------------------

    @property
    def address(self) -> str:
        return "unix:abstract=" + self._path[1:]

    def set_property(self, bus_name: str, path: str, interface: str, name: str, v: Variant) -> None:
        self.known_names.add(bus_name)
        self.properties.setdefault((bus_name, path, interface), {})[name] = v

    def emit_signal(
        self,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: Sequence[object] = (),
        *,
        sender: str = ":1.7",
    ) -> None:
        """Broadcast to every connected client (a real bus would filter by match rule)."""
        frame = encode_message(
            MESSAGE_SIGNAL,
            self._next_serial(),
            {
                FIELD_PATH: path,
                FIELD_INTERFACE: interface,
                FIELD_MEMBER: member,
                FIELD_SENDER: sender,
            },
            signature,
            body,
            flags=1,
        )
        self.send_raw(frame)

    def send_raw(self, data: bytes) -> None:
        with self._lock:
            for client in list(self._clients):
                try:
                    client.sendall(data)
                except OSError:
                    self._clients.remove(client)

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            for client in self._clients:
                with contextlib.suppress(OSError):
                    client.shutdown(socket.SHUT_RDWR)
                client.close()
            self._clients.clear()
        self._listener.close()

    def calls(self, member: str) -> list[Recorded]:
        return [rec for rec in self.sent if rec.member == member]

    # -- server side ------------------------------------------------------------------

    def _next_serial(self) -> int:
        self._serial += 1
        return self._serial

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                self._clients.append(client)
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        try:
            if not self._handshake(client):
                return
            unique = self.hello_reply
            said_hello = False
            while not self._stop.is_set():
                head = self._read_exact(client, 16)
                if head is None:
                    return
                total, _ = frame_length(head)
                rest = self._read_exact(client, total - 16)
                if rest is None:
                    return
                message = decode_message(head + rest)
                self.sent.append(Recorded(message))
                if message.kind != MESSAGE_METHOD_CALL:
                    continue
                if not said_hello:
                    if message.member != "Hello":
                        client.close()  # a real bus disconnects on any pre-Hello call
                        return
                    said_hello = True
                    client.sendall(self._reply(message, unique, "s", (unique,)))
                    if self.garbage_after_hello is not None:
                        client.sendall(self.garbage_after_hello)
                    if self.oversize_after_hello:
                        client.sendall(b"l" + bytes([4, 1, 1]) + struct.pack("<II", 1 << 30, 5))
                    if self.close_after_hello:
                        client.close()
                        return
                    continue
                reply = self._dispatch(message, unique)
                if reply is not None:
                    client.sendall(reply)
        except OSError:
            return
        finally:
            with self._lock:
                if client in self._clients:
                    self._clients.remove(client)

    def _handshake(self, client: socket.socket) -> bool:
        first = client.recv(1)
        if first != b"\0":
            client.close()
            return False
        line = self._read_line(client)
        self.auth_lines.append(line)
        if self.reject_auth or not line.startswith(b"AUTH EXTERNAL "):
            client.sendall(b"REJECTED DBUS_COOKIE_SHA1\r\n")
            line = self._read_line(client)
            client.close()
            return False
        client.sendall(b"OK 3c7b2d0e5f8a4b1c9d2e3f4a5b6c7d8e\r\n")
        line = self._read_line(client)
        self.auth_lines.append(line)
        if line != b"BEGIN":
            client.close()
            return False
        return True

    def _dispatch(self, message: Message, unique: str) -> bytes | None:
        if self.on_call is not None:
            custom = self.on_call(message)
            if custom is not None:
                return custom
        member = message.member or ""
        if member in self.error_for:
            return self._error(message, unique, self.error_for[member], f"{member} failed (test)")
        if member in self.wrong_signature_for:
            return self._reply(message, unique, "i", (7,))
        destination = str(message.fields.get(FIELD_DESTINATION, ""))
        if destination not in self.known_names:
            return self._error(
                message,
                unique,
                "org.freedesktop.DBus.Error.ServiceUnknown",
                f"The name {destination} was not provided by any .service files",
            )
        if destination == BUS_NAME and message.interface == BUS_IFACE:
            if member in ("AddMatch", "RemoveMatch"):
                rule = str(message.body[0])
                if member == "AddMatch":
                    self.matches.append(rule)
                elif rule in self.matches:
                    self.matches.remove(rule)
                return self._reply(message, unique)
            if member == "GetNameOwner":
                name = str(message.body[0])
                if name in self.known_names:
                    return self._reply(message, unique, "s", (":1.7",))
                return self._error(
                    message, unique, "org.freedesktop.DBus.Error.NameHasNoOwner", "no owner"
                )
        if message.interface == PROPERTIES_IFACE and member == "Get":
            iface, prop = (str(x) for x in message.body)
            table = self.properties.get((destination, message.path or "", iface), {})
            if prop in table:
                return self._reply(message, unique, "v", (table[prop],))
            return self._error(
                message,
                unique,
                "org.freedesktop.DBus.Error.UnknownProperty",
                f"Unknown property {prop}",
            )
        return self._error(
            message, unique, "org.freedesktop.DBus.Error.UnknownMethod", f"Unknown method {member}"
        )

    def _reply(
        self, call: Message, unique: str, signature: str = "", body: Sequence[Any] = ()
    ) -> bytes:
        return encode_message(
            MESSAGE_METHOD_RETURN,
            self._next_serial(),
            {FIELD_REPLY_SERIAL: call.serial, FIELD_DESTINATION: unique, FIELD_SENDER: ":1.7"},
            signature,
            body,
        )

    def _error(self, call: Message, unique: str, name: str, text: str) -> bytes:
        return encode_message(
            MESSAGE_ERROR,
            self._next_serial(),
            {
                FIELD_REPLY_SERIAL: call.serial,
                FIELD_ERROR_NAME: name,
                FIELD_DESTINATION: unique,
                FIELD_SENDER: BUS_NAME,
            },
            "s",
            (text,),
        )

    @staticmethod
    def _read_line(client: socket.socket) -> bytes:
        line = bytearray()
        while not line.endswith(b"\r\n"):
            chunk = client.recv(1)
            if not chunk:
                break
            line += chunk
            if len(line) > 4096:
                break
        return bytes(line[:-2]) if line.endswith(b"\r\n") else bytes(line)

    @staticmethod
    def _read_exact(client: socket.socket, count: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < count:
            chunk = client.recv(count - len(buf))
            if not chunk:
                return None
            buf += chunk
        return bytes(buf)
