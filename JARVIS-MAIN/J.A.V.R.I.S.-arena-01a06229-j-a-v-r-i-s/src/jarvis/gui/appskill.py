"""Owner-taught app packs (`app-skill/1`) — ADR-0026 D4.

Declarative teaching data that compiles through the kernel: bounded steps
over the guarded vocabulary only (focus / action / type / key). The schema
has NO field that can carry a command — no argv, no shell, no scripts.
Packs are receipt-pinned (sha256) and live inside the doctor integrity
scope; a pack whose bytes no longer match its receipt is skipped
fail-closed (the M9b discipline).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from jarvis.desktop.guards import is_blocked_app
from jarvis.journal.sqlite import state_dir
from jarvis.safety.tiers import SafetyRefusal

SCHEMA = "app-skill/1"
MAX_STEPS = 12
MAX_TEXT_CHARS = 200
MAX_TITLE_CHARS = 120
MAX_FIELD_CHARS = 80
MAX_PHRASES = 8
STEP_KINDS = ("focus", "action", "type", "key")

# first token must be a bare command name (no slash -> PATH lookup, no path smuggling);
# later tokens are arguments: paths, flags, simple values — still no shell metacharacters
_APP_LAUNCH_TOKEN_RE = re.compile(r"^[A-Za-z0-9/._+=-]{1,64}$")
_APP_CMD_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._-]{0,63}$")
_COMBO_RE = re.compile(r"^[A-Za-z0-9+-._]{1,32}$")
_PHRASE_RE = re.compile(r"^[^\n]{1,120}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def packs_dir(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "appskills"


def pack_path(pack_id: str, env: dict[str, str] | None = None) -> Path:
    return packs_dir(env) / f"{pack_id}.app-skill.json"


def receipt_path(pack_id: str, env: dict[str, str] | None = None) -> Path:
    return packs_dir(env) / f"{pack_id}.receipt.json"


def _clean(value: object, what: str, limit: int) -> str:
    if not isinstance(value, str):
        raise SafetyRefusal(f"{what} must be a string")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > limit:
        raise SafetyRefusal(f"{what} must be 1..{limit} chars")
    if any(ord(ch) < 0x20 for ch in cleaned):
        raise SafetyRefusal(f"control characters are not allowed in {what}")
    return cleaned


def validate_pack(document: object) -> dict[str, object]:
    """Validate an app pack document against the bounded vocabulary."""
    if not isinstance(document, dict):
        raise SafetyRefusal("app pack must be a JSON object")
    if document.get("schema") != SCHEMA:
        raise SafetyRefusal(f"schema must be {SCHEMA!r}")
    pack_id = document.get("id")
    if not isinstance(pack_id, str) or not _ID_RE.fullmatch(pack_id):
        raise SafetyRefusal("id must match ^[a-z][a-z0-9-]{1,30}$")
    _clean(document.get("description"), "description", 200)

    launch: tuple[str, ...] = ()
    app_block = document.get("app")
    if app_block is not None:
        if not isinstance(app_block, dict):
            raise SafetyRefusal("app must be an object with optional launch tokens")
        raw_tokens = app_block.get("launch")
        if raw_tokens is not None:
            if not isinstance(raw_tokens, list) or not raw_tokens:
                raise SafetyRefusal("app.launch must be a non-empty token list")
            for idx, token in enumerate(raw_tokens):
                token_re = _APP_CMD_TOKEN_RE if idx == 0 else _APP_LAUNCH_TOKEN_RE
                if not isinstance(token, str) or not token_re.fullmatch(token):
                    raise SafetyRefusal(f"app.launch token is not a plain launch token: {token!r}")
            launch = tuple(str(t) for t in raw_tokens)
            if is_blocked_app(launch[0]):
                raise SafetyRefusal(f"app {launch[0]!r} is on the blocked list")

    raw_phrases = document.get("phrases")
    if not isinstance(raw_phrases, list) or not 1 <= len(raw_phrases) <= MAX_PHRASES:
        raise SafetyRefusal(f"phrases must be a list of 1..{MAX_PHRASES} anchored regexes")
    phrases: list[str] = []
    for phrase in raw_phrases:
        if not isinstance(phrase, str) or not _PHRASE_RE.fullmatch(phrase):
            raise SafetyRefusal(f"phrase must be a single line of at most 120 chars: {phrase!r}")
        pattern = phrase if phrase.startswith("^") and phrase.endswith("$") else f"^{phrase}$"
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SafetyRefusal(f"phrase is not a valid regex: {exc}") from exc
        phrases.append(pattern)

    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise SafetyRefusal(f"steps must be a list of 1..{MAX_STEPS} bounded steps")

    steps: list[dict[str, object]] = []
    for index, raw in enumerate(raw_steps, 1):
        steps.append(_validate_step(raw, index))
    validated: dict[str, object] = {
        "schema": SCHEMA,
        "id": pack_id,
        "description": _clean(document.get("description"), "description", 200),
        "phrases": phrases,
        "steps": steps,
    }
    if launch:
        # omitted entirely when the pack carries no launch: an empty launch
        # list must not fail the pack's own re-validation on reload
        validated["app"] = {"launch": list(launch)}
    return validated


def _validate_step(raw: object, index: int) -> dict[str, object]:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise SafetyRefusal(f"step {index} must be an object with exactly one key")
    kind, body = next(iter(raw.items()))
    if kind not in STEP_KINDS:
        raise SafetyRefusal(
            f"step {index}: unknown kind {kind!r} (allowed: {', '.join(STEP_KINDS)})"
        )
    if kind == "focus":
        title = _clean(body, f"step {index} focus title", MAX_TITLE_CHARS)
        if is_blocked_app(title):
            raise SafetyRefusal(f"step {index}: focus target matches the blocked list")
        return {"focus": title}
    if kind == "key":
        combo = _clean(body, f"step {index} key combo", 32)
        if not _COMBO_RE.fullmatch(combo):
            raise SafetyRefusal(
                f"step {index}: key combo may contain only alphanumerics and + - . _"
            )
        return {"key": combo}
    if not isinstance(body, dict):
        raise SafetyRefusal(f"step {index} ({kind}) must carry an object")
    app = _clean(body.get("app", ""), f"step {index} app", MAX_FIELD_CHARS)
    role = _clean(body.get("role", ""), f"step {index} role", MAX_FIELD_CHARS)
    name = _clean(body.get("name", ""), f"step {index} name", MAX_FIELD_CHARS)
    if kind == "action":
        action = _clean(body.get("action"), f"step {index} action", 40)
        if not app or not role or not name:
            raise SafetyRefusal(f"step {index}: action steps need app, role and name")
        if is_blocked_app(app):
            raise SafetyRefusal(f"step {index}: app {app!r} is on the blocked list")
        return {"action": {"app": app, "role": role, "name": name, "action": action}}
    # type
    text = _clean(body.get("text"), f"step {index} type text", MAX_TEXT_CHARS)
    if not app:
        raise SafetyRefusal(f"step {index}: type steps need an app")
    if is_blocked_app(app):
        raise SafetyRefusal(f"step {index}: app {app!r} is on the blocked list")
    return {"type": {"app": app, "role": role, "name": name, "text": text}}


def _receipt_ok(pack_id: str, pack_bytes: bytes, env: dict[str, str] | None) -> bool:
    path = receipt_path(pack_id, env)
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(receipt, dict):
        return False
    return str(receipt.get("sha256", "")) == hashlib.sha256(pack_bytes).hexdigest()


def load_pack(pack_id: str, env: dict[str, str] | None = None) -> dict[str, object] | None:
    """The validated pack, or None (missing/drifted → fail-closed skip)."""
    if not isinstance(pack_id, str) or not _ID_RE.fullmatch(pack_id):
        return None
    path = pack_path(pack_id, env)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not _receipt_ok(pack_id, raw, env):
        return None
    try:
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    try:
        return validate_pack(document)
    except SafetyRefusal:
        return None


def installed_packs(env: dict[str, str] | None = None) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    try:
        paths = sorted(packs_dir(env).glob("*.app-skill.json"))
    except OSError:
        return out
    for path in paths:
        pack = load_pack(path.name[: -len(".app-skill.json")], env)
        if pack is not None:
            out.append(pack)
    return out


def match_pack(
    text: str, env: dict[str, str] | None = None
) -> tuple[dict[str, object], str] | None:
    """First installed pack whose phrase anchored-matches the text."""
    collapsed = " ".join(text.split())
    for pack in installed_packs(env):
        for phrase in pack["phrases"] if isinstance(pack["phrases"], list) else []:
            try:
                if re.fullmatch(str(phrase), collapsed):
                    return pack, collapsed
            except re.error:
                continue
    return None


def install_pack(document: object, env: dict[str, str] | None = None) -> dict[str, object]:
    """Validate, then atomically write pack bytes + sha256 receipt."""
    validated = validate_pack(document)
    pack_id = str(validated["id"])
    payload = json.dumps(validated, indent=2, sort_keys=True) + "\n"
    directory = packs_dir(env)
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{pack_id}.tmp"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(pack_path(pack_id, env))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    receipt = {"schema": SCHEMA, "id": pack_id, "sha256": digest}
    rtmp = directory / f".{pack_id}.receipt.tmp"
    rtmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rtmp.replace(receipt_path(pack_id, env))
    return {"pack": validated, "sha256": digest, "path": str(pack_path(pack_id, env))}


def remove_pack(pack_id: str, env: dict[str, str] | None = None) -> int:
    removed = 0
    for path in (pack_path(pack_id, env), receipt_path(pack_id, env)):
        if path.exists():
            path.unlink()
            removed += 1
    return removed


def default_pack_stub_path(env: dict[str, str] | None = None) -> Path:
    return Path(os.environ.get("HOME", "/tmp")) / "pack.app-skill.json"
