# ADR-0003: Model posture — hybrid router with local-first default

- **Status:** Accepted (2026-09-02, authority delegated by owner to engineer-of-record)
- **Context:** Owner requirement #9 explicitly asks for API models, local models, *and* an engine for basic tasks. Requirements #4/#6 (stability, anti-hallucination) and guideline 15 (security/privacy-first) constrain the default.
- **Decision:** Three execution paths behind one **complexity/sensitivity router**: (1) deterministic playbook engine for high-frequency basics (no LLM); (2) **local models (Ollama/llama.cpp) as default planner** when installed — offline, private, zero marginal cost; (3) API models opt-in (user-supplied keys) for hard planning and vision-based GUI grounding. Sensitive actions (T2/T3) prefer local review or the strongest available reviewer regardless of path.
- **Consequences:** Two provider paths must be maintained and tested with fakes from M2; router configuration must stay minimal (sane defaults, one config file); no phone-home without explicit user configuration (guideline 15).
