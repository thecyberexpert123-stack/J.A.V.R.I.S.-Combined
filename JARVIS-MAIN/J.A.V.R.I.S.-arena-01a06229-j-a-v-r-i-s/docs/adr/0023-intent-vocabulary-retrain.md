# ADR-0023: Intent classifier retrain over the full 56-playbook vocabulary

- **Status:** Accepted and implemented (2026-09-04; owner-directed "continue" — roadmap item R5a
  from `docs/RESEARCH-jarvis-agent-linux-2026.md`).
- **Context:** The proposals-only classifier (ADR-0015, v1.10.0) was trained when the catalog
  had 12 engine-legal intents. The catalog is now 56 playbooks across eight families
  (pkg/svc/sys/fs/file/gui/net/proc) — **44 playbook ids are invisible to the model**: it can
  neither rank them in "did you mean" disclosures nor propose them. Its position in the
  architecture is unchanged and deliberately narrow: it runs only after the deterministic
  engine missed, its output is a suggestion the user types themselves, any reconstruction must
  re-pass the real matchers, and `--no-ai` switches it off. This ADR widens what it *knows*;
  it does not widen what it *may do*.

## Decision

**D1 — The kernel owns the vocabulary; the trainer derives it.** `training/train_intent.py`
no longer hand-lists labels: `LABELS = sorted(p.id for p in PLAYBOOKS) + [UNKNOWN_LABEL]`,
imported from `jarvis.planner.playbooks` — the same single-source-of-truth discipline as
`suggest_intent` importing `match_intent`. Catalog drift now flows into the next training run
automatically, and a test pins `model["labels"] == sorted(PLAYBOOKS ids) + [unknown]` so the
shipped weights and the live catalog can never diverge silently (the vocabulary pin, sibling
of the catalog-stays-56 pin). Today that is 56 + `unknown` = 57 classes; the runtime reads the
label list from `model.json`, so inference code needs no structural change.

**D2 — Same gates, honestly earned at the larger label space.** The shipped weights must pass
exactly the ADR-0015 gates — holdout top-1 ≥ 0.88, top-3 ≥ 0.97, and unknown-recall
(abstention) ≥ 0.80 on the out-of-distribution pool — evaluated on the *rounded* artifact,
with the trainer refusing to write anything on failure. A 57-way softmax makes these gates
harder, not easier; they pass or nothing ships.

**D3 — Corpus aligned with the matcher surface, balanced by construction.** Every playbook id
gets a synthetic template corpus (≥ 12 phrasings each) written against the real matchers'
accepted surface — cue-word discipline keeps confusable families apart (first/last/contents
for head/tail/read; restart/stop/disable for the T2 service trio; kill/pid/name for the proc
pair). Fixed-phrase families gain realistic prefix variety ("please", "can you show",
"what is the", …). Because distinct texts per label vary, the trainer **upsamples the train
split to a common per-label target with the seeded RNG** — deterministic, and the stratified
holdout is split *before* upsampling so it stays free of duplicates (no leakage; the holdout
measures unique phrasings only). The unknown/OOD pool keeps its own growth.

**D4 — Reconstruction stays conservative; disclosure widens.** Slot extractors in
`suggest_intent` remain frozen at the original 12 labels: new families rank in top-k
disclosures (`rank_intents`, the unknown-request hint) but reconstruct nothing —
`suggest_intent` abstains on them, and a test pins that (e.g. a head/tail phrasing yields no
auto-suggestion). Widening extractors is per-family future work with its own review; the
matcher always disposes, paths are still never reconstructed, and T2 families gain only
"did you mean" visibility — the user typing the intent remains the sole consent path.

**D5 — Ship discipline unchanged.** Seeded deterministic trainer (byte-reproducible
`model.json`), stdlib-only inference, weights as package data, model stays tiny
(< 400 KB pin), the trainer never runs at runtime and is not in the wheel, `--no-ai` /
`JARVIS_NO_AI=1` still disables every path, and the **catalog stays 56** — this milestone
touches the trainer, the weights, and the honesty tests only; no playbook, matcher, or
authority surface changes.

## Consequences

- The recall widener finally covers the engine it serves: unknown-request hints can now
  suggest "did you mean: fs.tail / fs.head / …" across the whole catalog.
- Vocabulary drift is now a *CI* concern, not a silent staleness: retraining is required
  whenever playbooks change, and the tests make staleness loud.
- What is deliberately not here: extractor widening, any planner/authority change, and the
  other parked R5 items — capability manifests stay **owner-gated** (ADR-0017 D2: "no code
  moves until the owner says so"), and the synthesis-over-sources playbook (F6) remains
  parked.
