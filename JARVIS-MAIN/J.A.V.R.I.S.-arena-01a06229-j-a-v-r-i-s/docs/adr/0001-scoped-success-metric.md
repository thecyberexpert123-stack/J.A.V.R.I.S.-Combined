# ADR-0001: Success metric — scoped catalog with ≥98% verified target

- **Status:** Accepted (2026-09-02, authority delegated by owner to engineer-of-record)
- **Context:** Owner requirement #3 demands a 98% success rate. Research (`docs/RESEARCH.md` R1) shows state-of-the-art computer-use agents reach ~63.5–76% on OSWorld and ~20% on OSWorld 2.0 long-horizon tasks. A blanket open-world 98% promise is not technically honest.
- **Decision:** Adopt the scoped definition (PLAN §3): **S ≥ 98% on the versioned Tier-1 Task Catalog**, measured by execution-based evaluation in disposable environments, success = post-condition verification passes. Outside the catalog the agent runs in *explorer mode* (plan → confirm → execute → verify) and must decline or escalate on low confidence or failed verification. Eval results are versioned and published in `evals/results/`.
- **Consequences:** Capability growth is gated by measurement (catalog entries enter only when they hold ≥98% in CI); the published number is always auditable; marketing-style open-world claims are prohibited in all project communication.
