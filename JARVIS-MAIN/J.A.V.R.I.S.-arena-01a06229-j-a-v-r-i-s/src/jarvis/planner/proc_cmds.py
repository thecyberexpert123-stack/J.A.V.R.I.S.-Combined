"""Process and service mutations (ADR-0016 D3): the T2 catalog family.

Every entry is system-level by the tier definition: explicit approval, static
argv, validated unit names / PIDs, systemd required for unit operations (the
same honesty as svc.start). No process matching by pattern — `pkill` is exact
name only (`-x`), because pattern kills are how "stop that server" becomes
"kill the session".
"""

from __future__ import annotations

import re

from jarvis.planner.catalog_common import Params, clean_arg, verify_ran
from jarvis.planner.models import PlannedStep, Playbook, UndoPlan, UndoStatus
from jarvis.safety.tiers import Tier, validate_unit_name
from jarvis.system.models import MachineProfile, UnsupportedError

_SYSTEMCTL_FLAGS: dict[str, tuple[str, ...]] = {
    "svc.stop": ("stop",),
    "svc.restart": ("restart",),
    "svc.disable": ("disable",),
}

_UNDO_REASONS: dict[str, str] = {
    "svc.stop": "the service can be started again (jarvis do start <unit>)",
    "svc.restart": "a restart is idempotent; run it again if needed",
    "svc.disable": "the unit can be enabled again (jarvis do enable <unit>)",
}


def _require_systemd(profile: MachineProfile) -> None:
    if profile.init_system != "systemd":
        raise UnsupportedError(
            "unit operations require systemd; this machine runs "
            f"{profile.init_system or 'an unknown init system'}"
        )


def _make_svc_playbook(kind: str, verb_text: str) -> Playbook:
    pattern = (
        rf"^(?:{verb_text})(?: the | )?(?:service |unit |daemon )?"
        r"(?P<unit>[A-Za-z0-9][\w:@.-]*)(?: service| unit| daemon)?$"
    )

    def match(text: str) -> Params | None:
        m = re.match(pattern, text)
        if m is None:
            return None
        try:
            validate_unit_name(m.group("unit"))  # match-time validation:
            # invalid units fall through instead of hijacking + refusing
        except Exception:
            return None
        return {"unit": m.group("unit")}

    def build(params: Params, profile: MachineProfile) -> list[PlannedStep]:
        _require_systemd(profile)
        unit = validate_unit_name(str(params["unit"]))
        return [
            PlannedStep(
                description=f"{kind.split('.')[1]} unit {unit}",
                argv=("systemctl",) + _SYSTEMCTL_FLAGS[kind] + (unit,),
                tier=Tier.T2,
                requires_root=True,
                timeout_s=120.0,
            )
        ]

    def undo(params: Params, profile: MachineProfile) -> UndoPlan:
        return UndoPlan(status=UndoStatus.NONE_NEEDED, reason=_UNDO_REASONS[kind])

    description = {
        "svc.stop": "stop a systemd unit (T2, approval-gated)",
        "svc.restart": "restart a systemd unit (T2, approval-gated)",
        "svc.disable": "disable a systemd unit from starting at boot (T2, approval-gated)",
    }[kind]
    return Playbook(
        id=kind,
        description=description,
        tier=Tier.T2,
        match=match,
        build=build,
        verify=verify_ran,
        undo=undo,
    )


def _match_kill(text: str) -> Params | None:
    m = re.match(r"^(?:kill|terminate)(?: process| pid)? (?P<pid>\d{1,7})$", text)
    if m is None:
        return None
    return {"pid": m.group("pid")}


def _build_kill(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    pid = int(str(params["pid"]))
    if pid < 1:
        raise ValueError("pid must be positive")
    return [
        PlannedStep(
            description=f"send SIGTERM to pid {pid}",
            argv=("kill", str(pid)),
            tier=Tier.T2,
            requires_root=False,
            timeout_s=30.0,
        )
    ]


def _match_pkill(text: str) -> Params | None:
    m = re.match(
        r"^(?:kill|stop|terminate) (?:all |the |)(?:processes |process |)"
        r"named (?P<name>[A-Za-z0-9][A-Za-z0-9._+-]*)$",
        text,
    )
    if m is None:
        return None
    return {"name": m.group("name")}


def _build_pkill(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    name = clean_arg(str(params["name"]), "name")
    return [
        PlannedStep(
            description=f"send SIGTERM to processes named exactly {name!r} (-x, no patterns)",
            argv=("pkill", "-x", name),
            tier=Tier.T2,
            requires_root=False,
            timeout_s=30.0,
        )
    ]


def _no_undo_needed(params: Params, profile: MachineProfile) -> UndoPlan:
    return UndoPlan(
        status=UndoStatus.NONE_NEEDED,
        reason="processes are not state this kernel owns; restart the workload instead",
    )


PROC_PLAYBOOKS: tuple[Playbook, ...] = (
    _make_svc_playbook("svc.stop", "stop"),
    _make_svc_playbook("svc.restart", "restart"),
    _make_svc_playbook("svc.disable", "disable"),
    Playbook(
        id="proc.kill",
        description="send SIGTERM to a numeric process id (T2, approval-gated)",
        tier=Tier.T2,
        match=_match_kill,
        build=_build_kill,
        verify=verify_ran,
        undo=_no_undo_needed,
    ),
    Playbook(
        id="proc.kill_name",
        description="stop processes by EXACT name only — no patterns (T2, approval-gated)",
        tier=Tier.T2,
        match=_match_pkill,
        build=_build_pkill,
        verify=verify_ran,
        undo=_no_undo_needed,
    ),
)
