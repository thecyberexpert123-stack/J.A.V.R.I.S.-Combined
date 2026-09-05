"""Verified skill packs (ADR-0013 M9b) — the anti-ClawHub ecosystem design.

Where other agent ecosystems ship instruction files that the model reads at
runtime (the landscape research found ~12% of ClawHub's catalog malicious),
JARVIS skills are **data that compile through the kernel**: a pack may only
re-expose an existing playbook under new phrasings with fixed params. The
referenced playbook determines the argv and the tier — packs cannot add
commands, raise tiers, or carry instructions the model interprets.

Format note: ADR-0013 sketched ``SKILL.yaml``; packs are strict **JSON**
(``*.skill.json``) because the project is stdlib-only (ADR-0005) and YAML
would add a dependency for no capability gain. Schema otherwise follows the
ADR: id, one-line match regex, one playbook reference, fixed params, mandatory
eval cases, provenance.

Trust model: a pack installs only through explicit consent after its eval
cases pass as real dry-runs; the installed bytes are pinned by a receipt
(sha256) and live inside the M9c integrity scope, so any drift trips
``jarvis doctor``. A pack whose bytes no longer match its receipt is skipped
by the matcher (fail-closed) until re-installed.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from jarvis.core.fingerprint import build_profile
from jarvis.journal.sqlite import _utcnow, state_dir
from jarvis.planner.models import PlannedStep
from jarvis.planner.playbooks import PLAYBOOKS, Params, Playbook

SKILL_SCHEMA = 1
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_MATCH_RE = re.compile(r"^[^\n]{1,200}$")  # single line; backslashes fine (\s, \d, ...)
_KEY_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SkillError(ValueError):
    """A skill pack violates its schema or invariants."""


def skills_dir(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "skills"


def pack_path(skill_id: str, env: dict[str, str] | None = None) -> Path:
    return skills_dir(env) / f"{skill_id}.skill.json"


def receipt_path(skill_id: str, env: dict[str, str] | None = None) -> Path:
    return skills_dir(env) / f"{skill_id}.receipt.json"


def playbook_ids() -> tuple[str, ...]:
    return tuple(playbook.id for playbook in PLAYBOOKS)


def validate_skill(doc: object) -> list[str]:
    """Return all schema/invariant violations ([] means valid)."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["pack must be a JSON object"]
    if doc.get("schema") != SKILL_SCHEMA:
        errors.append(f"schema must be {SKILL_SCHEMA}")
    sid = doc.get("id")
    if not isinstance(sid, str) or not _ID_RE.fullmatch(sid):
        errors.append("id must match [a-z][a-z0-9-]{1,30}")
    description = doc.get("description")
    if not isinstance(description, str) or not 1 <= len(description) <= 200:
        errors.append("description must be 1..200 chars")
    pattern = doc.get("match")
    if not isinstance(pattern, str) or not _MATCH_RE.fullmatch(pattern):
        errors.append("match must be a single-line regex of at most 200 chars")
    else:
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"match does not compile: {exc}")
    playbook = doc.get("playbook")
    if not isinstance(playbook, str) or playbook not in playbook_ids():
        errors.append(f"playbook must be one of: {', '.join(playbook_ids())}")
    params = doc.get("params", {})
    if not isinstance(params, dict) or len(params) > 16:
        errors.append("params must be an object with at most 16 keys")
    else:
        for key, value in params.items():
            if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
                errors.append(f"param key {key!r} must match [a-z0-9_-]{{1,32}}")
            if not isinstance(value, (str, int, float, bool)):
                errors.append(f"param {key!r} must be a scalar")
    evals = doc.get("evals")
    if (
        not isinstance(evals, list)
        or not 1 <= len(evals) <= 10
        or any(not isinstance(e, dict) for e in evals)
    ):
        errors.append("evals must be a list of 1..10 objects")
    else:
        for case in evals:
            request = case.get("request")
            if not isinstance(request, str) or not request.strip():
                errors.append("each eval needs a non-empty request")
            elif isinstance(pattern, str):
                try:
                    if re.fullmatch(pattern, request.strip()) is None:
                        errors.append(f"eval request {request!r} does not match the pack's regex")
                except re.error:
                    pass  # already reported by the match check
    provenance = doc.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
    else:
        source = provenance.get("source")
        if not isinstance(source, str) or not 1 <= len(source) <= 300:
            errors.append("provenance.source must be 1..300 chars")
        digest = provenance.get("sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            errors.append("provenance.sha256 must be a lowercase hex sha256 of the pack bytes")
    return errors


def _params_of(doc: dict[str, object]) -> Params:
    raw = doc.get("params", {})
    assert isinstance(raw, dict)
    return {str(k): v for k, v in raw.items()}


def _pack_errors(path: Path) -> tuple[dict[str, object] | None, list[str]]:
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"unreadable pack: {exc}"]
    errors = validate_skill(doc)
    return (doc if not errors else None), errors


def _receipt_ok(sid: str, pack_bytes: bytes, env: dict[str, str] | None) -> bool:
    path = receipt_path(sid, env)
    if not path.is_file():
        return False
    try:
        receipt = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(receipt, dict):
        return False
    return str(receipt.get("sha256", "")) == hashlib.sha256(pack_bytes).hexdigest()


def installed_skills(
    env: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """Every installed pack with its load state: ok / invalid / drift."""
    out: list[dict[str, object]] = []
    directory = skills_dir(env)
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.skill.json")):
        doc, errors = _pack_errors(path)
        raw = path.read_bytes()
        sid = str(doc.get("id")) if isinstance(doc, dict) and doc.get("id") else path.stem
        status = "ok"
        if errors:
            status = "invalid"
        elif not _receipt_ok(sid, raw, env):
            status = "drift"  # bytes changed (or receipt missing) after install
        out.append({"id": sid, "path": path, "status": status, "errors": errors})
    return out


def match_skill(text: str, env: dict[str, str] | None = None) -> tuple[Playbook, Params] | None:
    """Resolve text through installed, receipt-verified packs.

    Deterministic: packs tried in id order, first fullmatch wins. Invalid or
    drifted packs are skipped (fail-closed). Returns (playbook, params) with
    the referenced playbook's own tier — or None, exactly like match_intent.
    """
    collapsed = re.sub(r"\s+", " ", text.strip())
    for entry in installed_skills(env):
        if entry["status"] != "ok":
            continue
        doc = json.loads(Path(str(entry["path"])).read_text())
        assert isinstance(doc, dict)
        pattern = doc.get("match")
        assert isinstance(pattern, str)
        if re.fullmatch(pattern, collapsed) is None:
            continue
        playbook: Playbook | None = next(
            (pb for pb in PLAYBOOKS if pb.id == doc.get("playbook")), None
        )
        if playbook is None:
            continue  # registry changed under the pack: fail closed
        params = _params_of(doc)
        params["skill"] = str(doc.get("id"))
        return playbook, params
    return None


def _dry_run_evals(doc: dict[str, object]) -> list[str]:
    """Run each eval case as a real planning dry-run (pure: no execution)."""
    errors: list[str] = []
    playbook = next((pb for pb in PLAYBOOKS if pb.id == doc.get("playbook")), None)
    assert playbook is not None  # validation guarantees this
    profile = build_profile()
    evals = doc.get("evals")
    assert isinstance(evals, list)
    pattern = str(doc.get("match", ""))
    params = _params_of(doc)
    for case in evals:
        assert isinstance(case, dict)
        request = str(case.get("request", "")).strip()
        if not request or re.fullmatch(pattern, request) is None:
            errors.append(f"eval {request!r} does not match the pack regex")
            continue
        try:
            steps: list[PlannedStep] = playbook.build(params, profile)
        except Exception as exc:
            errors.append(f"eval {request!r} failed to build a plan: {exc}")
            continue
        if not steps:
            errors.append(f"eval {request!r} produced an empty plan")
    return errors


def install_skill(
    source_path: Path, *, source: str = "", env: dict[str, str] | None = None
) -> dict[str, object]:
    """Validate, eval-dry-run, pin, and install a pack. Raises SkillError."""
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        raise SkillError(f"cannot read pack: {exc}") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SkillError(f"pack is not valid JSON: {exc}") from exc
    errors = validate_skill(doc)
    if errors:
        raise SkillError("; ".join(errors))
    assert isinstance(doc, dict)
    errors = _dry_run_evals(doc)
    if errors:
        raise SkillError("; ".join(errors))
    sid = str(doc["id"])
    provenance = doc.get("provenance")
    assert isinstance(provenance, dict)
    if not source:
        source = str(provenance.get("source", "local"))
    directory = skills_dir(env)
    directory.mkdir(parents=True, exist_ok=True)
    pack_bytes = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(pack_bytes).hexdigest()
    pack_path(sid, env).write_bytes(pack_bytes)
    receipt_path(sid, env).write_text(
        json.dumps(
            {
                "schema": SKILL_SCHEMA,
                "id": sid,
                "sha256": digest,
                "installed_utc": _utcnow(),
                "source": source,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return {"id": sid, "sha256": digest, "path": str(pack_path(sid, env))}


def remove_skill(skill_id: str, env: dict[str, str] | None = None) -> bool:
    removed = False
    for path in (pack_path(skill_id, env), receipt_path(skill_id, env)):
        if path.is_file():
            path.unlink()
            removed = True
    return removed
