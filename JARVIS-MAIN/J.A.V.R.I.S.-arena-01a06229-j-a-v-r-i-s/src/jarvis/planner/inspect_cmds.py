"""Read-only inspection commands (ADR-0016 D1-D3): the T0 catalog family.

Every entry: a pinned binary with a fully fixed flag prefix, at most one
validated argument slot, natural-language matchers, exit-code verification,
and "read-only; nothing to reverse" undo. `fs.find` and `fs.search` are
hand-written (two argument slots); the rest come from the spec table below —
the table is the audit surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.planner.catalog_common import (
    Params,
    clean_arg,
    no_undo,
    path_arg,
    verify_ran,
)
from jarvis.planner.models import PlannedStep, Playbook, UndoPlan, UndoStatus
from jarvis.safety.tiers import SafetyRefusal, Tier
from jarvis.system.models import MachineProfile

# --------------------------------------------------------------------------
# spec table (the audit surface — one row per command)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadOnlySpec:
    """One read-only command: binary+fixed flags, arg slot, NL patterns."""

    id: str
    description: str
    argv: tuple[str, ...]  # binary + fixed flags, never user data
    patterns_bare: tuple[str, ...]  # regexes without an argument
    patterns_arg: tuple[str, ...]  # regexes with (?P<arg>...)
    arg_kind: str  # path | name | host
    default_arg: str = ""  # used when matched without an argument
    timeout_s: float = 30.0


_ARG = r"(?P<arg>[^\n]+)"

SPECS: tuple[ReadOnlySpec, ...] = (
    # ---- files (path argument) -------------------------------------------
    ReadOnlySpec(
        id="fs.list",
        description="list directory contents (long form)",
        argv=("ls", "-la", "--color=never"),
        patterns_bare=(
            r"^(?:show |)(?:what(?:'|i)s |)?(?:in |)(?:the |)?(?:current |)"
            r"(?:folder|directory|dir)$",
            r"^list (?:the |)?(?:files|contents|directory)(?: here)?$",
            r"^(?:ls|dir)$",
        ),
        patterns_arg=(
            rf"^list (?:the |)?(?:files|directory|folder)(?: in| under| of)? {_ARG}$",
            rf"^(?:ls|list) {_ARG}$",
            rf"^what(?:'| i)s (?:in|inside) (?!(?:the )?file )(?:the |)?{_ARG}$",
        ),
        arg_kind="path",
        default_arg=".",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="fs.read",
        description="print a file's contents",
        argv=("cat",),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:read|cat)(?: the| this)?(?: file)? {_ARG}$",
            rf"^(?:show|view|display|print)(?: the)? contents of {_ARG}$",
            rf"^what(?:'| i)s in (?:the |)?file {_ARG}$",
        ),
        arg_kind="path",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="fs.head",
        description="show the first 20 lines of a file",
        argv=("head", "-n", "20"),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:head|first lines of|beginning of)(?: the| file)? {_ARG}$",
            rf"^show (?:the |)?first \d+ lines of {_ARG}$",
        ),
        arg_kind="path",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="fs.tail",
        description="show the last 20 lines of a file",
        argv=("tail", "-n", "20"),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:tail|last lines of|end of)(?: the| file)? {_ARG}$",
            rf"^show (?:the |)?last \d+ lines of {_ARG}$",
        ),
        arg_kind="path",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="fs.count",
        description="count lines, words and bytes in a file",
        argv=("wc",),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:count|wc)(?: the | )(?:lines|words|bytes)?(?: in| of)?(?: file)? {_ARG}$",
            rf"^how many lines (?:are )?in {_ARG}$",
        ),
        arg_kind="path",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="fs.stat",
        description="show file/directory metadata (size, times, permissions)",
        argv=("stat",),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:stat|metadata of|file info(?: for| of)?) {_ARG}$",
            rf"^(?:show |)(?:the |)?(?:size|permissions|timestamps) of {_ARG}$",
            rf"^when was {_ARG} (?:last )?(?:modified|changed)$",
        ),
        arg_kind="path",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="fs.file_type",
        description="identify a file's type",
        argv=("file",),
        patterns_bare=(),
        patterns_arg=(rf"^(?:what type of file is|file type of|type of) {_ARG}$",),
        arg_kind="path",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="fs.which",
        description="locate a program on PATH",
        argv=("which",),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:which|where is|locate|find the)(?: program| binary| command)? {_ARG}$",
            rf"^is there a {_ARG} (?:binary|command|program)(?: on my path| installed)?$",
        ),
        arg_kind="name",
        timeout_s=15.0,
    ),
    ReadOnlySpec(
        id="fs.disk_usage",
        description="show how much space a directory/file uses (human readable)",
        argv=("du", "-sh"),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:disk usage of|du|size of|how big is)(?: the | )"
            rf"(?:folder |directory |dir )?{_ARG}$",
            rf"^how much space (?:does|is) {_ARG} (?:use|take|using)$",
        ),
        arg_kind="path",
        default_arg=".",
        timeout_s=120.0,
    ),
    ReadOnlySpec(
        id="sys.checksum",
        description="compute a file's MD5 checksum",
        argv=("md5sum",),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:md5(?:sum)? of|checksum of|hash of) {_ARG}$",
            rf"^(?:compute|calculate) the (?:md5|checksum) of {_ARG}$",
        ),
        arg_kind="path",
        timeout_s=120.0,
    ),
    # ---- bare system probes ----------------------------------------------
    ReadOnlySpec(
        id="fs.disk_free",
        description="show free disk space per filesystem (human readable)",
        argv=("df", "-h"),
        patterns_bare=(
            r"^(?:show |display |)?(?:disk (?:free|space|usage summary)|df|"
            r"how much disk (?:space )?(?:is )?free|filesystem usage|storage space)$",
        ),
        patterns_arg=(rf"^disk (?:free|space)(?: on| for)? {_ARG}$",),
        arg_kind="path",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.memory",
        description="show memory and swap usage (human readable)",
        argv=("free", "-h"),
        patterns_bare=(
            r"^(?:show |display |)(?:memory(?: usage| info)?|free memory|ram(?: usage)?|"
            r"how much (?:memory|ram)(?: is| do i have)?(?: free| used)?)$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=15.0,
    ),
    ReadOnlySpec(
        id="sys.processes",
        description="list running processes (all users, full format)",
        argv=("ps", "aux"),
        patterns_bare=(
            r"^(?:show |display |list |)(?:processes|running processes|process list|"
            r"ps(?: aux)?|what(?:'| i)s running)$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.uptime",
        description="show uptime and load averages",
        argv=("uptime",),
        patterns_bare=(r"^(?:uptime|how long .* (?:up|running)|load average|system load)$",),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=15.0,
    ),
    ReadOnlySpec(
        id="sys.date",
        description="show the current date and time",
        argv=("date",),
        patterns_bare=(
            r"^(?:date(?: and time)?|time(?: now)?|what(?:'| i)s the (?:date|time)|"
            r"current (?:date|time))$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=15.0,
    ),
    ReadOnlySpec(
        id="sys.hostname",
        description="show the machine's hostname",
        argv=("hostname",),
        patterns_bare=(
            r"^(?:hostname|host name|what(?:'| i)s (?:this|the) (?:machine|host)(?: name)?)$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=15.0,
    ),
    ReadOnlySpec(
        id="sys.cpus",
        description="show CPU information",
        argv=("lscpu",),
        patterns_bare=(
            r"^(?:show |display |)(?:cpu(?: info| information| details)?|"
            r"processor info|cores)$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.pci",
        description="list PCI devices",
        argv=("lspci",),
        patterns_bare=(r"^(?:pci(?: devices)?|lspci|pci hardware)$",),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.usb",
        description="list USB devices",
        argv=("lsusb",),
        patterns_bare=(r"^(?:usb(?: devices)?|lsusb|usb hardware)$",),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.blocks",
        description="list block devices (disks and partitions)",
        argv=("lsblk",),
        patterns_bare=(
            r"^(?:blocks?|block devices|disks(?: and partitions)?|partitions|lsblk|"
            r"list (?:my |the )?disks)$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.sockets",
        description="list listening sockets (tcp/udp, numeric)",
        argv=("ss", "-tulwn"),
        patterns_bare=(
            r"^(?:sockets?|open ports?|listening ports?|listening sockets|netstat|ss|"
            r"what ports .* (?:open|listening))$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.network",
        description="show network interfaces and addresses",
        argv=("ip", "-brief", "addr"),
        patterns_bare=(
            r"^(?:show |display |)(?:my |)(?:network|interfaces|network interfaces|"
            r"ip (?:addr|addresses?|a)|my ip)$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.routes",
        description="show the routing table",
        argv=("ip", "route"),
        patterns_bare=(r"^(?:routes?|routing table|ip route|default gateway)$",),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.journal",
        description="show the last 50 systemd journal entries",
        argv=("journalctl", "--no-pager", "-n", "50"),
        patterns_bare=(
            r"^(?:journal(?:ctl)?(?: logs?)?|system logs?|recent logs?|"
            r"show (?:the )?(?:logs|journal))$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=60.0,
    ),
    ReadOnlySpec(
        id="sys.kernel_log",
        description="show the kernel ring buffer (may require root on some systems)",
        argv=("dmesg",),
        patterns_bare=(r"^(?:dmesg|kernel (?:log|messages|ring buffer))$",),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="sys.users",
        description="show logged-in users",
        argv=("who",),
        patterns_bare=(r"^(?:who(?: is (?:logged in|online))?|logged(?:-| )in users?|users)$",),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=15.0,
    ),
    ReadOnlySpec(
        id="sys.login_history",
        description="show the last 20 logins",
        argv=("last", "-n", "20"),
        patterns_bare=(r"^(?:last logins?|login history|who logged in (?:before|recently))$",),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=15.0,
    ),
    ReadOnlySpec(
        id="sys.env",
        description="print the environment variables",
        argv=("env",),
        patterns_bare=(r"^(?:env(?:ironment(?: variables)?)?|printenv|show environment)$",),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=15.0,
    ),
    ReadOnlySpec(
        id="sys.identity",
        description="show the current user and groups (id)",
        argv=("id",),
        patterns_bare=(
            r"^(?:id|who am i(?:m)?|my (?:user|uid|groups)|current user|"
            r"what user am i)$",
        ),
        patterns_arg=(),
        arg_kind="name",
        timeout_s=15.0,
    ),
    # ---- network probes (host argument) -----------------------------------
    ReadOnlySpec(
        id="net.ping",
        description="ping a host four times (IPv4, bounded wait)",
        argv=("ping", "-c", "4", "-W", "4"),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:ping|can you ping|check reachability of)(?: the host)? {_ARG}$",
            rf"^is {_ARG} (?:up|alive|reachable)$",
        ),
        arg_kind="host",
        timeout_s=30.0,
    ),
    ReadOnlySpec(
        id="net.dns",
        description="resolve a host via DNS (short answer)",
        argv=("dig", "+short"),
        patterns_bare=(),
        patterns_arg=(
            rf"^(?:dns|resolve|dig)(?: lookup for| record for)? {_ARG}$",
            rf"^what(?:'| i)s the ip (?:of|for) {_ARG}$",
        ),
        arg_kind="host",
        timeout_s=20.0,
    ),
)


def _match_spec(spec: ReadOnlySpec, text: str) -> Params | None:
    for pattern in spec.patterns_bare:
        if re.match(pattern, text):
            return {"arg": spec.default_arg}
    for pattern in spec.patterns_arg:
        match = re.match(pattern, text)
        if match:
            candidate = match.group("arg").strip()
            try:
                clean_arg(candidate, spec.arg_kind)  # validate at MATCH time so
                # invalid arguments fall through to later families instead of
                # hijacking the request and refusing at build time.
            except SafetyRefusal:
                return None
            return {"arg": candidate}
    return None


def _build_spec(spec: ReadOnlySpec, params: Params) -> list[PlannedStep]:
    arg = str(params.get("arg", spec.default_arg))
    # A bare-pattern match carries the spec's own default (trusted); anything
    # the user typed goes through the validator (refusal, never sanitization).
    value = arg if arg == spec.default_arg else clean_arg(arg, spec.arg_kind)
    # bare commands take no argument slot at all (empty default = none)
    argv = (*spec.argv, value) if value else spec.argv
    return [
        PlannedStep(
            description=spec.description,
            argv=argv,
            tier=Tier.T0,
            requires_root=False,
            timeout_s=spec.timeout_s,
        )
    ]


def make_readonly(spec: ReadOnlySpec) -> Playbook:
    """Materialize one spec into a full Playbook."""

    def match(text: str) -> Params | None:
        return _match_spec(spec, text)

    def build(params: Params, profile: MachineProfile) -> list[PlannedStep]:
        return _build_spec(spec, params)

    def undo(params: Params, profile: MachineProfile) -> UndoPlan:
        return no_undo("read-only; nothing to reverse")

    return Playbook(
        id=spec.id,
        description=spec.description,
        tier=Tier.T0,
        match=match,
        build=build,
        verify=verify_ran,
        undo=undo,
    )


# --------------------------------------------------------------------------
# hand-written two-slot readers: fs.find, fs.search
# --------------------------------------------------------------------------


def _match_find(text: str) -> Params | None:
    m = re.match(
        r"^(?:find|locate) (?:files|a file|file|anything|)(?: named| called| matching|"
        r" like)? (?P<glob>\S+)(?: in| under| from| starting (?:at|from)) (?P<path>.+)$",
        text,
    )
    if not m:
        m = re.match(
            r"^(?:find|locate) (?:in |under |from )?(?P<path>.+?) (?:for |files named |)"
            r"(?P<glob>\S+)$",
            text,
        )
    if not m:
        return None
    return {"glob": m.group("glob"), "path": m.group("path")}


def _build_find(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    pattern = clean_arg(str(params["glob"]), "glob")
    directory = path_arg(str(params["path"]))
    if not directory.is_dir():
        raise SafetyRefusal(f"not a directory: {directory}")
    return [
        PlannedStep(
            description=f"find files matching {pattern!r} under {directory}",
            argv=("find", str(directory), "-maxdepth", "5", "-name", pattern),
            tier=Tier.T0,
            requires_root=False,
            timeout_s=120.0,
        )
    ]


def _match_search(text: str) -> Params | None:
    m = re.match(
        r"^(?:search|grep|look) (?:for )?(?P<pattern>.+?) (?:in|within|inside|under) "
        r"(?P<path>.+)$",
        text,
    )
    if not m:
        return None
    try:
        # match-time validation: a rejected pattern leaves the playbook
        # unmatchable so the request falls through to honest refusal
        clean_arg(m.group("pattern").strip("'\""), "search-pattern")
        path_arg(m.group("path"))
    except SafetyRefusal:
        return None
    return {"pattern": m.group("pattern"), "path": m.group("path")}


def _build_search(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    pattern = clean_arg(str(params["pattern"]).strip("'\""), "search-pattern")
    target = path_arg(str(params["path"]))
    return [
        PlannedStep(
            description=f"search for {pattern!r} in {target}",
            argv=("grep", "-n", "-F", pattern, str(target)),
            tier=Tier.T0,
            requires_root=False,
            timeout_s=120.0,
        )
    ]


INSPECT_PLAYBOOKS: tuple[Playbook, ...] = (
    *(make_readonly(spec) for spec in SPECS),
    *(
        Playbook(
            id="fs.find",
            description="find files by name (max depth 5, read-only)",
            tier=Tier.T0,
            match=_match_find,
            build=_build_find,
            verify=verify_ran,
            undo=lambda params, profile: UndoPlan(
                status=UndoStatus.NONE_NEEDED, reason="read-only; nothing to reverse"
            ),
        ),
        Playbook(
            id="fs.search",
            description="search for a fixed string in a file or directory",
            tier=Tier.T0,
            match=_match_search,
            build=_build_search,
            verify=verify_ran,
            undo=lambda params, profile: UndoPlan(
                status=UndoStatus.NONE_NEEDED, reason="read-only; nothing to reverse"
            ),
        ),
    ),
)
