"""Policy-state integrity (ADR-0013 M9c): baseline, drift verification, canaries.

Answers the "gradual security degradation" attack class documented in the
2026 agent-landscape research (docs/RESEARCH-agent-landscape-2026.md):
policy-relevant state is hashed into an explicit, machine-local baseline;
every later ``jarvis doctor`` run reports drift from it.

Scope (the code and data JARVIS *obeys*):
- packaged knowledge-base files (citations JARVIS answers from);
- the decision and gate code: playbooks registry, safety kernel, runner,
  orchestrator, and both ingress front-ends (CLI app, MCP server);
- the context store module and the cautious-mode marker.

Honest limitation (stated, not hidden): anyone with arbitrary write access
can recompute hashes. The baseline is a tripwire against *invisible, gradual*
modification — it forces changes into the light at review time — not a
cryptographic anchor. It is written only via explicit ``--write-baseline``
and must be re-written deliberately after a reviewed upgrade.

Canaries: every human/MCP suggestion rendering issues a random token recorded
in ``canaries.jsonl``. If a canary string ever appears off-machine, the owner
can look up exactly which suggestion batch leaked (``jarvis doctor
--canaries``).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

import jarvis
from jarvis.journal.sqlite import _utcnow, state_dir

BASELINE_SCHEMA = 1
CANARY_PREFIX = "jarvis-canary-"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pkg_root() -> Path:
    assert jarvis.__file__ is not None
    return Path(jarvis.__file__).parent


@dataclass(frozen=True)
class IntegrityScope:
    """Explicit files plus directories (all ``*.py``/``*.json`` within, flat)."""

    files: tuple[Path, ...]
    dirs: tuple[Path, ...]

    def entries(self) -> list[Path]:
        paths = set(self.files)
        for directory in self.dirs:
            for pattern in ("*.py", "*.json"):
                paths.update(p for p in directory.glob(pattern) if p.is_file())
        return sorted(paths)


def default_scope() -> IntegrityScope:
    root = pkg_root()
    kb_data = root / "knowledge" / "data"
    kb_files = tuple(sorted(kb_data.glob("*.json"))) if kb_data.is_dir() else ()
    return IntegrityScope(
        files=(
            *kb_files,
            root / "cli" / "app.py",
            root / "cli" / "mcp_server.py",
            root / "context" / "store.py",
            root / "core" / "orchestrator.py",
            root / "execution" / "runner.py",
            root / "planner" / "playbooks.py",
            state_dir() / "cautious",
        ),
        dirs=(root / "safety", state_dir() / "charters", state_dir() / "skills"),
    )


def default_baseline_path(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "integrity-baseline.json"


def default_canaries_path(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "canaries.jsonl"


def write_baseline(
    baseline_path: Path, *, env: dict[str, str] | None = None, scope: IntegrityScope | None = None
) -> dict[str, object]:
    """Hash the current scope into ``baseline_path`` (explicit operation only).

    Files that do not currently exist (e.g. the optional cautious marker) are
    skipped; if they appear later they are reported as ``added`` drift.
    """
    entries: dict[str, str] = {}
    for path in (scope or default_scope()).entries():
        if path.is_file():
            entries[str(path)] = sha256_file(path)
    doc: dict[str, object] = {
        "schema": BASELINE_SCHEMA,
        "jarvis_version": jarvis.__version__,
        "created_utc": _utcnow(),
        "entries": entries,
    }
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return doc


@dataclass(frozen=True)
class DriftRow:
    path: Path
    status: str  # "ok" | "changed" | "missing" | "added"
    detail: str


@dataclass(frozen=True)
class IntegrityReport:
    rows: tuple[DriftRow, ...]
    baseline_version: str
    created_utc: str

    @property
    def drift(self) -> tuple[DriftRow, ...]:
        return tuple(r for r in self.rows if r.status != "ok")

    @property
    def clean(self) -> bool:
        return not self.drift


def verify(
    baseline_path: Path, *, env: dict[str, str] | None = None, scope: IntegrityScope | None = None
) -> IntegrityReport:
    """Compare the current scope against the baseline; never raises on drift."""
    raw = json.loads(baseline_path.read_text())
    entries = raw["entries"]
    assert isinstance(entries, dict)
    expected: dict[Path, str] = {Path(k): str(v) for k, v in entries.items()}
    current = (scope or default_scope()).entries()

    rows: list[DriftRow] = []
    existing = {path for path in current if path.is_file()}
    for path in existing:
        if path not in expected:
            rows.append(DriftRow(path, "added", "not in baseline (new file in scope)"))
            continue
        actual = sha256_file(path)
        if actual != expected[path]:
            rows.append(DriftRow(path, "changed", "content hash differs from baseline"))
        else:
            rows.append(DriftRow(path, "ok", ""))
    for path in sorted(set(expected) - existing):
        rows.append(DriftRow(path, "missing", "in baseline but absent on disk"))
    baseline_version = str(raw.get("jarvis_version", "unknown"))
    created = str(raw.get("created_utc", "unknown"))
    return IntegrityReport(rows=tuple(rows), baseline_version=baseline_version, created_utc=created)


# -- suggestion canaries ------------------------------------------------------


def issue_canary(surface: str, *, env: dict[str, str] | None = None) -> str:
    """Issue a leak-tracing token for one suggestion render, recorded locally."""
    token = CANARY_PREFIX + secrets.token_hex(4)
    record = json.dumps(
        {"issued_utc": _utcnow(), "surface": surface, "canary": token},
        sort_keys=True,
    )
    path = default_canaries_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(record + "\n")
    return token


def read_canaries(env: dict[str, str] | None = None) -> list[dict[str, object]]:
    path = default_canaries_path(env)
    if not path.is_file():
        return []
    out: list[dict[str, object]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
        out.append(parsed)
    return out


__all__ = [
    "BASELINE_SCHEMA",
    "CANARY_PREFIX",
    "DriftRow",
    "IntegrityReport",
    "IntegrityScope",
    "default_baseline_path",
    "default_canaries_path",
    "default_scope",
    "issue_canary",
    "pkg_root",
    "read_canaries",
    "sha256_file",
    "verify",
    "write_baseline",
]
