# ADR-0015: Learned intent recall — a purpose-built proposals-only classifier

- **Status:** Accepted and implemented (2026-09-04; owner-directed: "a neural
  network, specifically for this, so that the program can run during AI
  errors, and handle anything while the AI fails" → clarified and confirmed:
  the model is a recall widener, NOT a fallback executor — the answer to
  running during AI failure remains the deterministic engine, per ADR-0014).
  Research basis: [RESEARCH-tiny-intent-models-2026.md](../RESEARCH-tiny-intent-models-2026.md)
  (fastText/hashing-trick lineage, abstention structure, training-data honesty).
- **Context:** The engine misses requests whose *phrasing* matches no pattern
  ("can you install htop for me"), and the only recovery so far was the LLM
  planner or lexical `difflib` disclosure. A tiny purpose-built network can
  rank the playbook vocabulary for sloppier phrasing — milliseconds, no
  daemon, no runtime dependency (ADR-0005 intact) — provided it never gains
  authority.

## Decisions

**D1 — Architecture.** Bag of hashed features (word uni/bi-grams + character
trigrams, signed hashing trick into a fixed 256-dim vector, L2-normalized) →
one 48-unit ReLU hidden layer → softmax over the 12 playbook families plus an
explicit `unknown` class. ~13K parameters, 107 KB JSON shipped as package data
(`jarvis.intent/model.json`, mirroring the KB data pattern). Inference is
pure-stdlib dense math (~1 ms); the vectorizer lives in the runtime module and
the trainer imports it — single source of truth, so training and inference
cannot drift.

**D2 — Training.** Seeded deterministic trainer (`training/train_intent.py`,
dev-only, not shipped): templated synthetic corpus with filler/paraphrase
variation per family, an `unknown` class trained on deliberately diverse
off-catalog requests, stratified holdout. Gates enforced before weights are
written (top-1 ≥ 0.88, top-3 ≥ 0.97, OOD abstention ≥ 0.80), and the gates
evaluate the **rounded weights actually shipped**, not a fuller-precision
sibling. Two classic trainer bugs (missing error factor in the W1 gradient;
the ReLU zero-init deadlock) were caught by these gates before anything
shipped — the gates are the point.

**D3 — Authority contract (the core decision).** The classifier is
proposals-only, structurally:
- it is consulted ONLY after the deterministic engine missed AND the LLM
  planner is unavailable or honestly reported the request unexpressible — it
  never intercepts the engine;
- a suggestion must survive a deterministic slot extractor AND re-pass the
  REAL playbook matcher (`match_intent`); no acceptance, no suggestion. If
  either declines, the model abstains to disclosure;
- a suggestion is TEXT: "it looks like: `jarvis do install htop` — type that
  yourself to run it (suggestions never self-execute)" — the M8a/M8d pattern:
  the user types the command, the kernel disposes;
- `file.append` is deliberately extractor-free: the model never reconstructs
  paths — disclosure only;
- it is a model: `--no-ai` / `JARVIS_NO_AI=1` switches it off (ADR-0014 D7),
  and disclosure falls back to the lexical ranking (equivalent disclosure,
  neither is authority).

**D4 — Unknown-class abstention.** `unknown` is a trained class, and a
suggestion additionally requires top-1 probability ≥ 0.85 over a non-unknown
label. Below threshold, ranked labels still feed the "did you mean"
disclosure — abstention degrades to a weaker honesty, never to a guess.

**D5 — Scope guards.** The MCP surface is untouched (frozen
`javris-frontend/1` contract); nothing in `status`/`doctor` treats the model
file as policy (it is kernel-shipped content inside the integrity baseline
like the rest of `src/`); no new runtime dependency; English-only and
template-derived distribution are documented limitations, with the
`unknown_requests` journal as the drift signal the owner reviews.

## Consequences

- New: `src/jarvis/intent/` (classifier + weights), `training/train_intent.py`
  (dev-only trainer), `tests/test_intent_model.py` (14 tests, hand-written
  eval sets independent of the training generator), package-data entry.
- `jarvis ask` unknown-path hints may now contain an engine-legal suggested
  command; `error`/exit-code contracts unchanged (guideline 17).
- Honest limitations: recall gains are bounded by the synthetic corpus (the
  hand-written eval set is the honesty anchor); the model can be wrong with
  high confidence on adversarial phrasing — which is harmless by construction,
  because every suggestion still ends in a user-typed, kernel-validated
  command. Retraining after catalog growth is one command with gates.
