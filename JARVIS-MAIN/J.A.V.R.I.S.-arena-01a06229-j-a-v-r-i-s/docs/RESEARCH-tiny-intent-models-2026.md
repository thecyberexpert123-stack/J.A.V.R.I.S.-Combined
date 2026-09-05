# RESEARCH: tiny purpose-built intent models (2026-09-04)

Owner-directed follow-up to ADR-0014/M10: the owner asked whether a neural
network built *specifically for JARVIS* could improve behavior when the main
AI fails or the request is unknown. ADR-0014's answer stands — the fallback
for a failed AI is the deterministic engine, never a second probabilistic
system. The one gap a purpose-built model legitimately fills is **recall**:
mapping sloppier phrasing onto the playbook vocabulary as a proposals-only
advisor. This note records the evidence for the design ADR-0015 picks.

## R1. Tiny hashed-ngram classifiers are the established baseline

- fastText (Joulin et al., 2016, "Bag of Tricks for Efficient Text
  Classification"): a linear classifier over averaged bag-of-words/n-gram
  features is "on par with deep learning approaches" on text classification
  while being "orders of magnitude faster" — and character n-grams plus the
  **hashing trick** (no vocabulary file, fixed memory) are the standard
  ingredients ([paper summary](https://gist.github.com/shagunsodhani/432746f15889f7f4a798bf7f9ec4b7d8),
  [arXiv 1612.03651](https://arxiv.org/pdf/1612.03651)).
- fastText.zip (Prats et al.): the same family compressed to "often less than
  100kB" with hashing over words **and** n-grams "with almost no overhead at
  test time" — the model-size regime JARVIS needs (a package-data file, not a
  runtime dependency)
  ([openreview](https://openreview.net/pdf?id=SJc1hL5ee),
  [arXiv 1612.03651](https://arxiv.org/pdf/1612.03651)).

**Decision taken from this:** hashed word-uni/bi-grams + character trigrams
into a fixed 256-dim signed bag → one 48-unit ReLU hidden layer → softmax over
the 12 playbook families **plus an explicit `unknown` class**. Parameters:
~13K floats (107 KB JSON). Inference: pure-stdlib dense math, ~1 ms.

## R2. Why one small purpose-built model and not "a second AI for failover"

- Stacking a second probabilistic system as the failure path of the first
  widens the surprising-behavior space and shares the failure domain (same
  box, same resources). The degradation ladder (ADR-0014 research, R2) ends in
  deterministic rules and human handoff — not a smaller model. The purpose-
  built network is therefore an **advisory recall widener**, not a fallback
  executor: it may only emit *suggestions* whose reconstruction re-passes the
  real playbook matchers, and only after both the engine and (when enabled)
  the LLM planner have declined.
- The `unknown` class plus a confidence threshold makes abstention
  **structural** (the ADR-0014 research, R3): below-threshold and unknown
  outputs can only feed the "did you mean" disclosure, never a suggestion.

## R3. Training-data honesty

A closed-vocabulary intent classifier over a fixed catalog is trainable from
templated synthetic corpora — the industry-standard approach for intent
slots — but the corpus over-represents its own templates. Mitigations, in
order of honesty value: (1) a hand-written labeled/OOD eval set that is
**independent of the training generator** (the committed tests); (2) an
explicit `unknown` class trained on deliberately diverse off-catalog requests;
(3) documented limits: English-only, template-derived distribution, and the
journal's `unknown_requests` table as the drift signal that tells the owner
when real traffic disagrees with the corpus (growth-loop input, ADR-0014 D6).

## R4. What the trainer taught (recorded for future sessions)

Two classic failure modes were caught by the trainer's own gates, exactly as
gates are meant to: (1) a backprop bug — updating first-layer weights with a
gradient missing the error factor `d2[k]`; (2) the ReLU dead-at-initialization
deadlock — at zero weights every hidden unit outputs zero, so `dh = W2·d2 = 0`
forever and only the output bias learns (loss froze at the class-prior
entropy). The seeded random init is the standard symmetry breaker.
