"""Knowledge store: schema-validated, citation-required fact base (ADR-0009).

A fact cannot exist in the store without at least one source — the loader
refuses uncited claims, so "0 unverifiable facts" is a structural property,
not an aspiration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

_REQUIRED_SOURCE_FIELDS = ("kind", "ref")
_VERIFIER_KINDS = ("file_equals", "file_exists", "os_release_field", "binary_present", "command_ok")


class KnowledgeError(ValueError):
    """The KB on disk violates its schema (curation defect, fail loudly)."""


def _kb_files():
    """KB files ship inside the package (ADR-0011); sorted by name for determinism.

    No explicit Traversable import: it moved between stdlib modules across
    Python 3.10-3.14 and resources.files() is already correctly typed.
    """
    root = resources.files("jarvis.knowledge") / "data"
    files = [path for path in root.iterdir() if path.name.endswith(".json")]
    return sorted(files, key=lambda path: path.name)


@dataclass(frozen=True)
class Source:
    kind: str  # kernel-doc | man-page | docs | spec | proc | binary
    ref: str
    url: str = ""
    repo: str = ""


@dataclass(frozen=True)
class Fact:
    id: str
    topic: str
    claim: str
    patterns: tuple[str, ...]
    sources: tuple[Source, ...]
    verify: dict[str, object] | None


@dataclass(frozen=True)
class KnowledgeBase:
    version: int
    facts: tuple[Fact, ...]
    origin: str  # description of where it was loaded from


def _parse_source(raw: object, fact_id: str, index: int) -> Source:
    if not isinstance(raw, dict):
        raise KnowledgeError(f"{fact_id}: source #{index} is not an object")
    for field in _REQUIRED_SOURCE_FIELDS:
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise KnowledgeError(f"{fact_id}: source #{index} missing {field!r}")
    return Source(
        kind=str(raw["kind"]),
        ref=str(raw["ref"]),
        url=str(raw.get("url", "")),
        repo=str(raw.get("repo", "")),
    )


def _parse_fact(raw: object) -> Fact:
    if not isinstance(raw, dict):
        raise KnowledgeError("fact entry is not an object")
    fact_id = str(raw.get("id", "<missing>"))
    for field in ("id", "topic", "claim", "patterns", "sources"):
        if field not in raw:
            raise KnowledgeError(f"{fact_id}: missing required field {field!r}")
    if not raw["patterns"] or not raw["sources"]:
        raise KnowledgeError(
            f"{fact_id}: facts require at least one pattern and at least one "
            "source (citation-required store, ADR-0009)"
        )
    patterns = raw["patterns"]
    if not isinstance(patterns, list) or not all(isinstance(p, str) and bool(p) for p in patterns):
        raise KnowledgeError(f"{fact_id}: patterns must be a list of non-empty strings")
    sources = tuple(_parse_source(item, fact_id, i) for i, item in enumerate(raw["sources"]))
    verify = raw.get("verify")
    if verify is not None and (
        not isinstance(verify, dict) or verify.get("kind") not in _VERIFIER_KINDS
    ):
        raise KnowledgeError(f"{fact_id}: verify.kind must be one of {_VERIFIER_KINDS}")
    return Fact(
        id=str(raw["id"]),
        topic=str(raw["topic"]),
        claim=str(raw["claim"]),
        patterns=tuple(patterns),
        sources=sources,
        verify=dict(verify) if verify is not None else None,
    )


def load_kb(kb_dir: Path | None = None) -> KnowledgeBase:
    """Load and validate every knowledge/*.json file shipped with the package."""
    files = sorted(kb_dir.glob("*.json")) if kb_dir is not None else _kb_files()
    facts: list[Fact] = []
    version: int | None = None
    seen: set[str] = set()
    if not files:
        raise KnowledgeError("no knowledge files found in the package")
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "facts" not in data:
            raise KnowledgeError(f"{path.name}: not a knowledge document")
        file_version = data.get("kb_version")
        if not isinstance(file_version, int):
            raise KnowledgeError(f"{path.name}: missing integer kb_version")
        if version is None:
            version = file_version
        elif version != file_version:
            raise KnowledgeError(
                f"{path.name}: kb_version {file_version} != {version} (bump all files together)"
            )
        for raw in data["facts"]:
            fact = _parse_fact(raw)
            if fact.id in seen:
                raise KnowledgeError(f"{fact.id}: duplicate fact id across files")
            seen.add(fact.id)
            facts.append(fact)
    assert version is not None
    origin = f"{kb_dir} ({len(files)} files)" if kb_dir else f"package data ({len(files)} files)"
    return KnowledgeBase(version=version, facts=tuple(facts), origin=origin)


def match_fact(question: str, kb: KnowledgeBase) -> Fact | None:
    """Deterministic, anchored matching. Returns the most specific match or None."""
    q = question.lower().strip()
    best: tuple[int, Fact] | None = None
    for fact in kb.facts:
        for pattern in fact.patterns:
            if pattern.lower() in q:
                length = len(pattern)
                if best is None or length > best[0]:
                    best = (length, fact)
    return best[1] if best else None
