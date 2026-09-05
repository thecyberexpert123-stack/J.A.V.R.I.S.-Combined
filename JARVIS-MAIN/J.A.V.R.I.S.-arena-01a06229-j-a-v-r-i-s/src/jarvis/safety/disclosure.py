"""Blast-radius disclosure (M7): what a plan would touch, before it runs.

Advisory heuristics over planned steps — deterministic, no execution. The
authoritative guard remains the tier/approval/path policy; this layer exists
so a human can review a plan's *shape* at a glance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

_SYSTEM_PREFIXES = ("/etc/", "/usr/", "/var/", "/opt/", "/srv/", "/boot/")
_KERNEL_PREFIXES = ("/proc/", "/sys/", "/dev/")
_HOME_MARKERS = ("~/", "/home/")
_NETWORK_BINARIES = {
    "apt-get",
    "apt",
    "dnf",
    "pacman",
    "apk",
    "pip",
    "pip3",
    "curl",
    "wget",
}


def _path_class(token: str) -> str | None:
    if token.startswith(_SYSTEM_PREFIXES):
        return "system"
    if token.startswith(_KERNEL_PREFIXES):
        return "kernel"
    if token.startswith(_HOME_MARKERS) or token.startswith("/home/"):
        return "home"
    if token.startswith("/"):
        return "absolute"
    return None


def blast_radius(steps: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Summarize what a plan would touch. `steps` are step summaries (argv present)."""
    commands: set[str] = set()
    paths: dict[str, set[str]] = {
        "system": set(),
        "kernel": set(),
        "home": set(),
        "absolute": set(),
    }
    network = False
    root = False
    tier = 0
    for step in steps:
        root = root or bool(step.get("requires_root"))
        raw_tier = step.get("tier", 0)
        tier = max(tier, int(raw_tier) if isinstance(raw_tier, (int, float)) else 0)
        argv = step.get("argv")
        if not isinstance(argv, (list, tuple)) or not argv:
            continue
        argv_list = [str(a) for a in argv]
        commands.add(argv_list[0])
        if argv_list[0] in _NETWORK_BINARIES:
            network = True
        for token in argv_list[1:]:
            klass = _path_class(token)
            if klass is not None:
                paths[klass].add(token)
    return {
        "max_tier": tier,
        "requires_root": root,
        "network": network,
        "commands": sorted(commands),
        "paths": {k: sorted(v) for k, v in paths.items() if v},
    }
