"""Stdlib D-Bus client, read-only, for the briefing's environment signals (ADR-0031).

JARVIS needs three things from the system bus: ``Hello`` (mandatory first
call), ``org.freedesktop.DBus.Properties.Get`` on logind / NetworkManager, and
``AddMatch`` so the opt-in listener receives ``PrepareForSleep`` and
``PropertiesChanged`` broadcasts. That is a few hundred lines of the wire
protocol — far less than a dependency (ADR-0005) or a ``busctl`` child per
property (rejected by the owner: zero subprocesses in every mode).

What is implemented, straight from the D-Bus Specification (see the ADR's
Sources): server addresses (``unix:path=`` / ``unix:abstract=``, ``%XX``
escapes, ``;``-separated fallbacks, ``$DBUS_SYSTEM_BUS_ADDRESS``); SASL
``EXTERNAL`` authentication (NUL byte, ``AUTH EXTERNAL <hex uid>``, ``OK``,
``BEGIN``); the message format (``yyyyuua(yv)`` header, little-endian
emission, both endiannesses accepted); marshalling for every type code except
``h`` (unix fds are never negotiated); ``METHOD_CALL`` with ``NO_AUTO_START``
on **every** call so sensing can never activate a service; strict validation
with disconnect on any malformed frame; a 1 MiB message cap.

What is deliberately absent: ``DBUS_COOKIE_SHA1``/``ANONYMOUS`` mechanisms,
fd passing, ``ALLOW_INTERACTIVE_AUTHORIZATION`` (never set — a sensing probe
must not raise a polkit prompt), and any method that changes state. The only
frames this client ever *originates* are ``Hello``, ``Properties.Get``,
``AddMatch`` and the replies the spec obliges a peer to send
(``Peer.Ping`` → empty return, anything else → ``UnknownMethod``).
"""

from __future__ import annotations

import contextlib
import os
import re
import socket
import struct
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

__all__ = [
    "BUS_IFACE",
    "BUS_NAME",
    "BUS_PATH",
    "DEFAULT_TIMEOUT",
    "FLAG_NO_AUTO_START",
    "MAX_MESSAGE_BYTES",
    "MESSAGE_ERROR",
    "MESSAGE_METHOD_CALL",
    "MESSAGE_METHOD_RETURN",
    "MESSAGE_SIGNAL",
    "PROPERTIES_IFACE",
    "BusConnection",
    "BusError",
    "BusUnavailable",
    "Message",
    "ProtocolError",
    "RemoteError",
    "Variant",
    "connect_system_bus",
    "decode_message",
    "encode_message",
    "match_rule",
    "parse_address",
    "system_bus_address",
]

# -- protocol constants -------------------------------------------------------

PROTOCOL_VERSION = 1
MESSAGE_METHOD_CALL = 1
MESSAGE_METHOD_RETURN = 2
MESSAGE_ERROR = 3
MESSAGE_SIGNAL = 4

FLAG_NO_REPLY_EXPECTED = 0x1
FLAG_NO_AUTO_START = 0x2
# 0x4 ALLOW_INTERACTIVE_AUTHORIZATION is intentionally not defined here.

FIELD_PATH = 1
FIELD_INTERFACE = 2
FIELD_MEMBER = 3
FIELD_ERROR_NAME = 4
FIELD_REPLY_SERIAL = 5
FIELD_DESTINATION = 6
FIELD_SENDER = 7
FIELD_SIGNATURE = 8
FIELD_UNIX_FDS = 9
_FIELD_SIGNATURES = {1: "o", 2: "s", 3: "s", 4: "s", 5: "u", 6: "s", 7: "s", 8: "g", 9: "u"}

MAX_MESSAGE_BYTES = 1 << 20  # the spec allows 128 MiB; nothing we read needs more than a few KiB
MAX_DEPTH = 64
MAX_NAME_BYTES = 255
MAX_AUTH_LINE = 16 * 1024
MAX_QUEUED_SIGNALS = 256
DEFAULT_TIMEOUT = 2.0

BUS_NAME = "org.freedesktop.DBus"
BUS_PATH = "/org/freedesktop/DBus"
BUS_IFACE = "org.freedesktop.DBus"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
PEER_IFACE = "org.freedesktop.DBus.Peer"
ERROR_UNKNOWN_METHOD = "org.freedesktop.DBus.Error.UnknownMethod"

# The spec names /var/run/...; on current Linux /var/run is a symlink to /run.
SYSTEM_BUS_FALLBACK = (
    "unix:path=/run/dbus/system_bus_socket;unix:path=/var/run/dbus/system_bus_socket"
)

_BASIC_ALIGN = {
    "y": 1,
    "b": 4,
    "n": 2,
    "q": 2,
    "i": 4,
    "u": 4,
    "x": 8,
    "t": 8,
    "d": 8,
    "s": 4,
    "o": 4,
    "g": 1,
}
_STRUCT_FMT = {
    "y": "B",
    "b": "I",
    "n": "h",
    "q": "H",
    "i": "i",
    "u": "I",
    "x": "q",
    "t": "Q",
    "d": "d",
}
_PATH_ELEMENT = re.compile(r"[A-Za-z0-9_]+")
_MATCH_VALUE = re.compile(r"[A-Za-z0-9_.:/\-]+")


# -- errors -------------------------------------------------------------------


class BusError(Exception):
    """Any failure talking to the bus; the message is one honest line."""


class BusUnavailable(BusError):
    """No usable bus: socket absent, connection refused, authentication rejected."""


class ProtocolError(BusError):
    """The peer violated the wire format; the connection has been closed."""


class RemoteError(BusError):
    """A D-Bus ``ERROR`` reply (``name`` is the error name, e.g. ``…NameHasNoOwner``)."""

    def __init__(self, name: str, text: str) -> None:
        super().__init__(f"{name}: {text}" if text else name)
        self.name = name
        self.text = text


class Variant(NamedTuple):
    """A D-Bus variant: the contained signature and its value."""

    signature: str
    value: object


@dataclass(frozen=True)
class Message:
    kind: int
    serial: int
    flags: int
    fields: Mapping[int, object] = field(default_factory=dict)
    body: tuple[object, ...] = ()

    @property
    def signature(self) -> str:
        return str(self.fields.get(FIELD_SIGNATURE, ""))

    @property
    def path(self) -> str | None:
        value = self.fields.get(FIELD_PATH)
        return None if value is None else str(value)

    @property
    def interface(self) -> str | None:
        value = self.fields.get(FIELD_INTERFACE)
        return None if value is None else str(value)

    @property
    def member(self) -> str | None:
        value = self.fields.get(FIELD_MEMBER)
        return None if value is None else str(value)

    @property
    def sender(self) -> str | None:
        value = self.fields.get(FIELD_SENDER)
        return None if value is None else str(value)

    @property
    def reply_serial(self) -> int | None:
        value = self.fields.get(FIELD_REPLY_SERIAL)
        return value if isinstance(value, int) else None


# -- signatures ---------------------------------------------------------------


def split_signature(signature: str) -> list[str]:
    """Split a signature into complete single types (``ValueError`` when malformed)."""
    if len(signature) > MAX_NAME_BYTES:
        raise ValueError("signature longer than 255 bytes")
    out: list[str] = []
    pos = 0
    while pos < len(signature):
        end = _end_of_type(signature, pos, 0, allow_dict=False)
        out.append(signature[pos:end])
        pos = end
    return out


def _end_of_type(sig: str, pos: int, depth: int, *, allow_dict: bool) -> int:
    if depth > MAX_DEPTH:
        raise ValueError("signature nesting too deep")
    code = sig[pos]
    if code in _BASIC_ALIGN or code == "v":
        return pos + 1
    if code == "a":
        if pos + 1 >= len(sig):
            raise ValueError("array without an element type")
        return _end_of_type(sig, pos + 1, depth + 1, allow_dict=True)
    if code == "(":
        cursor = pos + 1
        if cursor < len(sig) and sig[cursor] == ")":
            raise ValueError("empty struct")
        while cursor < len(sig) and sig[cursor] != ")":
            cursor = _end_of_type(sig, cursor, depth + 1, allow_dict=False)
        if cursor >= len(sig):
            raise ValueError("unterminated struct")
        return cursor + 1
    if code == "{":
        if not allow_dict:
            raise ValueError("dict entry outside an array")
        cursor = pos + 1
        if cursor >= len(sig) or sig[cursor] not in _BASIC_ALIGN:
            raise ValueError("dict entry key must be a basic type")
        cursor = _end_of_type(sig, cursor + 1, depth + 1, allow_dict=False)
        if cursor >= len(sig) or sig[cursor] != "}":
            raise ValueError("dict entry must hold exactly a key and a value")
        return cursor + 1
    raise ValueError(f"unknown type code {code!r}")


def _alignment(type_sig: str) -> int:
    code = type_sig[0]
    if code in _BASIC_ALIGN:
        return _BASIC_ALIGN[code]
    if code == "a":
        return 4
    if code in "({":
        return 8
    return 1  # variant


def _valid_object_path(text: str) -> bool:
    if text == "/":
        return True
    if not text.startswith("/") or text.endswith("/"):
        return False
    return all(_PATH_ELEMENT.fullmatch(part) for part in text[1:].split("/"))


# -- marshalling --------------------------------------------------------------


class _Writer:
    def __init__(self, endian: str = "<") -> None:
        self.buf = bytearray()
        self.endian = endian

    def pad(self, boundary: int) -> None:
        while len(self.buf) % boundary:
            self.buf.append(0)

    def write(self, signature: str, values: Sequence[object], depth: int = 0) -> None:
        types = split_signature(signature)
        if len(types) != len(values):
            raise ValueError(
                f"signature {signature!r} needs {len(types)} values, got {len(values)}"
            )
        for type_sig, value in zip(types, values, strict=True):
            self._one(type_sig, value, depth)

    def _one(self, type_sig: str, value: object, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ValueError("value nesting too deep")
        code = type_sig[0]
        if code in _STRUCT_FMT:
            if code == "b":
                value = 1 if value else 0
            self.pad(_BASIC_ALIGN[code])
            self.buf += struct.pack(self.endian + _STRUCT_FMT[code], value)
        elif code in "so":
            if not isinstance(value, str) or "\0" in value:
                raise ValueError("strings must be str without NUL")
            if code == "o" and not _valid_object_path(value):
                raise ValueError(f"invalid object path {value!r}")
            data = value.encode("utf-8")
            self.pad(4)
            self.buf += struct.pack(self.endian + "I", len(data)) + data + b"\0"
        elif code == "g":
            if not isinstance(value, str):
                raise ValueError("signature must be str")
            split_signature(value)  # validates
            data = value.encode("ascii")
            self.buf += bytes([len(data)]) + data + b"\0"
        elif code == "v":
            if not isinstance(value, Variant):
                raise ValueError("variants must be Variant(signature, value)")
            if len(split_signature(value.signature)) != 1:
                raise ValueError("a variant holds exactly one complete type")
            self._one("g", value.signature, depth)
            self._one(value.signature, value.value, depth + 1)
        elif code == "a":
            self._array(type_sig[1:], value, depth)
        elif code == "(":
            inner = split_signature(type_sig[1:-1])
            if not isinstance(value, Sequence) or len(inner) != len(value):
                raise ValueError(f"struct {type_sig!r} needs {len(inner)} fields")
            self.pad(8)
            for item_sig, item in zip(inner, value, strict=True):
                self._one(item_sig, item, depth + 1)
        else:
            raise ValueError(f"cannot marshal type {type_sig!r}")

    def _array(self, elem: str, value: object, depth: int) -> None:
        self.pad(4)
        length_pos = len(self.buf)
        self.buf += b"\0\0\0\0"
        self.pad(_alignment(elem))  # present even for an empty array (spec)
        start = len(self.buf)
        if elem[0] == "{":
            if not isinstance(value, Mapping):
                raise ValueError("dict entries need a mapping")
            key_sig, val_sig = split_signature(elem[1:-1])
            for key, val in value.items():
                self.pad(8)
                self._one(key_sig, key, depth + 1)
                self._one(val_sig, val, depth + 1)
        elif elem == "y" and isinstance(value, (bytes, bytearray)):
            self.buf += bytes(value)
        else:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise ValueError("arrays need a sequence")
            for item in value:
                self._one(elem, item, depth + 1)
        length = len(self.buf) - start
        if length > MAX_MESSAGE_BYTES:
            raise ValueError("array exceeds the message cap")
        struct.pack_into(self.endian + "I", self.buf, length_pos, length)


class _Reader:
    def __init__(self, data: bytes, endian: str, pos: int = 0) -> None:
        self.data = data
        self.endian = endian
        self.pos = pos

    def _need(self, count: int) -> None:
        if self.pos + count > len(self.data):
            raise ProtocolError("truncated message")

    def pad(self, boundary: int) -> None:
        target = (self.pos + boundary - 1) // boundary * boundary
        if target > len(self.data):
            raise ProtocolError("truncated message (padding)")
        if any(self.data[self.pos : target]):
            raise ProtocolError("non-zero padding")
        self.pos = target

    def read(self, signature: str) -> tuple[object, ...]:
        try:
            types = split_signature(signature)
        except ValueError as exc:
            raise ProtocolError(f"invalid signature: {exc}") from None
        return tuple(self._one(type_sig, 0) for type_sig in types)

    def _one(self, type_sig: str, depth: int) -> object:
        if depth > MAX_DEPTH:
            raise ProtocolError("message nesting too deep")
        code = type_sig[0]
        if code in _STRUCT_FMT:
            size = _BASIC_ALIGN[code]
            self.pad(size)
            self._need(size)
            (value,) = struct.unpack_from(self.endian + _STRUCT_FMT[code], self.data, self.pos)
            self.pos += size
            if code == "b":
                if value not in (0, 1):
                    raise ProtocolError("boolean out of range")
                return bool(value)
            return value
        if code in "so":
            self.pad(4)
            self._need(4)
            (length,) = struct.unpack_from(self.endian + "I", self.data, self.pos)
            self.pos += 4
            return self._string(length, code)
        if code == "g":
            self._need(1)
            length = self.data[self.pos]
            self.pos += 1
            text = self._string(length, "g")
            try:
                split_signature(text)
            except ValueError as exc:
                raise ProtocolError(f"invalid signature value: {exc}") from None
            return text
        if code == "v":
            signature = str(self._one("g", depth))
            if len(split_signature(signature)) != 1:
                raise ProtocolError("variant with zero or several types")
            return Variant(signature, self._one(signature, depth + 1))
        if code == "a":
            return self._array(type_sig[1:], depth)
        if code == "(":
            self.pad(8)
            return tuple(self._one(item, depth + 1) for item in split_signature(type_sig[1:-1]))
        raise ProtocolError(f"unsupported type {type_sig!r}")

    def _string(self, length: int, code: str) -> str:
        self._need(length + 1)
        raw = self.data[self.pos : self.pos + length]
        if self.data[self.pos + length] != 0:
            raise ProtocolError("string without NUL terminator")
        self.pos += length + 1
        if b"\0" in raw:
            raise ProtocolError("embedded NUL in string")
        try:
            text = raw.decode("utf-8" if code != "g" else "ascii")
        except UnicodeDecodeError:
            raise ProtocolError("string is not valid UTF-8") from None
        if code == "o" and not _valid_object_path(text):
            raise ProtocolError(f"invalid object path {text!r}")
        return text

    def _array(self, elem: str, depth: int) -> object:
        self.pad(4)
        self._need(4)
        (length,) = struct.unpack_from(self.endian + "I", self.data, self.pos)
        self.pos += 4
        if length > MAX_MESSAGE_BYTES:
            raise ProtocolError("array exceeds the message cap")
        self.pad(_alignment(elem))
        end = self.pos + length
        if end > len(self.data):
            raise ProtocolError("array runs past the message")
        if elem[0] == "{":
            key_sig, val_sig = split_signature(elem[1:-1])
            mapping: dict[object, object] = {}
            while self.pos < end:
                self.pad(8)
                key = self._one(key_sig, depth + 1)
                mapping[key] = self._one(val_sig, depth + 1)
            result: object = mapping
        elif elem == "y":
            result = bytes(self.data[self.pos : end])
            self.pos = end
        else:
            items: list[object] = []
            while self.pos < end:
                items.append(self._one(elem, depth + 1))
            result = items
        if self.pos != end:
            raise ProtocolError("array length does not match its elements")
        return result


def encode_message(
    kind: int,
    serial: int,
    fields: Mapping[int, object],
    signature: str = "",
    body: Sequence[object] = (),
    *,
    flags: int = 0,
    endian: str = "<",
) -> bytes:
    """Serialise one message. Header fields are written in ascending code order."""
    if serial == 0:
        raise ValueError("serial must be non-zero")
    body_writer = _Writer(endian)
    body_writer.write(signature, body)
    body_bytes = bytes(body_writer.buf)
    all_fields = dict(fields)
    if signature:
        all_fields[FIELD_SIGNATURE] = signature
    header_fields = [
        (code, Variant(_FIELD_SIGNATURES[code], value))
        for code, value in sorted(all_fields.items())
        if value is not None
    ]
    writer = _Writer(endian)
    writer.buf += struct.pack(
        endian + "BBBBII",
        ord("l") if endian == "<" else ord("B"),
        kind,
        flags,
        PROTOCOL_VERSION,
        len(body_bytes),
        serial,
    )
    writer._one("a(yv)", header_fields, 0)
    writer.pad(8)
    writer.buf += body_bytes
    if len(writer.buf) > MAX_MESSAGE_BYTES:
        raise ValueError("message exceeds the cap")
    return bytes(writer.buf)


def _header_fields(raw: object) -> dict[int, object]:
    """Validate the decoded ``a(yv)`` header array: known codes typed, unknown ignored."""
    fields: dict[int, object] = {}
    if not isinstance(raw, list):
        raise ProtocolError("header field array missing")
    for entry in raw:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise ProtocolError("malformed header field")
        code, variant = entry
        if not isinstance(code, int) or not isinstance(variant, Variant):
            raise ProtocolError("malformed header field")
        expected = _FIELD_SIGNATURES.get(code)
        if expected is None:
            continue  # unknown header fields must be ignored (spec)
        if variant.signature != expected:
            raise ProtocolError(f"header field {code} carries {variant.signature!r}")
        if code in fields:
            raise ProtocolError("duplicate header field")
        fields[code] = variant.value
    return fields


def decode_message(data: bytes) -> Message:
    """Parse one complete message; any deviation from the spec is a ``ProtocolError``."""
    if len(data) < 16:
        raise ProtocolError("message shorter than its fixed header")
    if data[0] == ord("l"):
        endian = "<"
    elif data[0] == ord("B"):
        endian = ">"
    else:
        raise ProtocolError("unknown endianness marker")
    kind, flags, version = data[1], data[2], data[3]
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {version}")
    body_length, serial = struct.unpack_from(endian + "II", data, 4)
    if serial == 0:
        raise ProtocolError("zero serial")
    reader = _Reader(data, endian, pos=12)
    fields = _header_fields(reader._one("a(yv)", 0))
    reader.pad(8)
    if reader.pos + body_length != len(data):
        raise ProtocolError("body length does not match the frame")
    signature = str(fields.get(FIELD_SIGNATURE, ""))
    if body_length and not signature:
        raise ProtocolError("body without a signature")
    body = reader.read(signature) if signature else ()
    if reader.pos != len(data):
        raise ProtocolError("trailing bytes after the body")
    required: tuple[int, ...] = ()
    if kind == MESSAGE_METHOD_CALL:
        required = (FIELD_PATH, FIELD_MEMBER)
    elif kind == MESSAGE_SIGNAL:
        required = (FIELD_PATH, FIELD_INTERFACE, FIELD_MEMBER)
    elif kind == MESSAGE_METHOD_RETURN:
        required = (FIELD_REPLY_SERIAL,)
    elif kind == MESSAGE_ERROR:
        required = (FIELD_REPLY_SERIAL, FIELD_ERROR_NAME)
    for code in required:
        if code not in fields:
            raise ProtocolError(f"message type {kind} lacks header field {code}")
    return Message(kind, serial, flags, fields, body)


def frame_length(head: bytes) -> tuple[int, str]:
    """Total frame size implied by the 16-byte fixed header (and its endianness)."""
    if head[0] == ord("l"):
        endian = "<"
    elif head[0] == ord("B"):
        endian = ">"
    else:
        raise ProtocolError("unknown endianness marker")
    if head[3] != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {head[3]}")
    if len(head) < 16:
        raise ProtocolError("short fixed header")
    body_length, _serial, fields_length = struct.unpack_from(endian + "III", head, 4)
    header_length = 16 + fields_length
    padded = (header_length + 7) // 8 * 8
    total = padded + body_length
    if total > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"message of {total} bytes exceeds the {MAX_MESSAGE_BYTES} cap")
    return total, endian


# -- addresses, names, match rules -----------------------------------------------


def parse_address(text: str) -> list[str]:
    """``unix:`` entries of a server address as ``connect()`` targets, in order.

    Other transports are skipped (never an error): the system bus is a unix
    socket on every Linux we target. Abstract names get the leading NUL Python
    expects. ``%XX`` escapes are decoded per the spec.
    """
    targets: list[str] = []
    for entry in text.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        transport, _, params = entry.partition(":")
        if transport != "unix":
            continue
        options: dict[str, str] = {}
        for pair in params.split(","):
            key, sep, raw = pair.partition("=")
            if not sep:
                continue
            options[key] = _unescape(raw)
        if options.get("path"):
            targets.append(options["path"])
        elif options.get("abstract"):
            targets.append("\0" + options["abstract"])
    return targets


def _unescape(value: str) -> str:
    out = bytearray()
    pos = 0
    while pos < len(value):
        ch = value[pos]
        if ch == "%" and len(value) >= pos + 3:
            try:
                out.append(int(value[pos + 1 : pos + 3], 16))
            except ValueError:
                raise ValueError(f"bad %-escape in address {value!r}") from None
            pos += 3
            continue
        out += ch.encode("utf-8")
        pos += 1
    return out.decode("utf-8", errors="replace")


def describe_address(target: str) -> str:
    return "@" + target[1:] if target.startswith("\0") else target


def system_bus_address(env: Mapping[str, str] | None = None) -> str:
    mapping = os.environ if env is None else env
    return mapping.get("DBUS_SYSTEM_BUS_ADDRESS") or SYSTEM_BUS_FALLBACK


def match_rule(**criteria: str) -> str:
    """A match rule from fixed ``key='value'`` pairs (values are validated, never quoted)."""
    allowed = {"type", "sender", "interface", "member", "path", "path_namespace", "arg0"}
    parts: list[str] = []
    for key, value in criteria.items():
        if key not in allowed:
            raise ValueError(f"unsupported match key {key!r}")
        if not _MATCH_VALUE.fullmatch(value):
            raise ValueError(f"match value {value!r} needs quoting; refusing")
        parts.append(f"{key}='{value}'")
    return ",".join(parts)


# -- the connection -----------------------------------------------------------------


class BusConnection:
    """One authenticated connection; ``call``/``get_property``/``add_match``/``next_signal``."""

    def __init__(self, sock: socket.socket, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._sock: socket.socket | None = sock
        self._timeout = timeout
        self._serial = 0
        self._queue: deque[Message] = deque()
        self.unique_name: str | None = None

    # -- lifecycle ---------------------------------------------------------------------

    @classmethod
    def connect(
        cls,
        address: str | None = None,
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        uid: int | None = None,
    ) -> BusConnection:
        """Connect, authenticate (EXTERNAL) and say Hello; ``BusUnavailable`` when impossible."""
        text = address or system_bus_address(env)
        targets = parse_address(text)
        if not targets:
            raise BusUnavailable(f"no unix: address in {text!r}")
        failures: list[str] = []
        for target in targets:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
            sock.settimeout(timeout)
            try:
                sock.connect(target)
            except OSError as exc:
                sock.close()
                failures.append(f"{describe_address(target)}: {exc.strerror or exc}")
                continue
            conn = cls(sock, timeout=timeout)
            try:
                conn._authenticate(os.geteuid() if uid is None else uid)
                conn._hello()
            except BusError:
                conn.close()
                raise
            return conn
        raise BusUnavailable("; ".join(failures))

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()

    def __enter__(self) -> BusConnection:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # -- public verbs -------------------------------------------------------------------

    def call(
        self,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        args: Sequence[object] = (),
        *,
        timeout: float | None = None,
    ) -> Message:
        """A METHOD_CALL with NO_AUTO_START; returns the METHOD_RETURN or raises."""
        serial = self._next_serial()
        fields = {
            FIELD_PATH: path,
            FIELD_INTERFACE: interface,
            FIELD_MEMBER: member,
            FIELD_DESTINATION: destination,
        }
        self._send(
            encode_message(
                MESSAGE_METHOD_CALL, serial, fields, signature, args, flags=FLAG_NO_AUTO_START
            )
        )
        budget = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + budget
        while True:
            message = self._receive(deadline)
            if message is None:
                self.close()
                raise BusError(f"{member} timed out after {budget:g}s")
            if message.reply_serial == serial:
                if message.kind == MESSAGE_METHOD_RETURN:
                    return message
                if message.kind == MESSAGE_ERROR:
                    text = message.body[0] if message.body and message.signature[:1] == "s" else ""
                    raise RemoteError(str(message.fields[FIELD_ERROR_NAME]), str(text))
            self._unsolicited(message)

    def get_property(
        self,
        destination: str,
        path: str,
        interface: str,
        name: str,
        *,
        timeout: float | None = None,
    ) -> Variant:
        reply = self.call(
            destination, path, PROPERTIES_IFACE, "Get", "ss", (interface, name), timeout=timeout
        )
        if reply.signature != "v" or len(reply.body) != 1:
            raise ProtocolError(f"Properties.Get returned {reply.signature!r}, not a variant")
        value = reply.body[0]
        assert isinstance(value, Variant)
        return value

    def add_match(self, rule: str, *, timeout: float | None = None) -> None:
        self.call(BUS_NAME, BUS_PATH, BUS_IFACE, "AddMatch", "s", (rule,), timeout=timeout)

    def next_signal(self, timeout: float) -> Message | None:
        """The next queued or arriving SIGNAL, or ``None`` when ``timeout`` elapses."""
        deadline = time.monotonic() + timeout
        while True:
            if self._queue:
                return self._queue.popleft()
            message = self._receive(deadline)
            if message is None:
                return None
            self._unsolicited(message)

    # -- handshake ----------------------------------------------------------------------

    def _authenticate(self, uid: int) -> None:
        hex_uid = str(uid).encode("ascii").hex().encode("ascii")
        deadline = time.monotonic() + self._timeout  # the whole exchange, not per byte
        self._send(b"\0AUTH EXTERNAL " + hex_uid + b"\r\n")
        for _ in range(4):
            line = self._read_line(deadline)
            word, _, rest = line.partition(b" ")
            if word == b"OK":
                self._send(b"BEGIN\r\n")
                return
            if word == b"DATA":
                self._send(b"DATA " + hex_uid + b"\r\n")
                continue
            if word == b"REJECTED":
                offered = rest.decode("ascii", errors="replace").strip() or "nothing"
                raise BusUnavailable(f"EXTERNAL authentication rejected (server offers {offered})")
            if word == b"ERROR":
                raise BusUnavailable(f"authentication error: {rest.decode('ascii', 'replace')}")
            raise ProtocolError(f"unexpected authentication reply {line[:32]!r}")
        raise ProtocolError("authentication did not converge")

    def _hello(self) -> None:
        reply = self.call(BUS_NAME, BUS_PATH, BUS_IFACE, "Hello")
        name = reply.body[0] if reply.signature == "s" and reply.body else None
        if not isinstance(name, str) or not name.startswith(":"):
            raise ProtocolError("Hello did not return a unique name")
        self.unique_name = name

    # -- transport ----------------------------------------------------------------------

    def _next_serial(self) -> int:
        self._serial = self._serial % 0xFFFFFFFF + 1
        return self._serial

    def _send(self, data: bytes) -> None:
        if self._sock is None:
            raise BusError("connection is closed")
        try:
            self._sock.settimeout(self._timeout)  # _recv may have left a short deadline behind
            self._sock.sendall(data)
        except OSError as exc:
            self.close()
            raise BusError(f"send failed: {exc.strerror or exc}") from None

    def _read_line(self, deadline: float) -> bytes:
        line = bytearray()
        while not line.endswith(b"\r\n"):
            chunk = self._recv(1, deadline)
            if chunk is None:
                self.close()
                raise BusUnavailable("authentication timed out")
            line += chunk
            if len(line) > MAX_AUTH_LINE:
                self.close()
                raise ProtocolError("authentication line too long")
        return bytes(line[:-2])

    def _recv(self, count: int, deadline: float) -> bytes | None:
        """Up to ``count`` bytes, ``None`` on deadline; EOF/errors close and raise."""
        if self._sock is None:
            raise BusError("connection is closed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            # socket timeouts use poll(2) underneath: no FD_SETSIZE ceiling
            self._sock.settimeout(remaining)
            chunk = self._sock.recv(count)
        except TimeoutError:
            return None
        except OSError as exc:
            self.close()
            raise BusError(f"receive failed: {exc.strerror or exc}") from None
        if not chunk:
            self.close()
            raise ProtocolError("connection closed by the bus")
        return chunk

    def _read_exact(self, count: int, deadline: float) -> bytes | None:
        buf = bytearray()
        while len(buf) < count:
            chunk = self._recv(count - len(buf), deadline)
            if chunk is None:
                if buf:  # a partial frame cannot be resumed; the stream is now unaligned
                    self.close()
                    raise ProtocolError("timed out inside a frame")
                return None
            buf += chunk
        return bytes(buf)

    def _receive(self, deadline: float) -> Message | None:
        head = self._read_exact(16, deadline)
        if head is None:
            return None
        try:
            total, _endian = frame_length(head)
            rest = self._read_exact(total - 16, time.monotonic() + self._timeout)
            if rest is None:
                raise ProtocolError("frame body did not arrive")
            return decode_message(head + rest)
        except ProtocolError:
            self.close()
            raise

    def _unsolicited(self, message: Message) -> None:
        if message.kind == MESSAGE_SIGNAL:
            if len(self._queue) >= MAX_QUEUED_SIGNALS:
                self._queue.popleft()
            self._queue.append(message)
        elif message.kind == MESSAGE_METHOD_CALL and not message.flags & FLAG_NO_REPLY_EXPECTED:
            self._answer_call(message)
        # stray returns/errors and unknown message types are dropped (spec: ignore)

    def _answer_call(self, message: Message) -> None:
        fields: dict[int, object] = {FIELD_REPLY_SERIAL: message.serial}
        if message.sender is not None:
            fields[FIELD_DESTINATION] = message.sender
        if message.interface == PEER_IFACE and message.member == "Ping":
            self._send(encode_message(MESSAGE_METHOD_RETURN, self._next_serial(), fields))
            return
        fields[FIELD_ERROR_NAME] = ERROR_UNKNOWN_METHOD
        text = f"{message.interface or ''}.{message.member} is not offered by this read-only client"
        self._send(encode_message(MESSAGE_ERROR, self._next_serial(), fields, "s", (text,)))


def connect_system_bus(
    *, env: Mapping[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT
) -> BusConnection:
    """The system bus per ``$DBUS_SYSTEM_BUS_ADDRESS`` or the well-known socket paths."""
    return BusConnection.connect(env=env, timeout=timeout)
