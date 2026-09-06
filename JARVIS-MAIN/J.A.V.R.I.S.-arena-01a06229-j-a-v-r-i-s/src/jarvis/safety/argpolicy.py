"""Owner-authored, narrowing-only argument policy (ADR-0030).

One JSON file — ``state_dir()/policy/argument-policy.json`` — of rules that can
**only refuse**. A rule binds to playbook ids and to a *params* key (the
owner-meaningful object: ``names``, ``path``, ``unit`` …), never to argv
spellings, and carries exactly one effect:

- ``deny_regex``     — refuse when the value matches;
- ``allow_prefixes`` — refuse unless the resolved value starts with one;
- ``allow_regex``    — refuse unless the value matches.

Nothing here can grant: no tier field, no consent field, no input rewriting.
Absent file = today's behaviour byte-for-byte. A malformed file fails
**closed for the playbooks it names** (never system-wide, never wider) so a
typo cannot become a reason to delete the file.

The design mirrors Progent (arXiv:2504.11703 v3 §4: symbolic rules over tool
names and arguments, deterministic check, forbid evaluated before allow —
here trivially, because every effect is a refusal) and keeps the rules
human-owned (AgentSpec: generated rules reached 70.96 % recall).

Storage is integrity-scoped (owner decision D-A = A3): the directory is part
of ``integrity.default_scope()``, so silent removal of a rule is DRIFT in
``jarvis doctor``; ``jarvis policy lint`` reminds the owner to re-baseline.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from jarvis.journal.sqlite import state_dir
from jarvis.safety.tiers import SafetyRefusal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

POLICY_SCHEMA = 1
POLICY_FILENAME = "argument-policy.json"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\])?$")
_MAX_REASON = 200
_MAX_PATTERN = 200
# catastrophic-backtracking shapes an owner is unlikely to need: a quantified
# group that is itself quantified, e.g. (x+)+ or (a|aa)*
_NESTED_QUANTIFIER_RE = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*{]")
_EFFECTS = ("deny_regex", "allow_prefixes", "allow_regex")
_PATH_KEYS = frozenset({"path", "src", "dst"})


def policy_dir(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "policy"


def policy_path(env: dict[str, str] | None = None) -> Path:
    return policy_dir(env) / POLICY_FILENAME


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One validated rule. ``pattern`` is compiled once at load."""

    id: str
    playbooks: tuple[str, ...]  # ("*",) = every playbook that has the key
    keys: tuple[str, ...]  # params keys; "names[]" → key "names", each element
    effect: str  # one of _EFFECTS
    pattern: re.Pattern[str] | None
    prefixes: tuple[str, ...]
    reason: str

    def applies_to(self, playbook_id: str) -> bool:
        return "*" in self.playbooks or playbook_id in self.playbooks

    def check_value(self, key: str, value: str) -> str | None:
        """Return the refusal detail for one value, or None when it passes."""
        if self.effect == "deny_regex":
            assert self.pattern is not None
            if self.pattern.search(value):
                return f"{key}={value!r} matches deny_regex {self.pattern.pattern!r}"
            return None
        if self.effect == "allow_regex":
            assert self.pattern is not None
            if self.pattern.search(value):
                return None
            return f"{key}={value!r} does not match allow_regex {self.pattern.pattern!r}"
        # allow_prefixes — compare the *resolved* form for path-like keys so
        # ``~/Downloads/../.ssh`` is judged as ``~/.ssh`` (same normalisation the
        # playbooks apply: expanduser + resolve(strict=False)).
        candidate = _resolve_for_prefix(value) if key in _PATH_KEYS else value
        if any(candidate.startswith(prefix) for prefix in self.prefixes):
            return None
        return (
            f"{key}={value!r} (resolved {candidate!r}) is outside "
            f"allow_prefixes {list(self.prefixes)!r}"
        )


def _resolve_for_prefix(value: str) -> str:
    try:
        raw = Path(value).expanduser()
        if not raw.is_absolute():
            raw = Path.cwd() / raw
        return raw.resolve(strict=False).as_posix()
    except (OSError, RuntimeError, ValueError):
        return value


def _resolve_prefix(prefix: str) -> str:
    """Prefixes are resolved once at load; a trailing ``/`` is kept meaningful."""
    trailing = prefix.endswith("/")
    resolved = _resolve_for_prefix(prefix)
    if trailing and not resolved.endswith("/"):
        resolved += "/"
    return resolved


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    rule_id: str
    message: str

    def __str__(self) -> str:
        who = f" [{self.rule_id}]" if self.rule_id else ""
        return f"{self.level}{who}: {self.message}"


@dataclass(frozen=True)
class Policy:
    """The effective policy. ``state`` ∈ {absent, ok, malformed}."""

    rules: tuple[Rule, ...]
    state: str
    findings: tuple[Finding, ...] = ()
    # playbooks named by rules that could not be validated → refused outright
    broken_scope: frozenset[str] = frozenset()
    # True when even the rule list could not be parsed → every T1+ refused
    broken_all: bool = False
    path: Path | None = None
    known_playbooks: frozenset[str] = field(default_factory=frozenset)

    @staticmethod
    def empty(path: Path | None = None) -> Policy:
        return Policy(rules=(), state="absent", path=path)

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.level == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.level == "warning")

    def rules_for(self, playbook_id: str) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.applies_to(playbook_id))

    def bound_playbooks(self) -> frozenset[str]:
        out: set[str] = set()
        for rule in self.rules:
            if "*" in rule.playbooks:
                out.update(self.known_playbooks)
            else:
                out.update(rule.playbooks)
        return frozenset(out)

    def summary(self) -> str:
        if self.state == "absent":
            return "absent"
        if self.state == "malformed":
            what = (
                "every T1+ playbook"
                if self.broken_all
                else (", ".join(sorted(self.broken_scope)) or "nothing")
            )
            return f"MALFORMED — refusing {what} until `jarvis policy lint` passes"
        return f"{len(self.rules)} rule(s) over {len(self.bound_playbooks())} playbook(s) (ok)"

    # -- the check (called by the orchestrator, ADR-0030 D2) ------------------

    def check(self, playbook_id: str, params: Mapping[str, object], *, tier: int) -> None:
        """Raise ``SafetyRefusal`` when a rule refuses; never widens anything."""
        if self.state == "absent":
            return
        if self.broken_all and tier >= 1:
            raise SafetyRefusal(
                f"argument policy file {self.path} is malformed; refusing {playbook_id} "
                "(T1+) until `jarvis policy lint` passes"
            )
        if playbook_id in self.broken_scope:
            raise SafetyRefusal(
                f"argument policy file {self.path} has an invalid rule naming {playbook_id}; "
                "refusing it until `jarvis policy lint` passes"
            )
        for rule in self.rules_for(playbook_id):
            for key, value in _values(params, rule.keys):
                detail = rule.check_value(key, value)
                if detail is not None:
                    raise SafetyRefusal(
                        f"argument policy rule {rule.id!r} refused {playbook_id}: {detail}"
                        + (f" — {rule.reason}" if rule.reason else "")
                    )


def _values(params: Mapping[str, object], keys: Sequence[str]) -> Iterable[tuple[str, str]]:
    for spec in keys:
        each = spec.endswith("[]")
        key = spec[:-2] if each else spec
        if key not in params:
            continue
        raw = params[key]
        if each:
            if isinstance(raw, (list, tuple)):
                for item in raw:
                    yield key, str(item)
            else:
                yield key, str(raw)
        elif isinstance(raw, (list, tuple)):
            # a list addressed without [] — apply to every element (safer
            # than joining, which a regex could be tricked around)
            for item in raw:
                yield key, str(item)
        else:
            yield key, str(raw)


# --------------------------------------------------------------------------
# loading + validation
# --------------------------------------------------------------------------


def _compile(
    pattern: object, rule_id: str, what: str, findings: list[Finding]
) -> re.Pattern[str] | None:
    if not isinstance(pattern, str) or not pattern:
        findings.append(Finding("error", rule_id, f"{what} must be a non-empty string"))
        return None
    if len(pattern) > _MAX_PATTERN:
        findings.append(Finding("error", rule_id, f"{what} longer than {_MAX_PATTERN} chars"))
        return None
    if _NESTED_QUANTIFIER_RE.search(pattern):
        findings.append(
            Finding("error", rule_id, f"{what} nests quantifiers ({pattern!r}); rewrite it")
        )
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        findings.append(Finding("error", rule_id, f"{what} does not compile: {exc}"))
        return None


def _parse_rule(
    raw: object, index: int, known: frozenset[str], known_keys: Mapping[str, frozenset[str]]
) -> tuple[Rule | None, list[Finding], set[str]]:
    """Validate one rule. Returns (rule or None, findings, playbooks it names)."""
    findings: list[Finding] = []
    named: set[str] = set()
    if not isinstance(raw, dict):
        findings.append(Finding("error", f"#{index}", "rule is not an object"))
        return None, findings, named
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not _ID_RE.match(rule_id):
        findings.append(
            Finding("error", f"#{index}", "id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        )
        rule_id = f"#{index}"
    playbooks_raw = raw.get("playbooks")
    playbooks: list[str] = []
    if not isinstance(playbooks_raw, list) or not playbooks_raw:
        findings.append(Finding("error", rule_id, "playbooks must be a non-empty list"))
    else:
        for item in playbooks_raw:
            if not isinstance(item, str):
                findings.append(Finding("error", rule_id, "playbooks entries must be strings"))
                continue
            if item == "*":
                playbooks.append(item)
                named.update(known)
            elif item in known:
                playbooks.append(item)
                named.add(item)
            else:
                # a typo must not silently protect nothing: error, entry dropped
                findings.append(Finding("error", rule_id, f"unknown playbook id {item!r}"))
    argument = raw.get("argument")
    keys: list[str] = []
    if not isinstance(argument, str) or not argument.strip():
        findings.append(Finding("error", rule_id, "argument must be a non-empty string"))
    else:
        for part in argument.split("|"):
            part = part.strip()
            if not _KEY_RE.match(part):
                findings.append(
                    Finding("error", rule_id, f"argument key {part!r} is not a params key")
                )
                continue
            keys.append(part)
    effects = [name for name in _EFFECTS if name in raw]
    if len(effects) != 1:
        findings.append(
            Finding("error", rule_id, f"exactly one of {', '.join(_EFFECTS)} is required")
        )
    pattern: re.Pattern[str] | None = None
    prefixes: tuple[str, ...] = ()
    if len(effects) == 1:
        effect = effects[0]
        if effect in ("deny_regex", "allow_regex"):
            pattern = _compile(raw[effect], rule_id, effect, findings)
        else:
            raw_prefixes = raw["allow_prefixes"]
            if (
                not isinstance(raw_prefixes, list)
                or not raw_prefixes
                or not all(isinstance(p, str) and p for p in raw_prefixes)
            ):
                findings.append(
                    Finding("error", rule_id, "allow_prefixes must be a non-empty list of strings")
                )
            else:
                path_keys = [k.rstrip("[]") for k in keys if k.rstrip("[]") in _PATH_KEYS]
                prefixes = tuple(_resolve_prefix(p) if path_keys else p for p in raw_prefixes)
    reason = raw.get("reason", "")
    if not isinstance(reason, str) or "\n" in reason or len(reason) > _MAX_REASON:
        findings.append(
            Finding(
                "error", rule_id, f"reason must be a single line of at most {_MAX_REASON} chars"
            )
        )
        reason = ""
    unknown = sorted(set(raw) - {"id", "playbooks", "argument", "reason", *_EFFECTS})
    if unknown:
        findings.append(Finding("error", rule_id, f"unknown field(s) {unknown!r}"))
    # keys the named playbooks never produce: a warning, the rule stays (it
    # may be written ahead of a playbook or a phrasing)
    for pb in playbooks:
        if pb == "*":
            continue
        produced = known_keys.get(pb, frozenset())
        for key in keys:
            if produced and key.rstrip("[]") not in produced:
                findings.append(
                    Finding(
                        "warning",
                        rule_id,
                        f"{pb} does not produce argument {key.rstrip('[]')!r} "
                        f"(it produces {sorted(produced)!r}); rule is inert for it",
                    )
                )
    if any(f.level == "error" for f in findings):
        return None, findings, named
    return (
        Rule(
            id=rule_id,
            playbooks=tuple(playbooks),
            keys=tuple(keys),
            effect=effects[0],
            pattern=pattern,
            prefixes=prefixes,
            reason=reason,
        ),
        findings,
        named,
    )


def parse_policy(
    text: str,
    *,
    known_playbooks: frozenset[str],
    known_keys: Mapping[str, frozenset[str]] | None = None,
    path: Path | None = None,
) -> Policy:
    """Parse + validate policy text. Never raises; degraded states are explicit."""
    keys_by_pb = known_keys or {}
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return Policy(
            rules=(),
            state="malformed",
            findings=(Finding("error", "", f"not valid JSON: {exc}"),),
            broken_all=True,
            path=path,
            known_playbooks=known_playbooks,
        )
    findings: list[Finding] = []
    if not isinstance(doc, dict):
        return Policy(
            rules=(),
            state="malformed",
            findings=(Finding("error", "", "top level must be an object"),),
            broken_all=True,
            path=path,
            known_playbooks=known_playbooks,
        )
    if doc.get("schema") != POLICY_SCHEMA:
        findings.append(Finding("error", "", f"schema must be {POLICY_SCHEMA}"))
    unknown_top = sorted(set(doc) - {"schema", "rules"})
    if unknown_top:
        findings.append(Finding("error", "", f"unknown top-level field(s) {unknown_top!r}"))
    rules_raw = doc.get("rules")
    if not isinstance(rules_raw, list):
        findings.append(Finding("error", "", "rules must be a list"))
        return Policy(
            rules=(),
            state="malformed",
            findings=tuple(findings),
            broken_all=True,
            path=path,
            known_playbooks=known_playbooks,
        )
    rules: list[Rule] = []
    broken: set[str] = set()
    seen_ids: set[str] = set()
    for index, raw in enumerate(rules_raw):
        rule, rule_findings, named = _parse_rule(raw, index, known_playbooks, keys_by_pb)
        findings.extend(rule_findings)
        if rule is None:
            broken.update(named)
            continue
        if rule.id in seen_ids:
            findings.append(Finding("error", rule.id, "duplicate rule id"))
            broken.update(named)
            continue
        seen_ids.add(rule.id)
        rules.append(rule)
    has_errors = any(f.level == "error" for f in findings)
    top_level_error = any(f.level == "error" and f.rule_id == "" for f in findings)
    return Policy(
        rules=tuple(rules),
        state="malformed" if has_errors else "ok",
        findings=tuple(findings),
        broken_scope=frozenset(broken),
        broken_all=top_level_error,
        path=path,
        known_playbooks=known_playbooks,
    )


def _catalog() -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """Playbook ids and the params keys each is known to produce (from hints)."""
    from jarvis.planner.intent_hints import INTENT_HINTS
    from jarvis.planner.playbooks import PLAYBOOKS

    ids = frozenset(pb.id for pb in PLAYBOOKS)
    keys: dict[str, frozenset[str]] = {}
    for pb in PLAYBOOKS:
        phrase = INTENT_HINTS.get(pb.id)
        if not phrase:
            continue
        try:
            params = pb.match(phrase)
        except Exception:  # a hint that explodes is a test failure elsewhere
            params = None
        if params:
            keys[pb.id] = frozenset(params.keys())
    return ids, keys


def load_policy(env: dict[str, str] | None = None, *, path: Path | None = None) -> Policy:
    """Load the owner's policy; absent → ``Policy.empty()`` (today's behaviour)."""
    target = path if path is not None else policy_path(env)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Policy.empty(target)
    except OSError as exc:  # unreadable but present: fail closed for T1+
        return Policy(
            rules=(),
            state="malformed",
            findings=(Finding("error", "", f"cannot read policy file: {exc}"),),
            broken_all=True,
            path=target,
        )
    ids, keys = _catalog()
    return parse_policy(text, known_playbooks=ids, known_keys=keys, path=target)


class PolicyCache:
    """mtime/size-keyed loader so a long-lived doorway sees edits without restart."""

    def __init__(self, env: dict[str, str] | None = None, *, path: Path | None = None) -> None:
        self._path = path if path is not None else policy_path(env)
        self._stamp: tuple[int, int] | None = None
        self._policy: Policy | None = None

    def current(self) -> Policy:
        try:
            st = os.stat(self._path)
            stamp: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            stamp = None
        except OSError:
            stamp = (-1, -1)
        if self._policy is None or stamp != self._stamp:
            self._policy = load_policy(path=self._path)
            self._stamp = stamp
        return self._policy


EXAMPLE_POLICY: dict[str, object] = {
    "schema": POLICY_SCHEMA,
    "rules": [
        {
            "id": "no-kernel-removal",
            "playbooks": ["pkg.remove"],
            "argument": "names[]",
            "deny_regex": "^(linux-image|linux-headers|grub|systemd|sudo)",
            "reason": "boot- and login-critical; remove by hand if ever",
        },
        {
            "id": "scratch-dirs-only",
            "playbooks": ["fs.remove", "fs.move"],
            "argument": "path|src|dst",
            "allow_prefixes": ["~/Downloads/", "~/tmp/"],
            "reason": "JARVIS deletes/moves only inside scratch space",
        },
        {
            "id": "never-touch-login-services",
            "playbooks": ["svc.stop", "svc.restart", "svc.disable"],
            "argument": "unit",
            "deny_regex": "^(sshd|ssh|NetworkManager|systemd-logind|gdm|sddm)(\\.service)?$",
            "reason": "would lock me out of the box",
        },
    ],
}
