"""ADR-0031 D2/D6: the stdlib D-Bus client — wire format, handshake, safety rails.

The byte vectors below were produced by an independent implementation
(jeepney 0.9.0, installed only to generate them and removed again — it is
not a dependency) so the codec is checked against something other than
itself. The fake bus in ``fakebus.py`` then exercises the handshake and the
failure modes the ADR promises to survive.
"""

from __future__ import annotations

import binascii
import socket
import struct

import pytest

from fakebus import FakeBus
from jarvis.system import dbus_client as dc
from jarvis.system.dbus_client import (
    BUS_IFACE,
    BUS_NAME,
    BUS_PATH,
    FLAG_NO_AUTO_START,
    MESSAGE_METHOD_CALL,
    MESSAGE_METHOD_RETURN,
    MESSAGE_SIGNAL,
    BusConnection,
    BusError,
    BusUnavailable,
    ProtocolError,
    RemoteError,
    Variant,
    decode_message,
    encode_message,
    match_rule,
    parse_address,
    split_signature,
)

_F = dc  # header field constants live on the module

# --------------------------------------------------------------------------
# golden vectors (independent implementation)
# --------------------------------------------------------------------------

HELLO_HEX = (
    "6c01020100000000010000006d00000001016f00150000002f6f72672f667265656465736b746f702f44427573"
    "00000002017300140000006f72672e667265656465736b746f702e4442757300000000030173000500000048656c"
    "6c6f00000006017300140000006f72672e667265656465736b746f702e4442757300000000"
)
GET_HEX = (
    "6c0102013a000000020000008000000001016f00170000002f6f72672f667265656465736b746f702f6c6f6769"
    "6e3100020173001f0000006f72672e667265656465736b746f702e444275732e50726f70657274696573000301"
    "730003000000476574000000000006017300160000006f72672e667265656465736b746f702e6c6f67696e3100"
    "0008016700027373001e0000006f72672e667265656465736b746f702e6c6f67696e312e4d616e616765720000"
    "11000000507265706172696e67466f72536c65657000"
)
RETURN_VARIANT_BOOL_HEX = (
    "6c02000108000000090000002f000000050175000200000006017300050000003a312e34320000000701730004"
    "0000003a312e370000000008016700017600000162000001000000"
)
SIGNAL_PROPS_CHANGED_HEX = (
    "6c040101720000004d0000008e00000001016f001f0000002f6f72672f667265656465736b746f702f4e657477"
    "6f726b4d616e6167657200020173001f0000006f72672e667265656465736b746f702e444275732e50726f7065"
    "727469657300030173001100000050726f706572746965734368616e676564000000000000000701730004000000"
    "3a312e3300000000080167000873617b73767d61730000001e0000006f72672e667265656465736b746f702e4e65"
    "74776f726b4d616e61676572000030000000070000004d657465726564000175000003000000000000000c000000"
    "436f6e6e6563746976697479000175000400000016000000110000005072696d617279436f6e6e656374696f6e00"
)
MIXED_HEX = (
    "6c02000142000000010000001a0000000501750001000000080167000c79626e716975787464736f670000000000"
    "0000ff00000001000000fefffffffdffffff0400000000000000fbffffffffffffff0600000000000000000000000000"
    "f83f0100000073000000020000002f6f00016700"
)
NESTED_HEX = (
    "6c02000140000000010000001700000005017500010000000801670009617b73617b73767d7d0000380000000000"
    "0000010000006b0000002800000000000000010000007800016900000000ffffffff0100000079000174000000000000"
    "00000000000000010000"
)
EMPTY_ARRAY_HEX = "6c0200010400000001000000100000000501750001000000080167000261730000000000"
EMPTY_DICT_HEX = (
    "6c02000108000000010000001300000005017500010000000801670005617b73767d"
    "0000000000000000000000000000"
)


def _hello() -> bytes:
    return encode_message(
        MESSAGE_METHOD_CALL,
        1,
        {_F.FIELD_PATH: BUS_PATH, _F.FIELD_INTERFACE: BUS_IFACE, _F.FIELD_MEMBER: "Hello"}
        | {_F.FIELD_DESTINATION: BUS_NAME},
        flags=FLAG_NO_AUTO_START,
    )


def test_hello_frame_matches_independent_implementation() -> None:
    assert _hello() == binascii.unhexlify(HELLO_HEX)


def test_properties_get_frame_matches_independent_implementation() -> None:
    frame = encode_message(
        MESSAGE_METHOD_CALL,
        2,
        {
            _F.FIELD_PATH: "/org/freedesktop/login1",
            _F.FIELD_INTERFACE: dc.PROPERTIES_IFACE,
            _F.FIELD_MEMBER: "Get",
            _F.FIELD_DESTINATION: "org.freedesktop.login1",
        },
        "ss",
        ("org.freedesktop.login1.Manager", "PreparingForSleep"),
        flags=FLAG_NO_AUTO_START,
    )
    assert frame == binascii.unhexlify(GET_HEX)


@pytest.mark.parametrize(
    ("hex_frame", "signature", "body"),
    [
        (RETURN_VARIANT_BOOL_HEX, "v", (Variant("b", True),)),
        (EMPTY_ARRAY_HEX, "as", ([],)),
        (EMPTY_DICT_HEX, "a{sv}", ({},)),
        (
            NESTED_HEX,
            "a{sa{sv}}",
            ({"k": {"x": Variant("i", -1), "y": Variant("t", 2**40)}},),
        ),
        (MIXED_HEX, "ybnqiuxtdsog", (255, True, -2, 65535, -3, 4, -5, 6, 1.5, "s", "/o", "g")),
    ],
)
def test_marshalling_round_trips_against_golden_bytes(
    hex_frame: str, signature: str, body: tuple[object, ...]
) -> None:
    raw = binascii.unhexlify(hex_frame)
    message = decode_message(raw)
    assert message.signature == signature
    assert message.body == body
    fields = {code: value for code, value in message.fields.items() if code != _F.FIELD_SIGNATURE}
    assert encode_message(message.kind, message.serial, fields, signature, body) == raw


def test_properties_changed_signal_decodes() -> None:
    message = decode_message(binascii.unhexlify(SIGNAL_PROPS_CHANGED_HEX))
    assert message.kind == MESSAGE_SIGNAL
    assert message.member == "PropertiesChanged"
    assert message.path == "/org/freedesktop/NetworkManager"
    iface, changed, invalidated = message.body
    assert iface == "org.freedesktop.NetworkManager"
    assert changed == {"Metered": Variant("u", 3), "Connectivity": Variant("u", 4)}
    assert invalidated == ["PrimaryConnection"]


def test_big_endian_frames_are_accepted() -> None:
    little = encode_message(
        MESSAGE_METHOD_RETURN, 3, {_F.FIELD_REPLY_SERIAL: 1}, "v", (Variant("u", 7),)
    )
    big = encode_message(
        MESSAGE_METHOD_RETURN, 3, {_F.FIELD_REPLY_SERIAL: 1}, "v", (Variant("u", 7),), endian=">"
    )
    assert big != little and big[0] == ord("B")
    assert decode_message(big).body == decode_message(little).body == (Variant("u", 7),)


# --------------------------------------------------------------------------
# strictness: every malformed frame is a ProtocolError, never a crash or a guess
# --------------------------------------------------------------------------


def _corrupt(raw: bytes, offset: int, value: int) -> bytes:
    data = bytearray(raw)
    data[offset] = value
    return bytes(data)


@pytest.mark.parametrize(
    ("label", "frame"),
    [
        ("short", b"l\x01\x00\x01"),
        ("endianness", _corrupt(binascii.unhexlify(HELLO_HEX), 0, ord("x"))),
        ("version", _corrupt(binascii.unhexlify(HELLO_HEX), 3, 2)),
        ("zero serial", _corrupt(binascii.unhexlify(HELLO_HEX), 8, 0)),
        ("truncated", binascii.unhexlify(HELLO_HEX)[:-5]),
        ("trailing", binascii.unhexlify(HELLO_HEX) + b"\0"),
        (
            "bad path",
            binascii.unhexlify(HELLO_HEX).replace(
                b"/org/freedesktop/DBus", b"/org//reedesktop/DBus"
            ),
        ),
        ("non-zero padding", _corrupt(binascii.unhexlify(RETURN_VARIANT_BOOL_HEX), 63, 1)),
        ("bool out of range", _corrupt(binascii.unhexlify(RETURN_VARIANT_BOOL_HEX), 68, 2)),
    ],
)
def test_malformed_frames_are_rejected(label: str, frame: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_message(frame)


def test_header_field_with_wrong_type_is_corrupt_but_unknown_fields_are_ignored() -> None:
    # unknown code 200 with any payload: ignored (spec)
    fields = [(1, Variant("o", "/x")), (3, Variant("s", "M")), (200, Variant("u", 9))]
    writer = dc._Writer()
    writer.buf += struct.pack("<BBBBII", ord("l"), MESSAGE_METHOD_CALL, 0, 1, 0, 5)
    writer._one("a(yv)", fields, 0)
    writer.pad(8)
    assert decode_message(bytes(writer.buf)).member == "M"
    # known code PATH carrying a string instead of an object path: corrupt
    writer = dc._Writer()
    writer.buf += struct.pack("<BBBBII", ord("l"), MESSAGE_METHOD_CALL, 0, 1, 0, 5)
    writer._one("a(yv)", [(1, Variant("s", "/x")), (3, Variant("s", "M"))], 0)
    writer.pad(8)
    with pytest.raises(ProtocolError, match="header field 1"):
        decode_message(bytes(writer.buf))


def test_frame_length_enforces_the_message_cap() -> None:
    head = b"l" + bytes([MESSAGE_SIGNAL, 1, 1]) + struct.pack("<III", 1 << 30, 5, 0)
    with pytest.raises(ProtocolError, match="exceeds"):
        dc.frame_length(head)


@pytest.mark.parametrize(
    "bad", ["a", "(", "()", "{ss}", "a{vs}", "a{s}", "z", "(" * 70 + "i" + ")" * 70]
)
def test_invalid_signatures_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        split_signature(bad)


def test_encoder_refuses_what_the_wire_cannot_carry() -> None:
    with pytest.raises(ValueError):
        encode_message(MESSAGE_METHOD_RETURN, 1, {}, "s", ("nul\0inside",))
    with pytest.raises(ValueError):
        encode_message(MESSAGE_METHOD_RETURN, 1, {}, "o", ("not-a-path",))
    with pytest.raises(ValueError):
        encode_message(MESSAGE_METHOD_RETURN, 0, {})  # zero serial
    with pytest.raises(ValueError):
        encode_message(MESSAGE_METHOD_RETURN, 1, {}, "v", (("b", True),))  # not a Variant


# --------------------------------------------------------------------------
# addresses and match rules
# --------------------------------------------------------------------------


def test_parse_address_handles_path_abstract_escapes_and_fallbacks() -> None:
    assert parse_address("unix:path=/run/dbus/system_bus_socket") == ["/run/dbus/system_bus_socket"]
    assert parse_address("unix:abstract=/tmp/dbus-XYZ,guid=abc") == ["\0/tmp/dbus-XYZ"]
    assert parse_address("tcp:host=1.2.3.4,port=1;unix:path=/a%20b") == ["/a b"]
    assert parse_address(dc.SYSTEM_BUS_FALLBACK) == [
        "/run/dbus/system_bus_socket",
        "/var/run/dbus/system_bus_socket",
    ]
    assert parse_address("tcp:host=x") == []


def test_system_bus_address_prefers_the_environment() -> None:
    assert dc.system_bus_address({"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/x"}) == "unix:path=/x"
    assert dc.system_bus_address({}) == dc.SYSTEM_BUS_FALLBACK


def test_match_rule_is_fixed_keys_and_validated_values() -> None:
    rule = match_rule(type="signal", sender="org.freedesktop.login1", member="PrepareForSleep")
    assert rule == "type='signal',sender='org.freedesktop.login1',member='PrepareForSleep'"
    with pytest.raises(ValueError):
        match_rule(sender="evil',eavesdrop='true")
    with pytest.raises(ValueError):
        match_rule(eavesdrop="true")  # not an allowed key, ever


# --------------------------------------------------------------------------
# the connection against the fake bus
# --------------------------------------------------------------------------


@pytest.fixture()
def bus() -> FakeBus:  # type: ignore[misc]
    fake = FakeBus()
    yield fake
    fake.close()


def test_handshake_hello_first_and_no_auto_start_on_every_call(bus: FakeBus) -> None:
    bus.set_property(
        "org.freedesktop.login1",
        "/org/freedesktop/login1",
        "org.freedesktop.login1.Manager",
        "IdleHint",
        Variant("b", False),
    )
    with BusConnection.connect(bus.address, uid=1000) as conn:
        assert conn.unique_name == ":1.42"
        value = conn.get_property(
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager",
            "IdleHint",
        )
    assert value == Variant("b", False)
    assert bus.auth_lines == [b"AUTH EXTERNAL 31303030", b"BEGIN"]  # hex("1000")
    assert [rec.member for rec in bus.sent] == ["Hello", "Get"]
    assert all(rec.flags & FLAG_NO_AUTO_START for rec in bus.sent)
    assert not any(rec.flags & 0x4 for rec in bus.sent)  # never ALLOW_INTERACTIVE_AUTHORIZATION
    assert bus.sent[1].body == ("org.freedesktop.login1.Manager", "IdleHint")


def test_add_match_reaches_the_bus_and_signals_arrive(bus: FakeBus) -> None:
    rule = match_rule(type="signal", interface="org.freedesktop.login1.Manager")
    with BusConnection.connect(bus.address, uid=1000) as conn:
        conn.add_match(rule)
        assert bus.matches == [rule]
        bus.emit_signal(
            "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager",
            "PrepareForSleep",
            "b",
            (True,),
        )
        signal = conn.next_signal(2.0)
        assert signal is not None and signal.member == "PrepareForSleep"
        assert signal.body == (True,)
        assert conn.next_signal(0.05) is None


def test_remote_errors_carry_the_error_name(bus: FakeBus) -> None:
    with BusConnection.connect(bus.address, uid=1000) as conn:
        with pytest.raises(RemoteError) as info:
            conn.get_property("org.freedesktop.UPower", "/org/freedesktop/UPower", "x", "OnBattery")
        assert info.value.name == "org.freedesktop.DBus.Error.ServiceUnknown"
        assert conn.connected  # an error reply is not a protocol violation


def test_wrong_reply_signature_is_a_protocol_error(bus: FakeBus) -> None:
    bus.wrong_signature_for.add("Get")
    with BusConnection.connect(bus.address, uid=1000) as conn, pytest.raises(ProtocolError):
        conn.get_property(BUS_NAME, BUS_PATH, BUS_IFACE, "Features")


def test_rejected_authentication_is_unavailable_not_a_crash() -> None:
    bus = FakeBus(reject_auth=True)
    try:
        with pytest.raises(BusUnavailable, match="rejected"):
            BusConnection.connect(bus.address, uid=1000)
    finally:
        bus.close()


def test_garbage_after_hello_disconnects(bus: FakeBus) -> None:
    bus.garbage_after_hello = b"l\x02\x01\x01" + b"\0" * 12  # zero serial
    with BusConnection.connect(bus.address, uid=1000) as conn:
        with pytest.raises(ProtocolError):
            conn.call(BUS_NAME, BUS_PATH, BUS_IFACE, "GetNameOwner", "s", ("x",))
        assert not conn.connected


def test_oversize_frame_is_refused_before_it_is_read(bus: FakeBus) -> None:
    bus.oversize_after_hello = True
    with BusConnection.connect(bus.address, uid=1000) as conn:
        with pytest.raises(ProtocolError, match="exceeds"):
            conn.call(BUS_NAME, BUS_PATH, BUS_IFACE, "GetNameOwner", "s", ("x",))
        assert not conn.connected


def test_absent_socket_is_unavailable_with_every_path_named() -> None:
    with pytest.raises(BusUnavailable) as info:
        BusConnection.connect("unix:path=/nonexistent/a;unix:abstract=jarvis-test-none", uid=1)
    assert "/nonexistent/a" in str(info.value) and "@jarvis-test-none" in str(info.value)


def test_call_times_out_honestly_and_closes() -> None:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    name = "\0jarvis-test-silent-" + str(id(listener))
    listener.bind(name)
    listener.listen(1)
    try:
        with pytest.raises(BusUnavailable, match="timed out"):
            BusConnection.connect("unix:abstract=" + name[1:], uid=1, timeout=0.2)
    finally:
        listener.close()


def test_peer_ping_is_answered_and_other_calls_get_unknown_method(bus: FakeBus) -> None:
    with BusConnection.connect(bus.address, uid=1000) as conn:
        ping = encode_message(
            MESSAGE_METHOD_CALL,
            900,
            {_F.FIELD_PATH: "/", _F.FIELD_INTERFACE: dc.PEER_IFACE, _F.FIELD_MEMBER: "Ping"}
            | {_F.FIELD_SENDER: ":1.9"},
        )
        exec_call = encode_message(
            MESSAGE_METHOD_CALL,
            901,
            {_F.FIELD_PATH: "/", _F.FIELD_INTERFACE: "org.example", _F.FIELD_MEMBER: "Execute"}
            | {_F.FIELD_SENDER: ":1.9"},
        )
        bus.send_raw(ping + exec_call)
        assert conn.next_signal(0.3) is None  # both handled inline, nothing queued
    replies = [rec.message for rec in bus.sent if rec.message.reply_serial in (900, 901)]
    assert [m.kind for m in replies] == [MESSAGE_METHOD_RETURN, dc.MESSAGE_ERROR]
    assert replies[1].fields[_F.FIELD_ERROR_NAME] == dc.ERROR_UNKNOWN_METHOD


def test_client_never_originates_state_changing_frames(bus: FakeBus) -> None:
    """The surface is Hello / Properties.Get / AddMatch — nothing else exists to call."""
    public = {name for name in dir(BusConnection) if not name.startswith("_")}
    assert public == {
        "add_match",
        "call",
        "close",
        "connect",
        "connected",
        "get_property",
        "next_signal",
    }
    with BusConnection.connect(bus.address, uid=1000):
        pass
    assert [rec.member for rec in bus.sent] == ["Hello"]


def test_bus_error_hierarchy() -> None:
    assert issubclass(BusUnavailable, BusError)
    assert issubclass(ProtocolError, BusError)
    assert issubclass(RemoteError, BusError)
