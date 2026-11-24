"""Settings: which models fill which slot, which kind of task goes to which slot, and the limits.

Everything lives in one TOML file (``crossvet-chat.toml`` in the working folder, else
``~/.config/crossvet/chat.toml``, else the path in ``CROSSVET_CHAT_CONFIG``). API keys are never in it:
they are read from the environment (see ``.env.example``).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# A slot is an ordered list of models. The first is tried first; the rest are used, in order,
# when the one before fails a check (see guard.py).
SLOTS = ("quick", "balanced", "strong", "fresh", "long", "reviewer")
SLOT_HELP = {
    "quick": "short lookups, summaries, extraction: the cheapest capable model",
    "balanced": "everyday writing and general questions",
    "strong": "code, analysis and anything hard",
    "fresh": "questions about what is happening now: a model with live search or real-time data",
    "long": "very long inputs: the largest context window",
    "reviewer": "second opinions: a model from a different vendor than your main one",
}

# Which slot each kind of task starts in (classify.py names the kinds).
DEFAULT_ROUTES = {
    "quick": "quick",
    "summarize": "quick",
    "extract": "quick",
    "translate": "quick",
    "writing": "balanced",
    "general": "balanced",
    "code": "strong",
    "reasoning": "strong",
    "review": "reviewer",
    "fresh": "fresh",
}
# When a task is hard, or a slot is empty, move up this ladder.
LADDER = ("quick", "balanced", "strong")


@dataclass
class ModelInfo:
    """What the config says about one model. Prices are USD per million tokens."""

    context: int = 0
    input: float | None = None
    output: float | None = None


@dataclass
class Config:
    """The whole configuration."""

    slots: dict[str, list[str]] = field(default_factory=dict)
    routes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ROUTES))
    models: dict[str, ModelInfo] = field(default_factory=dict)
    max_usd_per_day: float = 0.0   # 0 = no cap
    max_usd_per_call: float = 0.0  # 0 = no cap; estimated before the call from the input size
    max_output_tokens: int = 4000
    memory_chars: int = 6000       # how much shared memory is put in front of a model
    history_turns: int = 12        # how many earlier turns of the thread a model sees
    db_path: str = ""
    record_sink: str = "auto"      # auto | langfuse | jsonl | off (record.py)
    record_content: str = "full"   # full | metadata: leave request and answer text out of the sinks
    record_jsonl: str = ""         # path of a JSON-lines copy, "" = none
    router: str = "rules"          # rules | jev | openrouter-auto | openrouter-auto-code | jev-router (router.py)
    jev_model: str = ""            # "" = ~typesafe/jev-latest
    jev_min_confidence: float = 0.5
    check: str = ""                # "" = code checks only; "jev" = also ask Jev whether the answer addresses the request
    check_threshold: float = 0.2   # with check = "jev": below this probability, try the next model
    explore: float = 0.0           # share of routed requests where the second choice answers first (tuning.py)
    min_ratings: int = 3           # `tune` marks a proposal resting on fewer ratings per model as weak
    source: str = ""               # the file this was read from, "" for built-in defaults

    def slot(self, name: str) -> list[str]:
        """Models in a slot, falling back up the ladder and then to any configured model."""
        if self.slots.get(name):
            return list(self.slots[name])
        if name in LADDER:
            for other in LADDER[LADDER.index(name) + 1:] + LADDER[: LADDER.index(name)][::-1]:
                if self.slots.get(other):
                    return list(self.slots[other])
        for other in ("balanced", "strong", "quick"):
            if self.slots.get(other):
                return list(self.slots[other])
        return []

    def info(self, model: str) -> ModelInfo:
        """Context window and prices for a model, or empty values when the config has none."""
        return self.models.get(model, ModelInfo())

    def all_models(self) -> list[str]:
        """Every model named in any slot, in slot order, without repeats."""
        seen: list[str] = []
        for name in SLOTS:
            for model in self.slots.get(name, []):
                if model not in seen:
                    seen.append(model)
        return seen


def config_path() -> Path | None:
    """Return the config file in use, or ``None`` when there is none."""
    explicit = os.environ.get("CROSSVET_CHAT_CONFIG")
    candidates = [Path(explicit)] if explicit else [Path("crossvet-chat.toml"), Path.home() / ".config" / "crossvet" / "chat.toml"]
    return next((p for p in candidates if p.is_file()), None)


def default_db_path() -> str:
    """Where shared memory is stored unless the config or ``CROSSVET_CHAT_DB`` says otherwise."""
    return os.environ.get("CROSSVET_CHAT_DB") or str(Path.home() / ".local" / "share" / "crossvet" / "chat.db")


def parse(data: dict, source: str = "") -> Config:
    """Build a ``Config`` from parsed TOML, rejecting unknown slots and routes to unknown slots."""
    slots = {k: [str(m) for m in v] for k, v in (data.get("slots") or {}).items()}
    unknown = sorted(set(slots) - set(SLOTS))
    if unknown:
        raise ValueError(f"unknown slot(s) {unknown} in {source or 'config'}; slots are {', '.join(SLOTS)}")
    routes = {**DEFAULT_ROUTES, **{str(k): str(v) for k, v in (data.get("routes") or {}).items()}}
    bad = sorted(k for k, v in routes.items() if v not in SLOTS)
    if bad:
        raise ValueError(f"route(s) {bad} in {source or 'config'} point at a slot that does not exist")
    models = {
        name: ModelInfo(int(v.get("context", 0) or 0), _price(v.get("input")), _price(v.get("output")))
        for name, v in (data.get("models") or {}).items()
    }
    limits = data.get("limits") or {}
    memory = data.get("memory") or {}
    record = data.get("record") or {}
    sink, content = str(record.get("sink", "auto") or "auto"), str(record.get("content", "full") or "full")
    if sink not in ("auto", "langfuse", "jsonl", "off") or content not in ("full", "metadata"):
        raise ValueError(f"[record] in {source or 'config'}: sink is auto, langfuse, jsonl or off; content is full or metadata")
    router = data.get("router") or {}
    use, check = str(router.get("use", "rules") or "rules"), str(router.get("check", "") or "")
    if use not in ("rules", "jev", "openrouter-auto", "openrouter-auto-code", "jev-router") or check not in ("", "jev"):
        raise ValueError(f"[router] in {source or 'config'}: use is rules, jev, openrouter-auto, openrouter-auto-code or jev-router;"
                         " check is empty or jev")
    return Config(
        slots=slots,
        routes=routes,
        models=models,
        max_usd_per_day=float(limits.get("max_usd_per_day", 0) or 0),
        max_usd_per_call=float(limits.get("max_usd_per_call", 0) or 0),
        max_output_tokens=int(limits.get("max_output_tokens", 4000) or 4000),
        memory_chars=int(memory.get("chars", 6000) or 0),
        history_turns=int(memory.get("history_turns", 12) or 0),
        db_path=str(memory.get("db", "") or ""),
        record_sink=sink,
        record_content=content,
        record_jsonl=str(record.get("jsonl", "") or ""),
        router=use,
        jev_model=str(router.get("jev_model", "") or ""),
        jev_min_confidence=float(router.get("jev_min_confidence", 0.5)),
        check=check,
        check_threshold=float(router.get("check_threshold", 0.2)),
        explore=_share((data.get("tuning") or {}).get("explore", 0.0), source),
        min_ratings=int((data.get("tuning") or {}).get("min_ratings", 3)),
        source=source,
    )


def _share(value: object, source: str) -> float:
    share = float(value or 0)  # type: ignore[arg-type]
    if not 0 <= share <= 0.5:
        raise ValueError(f"[tuning] explore in {source or 'config'} must be between 0 and 0.5")
    return share


def _price(value: object) -> float | None:
    return None if value in (None, "") else float(value)  # type: ignore[arg-type]


def load(path: str | Path | None = None) -> Config:
    """Read the config file, or return empty defaults when there is none."""
    found = Path(path) if path else config_path()
    if not found:
        return Config()
    with open(found, "rb") as handle:
        return parse(tomllib.load(handle), str(found))
