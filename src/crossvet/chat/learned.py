"""A router learned from your own rated answers, checked against the rules before it is used.

Each rated answer becomes one example: the request's words, and the slot that served you well.
An answer rated good teaches its own slot. One rated bad, or asked again one slot up, teaches
the next slot up the quick → balanced → strong ladder (a bad answer from the strongest slot
teaches nothing, since nothing is stronger).

The model is multinomial naive Bayes over words, written here in plain Python: small, quick, and
easy to inspect. ``train`` holds out the newest 20% of examples, scores the learned router and
the rules on them, and saves the model with both scores. ``[router] use = "learned"`` uses it
only above ``learned_min_confidence``; anything else falls back to the rules.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from crossvet.chat.config import LADDER

if TYPE_CHECKING:
    from crossvet.chat.config import Config
    from crossvet.chat.memory import Memory

SCHEMA = "CREATE TABLE IF NOT EXISTS learned_router (id INTEGER PRIMARY KEY, ts REAL NOT NULL, model TEXT NOT NULL)"
MIN_EXAMPLES = 30
HELD_OUT = 0.2


def words(text: str) -> list[str]:
    """Return the lower-case words of ``text`` (letters, digits and a few code marks), at most 400."""
    return re.findall(r"[a-z0-9_#+]+|[{}();=<>]", (text or "").lower())[:400]


@dataclass
class Example:
    """One rated request and the slot that served it well."""

    ts: float
    text: str
    slot: str


@dataclass
class Model:
    """Naive Bayes counts per slot, and how it scored against the rules on held-out examples."""

    priors: dict[str, int] = field(default_factory=dict)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    totals: dict[str, int] = field(default_factory=dict)
    vocabulary: int = 0
    examples: int = 0
    held_out: int = 0
    accuracy: float | None = None        # the learned router on held-out examples
    rules_accuracy: float | None = None  # the rules on the same examples
    trained_at: float = 0.0

    def predict(self, text: str) -> tuple[str, float]:
        """Return the most likely slot for ``text`` and its probability."""
        if not self.priors:
            return "balanced", 0.0
        total = sum(self.priors.values())
        logs = {}
        for slot, n in self.priors.items():
            score = math.log(n / total)
            counts, size = self.counts.get(slot, {}), self.totals.get(slot, 0) + self.vocabulary
            for word in words(text):
                score += math.log((counts.get(word, 0) + 1) / size)
            logs[slot] = score
        top = max(logs.values())
        shares = {slot: math.exp(v - top) for slot, v in logs.items()}
        best = max(shares, key=shares.get)  # type: ignore[arg-type]
        return best, shares[best] / sum(shares.values())

    def to_json(self) -> str:
        """Return the model as JSON."""
        return json.dumps(self.__dict__)


def fit(examples: list[Example]) -> Model:
    """Count words per slot over ``examples``."""
    model = Model(examples=len(examples), trained_at=time.time())
    vocabulary: set[str] = set()
    for example in examples:
        model.priors[example.slot] = model.priors.get(example.slot, 0) + 1
        counts = Counter(words(example.text))
        slot_counts = model.counts.setdefault(example.slot, {})
        for word, n in counts.items():
            slot_counts[word] = slot_counts.get(word, 0) + n
            vocabulary.add(word)
        model.totals[example.slot] = model.totals.get(example.slot, 0) + sum(counts.values())
    model.vocabulary = len(vocabulary)
    return model


def _up(slot: str) -> str | None:
    return LADDER[LADDER.index(slot) + 1] if slot in LADDER[:-1] else None


def examples(memory: Memory) -> list[Example]:
    """Turn rated answers in the store into examples, oldest first."""
    signals: dict[int, list[tuple[str, float]]] = {}
    for rating in memory.ratings():
        signals.setdefault(rating.turn_id, []).append((rating.name, rating.value))
    out = []
    for answer in memory.answers():
        slot = answer.meta.get("slot")
        names = signals.get(answer.id)
        if slot not in LADDER or not names or answer.meta.get("private"):
            continue
        feedback = [v for n, v in names if n == "user-feedback"]
        if feedback:
            label = slot if feedback[-1] >= 0.5 else _up(slot)
        elif any(n == "retried" for n, _ in names):
            label = _up(slot)
        else:
            continue
        question = memory.question_for(answer)
        if label and question and question.content.strip():
            out.append(Example(answer.ts, question.content, label))
    return sorted(out, key=lambda e: e.ts)


def train(memory: Memory, config: Config, minimum: int = MIN_EXAMPLES) -> Model:
    """Train on all but the newest 20% of examples, score both routers on those, then refit on everything and save.

    Raise ``ValueError`` when there are fewer than ``minimum`` examples.
    """
    from crossvet.chat.routing import route

    found = examples(memory)
    if len(found) < minimum:
        raise ValueError(f"{len(found)} rated answer(s) can teach the router; at least {minimum} are needed "
                         "(rate answers with /good and /bad)")
    cut = max(1, int(len(found) * (1 - HELD_OUT)))
    train_set, test_set = found[:cut], found[cut:]
    trial = fit(train_set)
    learned_hits = sum(trial.predict(e.text)[0] == e.slot for e in test_set)
    rules_hits = sum(route(e.text, config).slot == e.slot for e in test_set)
    model = fit(found)
    model.held_out = len(test_set)
    model.accuracy = learned_hits / len(test_set) if test_set else None
    model.rules_accuracy = rules_hits / len(test_set) if test_set else None
    memory.db.execute(SCHEMA)
    memory.db.execute("INSERT INTO learned_router(ts, model) VALUES (?, ?)", (model.trained_at, model.to_json()))
    memory.db.commit()
    return model


def load(memory: Memory) -> Model | None:
    """Return the newest saved model, or ``None`` when none has been trained."""
    memory.db.execute(SCHEMA)
    row = memory.db.execute("SELECT model FROM learned_router ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    data: dict[str, Any] = json.loads(row[0])
    return Model(**data)


__all__ = ["Example", "MIN_EXAMPLES", "Model", "examples", "fit", "load", "train", "words"]
