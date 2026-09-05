"""Deterministic synthesis over read-only inspection sources (ADR-0024).

The F6 playbook's digest is computed, never generated: pure-stdlib parsing of
the source commands' captured stdout with disclosed thresholds and per-line
source citations. Unparseable sources become explicit ``[source unreadable]``
lines — never guesses. No LLM anywhere in this path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

WARN_USED_PCT = 85.0
_LINE_LIMIT = 160

SOURCES: tuple[str, ...] = ("fs.disk_free (df -h)", "sys.memory (free -h)", "sys.uptime (uptime)")


def _hygiene(text: str, limit: int = _LINE_LIMIT) -> str:
    cleaned = "".join(ch for ch in text if ord(ch) >= 32 and ord(ch) != 127)
    collapsed = " ".join(cleaned.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _parse_size_gib(token: str) -> float | None:
    """`free -h` sizes like 15.6Gi / 487Mi / 1.9Ti → GiB (None if unknown)."""
    multipliers = {"Ki": 1 / 1024**2, "Mi": 1 / 1024, "Gi": 1.0, "Ti": 1024.0, "Pi": 1024.0**2}
    for suffix, factor in multipliers.items():
        if token.endswith(suffix):
            try:
                return float(token[: -len(suffix)]) * factor
            except ValueError:
                return None
    return None


def _disk_line(df_text: str) -> tuple[str, bool]:
    """Root-filesystem used% from `df -h`. Returns (line, readable)."""
    for row in df_text.splitlines():
        cells = row.split()
        if len(cells) >= 6 and cells[-1] == "/" and cells[-2].endswith("%"):
            try:
                used_pct = float(cells[-2][:-1])
            except ValueError:
                break
            mark = "WARN (threshold 85% used)" if used_pct >= WARN_USED_PCT else "ok"
            return (
                f"disk: root filesystem {used_pct:.0f}% used — {mark} [source: fs.disk_free]",
                True,
            )
    return "[source unreadable: fs.disk_free (df -h) — no root row parsed]", False


def _memory_line(free_text: str) -> tuple[str, bool]:
    """Used% from `free -h` (available vs total on the Mem: row)."""
    for row in free_text.splitlines():
        cells = row.split()
        if cells[:1] == ["Mem:"] and len(cells) >= 7:
            total = _parse_size_gib(cells[1])
            available = _parse_size_gib(cells[6])
            if total is not None and available is not None and total > 0:
                used_pct = 100.0 * (total - available) / total
                mark = "WARN (threshold 85% used)" if used_pct >= WARN_USED_PCT else "ok"
                return (
                    f"memory: {used_pct:.0f}% used "
                    f"({available:.1f} of {total:.1f} GiB available) — {mark} "
                    "[source: sys.memory]",
                    True,
                )
    return "[source unreadable: sys.memory (free -h) — no Mem row parsed]", False


def _load_line(uptime_text: str, cores: int) -> tuple[str, bool]:
    """Load-1 vs core count from `uptime`."""
    marker = "load average:"
    for row in uptime_text.splitlines():
        idx = row.find(marker)
        if idx >= 0:
            parts = [p.strip(" ,") for p in row[idx + len(marker) :].split() if p.strip(" ,")]
            if parts:
                try:
                    load1 = float(parts[0])
                except ValueError:
                    break
                mark = f"WARN (load1 > {cores} cores)" if load1 > cores else "ok"
                return (
                    f"load: {load1:.2f} (1m) on {cores} cores — {mark} [source: sys.uptime]",
                    True,
                )
    return "[source unreadable: sys.uptime (uptime) — no load average parsed]", False


@dataclass(frozen=True)
class DigestReport:
    lines: tuple[str, ...]
    ok: bool
    sources_readable: int
    warnings: int


def synthesize_digest(
    df_text: str, free_text: str, uptime_text: str, *, cores: int | None = None
) -> DigestReport:
    """Deterministic, cited digest over the three source outputs (D1/D3)."""
    if cores is None:
        cores = os.cpu_count() or 1
    disk_line, disk_ok = _disk_line(df_text)
    memory_line, memory_ok = _memory_line(free_text)
    load_line, load_ok = _load_line(uptime_text, cores)
    body: tuple[str, ...] = (
        f"digest: computed deterministically from {len(SOURCES)} read-only sources (no LLM)",
        _hygiene(disk_line),
        _hygiene(memory_line),
        _hygiene(load_line),
    )
    readable = sum(1 for flag in (disk_ok, memory_ok, load_ok) if flag)
    warnings = sum(1 for line in body[1:] if "WARN" in line)
    lines: tuple[str, ...] = (
        *body,
        f"verdict: {readable}/3 sources readable, {warnings} threshold warning(s)",
    )
    return DigestReport(lines=lines, ok=readable > 0, sources_readable=readable, warnings=warnings)
