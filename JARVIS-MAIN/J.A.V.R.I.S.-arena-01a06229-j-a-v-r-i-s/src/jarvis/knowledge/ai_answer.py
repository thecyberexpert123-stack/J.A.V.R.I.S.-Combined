"""Grounded AI answer synthesis on KB misses (ADR-0014 D5).

Deterministic cite-or-abstain answers run FIRST and unchanged (ADR-0009).
Only when the KB cannot match a question — and the operator has not disabled
AI — does the planner backend get one bounded chance to synthesize an answer
from an evidence envelope of REAL KB facts (ids, claims, sources; capped).

The output contract is structural abstention (AbstentionBench's finding:
prompt-begged abstention fails; structure does not): the model may cite ONLY
fact ids from the supplied envelope; empty or unknown citations, an explicit
``abstain``, an oversized answer, or injection-shaped prose are all forced
abstentions. Any failure falls back to the deterministic refusal with a
one-line disclosure appended to the note. The model never gains authority:
an AI answer is text plus citations to facts the kernel can independently
verify on this machine.
"""

from __future__ import annotations

import json
from dataclasses import replace

from jarvis.context.store import find_injection_pattern
from jarvis.knowledge.answers import (
    STATUS_ANSWERED,
    STATUS_ANSWERED_UNVERIFIED_HERE,
    STATUS_REFUSED,
    Answer,
)
from jarvis.knowledge.answers import answer as kb_answer
from jarvis.knowledge.grounding import verify_fact
from jarvis.knowledge.store import KnowledgeBase
from jarvis.providers.base import FailureKind, ProviderError
from jarvis.providers.breaker import ProviderBreaker, default_breaker_path, guarded_complete
from jarvis.providers.router import plan_routing

MAX_EVIDENCE_FACTS = 24
MAX_CLAIM_CHARS = 240
MAX_ANSWER_CHARS = 600
MAX_QUESTION_CHARS = 800
_TIMEOUT_S = 60.0

ANSWER_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "abstain": {"type": "boolean"},
        "answer": {"type": "string"},
        "fact_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["abstain", "answer", "fact_ids"],
}

_SYSTEM_PROMPT = f"""You are the answer layer inside JARVIS, a Linux automation agent.
Respond with STRICT JSON only - no markdown, no prose outside the JSON:
{{"abstain": <bool>, "answer": "<at most {MAX_ANSWER_CHARS} chars>",
  "fact_ids": ["<fact id>", ...]}}
Rules:
- Answer ONLY from the evidence facts supplied in the user message; cite the fact ids you used.
- If the evidence is insufficient, set "abstain" to true with an empty answer and empty fact_ids.
- An honest abstention is a GOOD outcome; never guess and never use outside knowledge.
- Plain prose only: never shell commands, flags, paths, or instructions to run anything.
"""


def _evidence_envelope(kb: KnowledgeBase) -> str:
    lines: list[str] = []
    for fact in kb.facts[:MAX_EVIDENCE_FACTS]:
        sources = ", ".join(f"{s.kind}:{s.ref}" for s in fact.sources) or "no sources"
        claim = fact.claim[:MAX_CLAIM_CHARS]
        lines.append(f"- {fact.id}: {claim} [sources: {sources}]")
    if len(kb.facts) > MAX_EVIDENCE_FACTS:
        lines.append(f"(evidence truncated to {MAX_EVIDENCE_FACTS} of {len(kb.facts)} facts)")
    return "\n".join(lines)


class _Refused(Exception):
    """Model output failed the answer contract (malformed-class failure)."""


def _validate_synthesis(raw: str, evidence_ids: frozenset[str]) -> tuple[str, list[str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _Refused(f"output was not valid JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise _Refused("output was not a JSON object")
    answer_text = data.get("answer", "")
    if not isinstance(answer_text, str):
        raise _Refused('"answer" is not a string')
    if len(answer_text) > MAX_ANSWER_CHARS:
        raise _Refused(f"answer exceeds {MAX_ANSWER_CHARS} chars")
    pattern = find_injection_pattern(answer_text)
    if pattern is not None:
        raise _Refused(f"answer text matches injection pattern {pattern!r}")
    raw_ids = data.get("fact_ids", [])
    if not isinstance(raw_ids, list) or not all(isinstance(i, str) for i in raw_ids):
        raise _Refused('"fact_ids" is not a list of strings')
    cited = [fid for fid in raw_ids if fid]  # dedupe, preserve order
    cited = list(dict.fromkeys(cited))
    unknown = [fid for fid in cited if fid not in evidence_ids]
    if unknown:
        raise _Refused(f"cited unknown fact id(s): {', '.join(unknown[:3])}")
    if data.get("abstain") is True or not cited:
        return "", []
    if not answer_text.strip():
        raise _Refused("cited facts but produced an empty answer")
    return answer_text, cited


def answer_with_ai(
    question: str, kb: KnowledgeBase, *, enabled: bool = True, env: dict[str, str] | None = None
) -> Answer:
    """Deterministic answer first; on a KB miss, one bounded grounded AI attempt."""
    base = kb_answer(question, kb)
    if base.status != STATUS_REFUSED or not enabled:
        return base

    routing = plan_routing(env=env, enabled=True)
    provider = routing.provider
    if provider is None:
        return replace(base, note=f"{base.note} — ai synthesis unavailable ({routing.note})")

    breaker = ProviderBreaker(default_breaker_path(env))
    evidence_ids = frozenset(fact.id for fact in kb.facts)
    prompt = (
        f"Question: {question[:MAX_QUESTION_CHARS]}\n\n"
        f"Evidence facts (cite ONLY these ids):\n{_evidence_envelope(kb)}"
    )
    try:
        raw = guarded_complete(
            provider,
            _SYSTEM_PROMPT,
            prompt,
            breaker,
            timeout_s=_TIMEOUT_S,
            schema=ANSWER_JSON_SCHEMA,
        )
    except ProviderError as exc:
        if exc.kind is not FailureKind.BREAKER_OPEN:
            breaker.record_failure(provider.name, str(exc.kind), str(exc))
        return replace(
            base,
            note=f"{base.note} — ai synthesis failed ({exc.kind}); deterministic refusal stands",
        )

    try:
        answer_text, cited = _validate_synthesis(raw, evidence_ids)
    except _Refused as exc:
        breaker.record_failure(provider.name, "malformed", str(exc))
        return replace(
            base,
            note=f"{base.note} — ai synthesis refused ({exc}); deterministic refusal stands",
        )

    if not cited:
        breaker.record_success(provider.name)  # honest abstention = healthy model (ADR-0014 D1)
        return replace(
            base,
            note=(
                f"{base.note} — the model abstained honestly: no cited evidence basis "
                "for this question"
            ),
        )
    breaker.record_success(provider.name)

    facts = {fact.id: fact for fact in kb.facts}
    primary = facts[cited[0]]
    machine_status, machine_detail = verify_fact(primary.verify)
    status = STATUS_ANSWERED if machine_status == "verified" else STATUS_ANSWERED_UNVERIFIED_HERE
    return Answer(
        question=question,
        status=status,
        fact_id=primary.id,
        claim=primary.claim,
        sources=tuple(
            {
                "kind": s.kind,
                "ref": s.ref,
                **({"url": s.url} if s.url else {}),
                **({"repo": s.repo} if s.repo else {}),
            }
            for s in primary.sources
        ),
        machine_status=machine_status,
        machine_detail=machine_detail,
        note=(
            f"ai-synthesized from {len(cited)} cited fact(s) ({', '.join(cited)}); "
            "verification shown for the primary fact — every claim above is KB-cited"
        ),
        ai_text=answer_text,
    )
