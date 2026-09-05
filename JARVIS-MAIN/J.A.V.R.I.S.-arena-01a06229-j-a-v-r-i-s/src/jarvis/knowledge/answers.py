"""Cite-or-abstain answer layer (ADR-0009).

An answer is either grounded in a KB fact WITH its citations and an honest
on-machine verification status, or it is refused. There is no path that
produces an uncited claim.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.knowledge.grounding import verify_fact
from jarvis.knowledge.store import Fact, KnowledgeBase, match_fact

STATUS_ANSWERED = "answered"
STATUS_ANSWERED_UNVERIFIED_HERE = "answered-unverified-here"
STATUS_REFUSED = "refused"


@dataclass(frozen=True)
class Answer:
    question: str
    status: str  # answered | answered-unverified-here | refused
    fact_id: str
    claim: str
    sources: tuple[dict[str, str], ...]
    machine_status: str  # verified | contradicted | unverifiable-here
    machine_detail: str
    note: str
    ai_text: str = ""  # non-empty only for AI-synthesized answers (ADR-0014 D5)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "status": self.status,
            "fact_id": self.fact_id,
            "claim": self.claim,
            "sources": [dict(s) for s in self.sources],
            "machine": {"status": self.machine_status, "detail": self.machine_detail},
            "note": self.note,
            "ai_text": self.ai_text or None,
        }


def answer(question: str, kb: KnowledgeBase) -> Answer:
    fact: Fact | None = match_fact(question, kb)
    if fact is None:
        return Answer(
            question=question,
            status=STATUS_REFUSED,
            fact_id="",
            claim="",
            sources=(),
            machine_status="unverifiable-here",
            machine_detail="",
            note=(
                "no cited fact matches this question; I will not guess "
                f"(browse what I know: jarvis facts — {len(kb.facts)} facts, "
                f"KB v{kb.version})"
            ),
        )

    status, detail = verify_fact(fact.verify)
    sources = tuple(
        {
            "kind": s.kind,
            "ref": s.ref,
            **({"url": s.url} if s.url else {}),
            **({"repo": s.repo} if s.repo else {}),
        }
        for s in fact.sources
    )

    if status == "verified":
        answer_status = STATUS_ANSWERED
        note = "verified on this machine"
    elif status == "contradicted":
        answer_status = STATUS_ANSWERED_UNVERIFIED_HERE
        note = (
            "cited fact does NOT hold on this machine — treat as not "
            "applicable here, see sources for scope"
        )
    else:
        answer_status = STATUS_ANSWERED_UNVERIFIED_HERE
        note = "documentation-sourced; no local check possible here"

    return Answer(
        question=question,
        status=answer_status,
        fact_id=fact.id,
        claim=fact.claim,
        sources=sources,
        machine_status=status,
        machine_detail=detail,
        note=note,
    )
