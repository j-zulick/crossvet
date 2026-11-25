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
SLOTS = ("quick", "balanced", "strong", "fresh", "long", "reviewer", "vision", "audio")
SLOT_HELP = {
    "quick": "short lookups, summaries, extraction: the cheapest capable model",
    "balanced": "everyday writing and general questions",
    "strong": "code, analysis and anything hard",
    "fresh": "questions about what is happening now: a model with live search or real-time data",
    "long": "very long inputs: the largest context window",
    "reviewer": "second opinions: a model from a different vendor than your main one",
    "vision": "requests with images or screenshots: a model that reads images",
    "audio": "requests with audio: a model that takes audio (or set [inputs] transcribe)",
}
INPUT_TYPES = ("image", "audio", "pdf")
DEFAULT_INPUT_SLOTS = {"image": "vision", "audio": "audio", "pdf": "long"}
GOALS = ("auto", "best", "cheapest", "fastest")
LOCAL_PROVIDERS = ("ollama", "local")

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
    takes: tuple[str, ...] = ()  # input types beyond text ("image", "audio", "pdf"); empty = not stated


@dataclass
class Config:
    """The whole configuration."""

    slots: dict[str, list[str]] = field(default_factory=dict)
    routes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ROUTES))
    models: dict[str, ModelInfo] = field(default_factory=dict)
    max_usd_per_day: float = 0.0   # 0 = no cap
    max_usd_per_call: float = 0.0  # 0 = no cap; estimated before the call from the input size
    max_output_tokens: int = 4000
    timeout_seconds: float = 120.0      # one model call, start to finish
    max_request_bytes: int = 2_000_000  # the largest request the server accepts
    memory_chars: int = 6000       # how much shared memory is put in front of a model
    history_turns: int = 12        # how many earlier turns of the thread a model sees
    db_path: str = ""
    record_sink: str = "auto"      # auto | langfuse | jsonl | off (record.py)
    record_content: str = "full"   # full | metadata: leave request and answer text out of the sinks
    record_jsonl: str = ""         # path of a JSON-lines copy, "" = none
    router: str = "rules"          # rules | jev | openrouter-auto | openrouter-auto-code | jev-router (router.py)
    jev_model: str = ""            # "" = ~typesafe/jev-latest
    jev_min_confidence: float = 0.5
    classify_general: str = ""     # "" = off; "quick" = the first quick-slot model, or provider:model, names the kind of a "general" request
    check: str = ""                # "" = code checks only; "jev" = also ask Jev whether the answer addresses the request
    check_threshold: float = 0.2   # with check = "jev": below this probability, try the next model
    explore: float = 0.0           # share of routed requests where the second choice answers first (tuning.py)
    min_ratings: int = 3           # `tune` marks a proposal resting on fewer ratings per model as weak
    keep_days: float = 0.0         # [retention]: turns older than this are what `prune` removes; 0 = keep everything
    kinds: dict[str, list[str]] = field(default_factory=dict)  # [kinds]: models to try first for one kind of task
    input_slots: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_INPUT_SLOTS))  # [inputs]: input type -> slot
    transcribe: str = ""           # [inputs]: provider:model that turns audio into text before routing ("" = send the audio)
    goal: str = "auto"             # [router]: auto | best | cheapest | fastest
    cascade: bool = False          # [router]: start from the quick slot and climb only when an answer fails a check
    quick_history_turns: int = 4   # [memory]: earlier turns sent to a quick-slot model (others get history_turns)
    private_models: list[str] = field(default_factory=list)  # [privacy] models: where private requests may go
    private_auto: bool = True      # [privacy] auto: requests that look private (keys, ID numbers, "confidential") stay local
    local_first: bool = False      # [router]: quick-slot requests try local models first, then the cloud
    learned_min_confidence: float = 0.6  # [router] with use = "learned": below this, the rules decide
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

    def local_models(self) -> list[str]:
        """Where private requests may go: [privacy] models, else every configured model on your own machine."""
        if self.private_models:
            return list(self.private_models)
        return [m for m in self.all_models() if m.split(":", 1)[0] in LOCAL_PROVIDERS]

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
        name: ModelInfo(int(v.get("context", 0) or 0), _price(v.get("input")), _price(v.get("output")),
                        _takes(v.get("takes", ()), name, source))
        for name, v in (data.get("models") or {}).items()
    }
    from crossvet.chat.classify import KINDS

    kinds = {str(k): [str(m) for m in v] for k, v in (data.get("kinds") or {}).items()}
    if sorted(set(kinds) - set(KINDS)):
        raise ValueError(f"[kinds] in {source or 'config'}: unknown kind(s) {sorted(set(kinds) - set(KINDS))}; kinds are {', '.join(KINDS)}")
    inputs = data.get("inputs") or {}
    input_slots = {**DEFAULT_INPUT_SLOTS, **{k: str(v) for k, v in inputs.items() if k in INPUT_TYPES}}
    if any(v not in SLOTS for v in input_slots.values()):
        raise ValueError(f"[inputs] in {source or 'config'}: each input type names a slot ({', '.join(SLOTS)})")
    privacy = data.get("privacy") or {}
    limits = data.get("limits") or {}
    memory = data.get("memory") or {}
    record = data.get("record") or {}
    sink, content = str(record.get("sink", "auto") or "auto"), str(record.get("content", "full") or "full")
    if sink not in ("auto", "langfuse", "jsonl", "off") or content not in ("full", "metadata"):
        raise ValueError(f"[record] in {source or 'config'}: sink is auto, langfuse, jsonl or off; content is full or metadata")
    router = data.get("router") or {}
    use, check = str(router.get("use", "rules") or "rules"), str(router.get("check", "") or "")
    if use not in ("rules", "jev", "openrouter-auto", "openrouter-auto-code", "jev-router", "learned") or check not in ("", "jev"):
        raise ValueError(f"[router] in {source or 'config'}: use is rules, jev, learned, openrouter-auto, openrouter-auto-code"
                         " or jev-router; check is empty or jev")
    goal = str(router.get("goal", "auto") or "auto")
    if goal not in GOALS:
        raise ValueError(f"[router] goal in {source or 'config'} is one of {', '.join(GOALS)}")
    return Config(
        slots=slots,
        routes=routes,
        models=models,
        max_usd_per_day=float(limits.get("max_usd_per_day", 0) or 0),
        max_usd_per_call=float(limits.get("max_usd_per_call", 0) or 0),
        max_output_tokens=int(limits.get("max_output_tokens", 4000) or 4000),
        timeout_seconds=_positive(limits.get("timeout_seconds", 120), "timeout_seconds", source),
        max_request_bytes=int(_positive(limits.get("max_request_bytes", 2_000_000), "max_request_bytes", source)),
        memory_chars=int(memory.get("chars", 6000) or 0),
        history_turns=int(memory.get("history_turns", 12) or 0),
        db_path=str(memory.get("db", "") or ""),
        record_sink=sink,
        record_content=content,
        record_jsonl=str(record.get("jsonl", "") or ""),
        router=use,
        jev_model=str(router.get("jev_model", "") or ""),
        jev_min_confidence=float(router.get("jev_min_confidence", 0.5)),
        classify_general=_classifier(router.get("classify_general", ""), source),
        check=check,
        check_threshold=float(router.get("check_threshold", 0.2)),
        explore=_share((data.get("tuning") or {}).get("explore", 0.0), source),
        min_ratings=int((data.get("tuning") or {}).get("min_ratings", 3)),
        keep_days=_not_negative((data.get("retention") or {}).get("keep_days", 0), "keep_days", source),
        kinds=kinds,
        input_slots=input_slots,
        transcribe=str(inputs.get("transcribe", "") or ""),
        goal=goal,
        cascade=bool(router.get("cascade", False)),
        local_first=bool(router.get("local_first", False)),
        quick_history_turns=int(memory.get("quick_history_turns", 4) or 0),
        private_models=[str(m) for m in privacy.get("models", [])],
        private_auto=bool(privacy.get("auto", True)),
        learned_min_confidence=float(router.get("learned_min_confidence", 0.6)),
        source=source,
    )


def _takes(value: object, model: str, source: str) -> tuple[str, ...]:
    takes = tuple(str(t) for t in (value or ()))
    if any(t not in INPUT_TYPES for t in takes):
        raise ValueError(f"[models.\"{model}\"] takes in {source or 'config'} lists input types from {', '.join(INPUT_TYPES)}")
    return takes


def _classifier(value: object, source: str) -> str:
    if value is True:
        return "quick"
    name = str(value or "").strip()
    if name and name != "quick" and ":" not in name:
        raise ValueError(f'[router] classify_general in {source or "config"} is "", "quick" or a provider:model name')
    return name


def _not_negative(value: object, name: str, source: str) -> float:
    number = float(value or 0)
    if number < 0:
        raise ValueError(f"[retention] {name} in {source or 'config'} must be 0 (keep everything) or more")
    return number


def _positive(value: object, name: str, source: str) -> float:
    number = float(value)  # type: ignore[arg-type]
    if number <= 0:
        raise ValueError(f"[limits] {name} in {source or 'config'} must be more than 0")
    return number


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
