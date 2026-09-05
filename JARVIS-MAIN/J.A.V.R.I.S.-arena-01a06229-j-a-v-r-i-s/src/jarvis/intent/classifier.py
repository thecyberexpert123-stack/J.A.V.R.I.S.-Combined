"""Tiny learned intent classifier (ADR-0015) — a *proposals-only* recall widener.

Purpose-built neural network for JARVIS: a bag-of-hashed-ngrams MLP (fastText-
style features, Joulin et al. 2016) that maps free-phrased requests onto the
playbook catalog. Position in the architecture is deliberately narrow:

- it runs ONLY after the deterministic engine missed AND the LLM planner is
  unavailable or honestly unexpressible — it never intercepts the engine;
- its output is a SUGGESTION (an engine-legal intent string the user types
  themselves) or disclosure candidates ("did you mean") — it never executes,
  never consents, never widens authority (ADR-0012 invariant);
- any reconstruction MUST re-pass the real playbook matchers; anything the
  matchers refuse is abstained from;
- it is a model: ``--no-ai`` / ``JARVIS_NO_AI=1`` switches it off (ADR-0014 D7).

Weights ship as package data (``model.json``), trained by the seeded,
deterministic trainer in ``training/train_intent.py`` — stdlib-only inference
(ADR-0005), no runtime dependency on any ML framework.
"""

from __future__ import annotations

import json
import math
import zlib
from functools import lru_cache
from importlib import resources

MODEL_FORMAT = "jarvis-intent/1"
UNKNOWN_LABEL = "unknown"
PROPOSE_THRESHOLD = 0.85
FEATURE_DIM = 256
HIDDEN = 48
MAX_TEXT_CHARS = 200

# -- vectorization (imported by the trainer: single source of truth) ---------
_STOP_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "app",
        "application",
        "about",
        "add",
        "all",
        "at",
        "automatically",
        "available",
        "anymore",
        "active",
        "boot",
        "box",
        "bring",
        "can",
        "could",
        "cache",
        "change",
        "for",
        "from",
        "details",
        "delete",
        "disable",
        "do",
        "does",
        "done",
        "everything",
        "enable",
        "find",
        "fire",
        "fix",
        "get",
        "give",
        "good",
        "gone",
        "have",
        "help",
        "how",
        "here",
        "i",
        "in",
        "index",
        "info",
        "install",
        "into",
        "is",
        "it",
        "its",
        "just",
        "lists",
        "list",
        "look",
        "looking",
        "machine",
        "make",
        "me",
        "my",
        "need",
        "nice",
        "now",
        "of",
        "off",
        "on",
        "open",
        "or",
        "out",
        "package",
        "packages",
        "please",
        "put",
        "remove",
        "repositories",
        "repository",
        "rid",
        "running",
        "run",
        "search",
        "service",
        "services",
        "set",
        "show",
        "some",
        "start",
        "startup",
        "status",
        "stop",
        "stuff",
        "sync",
        "system",
        "take",
        "tell",
        "that",
        "the",
        "thing",
        "this",
        "there",
        "to",
        "up",
        "update",
        "upgrade",
        "unit",
        "use",
        "want",
        "what",
        "when",
        "why",
        "with",
        "you",
        "your",
    }
)


def _normalize(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text.lower())
    return " ".join(cleaned.split())[:MAX_TEXT_CHARS]


def _features(text: str) -> dict[int, float]:
    """Hashed word unigrams+bigrams and character trigrams → signed buckets."""
    normalized = _normalize(text)
    grams: list[str] = []
    tokens = normalized.split()
    grams.extend(tokens)
    grams.extend(f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1))
    padded = f"\x02{normalized}\x03"
    grams.extend(padded[i : i + 3] for i in range(max(len(padded) - 2, 0)))
    buckets: dict[int, float] = {}
    for gram in grams:
        h = zlib.crc32(gram.encode("utf-8"))
        index = h % FEATURE_DIM
        sign = 1.0 if (h >> 31) & 1 == 0 else -1.0
        buckets[index] = buckets.get(index, 0.0) + sign
    norm = math.sqrt(sum(value * value for value in buckets.values()))
    if norm > 0.0:
        buckets = {index: value / norm for index, value in buckets.items()}
    return buckets


# -- model -------------------------------------------------------------------
class IntentModel:
    """Dense 48-unit ReLU MLP over the hashed features; pure-stdlib inference."""

    def __init__(
        self,
        labels: list[str],
        w1: list[list[float]],
        b1: list[float],
        w2: list[list[float]],
        b2: list[float],
    ) -> None:
        self.labels = labels
        self.w1 = w1
        self.b1 = b1
        self.w2 = w2
        self.b2 = b2
        self.n_classes = len(labels)

    def scores(self, buckets: dict[int, float]) -> list[float]:
        acc = list(self.b1)
        for index, value in buckets.items():
            row = self.w1[index]
            for j in range(HIDDEN):
                acc[j] += value * row[j]
        hidden = [value if value > 0.0 else 0.0 for value in acc]
        logits = [
            self.b2[k] + sum(hidden[j] * self.w2[j][k] for j in range(HIDDEN))
            for k in range(self.n_classes)
        ]
        peak = max(logits)
        exps = [math.exp(value - peak) for value in logits]
        total = sum(exps)
        return [value / total for value in exps]


@lru_cache(maxsize=1)
def load_model() -> IntentModel | None:
    """Load the shipped weights; None (honest fallback) if unavailable."""
    try:
        raw = (resources.files("jarvis.intent") / "model.json").read_text(encoding="utf-8")
        document = json.loads(raw)
        if document.get("format") != MODEL_FORMAT:
            return None
        return IntentModel(
            labels=[str(label) for label in document["labels"]],
            w1=[[float(v) for v in row] for row in document["w1"]],
            b1=[float(v) for v in document["b1"]],
            w2=[[float(v) for v in row] for row in document["w2"]],
            b2=[float(v) for v in document["b2"]],
        )
    except (OSError, KeyError, TypeError, ValueError):
        return None


def classify(text: str) -> dict[str, float] | None:
    """Full label→probability distribution, or None when no model is available."""
    model = load_model()
    if model is None:
        return None
    probs = model.scores(_features(text))
    return dict(zip(model.labels, probs, strict=True))


def rank_intents(text: str, k: int = 3) -> list[tuple[str, float]]:
    """Top-k playbook labels (unknown excluded) for unknown-request disclosure."""
    distribution = classify(text)
    if distribution is None:
        return []
    pairs = [
        (label, prob)
        for label, prob in distribution.items()
        if label != UNKNOWN_LABEL and prob > 0.0
    ]
    pairs.sort(key=lambda pair: pair[1], reverse=True)
    return pairs[:k]


# -- slot reconstruction (proposals only; the real matchers dispose) ----------
def _slot_tokens(text: str, limit: int) -> list[str]:
    tokens = []
    for raw in _normalize(text).split():
        if raw in _STOP_TOKENS or len(raw) < 2 or len(raw) > 30:
            continue
        if not all(ch.isalnum() or ch in "+._-" for ch in raw):
            continue
        tokens.append(raw)
        if len(tokens) >= limit:
            break
    return tokens


def suggest_intent(text: str) -> str | None:
    """A confident, engine-legal reconstruction — or None (abstain).

    The classifier picks the family; a deterministic extractor fills the slot;
    the REAL playbook matcher has the final word. No matcher acceptance, no
    suggestion. This is proposals-not-authority, enforced structurally.
    """
    from jarvis.planner.playbooks import match_intent  # kernel owns the vocabulary

    distribution = classify(text)
    if distribution is None:
        return None
    top = max(distribution.items(), key=lambda pair: pair[1])
    label, prob = top
    if label == UNKNOWN_LABEL or prob < PROPOSE_THRESHOLD:
        return None

    candidates: list[str] = []
    if label == "pkg.install":
        slots = _slot_tokens(text, 3)
        if slots:
            candidates.append("install " + " ".join(slots))
    elif label == "pkg.remove":
        slots = _slot_tokens(text, 3)
        if slots:
            candidates.append("remove " + " ".join(slots))
    elif label == "pkg.search":
        slots = _slot_tokens(text, 3)
        if slots:
            candidates.append("search " + " ".join(slots))
    elif label == "pkg.info":
        slots = _slot_tokens(text, 1)
        if slots:
            candidates.append(f"info {slots[0]}")
    elif label in {"svc.start", "svc.enable", "svc.status", "gui.launch"}:
        slots = _slot_tokens(text, 1)
        if slots:
            verb = {
                "svc.start": "start",
                "svc.enable": "enable",
                "svc.status": "status of",
                "gui.launch": "open",
            }[label]
            candidates.append(f"{verb} {slots[0]}")
    elif label == "pkg.cache.refresh":
        candidates.append("update the package cache")
    elif label == "pkg.upgrade":
        candidates.append("upgrade the system")
    elif label == "sys.info":
        candidates.append("system info")
    # file.append and anything else: deliberately NO extractor (paths/text).

    for candidate in candidates:
        try:
            if match_intent(candidate) is not None:
                return candidate
        except Exception:
            continue
    return None
