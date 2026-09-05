"""Supervised growth loop (ADR-0012 M8d): JARVIS drafts, the owner decides.

Growth proposals are *inert data* in ``state_dir()/proposals``:
- knowledge facts, validated by the real citation-required KB store
  (ADR-0009: an uncited fact cannot even be drafted);
- skill packs, validated by the M9b machinery (evals dry-run, scalar params,
  real playbook references only).

Nothing here touches the kernel, policy, or the shipped KB/skill stores —
the kernel and policy are permanently outside the write scope (anti-Ultron
clause). Promotion paths are owner actions: a fact proposal becomes KB only
through an owner-reviewed PR to the repository (JARVIS exports the artifact
and the exact commands; it never opens or merges PRs itself — merge authority
is the owner's per the governance charter), and a skill proposal installs
only via the consented `jarvis skill install`.

Documented interpretation of the ADR's "drafts ... as PRs": drafting,
validation, and export are automated; PR creation and merge remain owner
actions (no remote/credential actions from the product).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from jarvis.journal.sqlite import _utcnow, state_dir
from jarvis.knowledge.store import load_kb
from jarvis.planner.skills import _dry_run_evals, validate_skill

_PROPOSAL_SCHEMA = 1


class GrowError(ValueError):
    """A growth proposal is invalid or unknown."""


def proposals_dir(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "proposals"


def _meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def draft_fact(
    fact: dict[str, object], *, rationale: str = "", env: dict[str, str] | None = None
) -> dict[str, object]:
    """Validate a fact through the real KB store; park it as a proposal."""
    if not isinstance(fact, dict):
        raise GrowError("fact must be a JSON object")
    fact_id = str(fact.get("id", "<missing>"))
    if not fact_id.replace("-", "").replace(".", "").isalnum() or not fact_id:
        raise GrowError(f"fact id {fact_id!r} must be alphanumeric ([a-z0-9.-])")
    directory = proposals_dir(env) / "facts"
    directory.mkdir(parents=True, exist_ok=True)
    document = {"kb_version": 1, "origin": "growth proposal (ADR-0012 M8d)", "facts": [fact]}
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "candidate.json"
        candidate.write_text(json.dumps(document, indent=2) + "\n")
        try:
            load_kb(candidate.parent)
        except Exception as exc:
            raise GrowError(f"KB store refuses this fact (ADR-0009): {exc}") from exc
    target = directory / f"{fact_id}.json"
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    _meta_path(target).write_text(
        json.dumps(
            {
                "schema": _PROPOSAL_SCHEMA,
                "kind": "fact",
                "id": fact_id,
                "proposed_utc": _utcnow(),
                "rationale": rationale[:300],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return {"kind": "fact", "id": fact_id, "path": str(target)}


def draft_skill(
    pack_file: Path, *, rationale: str = "", env: dict[str, str] | None = None
) -> dict[str, object]:
    """Validate a skill pack through the M9b machinery; park it as a proposal."""
    try:
        raw = pack_file.read_bytes()
    except OSError as exc:
        raise GrowError(f"cannot read pack: {exc}") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GrowError(f"pack is not valid JSON: {exc}") from exc
    errors = validate_skill(doc)
    if errors:
        raise GrowError("; ".join(errors))
    assert isinstance(doc, dict)
    eval_errors = _dry_run_evals(doc)
    if eval_errors:
        raise GrowError("; ".join(eval_errors))
    sid = str(doc["id"])
    directory = proposals_dir(env) / "skills"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{sid}.skill.json"
    target.write_bytes((json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())
    _meta_path(target).write_text(
        json.dumps(
            {
                "schema": _PROPOSAL_SCHEMA,
                "kind": "skill",
                "id": sid,
                "proposed_utc": _utcnow(),
                "rationale": rationale[:300],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return {"kind": "skill", "id": sid, "path": str(target)}


def list_proposals(env: dict[str, str] | None = None) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for kind in ("facts", "skills"):
        directory = proposals_dir(env) / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            if path.name.endswith(".meta.json"):
                continue
            meta = {}
            if _meta_path(path).is_file():
                try:
                    loaded = json.loads(_meta_path(path).read_text())
                    meta = loaded if isinstance(loaded, dict) else {}
                except json.JSONDecodeError:
                    meta = {}
            out.append(
                {
                    "kind": kind.rstrip("s"),
                    "id": str(meta.get("id", path.stem)),
                    "proposed_utc": meta.get("proposed_utc", "?"),
                    "rationale": meta.get("rationale", ""),
                    "path": str(path),
                }
            )
    return out


def show_proposal(proposal_id: str, env: dict[str, str] | None = None) -> str:
    for entry in list_proposals(env):
        if entry["id"] == proposal_id:
            assert isinstance(entry["path"], str)
            return Path(entry["path"]).read_text()
    raise GrowError(f"no proposal {proposal_id!r} (list with: jarvis grow list)")


def prune_proposal(proposal_id: str, env: dict[str, str] | None = None) -> bool:
    for entry in list_proposals(env):
        if entry["id"] == proposal_id:
            assert isinstance(entry["path"], str)
            path = Path(entry["path"])
            path.unlink(missing_ok=True)
            _meta_path(path).unlink(missing_ok=True)
            return True
    return False


def export_proposal(
    proposal_id: str, out_dir: Path, env: dict[str, str] | None = None
) -> dict[str, object]:
    """Copy the ready-to-PR artifact; the owner runs the printed commands."""
    for entry in list_proposals(env):
        if entry["id"] != proposal_id:
            continue
        assert isinstance(entry["path"], str)
        source = Path(entry["path"])
        kind = str(entry["kind"])
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"{proposal_id}.json" if kind == "fact" else f"{proposal_id}.skill.json"
        target = out_dir / name
        target.write_text(source.read_text())
        commands = (
            [
                f"git checkout -b grow/{proposal_id}",
                f"git add src/jarvis/knowledge/data/{name}  # after copying the file there",
                f"git commit -m 'grow: add fact {proposal_id} (owner-reviewed)'",
                "git push -u origin grow/" + proposal_id,
                f"gh pr create --fill --head grow/{proposal_id}  # review, then YOU merge",
            ]
            if kind == "fact"
            else [
                f"jarvis --yes skill install {target}  # consented install; evals re-run",
            ]
        )
        return {"kind": kind, "artifact": str(target), "commands": commands}
    raise GrowError(f"no proposal {proposal_id!r} (list with: jarvis grow list)")
