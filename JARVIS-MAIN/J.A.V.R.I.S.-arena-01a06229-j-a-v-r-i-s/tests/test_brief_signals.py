"""ADR-0031: environment signals as briefing inputs — sensing, holds, listener, units.

Fixtures are fake sysfs roots (the kernel ABI file names, verbatim) and the
in-process fake bus; nothing here touches the real ``/sys`` or a real bus.
"""

from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stdout
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fakebus import FakeBus
from jarvis.brief import engine, install, listen, signals
from jarvis.brief.engine import Briefing, BriefLedger, compose, decide, run_once
from jarvis.brief.signals import Battery, Signals, sense
from jarvis.cli.app import main
from jarvis.context.store import ContextStore
from jarvis.journal.sqlite import Journal
from jarvis.system.dbus_client import Variant

LOGIN1 = "org.freedesktop.login1"
MANAGER_PATH = "/org/freedesktop/login1"
MANAGER = "org.freedesktop.login1.Manager"
SESSION = "org.freedesktop.login1.Session"
SESSION_AUTO = "/org/freedesktop/login1/session/auto"
NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NOW = datetime(2026, 9, 6, 9, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def laptop_root(tmp_path: Path, *, capacity: str = "15", status: str = "Discharging") -> Path:
    root = tmp_path / "root"
    # Everything that must be skipped sorts BEFORE the real battery ("macsmc-battery",
    # the Apple-silicon name, sorts after "hid-…"): a UPS (type filter), a mains adapter
    # (type filter) and a wireless mouse cell (scope=Device, as hid-input registers it).
    _write(root, "sys/class/power_supply/APC-UPS/type", "UPS\n")
    _write(root, "sys/class/power_supply/APC-UPS/capacity", "55\n")
    _write(root, "sys/class/power_supply/APC-UPS/status", "Discharging\n")
    _write(root, "sys/class/power_supply/AC/type", "Mains\n")
    _write(root, "sys/class/power_supply/AC/online", "0\n")
    _write(root, "sys/class/power_supply/hid-0005:046D:B023.0003-battery/type", "Battery\n")
    _write(root, "sys/class/power_supply/hid-0005:046D:B023.0003-battery/scope", "Device\n")
    _write(root, "sys/class/power_supply/hid-0005:046D:B023.0003-battery/capacity", "40\n")
    _write(root, "sys/class/power_supply/hid-0005:046D:B023.0003-battery/status", "Discharging\n")
    _write(root, "sys/class/power_supply/macsmc-battery/type", "Battery\n")
    _write(root, "sys/class/power_supply/macsmc-battery/scope", "System\n")
    _write(root, "sys/class/power_supply/macsmc-battery/capacity", f"{capacity}\n")
    _write(root, "sys/class/power_supply/macsmc-battery/status", f"{status}\n")
    _write(root, "sys/class/net/lo/type", "772\n")
    _write(root, "sys/class/net/lo/operstate", "unknown\n")
    _write(root, "sys/class/net/lo/carrier", "1\n")
    _write(root, "sys/class/net/wlp2s0/type", "1\n")
    _write(root, "sys/class/net/wlp2s0/operstate", "down\n")
    _write(root, "sys/power/suspend_stats/success", "7\n")
    _write(root, "proc/sys/kernel/random/boot_id", "11111111-2222-3333-4444-555555555555\n")
    return root


@pytest.fixture()
def bus() -> FakeBus:  # type: ignore[misc]
    fake = FakeBus()
    fake.set_property(LOGIN1, MANAGER_PATH, MANAGER, "PreparingForSleep", Variant("b", False))
    fake.set_property(LOGIN1, MANAGER_PATH, MANAGER, "PreparingForShutdown", Variant("b", False))
    fake.set_property(LOGIN1, MANAGER_PATH, MANAGER, "IdleHint", Variant("b", False))
    fake.set_property(LOGIN1, SESSION_AUTO, SESSION, "LockedHint", Variant("b", False))
    fake.set_property(NM, NM_PATH, NM, "Metered", Variant("u", 4))  # GUESS_NO
    fake.set_property(NM, NM_PATH, NM, "Connectivity", Variant("u", 4))  # FULL
    yield fake
    fake.close()


@pytest.fixture()
def quiet_suggestions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "generate_suggestions", lambda *a, **k: [])


def _run(
    journal: Journal, state: Path, *, disk_free: float = 50.0, **kwargs: object
) -> tuple[dict[str, object], str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        payload = run_once(
            journal=journal,
            profile=object(),
            state=state,
            disk_free=disk_free,
            now=NOW,
            no_desktop=True,
            **kwargs,  # type: ignore[arg-type]
        )
    return payload, buf.getvalue()


# --------------------------------------------------------------------------
# D1 / D2: sysfs sensing with the HUD-identical battery filter
# --------------------------------------------------------------------------


def test_battery_skips_mains_and_peripherals_and_clamps(tmp_path: Path) -> None:
    root = laptop_root(tmp_path, capacity="101", status="Full")
    battery = signals.read_battery(root)
    assert battery == Battery(percent=100, status="Full", discharging=False)


def test_battery_none_when_only_peripherals_or_nothing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write(root, "sys/class/power_supply/hid-mouse/type", "Battery\n")
    _write(root, "sys/class/power_supply/hid-mouse/scope", "Device\n")
    _write(root, "sys/class/power_supply/hid-mouse/capacity", "40\n")
    _write(root, "sys/class/power_supply/hid-mouse/status", "Discharging\n")
    assert signals.read_battery(root) is None  # a desktop with a wireless mouse
    assert signals.read_battery(tmp_path / "empty") is None  # container / VM
    # a battery without a scope file (older drivers, ACPI BAT0) still counts
    _write(root, "sys/class/power_supply/BAT0/type", "Battery\n")
    _write(root, "sys/class/power_supply/BAT0/capacity", "80\n")
    _write(root, "sys/class/power_supply/BAT0/status", "Charging\n")
    assert signals.read_battery(root) == Battery(percent=80, status="Charging", discharging=False)


def test_battery_unknown_status_is_not_discharging(tmp_path: Path) -> None:
    root = laptop_root(tmp_path, capacity="10", status="Vendor-Weird")
    battery = signals.read_battery(root)
    assert battery is not None and battery.discharging is None and battery.status == "Unknown"
    # S1 requires an explicit "Discharging": unknown never produces a line
    assert Signals(mode="sysfs", battery=battery).items() == ()


def test_link_ignores_loopback_and_reads_unknown_with_carrier(tmp_path: Path) -> None:
    root = laptop_root(tmp_path)
    assert signals.read_link(root) is False  # lo excluded (type 772), wlan down
    _write(root, "sys/class/net/wlp2s0/operstate", "up\n")
    assert signals.read_link(root) is True
    _write(root, "sys/class/net/wlp2s0/operstate", "unknown\n")
    _write(root, "sys/class/net/wlp2s0/carrier", "1\n")
    assert signals.read_link(root) is True  # ABI: unknown = "must be considered for user data"
    _write(root, "sys/class/net/wlp2s0/carrier", "0\n")
    assert signals.read_link(root) is False
    assert signals.read_link(tmp_path / "nowhere") is None  # no /sys at all → not sensed
    only_lo = tmp_path / "only_lo"
    _write(only_lo, "sys/class/net/lo/type", "772\n")
    _write(only_lo, "sys/class/net/lo/operstate", "unknown\n")
    assert signals.read_link(only_lo) is None  # loopback alone is not a judgement


def test_suspend_cycles_delta_within_one_boot(tmp_path: Path) -> None:
    root = laptop_root(tmp_path)
    current = signals.read_suspend_count(root)
    assert current is not None and current.success == 7
    previous = {"boot_id": current.boot_id, "success": 5}
    assert sense("sysfs", root=root, previous_suspend=previous).suspend_cycles == 2
    other_boot = {"boot_id": "other", "success": 5}
    assert sense("sysfs", root=root, previous_suspend=other_boot).suspend_cycles is None
    assert sense("sysfs", root=root, previous_suspend=None).suspend_cycles is None
    assert sense("sysfs", root=tmp_path / "nowhere").suspend is None


def test_off_mode_senses_nothing_and_is_the_empty_value(tmp_path: Path) -> None:
    sensed = sense("off", root=laptop_root(tmp_path))
    assert sensed == Signals()
    assert not sensed.sensed and sensed.items() == () and sensed.holds() == ()
    assert sensed.context_line() is None
    with pytest.raises(ValueError):
        sense("busctl")  # rejected by the owner; not a mode


def test_sysfs_mode_yields_items_and_context_but_no_holds(tmp_path: Path) -> None:
    sensed = sense("sysfs", root=laptop_root(tmp_path))
    assert sensed.items() == (
        "battery 15% and discharging — not a moment for a long upgrade",
        "no network link — package-index suggestions need a connection",
    )
    assert sensed.items(battery_low=10) == (
        "no network link — package-index suggestions need a connection",
    )
    assert sensed.holds() == ()  # S4/S5 need the bus
    assert sensed.context_line() == "battery 15% (discharging); link: down"
    assert sensed.bus == "off"


# --------------------------------------------------------------------------
# D2 bus mode: read-only, null on any failure, never "no"
# --------------------------------------------------------------------------


def test_bus_mode_reads_the_six_properties_read_only(tmp_path: Path, bus: FakeBus) -> None:
    sensed = sense("bus", root=laptop_root(tmp_path), bus_address=bus.address)
    assert sensed.bus == "ok"
    assert (sensed.metered, sensed.connectivity, sensed.locked, sensed.idle) == (
        False,
        4,
        False,
        False,
    )
    assert sensed.preparing_for_sleep is False and sensed.preparing_for_shutdown is False
    assert [rec.member for rec in bus.sent] == ["Hello"] + ["Get"] * 6
    assert all(rec.flags & 0x2 for rec in bus.sent), "NO_AUTO_START on every call"
    gets = [rec.body for rec in bus.sent if rec.member == "Get"]
    assert (SESSION, "LockedHint") in gets and (NM, "Metered") in gets


@pytest.mark.parametrize(
    ("metered_value", "expected"),
    [(0, None), (1, True), (2, False), (3, True), (4, False), (99, None)],
)
def test_metered_enum_mapping(
    tmp_path: Path, bus: FakeBus, metered_value: int, expected: bool | None
) -> None:
    bus.set_property(NM, NM_PATH, NM, "Metered", Variant("u", metered_value))
    assert sense("bus", root=tmp_path, bus_address=bus.address).metered is expected


def test_bus_facts_are_null_when_a_service_is_absent(tmp_path: Path, bus: FakeBus) -> None:
    bus.known_names.discard(NM)  # no NetworkManager on this host
    sensed = sense("bus", root=tmp_path, bus_address=bus.address)
    assert sensed.metered is None and sensed.connectivity is None
    assert sensed.locked is False  # logind still answered
    assert sensed.bus == "ok"
    assert sensed.items() == ()  # null never becomes a line


def test_bus_unavailable_degrades_to_sysfs_only(tmp_path: Path) -> None:
    sensed = sense("bus", root=laptop_root(tmp_path), bus_address="unix:path=/nonexistent/bus")
    assert sensed.bus.startswith("unavailable:")
    assert sensed.battery is not None and sensed.link is False  # sysfs facts intact
    assert sensed.locked is None and sensed.holds() == ()


def test_bus_wrong_typed_property_is_null(tmp_path: Path, bus: FakeBus) -> None:
    bus.set_property(LOGIN1, SESSION_AUTO, SESSION, "LockedHint", Variant("s", "true"))
    assert sense("bus", root=tmp_path, bus_address=bus.address).locked is None


def test_rejected_bus_authentication_is_not_an_error(tmp_path: Path) -> None:
    rejecting = FakeBus(reject_auth=True)
    try:
        sensed = sense("bus", root=tmp_path, bus_address=rejecting.address)
    finally:
        rejecting.close()
    assert "rejected" in sensed.bus and sensed.holds() == ()


# --------------------------------------------------------------------------
# D3: holds withhold the knock only; everything else is written as usual
# --------------------------------------------------------------------------


def test_holds_only_from_explicit_true() -> None:
    assert Signals(mode="bus", locked=True).holds() == ("session-locked",)
    assert Signals(mode="bus", preparing_for_sleep=True).holds() == ("sleep-imminent",)
    assert Signals(mode="bus", preparing_for_shutdown=True).holds() == ("shutdown-imminent",)
    assert Signals(mode="bus", locked=None, preparing_for_sleep=None).holds() == ()
    assert Signals(mode="bus", locked=False).holds() == ()
    assert signals.holds_from_mapping({"session": "garbage"}) == ()


def test_held_briefing_written_ledgered_not_knocked(
    tmp_path: Path,
    bus: FakeBus,
    journal: Journal,
    quiet_suggestions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus.set_property(LOGIN1, SESSION_AUTO, SESSION, "LockedHint", Variant("b", True))
    knocks: list[str] = []
    monkeypatch.setattr(engine, "desktop_notify", lambda line: knocks.append(line) or True)
    journal.begin_task("t1", "demo", "svc.stop", 2, {}, {})
    journal.finish_task("t1", "failed")
    root = laptop_root(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        payload = run_once(
            journal=journal,
            profile=object(),
            state=tmp_path / "state",
            disk_free=50.0,
            now=NOW,
            signals_mode="bus",
            sysfs_root=root,
            bus_address=bus.address,
        )
    assert payload["decision"] == "notify" and payload["holds"] == ["session-locked"]
    assert knocks == [], "a held briefing must not knock"
    latest = (tmp_path / "state" / "briefings" / "latest.md").read_text()
    assert "held: session-locked (desktop notification withheld)" in latest
    assert "(held: session-locked; written to briefings/latest.md" in buf.getvalue()
    rows = [
        json.loads(line)
        for line in (tmp_path / "state" / "briefings" / "ledger.jsonl").read_text().splitlines()
    ]
    assert rows[-1]["delivered"] is False and rows[-1]["holds"] == ["session-locked"]
    assert rows[-1]["signals"]["session"]["locked"] is True
    ledger = BriefLedger(tmp_path / "state")
    assert ledger.stats()["held"] == 1
    held = ledger.held_undelivered(now=NOW)  # the run was stamped with NOW, not today
    assert held is not None and held["id"] == payload["id"]
    assert ledger.held_undelivered(now=NOW + timedelta(days=1)) is None, "held runs expire daily"


def test_unheld_briefing_still_knocks(
    tmp_path: Path,
    bus: FakeBus,
    journal: Journal,
    quiet_suggestions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knocks: list[str] = []
    monkeypatch.setattr(engine, "desktop_notify", lambda line: knocks.append(line) or True)
    journal.begin_task("t1", "demo", "svc.stop", 2, {}, {})
    journal.finish_task("t1", "failed")
    with redirect_stdout(io.StringIO()):
        payload = run_once(
            journal=journal,
            profile=object(),
            state=tmp_path / "state",
            disk_free=50.0,
            now=NOW,
            signals_mode="bus",
            sysfs_root=tmp_path / "nowhere",
            bus_address=bus.address,
            json_output=True,
        )
    assert payload["holds"] == [] and payload["delivered"] is True
    assert len(knocks) == 1


# --------------------------------------------------------------------------
# golden: "off" is byte-identical to the pre-ADR engine; ids stable without signal lines
# --------------------------------------------------------------------------

GOLDEN = (
    "# JARVIS briefing 0e7583e21c1a\n"
    "created: 2026-09-06T09:00:00+00:00\n"
    "\n"
    "- 1 task(s) failed in the last 7 days\n"
    "- 1 unmapped request(s) to review (jarvis grow)\n"
    "- low disk: 5.0% free on /\n"
    "\n"
    "decision: notify (1 task(s) failed in the last 7 days; 1 unmapped request(s) to review "
    "(jarvis grow); low disk: 5.0% free on /)\n"
)


def _golden_journal(journal: Journal) -> Journal:
    journal.begin_task("tfail", "failing demo", "svc.stop", 2, {}, {})
    journal.finish_task("tfail", "failed")
    journal.record_unknown_request("make me a sandwich", "unmatched", [])
    return journal


def test_off_mode_output_is_byte_identical_to_v1_22(
    tmp_path: Path, journal: Journal, quiet_suggestions: None
) -> None:
    """Captured from the v1.22.0 engine with the same seeded journal (see ADR-0031 D6)."""
    _golden_journal(journal)
    buf = io.StringIO()
    with redirect_stdout(buf):
        payload = run_once(
            journal=journal,
            profile=object(),
            state=tmp_path,
            disk_free=5.0,
            now=NOW,
            no_desktop=True,
            signals_mode="off",
        )
    assert buf.getvalue() == GOLDEN
    assert (tmp_path / "briefings" / "latest.md").read_text() == GOLDEN
    assert payload["id"] == "0e7583e21c1a"
    row = json.loads((tmp_path / "briefings" / "ledger.jsonl").read_text().splitlines()[-1])
    assert set(row) == {"ts", "kind", "id", "decision", "reasons", "delivered"}  # no new keys


def test_id_is_unchanged_when_signals_add_no_line(
    tmp_path: Path, journal: Journal, quiet_suggestions: None
) -> None:
    _golden_journal(journal)
    root = tmp_path / "root"
    _write(root, "sys/class/net/eth0/type", "1\n")
    _write(root, "sys/class/net/eth0/operstate", "up\n")
    payload, out = _run(
        journal, tmp_path / "s", disk_free=5.0, signals_mode="sysfs", sysfs_root=root
    )  # type: ignore[arg-type]
    assert payload["id"] == "0e7583e21c1a"
    assert out.endswith("context: link: up\n")


def test_id_changes_when_a_signal_line_is_added(
    tmp_path: Path, journal: Journal, quiet_suggestions: None
) -> None:
    _golden_journal(journal)
    payload, _ = _run(
        journal,
        tmp_path / "s",
        disk_free=5.0,
        signals_mode="sysfs",
        sysfs_root=laptop_root(tmp_path),
    )  # type: ignore[arg-type]
    assert payload["id"] != "0e7583e21c1a"
    assert payload["items"][-1].startswith("no network link")


def test_compose_stays_subprocess_free_with_signals(
    tmp_path: Path, journal: Journal, monkeypatch: pytest.MonkeyPatch, quiet_suggestions: None
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("compose/sense spawned a subprocess")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    sensed = sense("bus", root=laptop_root(tmp_path), bus_address="unix:path=/nonexistent")
    briefing = compose(
        journal,
        ContextStore(tmp_path / "ctx.json"),
        object(),
        disk_free=50.0,
        now=NOW,
        signals=sensed,
    )
    assert briefing.items and briefing.holds == ()


def test_briefing_dataclass_is_additive() -> None:
    names = [f.name for f in fields(Briefing)]
    assert names[:5] == ["briefing_id", "created", "items", "decision", "reasons"]
    assert names[5:] == ["holds", "signals", "context"]
    legacy = Briefing(briefing_id="abc", created="t", items=("x",))
    assert decide(legacy).to_json_dict()["holds"] == []
    assert decide(legacy).markdown().count("context:") == 0


# --------------------------------------------------------------------------
# D8: the listener — record + deliver on unlock/resume, nothing else
# --------------------------------------------------------------------------


def _held_ledger(state: Path, briefing_id: str = "held0001abcd") -> BriefLedger:
    ledger = BriefLedger(state)
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    briefing = Briefing(
        briefing_id=briefing_id,
        created=stamp,
        items=("1 task(s) failed in the last 7 days",),
        decision="notify",
        reasons=("1 task(s) failed in the last 7 days",),
        holds=("session-locked",),
        signals={"mode": "bus", "session": {"locked": True}},
    )
    ledger.record_run(briefing, delivered=False)
    return ledger


def _signal(
    path: str, iface: str, member: str, sig: str = "", body: tuple[object, ...] = ()
) -> object:
    from jarvis.system.dbus_client import (
        FIELD_INTERFACE,
        FIELD_MEMBER,
        FIELD_PATH,
        MESSAGE_SIGNAL,
        decode_message,
        encode_message,
    )

    return decode_message(
        encode_message(
            MESSAGE_SIGNAL,
            5,
            {FIELD_PATH: path, FIELD_INTERFACE: iface, FIELD_MEMBER: member},
            sig,
            body,
            flags=1,
        )
    )


def test_listener_subscribes_with_the_four_rules_and_reads_lockedhint(
    tmp_path: Path, bus: FakeBus
) -> None:
    listener = listen.Listener(BriefLedger(tmp_path), notify=lambda line: True)
    listener.subscribe(bus.address)
    assert bus.matches == list(listen.MATCH_RULES)
    assert len(bus.matches) == 4
    assert all("eavesdrop" not in rule for rule in bus.matches)
    assert listener.locked is False
    assert [rec.member for rec in bus.sent] == [
        "Hello",
        "AddMatch",
        "AddMatch",
        "AddMatch",
        "AddMatch",
        "Get",
    ]
    listener.disconnect()


def test_listener_delivers_the_held_briefing_once_on_unlock(tmp_path: Path, bus: FakeBus) -> None:
    ledger = _held_ledger(tmp_path)
    delivered: list[str] = []
    listener = listen.Listener(ledger, notify=lambda line: delivered.append(line) or True)
    bus.set_property(LOGIN1, SESSION_AUTO, SESSION, "LockedHint", Variant("b", True))
    listener.subscribe(bus.address)
    assert listener.locked is True
    # the lock screen goes away: logind emits PropertiesChanged on the session object
    bus.set_property(LOGIN1, SESSION_AUTO, SESSION, "LockedHint", Variant("b", False))
    changed = _signal(
        "/org/freedesktop/login1/session/_33",
        "org.freedesktop.DBus.Properties",
        "PropertiesChanged",
        "sa{sv}as",
        (SESSION, {"LockedHint": Variant("b", False)}, []),
    )
    listener.handle(changed)  # type: ignore[arg-type]
    assert delivered == ["1 task(s) failed in the last 7 days"]
    # a second unlock / resume does not deliver again (once per id)
    listener.handle(changed)  # type: ignore[arg-type]
    assert listener.deliver_if_clear("resume") is False
    assert len(delivered) == 1
    assert ledger.held_undelivered() is None
    kinds = [
        json.loads(line)["kind"]
        for line in (tmp_path / "briefings" / "ledger.jsonl").read_text().splitlines()
    ]
    assert kinds == ["run", "event", "event", "delivery"]
    assert ledger.stats()["late_deliveries"] == 1 and ledger.stats()["events"] == 2
    listener.disconnect()


def test_failed_delivery_is_not_retried_before_the_backoff(tmp_path: Path, bus: FakeBus) -> None:
    ledger = _held_ledger(tmp_path)
    attempts: list[str] = []
    clock = [1000.0]
    listener = listen.Listener(
        ledger,
        notify=lambda line: attempts.append(line) is None and False,  # notify-send absent
        clock=lambda: clock[0],
    )
    listener.subscribe(bus.address)
    assert listener.deliver_if_clear("unlock") is False
    assert len(attempts) == 1
    assert ledger.held_undelivered() is not None  # still held: nothing was delivered
    assert listener.deliver_if_clear("resume") is False
    assert len(attempts) == 1, "no retry storm within RETRY_DELIVERY_AFTER"
    clock[0] += listen.RETRY_DELIVERY_AFTER
    listener.deliver_if_clear("resume")
    assert len(attempts) == 2
    rows = [
        json.loads(line)
        for line in (tmp_path / "briefings" / "ledger.jsonl").read_text().splitlines()
    ]
    assert [r["delivered"] for r in rows if r["kind"] == "delivery"] == [False, False]
    listener.disconnect()


def test_listener_delivers_on_resume_and_records_sleep(tmp_path: Path, bus: FakeBus) -> None:
    ledger = _held_ledger(tmp_path)
    delivered: list[str] = []
    listener = listen.Listener(ledger, notify=lambda line: delivered.append(line) or True)
    listener.subscribe(bus.address)
    listener.handle(_signal(MANAGER_PATH, MANAGER, "PrepareForSleep", "b", (True,)))  # type: ignore[arg-type]
    assert delivered == []
    listener.handle(_signal(MANAGER_PATH, MANAGER, "PrepareForSleep", "b", (False,)))  # type: ignore[arg-type]
    assert len(delivered) == 1
    events = [
        json.loads(line)
        for line in (tmp_path / "briefings" / "ledger.jsonl").read_text().splitlines()
    ]
    assert [e.get("event") for e in events if e["kind"] == "event"] == ["bus", "sleep", "resume"]
    listener.disconnect()


def test_listener_does_not_deliver_while_still_locked_on_resume(
    tmp_path: Path, bus: FakeBus
) -> None:
    ledger = _held_ledger(tmp_path)
    delivered: list[str] = []
    listener = listen.Listener(ledger, notify=lambda line: delivered.append(line) or True)
    bus.set_property(LOGIN1, SESSION_AUTO, SESSION, "LockedHint", Variant("b", True))
    listener.subscribe(bus.address)
    listener.handle(_signal(MANAGER_PATH, MANAGER, "PrepareForSleep", "b", (False,)))  # type: ignore[arg-type]
    assert delivered == [], "resume with the screen still locked keeps the hold"
    listener.disconnect()


def test_listener_record_only_never_delivers(tmp_path: Path, bus: FakeBus) -> None:
    ledger = _held_ledger(tmp_path)
    delivered: list[str] = []
    listener = listen.Listener(
        ledger, record_only=True, notify=lambda line: delivered.append(line) or True
    )
    listener.subscribe(bus.address)
    listener.handle(_signal(MANAGER_PATH, MANAGER, "PrepareForSleep", "b", (False,)))  # type: ignore[arg-type]
    assert delivered == [] and ledger.held_undelivered() is not None
    listener.disconnect()


def test_listener_records_network_changes_and_shutdown(tmp_path: Path, bus: FakeBus) -> None:
    ledger = BriefLedger(tmp_path)
    listener = listen.Listener(ledger, notify=lambda line: True)
    listener.subscribe(bus.address)
    listener.handle(
        _signal(
            NM_PATH,
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            "sa{sv}as",
            (NM, {"Metered": Variant("u", 1), "Connectivity": Variant("u", 2)}, []),
        )  # type: ignore[arg-type]
    )
    listener.handle(_signal(MANAGER_PATH, MANAGER, "PrepareForShutdown", "b", (True,)))  # type: ignore[arg-type]
    rows = [
        json.loads(line)
        for line in (tmp_path / "briefings" / "ledger.jsonl").read_text().splitlines()
    ]
    assert rows[1] == {
        **rows[1],
        "kind": "event",
        "event": "network",
        "metered": True,
        "connectivity": 2,
    }
    assert rows[2]["event"] == "shutdown"
    listener.disconnect()


def test_listener_never_originates_anything_but_hello_addmatch_get(
    tmp_path: Path, bus: FakeBus
) -> None:
    ledger = _held_ledger(tmp_path)
    listener = listen.Listener(ledger, notify=lambda line: True)
    listener.subscribe(bus.address)
    for frame in (
        _signal(MANAGER_PATH, MANAGER, "PrepareForSleep", "b", (True,)),
        _signal(MANAGER_PATH, MANAGER, "PrepareForSleep", "b", (False,)),
        _signal(
            "/org/freedesktop/login1/session/_33",
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            "sa{sv}as",
            (SESSION, {"LockedHint": Variant("b", True)}, []),
        ),
        _signal(
            "/org/freedesktop/login1/session/_33",
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            "sa{sv}as",
            (SESSION, {"LockedHint": Variant("b", False)}, []),
        ),
        _signal(MANAGER_PATH, MANAGER, "PrepareForShutdown", "b", (True,)),
        _signal(
            NM_PATH,
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            "sa{sv}as",
            (NM, {"Metered": Variant("u", 1)}, []),
        ),
        _signal("/x", "org.example", "Execute", "s", ("rm -rf /",)),
    ):
        listener.handle(frame)  # type: ignore[arg-type]
    assert {rec.member for rec in bus.sent} <= {"Hello", "AddMatch", "Get"}
    assert all(rec.flags & 0x2 for rec in bus.sent)
    listener.disconnect()


def test_listener_never_composes_or_executes() -> None:
    source = Path(listen.__file__).read_text()
    for forbidden in ("compose(", "run_once(", "Orchestrator", "subprocess", "playbook", "Runner"):
        assert forbidden not in source, f"listener must not reference {forbidden}"


def test_listener_event_rate_limit(tmp_path: Path) -> None:
    ledger = BriefLedger(tmp_path)
    clock = [0.0]
    listener = listen.Listener(ledger, notify=lambda line: True, clock=lambda: clock[0])
    for _ in range(listen.MAX_EVENTS_PER_HOUR + 10):
        listener.record("network", {})
    rows = (tmp_path / "briefings" / "ledger.jsonl").read_text().splitlines()
    assert len(rows) == listen.MAX_EVENTS_PER_HOUR + 1  # + one "event-limit" marker
    assert json.loads(rows[-1])["event"] == "event-limit"
    clock[0] = 3601.0
    listener.record("network", {})
    assert (
        len((tmp_path / "briefings" / "ledger.jsonl").read_text().splitlines())
        == listen.MAX_EVENTS_PER_HOUR + 2
    )


def test_held_undelivered_is_superseded_by_a_newer_unheld_run(tmp_path: Path) -> None:
    ledger = _held_ledger(tmp_path)
    later = Briefing(
        briefing_id="new00002abcd",
        created=datetime.now(timezone.utc).isoformat(),
        items=("x",),
        decision="notify",
        reasons=("x",),
    )
    ledger.record_run(later, delivered=True)
    assert ledger.held_undelivered() is None


def test_held_undelivered_ignores_yesterday(tmp_path: Path) -> None:
    ledger = BriefLedger(tmp_path)
    old = Briefing(
        briefing_id="old00003abcd",
        created="2020-01-01T09:00:00+00:00",
        items=("x",),
        decision="notify",
        reasons=("x",),
        holds=("session-locked",),
    )
    ledger.record_run(old, delivered=False)
    assert ledger.held_undelivered() is None


def test_run_listener_without_a_bus_stays_up_and_exits_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    rc = listen.run_listener(state=tmp_path, address="unix:path=/nonexistent/bus", once=True)
    assert rc == 0
    err = capsys.readouterr().err
    assert "bus unavailable" in err and "retry in 2s" in err


def test_run_listener_one_pass_against_the_fake_bus(
    tmp_path: Path, bus: FakeBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    rc = listen.run_listener(state=tmp_path, address=bus.address, once=True)
    assert rc == 0 and bus.matches == list(listen.MATCH_RULES)


# --------------------------------------------------------------------------
# D5: units — default text unchanged; flags rendered; listener unit
# --------------------------------------------------------------------------


def test_default_service_unit_text_is_unchanged() -> None:
    assert install.service_content("/usr/bin/python3") == (
        "[Unit]\n"
        "Description=JARVIS briefing (propose-only; ADR-0021)\n"
        "\n"
        "[Service]\n"
        "ExecStart=/usr/bin/python3 -m jarvis brief --quiet\n"
        "Type=oneshot\n"
    )


def test_signal_flags_render_into_execstart_only_when_non_default() -> None:
    text = install.service_content("/usr/bin/python3", signals="bus", battery_low=30)
    assert (
        "ExecStart=/usr/bin/python3 -m jarvis brief --quiet --signals bus --battery-low 30\n"
        in text
    )
    assert install.service_content(
        "/usr/bin/python3", signals="sysfs", battery_low=20
    ) == install.service_content("/usr/bin/python3")
    with pytest.raises(Exception, match="--signals"):
        install.service_content("/usr/bin/python3", signals="busctl")
    with pytest.raises(Exception, match="--battery-low"):
        install.service_content("/usr/bin/python3", battery_low=101)


def test_listener_unit_is_supervised_and_optionally_hardened(tmp_path: Path) -> None:
    plain = install.listener_content("/usr/bin/python3")
    assert "Type=notify\n" in plain and "NotifyAccess=main\n" in plain
    assert f"WatchdogSec={install.LISTENER_WATCHDOG_SEC}\n" in plain
    assert "Restart=on-failure\n" in plain
    assert "ExecStart=/usr/bin/python3 -m jarvis brief listen\n" in plain
    assert plain.endswith("[Install]\nWantedBy=default.target\n")
    assert "ProtectSystem" not in plain
    hardened = install.listener_content(
        "/usr/bin/python3", harden=True, state=tmp_path, record_only=True
    )
    assert "-m jarvis brief listen --record-only\n" in hardened
    for directive in install.HARDENING_DIRECTIVES:
        assert directive in hardened
    assert f"ReadWritePaths={tmp_path}\n" in hardened
    assert "RestrictAddressFamilies=AF_UNIX" in hardened  # the bus socket stays reachable


def test_install_writes_both_units_and_uninstall_removes_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(install, "_systemctl_available", lambda: False)
    monkeypatch.setattr(install.sys, "executable", "/usr/bin/python3")
    assert install.install_timer("daily", tmp_path, signals="bus", listen=True) == 0
    out = capsys.readouterr().out
    assert "jarvis-signals.service" in out and "NOT enabled" in out
    assert "signals=bus" in out and "listener:" in out
    unit = install.listener_path(tmp_path).read_text()
    assert "-m jarvis brief listen\n" in unit
    assert "--signals bus" in install.service_path(tmp_path).read_text()
    assert install.uninstall_timer(tmp_path) == 0
    assert not install.listener_path(tmp_path).exists()
    assert not install.service_path(tmp_path).exists()


def test_install_without_listen_leaves_no_listener_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(install, "_systemctl_available", lambda: False)
    assert install.install_timer("weekly", tmp_path) == 0
    assert not install.listener_path(tmp_path).exists()
    assert "listener" not in capsys.readouterr().out.split("disclosure")[0]


def test_install_validates_before_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install, "_systemctl_available", lambda: False)
    with pytest.raises(Exception, match="--battery-low"):
        install.install_timer("daily", tmp_path, battery_low=-1, listen=True)
    assert not install.service_path(tmp_path).exists()
    assert not install.listener_path(tmp_path).exists()


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def test_cli_flags_on_brief_and_brief_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quiet_suggestions: None
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    seen: list[dict[str, object]] = []

    def fake_run_once(**kwargs: object) -> dict[str, object]:
        seen.append(kwargs)
        return {"id": "x", "decision": "silence"}

    monkeypatch.setattr(engine, "run_once", fake_run_once)
    assert main(["brief", "--quiet", "--signals", "bus", "--battery-low", "35"]) == 0
    assert main(["brief", "run", "--signals", "off"]) == 0
    assert main(["brief", "--quiet"]) == 0
    assert [(k["signals_mode"], k["battery_low"], k["quiet"]) for k in seen] == [
        ("bus", 35, True),
        ("off", 20, False),
        ("sysfs", 20, True),
    ]
    assert signals.DEFAULT_BATTERY_LOW == 20  # the parser literals must track this constant


def test_cli_refuses_out_of_range_threshold_and_unknown_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert main(["brief", "run", "--battery-low", "200"]) == 2
    assert "refused: --battery-low" in capsys.readouterr().err
    with pytest.raises(Exception, match="--signals"):
        run_once(
            state=tmp_path,
            journal=Journal(tmp_path / "j.db"),
            profile=object(),
            signals_mode="busctl",
        )
    assert not (tmp_path / "briefings").exists(), "a refused run writes nothing"


def test_cli_status_reports_held_and_listener_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    _held_ledger(tmp_path)
    assert main(["brief", "status"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["held"] == 1 and stats["held_undelivered"] == "held0001abcd"
    assert stats["events"] == 0 and stats["late_deliveries"] == 0


def test_cli_listen_once_without_bus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=/nonexistent/system_bus_socket")
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert main(["brief", "listen", "--once"]) == 0
    assert "bus unavailable" in capsys.readouterr().err


def test_cli_install_help_lists_the_new_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["brief", "install", "--help"])
    out = capsys.readouterr().out
    for flag in ("--signals", "--battery-low", "--listen", "--record-only", "--harden"):
        assert flag in out
