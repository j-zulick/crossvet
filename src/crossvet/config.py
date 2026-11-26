"""Settings: your default model, short names, the model menu, prices, limits, and the slots ``auto`` uses.

A request names its model (``anthropic:claude-opus-5-5``, or a short name such as ``opus``); a request
that names none goes to ``default_model``. Crossvet chooses a model only when the request asks it to,
by naming ``auto`` (or ``crossvet/strong``, ``crossvet/cheapest``...): see ``routing.py``.

Settings live in one TOML file: the path in ``CROSSVET_CONFIG``, else ``./crossvet.toml``, else
``~/.config/crossvet/crossvet.toml``. Without a file, the built-in table below is used for the
providers whose keys are set. API keys are never in the file: they come from the environment,
``./.env`` or ``~/.config/crossvet/.env``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from crossvet import providers

HOME = Path.home() / ".config" / "crossvet"

# Models this project has called live, with their short names and list prices in USD per million
# tokens (input, output), from the vendors' pricing pages on 2026-11-26. Prices are for prompts up
# to 100,000 tokens (Anthropic) and 272,000 tokens (OpenAI); longer prompts cost more.
KNOWN_DATE = "2026-11-26"
KNOWN: dict[str, tuple[float, float, tuple[str, ...]]] = {
    "anthropic:claude-opus-5-5": (4.0, 20.0, ("claude", "opus")),
    "anthropic:claude-sonnet-5-5": (2.0, 10.0, ("sonnet",)),
    "anthropic:claude-haiku-5-5": (0.10, 0.50, ("haiku",)),
    "openai:gpt-6.1-sol": (2.0, 10.0, ("gpt", "sol")),
    "openai:gpt-6.1-terra": (1.0, 5.0, ("terra",)),
    "openai:gpt-6-luna": (0.10, 0.50, ("luna",)),
}
# The built-in default: the first of these your keys can call.
DEFAULT_ORDER = ("anthropic:claude-sonnet-5-5", "openai:gpt-6.1-terra")
DEFAULT_ALIASES = ("", "default", "crossvet")
TOP_KEYS = {"default_model", "models", "names", "prices", "limits", "store", "slots", "routes", "router", "lab", "score"}
SLOTS = ("quick", "balanced", "strong", "long", "vision", "reviewer", "private")
GOALS = ("auto", "best", "cheapest", "fastest")
# Which slot each kind of task starts in (classify.py names the kinds).
DEFAULT_ROUTES = {"quick": "quick", "summarize": "quick", "extract": "quick", "translate": "quick", "writing": "balanced",
                  "general": "balanced", "fresh": "balanced", "code": "strong", "reasoning": "strong", "review": "reviewer"}
# The built-in slots: the first model in each list that your keys can call goes first.
DEFAULT_SLOTS = {
    "quick": ("anthropic:claude-haiku-5-5", "openai:gpt-6-luna"),
    "balanced": ("anthropic:claude-sonnet-5-5", "openai:gpt-6.1-terra"),
    "strong": ("anthropic:claude-opus-5-5", "openai:gpt-6.1-sol"),
    "long": ("anthropic:claude-sonnet-5-5", "openai:gpt-6.1-sol"),
    "vision": ("anthropic:claude-opus-5-5", "openai:gpt-6.1-sol"),
    "reviewer": ("openai:gpt-6.1-sol", "anthropic:claude-opus-5-5"),
}
ROUTER_KEYS = {"goal", "escalate", "max_steps", "private_auto", "long_chars"}
SCORE_KEYS = {"enabled", "sample", "judge", "max_usd_per_day", "apps", "shadow", "shadow_sample", "shadow_model"}
LIMIT_KEYS = {"max_usd_per_day", "max_usd_per_call", "max_output_tokens", "timeout_seconds", "max_request_bytes"}


@dataclass
class Config:
    """The whole configuration."""

    default_model: str = ""
    models: list[str] = field(default_factory=list)                    # the model menu (/v1/models, list_models)
    names: dict[str, str] = field(default_factory=dict)                # short name -> provider:model
    prices: dict[str, tuple[float, float]] = field(default_factory=dict)  # USD per million tokens (input, output)
    max_usd_per_day: float = 5.0       # 0 = no cap
    max_usd_per_call: float = 0.50     # 0 = no cap; a worst-case estimate made before the call
    max_output_tokens: int = 4000
    timeout_seconds: float = 120.0     # one model call, start to finish
    max_request_bytes: int = 2_000_000  # the largest request the server accepts
    store: str = ""                    # "" = CROSSVET_DB, else ~/.local/share/crossvet/chat.db
    lab: str = ""                      # "" = CROSSVET_LAB_DB, else lab.db next to the log
    slots: dict[str, list[str]] = field(default_factory=dict)  # [slots]: slot -> models, first callable goes first
    routes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ROUTES))  # [routes]: kind of task -> slot
    goal: str = "auto"                 # [router] goal: auto (slot order) | best | cheapest | fastest
    escalate: bool = True              # [router] escalate: try the next model after an error, an empty answer or bad JSON
    max_steps: int = 2                 # [router] max_steps: extra models tried after the first
    private_auto: bool = True          # [router] private_auto: requests that look private only go to the private slot
    long_chars: int = 60_000           # [router] long_chars: a request this long goes to the long slot
    score_enabled: bool = False        # [score] enabled: judge a sample of answers (they go to a second vendor)
    score_sample: float = 0.1          # [score] sample: share of answers judged
    score_judge: str = ""              # [score] judge: "" = the strongest model from another vendor than the answer's
    score_max_usd_per_day: float = 1.0  # [score] max_usd_per_day: the judge's and shadow answers' own daily cap
    score_apps: list[str] = field(default_factory=list)  # [score] apps: only answers from these apps; empty = all
    score_shadow: bool = False         # [score] shadow: a cheaper model answers a sample of judged questions
    score_shadow_sample: float = 0.05  # [score] shadow_sample
    score_shadow_model: str = ""       # [score] shadow_model: "" = the cheapest model in the quick slot
    source: str = ""                   # the file this was read from; "" for the built-in table

    def resolve(self, name: str | None) -> str:
        """Return the ``provider:model`` a name means: the default, a short name, or a full name."""
        name = (name or "").strip()
        if name.lower() in DEFAULT_ALIASES:
            if not self.default_model:
                raise ValueError("no model was named and there is no default_model: name one (`crossvet models` "
                                 "lists them) or set default_model in crossvet.toml")
            return self.resolve(self.default_model)
        if name in self.names:
            return self.names[name]
        if ":" in name:
            providers.split(name)  # raises for an unknown provider
            return name
        known = ", ".join(sorted(self.names)) or "none set"
        raise ValueError(f"unknown model {name!r}: write provider:model (for example openai:gpt-6.1-sol) "
                         f"or a short name ({known})")

    def price(self, model: str) -> tuple[float, float] | None:
        """USD per million tokens (input, output) for a model, or ``None`` when no price is known."""
        if model in self.prices:
            return self.prices[model]
        known = KNOWN.get(model)
        return (known[0], known[1]) if known else None

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        """List-price cost of a call, or ``None`` when the model has no price."""
        price = self.price(model)
        return None if price is None else (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000

    def menu(self) -> list[str]:
        """Every model to offer in a menu: the default first, then the list, then short-name targets."""
        seen: list[str] = []
        try:
            first = [self.resolve(None)]
        except ValueError:
            first = []
        for model in [*first, *self.models, *self.names.values()]:
            if model not in seen:
                seen.append(model)
        return seen

    def slot_models(self, slot: str) -> list[str]:
        """Models in a slot, in order; an empty slot falls back to the next one up (quick -> balanced -> strong)."""
        if self.slots.get(slot):
            return list(self.slots[slot])
        if slot == "private":
            return []  # never falls back: private requests stay where you said they may go
        for other in ("balanced", "strong", "quick"):
            if self.slots.get(other):
                return list(self.slots[other])
        return [m for m in self.menu()]

    def lab_path(self, store: str = "") -> str:
        """Where decisions, ratings, notes, reviews and scores are kept: next to the log in use, unless set."""
        explicit = os.environ.get("CROSSVET_LAB_DB") or self.lab
        if explicit:
            return explicit
        store = store or self.store_path()
        return ":memory:" if store == ":memory:" else str(Path(store).with_name("lab.db"))

    def store_path(self) -> str:
        """Where the local log of turns is kept."""
        return os.environ.get("CROSSVET_DB") or self.store or str(Path.home() / ".local" / "share" / "crossvet" / "chat.db")


def callable_now(model: str) -> bool:
    """Whether a model's provider has its key (or needs none)."""
    try:
        return providers.available(providers.split(model)[0])
    except providers.ProviderError:
        return False


def builtin() -> Config:
    """Return the settings used without a file: the known models your keys can call."""
    usable = [m for m in KNOWN if callable_now(m)]
    names = {short: m for m in usable for short in KNOWN[m][2]}
    default = next((m for m in DEFAULT_ORDER if m in usable), usable[0] if usable else "")
    slots = {slot: [m for m in models if m in usable] for slot, models in DEFAULT_SLOTS.items()}
    return Config(default_model=default, models=usable, names=names, slots={k: v for k, v in slots.items() if v})


def config_path() -> Path | None:
    """Return the settings file in use, or ``None`` when there is none."""
    explicit = os.environ.get("CROSSVET_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    return next((p for p in (Path("crossvet.toml"), HOME / "crossvet.toml") if p.is_file()), None)


def old_config() -> Path | None:
    """Return a Crossvet 1.x settings file, if one is lying around (2.0 does not read it)."""
    return next((p for p in (Path("crossvet-chat.toml"), HOME / "chat.toml") if p.is_file()), None)


def _number(value: object, name: str, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} in {source} must be a number of 0 or more")
    return float(value)


def parse(data: dict, source: str = "settings") -> Config:
    """Build a ``Config`` from parsed TOML; reject unknown keys and names that point nowhere."""
    unknown = set(data) - TOP_KEYS
    if unknown:
        raise ValueError(f"unknown setting(s) in {source}: {', '.join(sorted(unknown))}")
    limits = data.get("limits") or {}
    if set(limits) - LIMIT_KEYS:
        raise ValueError(f"unknown [limits] setting(s) in {source}: {', '.join(sorted(set(limits) - LIMIT_KEYS))}")
    names = {str(k): str(v) for k, v in (data.get("names") or {}).items()}
    models = [str(m) for m in data.get("models") or []]
    for model in [*names.values(), *models]:
        providers.split(model)
    prices = {}
    for model, value in (data.get("prices") or {}).items():
        prices[str(model)] = (_number(value.get("input"), f"prices.{model}.input", source),
                              _number(value.get("output"), f"prices.{model}.output", source))
    from crossvet.classify import KINDS

    slots: dict[str, list[str]] = {}
    for slot, value in (data.get("slots") or {}).items():
        if slot not in SLOTS:
            raise ValueError(f"unknown slot {slot!r} in {source}: the slots are {', '.join(SLOTS)}")
        listed = [value] if isinstance(value, str) else [str(v) for v in value or []]
        for model in listed:
            providers.split(model)
        slots[slot] = listed
    routes = dict(DEFAULT_ROUTES)
    for kind, slot in (data.get("routes") or {}).items():
        if kind not in KINDS or slot not in SLOTS:
            raise ValueError(f"[routes] {kind} = {slot!r} in {source}: kinds are {', '.join(KINDS)}; slots are {', '.join(SLOTS)}")
        routes[kind] = str(slot)
    router = data.get("router") or {}
    if set(router) - ROUTER_KEYS:
        raise ValueError(f"unknown [router] setting(s) in {source}: {', '.join(sorted(set(router) - ROUTER_KEYS))}")
    if router.get("goal", "auto") not in GOALS:
        raise ValueError(f"[router] goal in {source} must be one of {', '.join(GOALS)}")
    score = data.get("score") or {}
    if set(score) - SCORE_KEYS:
        raise ValueError(f"unknown [score] setting(s) in {source}: {', '.join(sorted(set(score) - SCORE_KEYS))}")
    for key in ("sample", "shadow_sample"):
        if key in score and not 0 <= _number(score[key], f"[score] {key}", source) <= 1:
            raise ValueError(f"[score] {key} in {source} must be between 0 and 1")
    for key in ("judge", "shadow_model"):
        if score.get(key) and ":" in str(score[key]):
            providers.split(str(score[key]))
    cfg = Config(default_model=str(data.get("default_model", "")), models=models, names=names, prices=prices,
                 store=str((data.get("store") or {}).get("path", "")), lab=str((data.get("lab") or {}).get("path", "")),
                 slots=slots, routes=routes, goal=str(router.get("goal", "auto")),
                 escalate=bool(router.get("escalate", True)),
                 max_steps=int(_number(router.get("max_steps", 2), "[router] max_steps", source)),
                 private_auto=bool(router.get("private_auto", True)),
                 long_chars=int(_number(router.get("long_chars", 60_000), "[router] long_chars", source)) or 60_000,
                 score_enabled=bool(score.get("enabled", False)), score_sample=float(score.get("sample", 0.1)),
                 score_judge=str(score.get("judge", "")),
                 score_max_usd_per_day=_number(score.get("max_usd_per_day", 1.0), "[score] max_usd_per_day", source),
                 score_apps=[str(a) for a in score.get("apps") or []], score_shadow=bool(score.get("shadow", False)),
                 score_shadow_sample=float(score.get("shadow_sample", 0.05)), score_shadow_model=str(score.get("shadow_model", "")),
                 source=source)
    if "max_usd_per_day" in limits:
        cfg.max_usd_per_day = _number(limits["max_usd_per_day"], "max_usd_per_day", source)
    if "max_usd_per_call" in limits:
        cfg.max_usd_per_call = _number(limits["max_usd_per_call"], "max_usd_per_call", source)
    if "max_output_tokens" in limits:
        cfg.max_output_tokens = int(_number(limits["max_output_tokens"], "max_output_tokens", source)) or 4000
    if "timeout_seconds" in limits:
        cfg.timeout_seconds = _number(limits["timeout_seconds"], "timeout_seconds", source) or 120.0
    if "max_request_bytes" in limits:
        cfg.max_request_bytes = int(_number(limits["max_request_bytes"], "max_request_bytes", source)) or 2_000_000
    if cfg.default_model:
        cfg.resolve(cfg.default_model)  # raises when it points nowhere
    return cfg


def load(path: str | Path | None = None) -> Config:
    """Read the settings file in use, or return the built-in settings when there is none."""
    file = Path(path).expanduser() if path else config_path()
    if file is None:
        return builtin()
    if not file.is_file():
        raise ValueError(f"settings file {file} does not exist")
    try:
        data = tomllib.loads(file.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{file} is not valid TOML: {exc}") from exc
    return parse(data, str(file))


def render(cfg: Config) -> str:
    """Return a settings file for ``cfg``, with comments, as ``crossvet init`` writes it."""
    lines = [
        "# Crossvet settings. API keys are NOT stored here: they come from the environment or a .env file.",
        "# A request names its model, or gets default_model. Name `auto` and Crossvet picks from the slots below.",
        "",
        f'default_model = "{cfg.default_model}"',
        "",
        "# The model menu your chat app shows (GET /v1/models). Any provider:model works even if it is not listed.",
        "models = [" + ", ".join(f'"{m}"' for m in cfg.models) + "]",
        "",
        "# Short names you can type instead of provider:model (in /model, ask_model, --model).",
        "[names]",
        *(f'{short} = "{model}"' for short, model in cfg.names.items()),
        "",
        "[limits]",
        f"max_usd_per_day = {cfg.max_usd_per_day}     # 0 = no cap",
        f"max_usd_per_call = {cfg.max_usd_per_call}   # worst case, estimated before the call; needs a price",
        f"max_output_tokens = {cfg.max_output_tokens}",
        f"timeout_seconds = {cfg.timeout_seconds:g}       # one model call, start to finish",
        f"max_request_bytes = {cfg.max_request_bytes}  # the largest request `crossvet serve` accepts",
        "",
        "# The slots `auto` picks from (first callable model goes first). `crossvet route TEXT` shows a decision.",
        "[slots]",
        *(f'{slot} = [' + ", ".join(f'"{m}"' for m in models) + "]" for slot, models in cfg.slots.items()),
        '# private = ["ollama:gemma3"]   # where requests that look private may go; empty = they are refused',
        "",
        "# Judging answers sends them to a second vendor, so it is off until you turn it on (`crossvet score run`).",
        "[score]",
        f"enabled = {str(cfg.score_enabled).lower()}",
        f"sample = {cfg.score_sample}            # share of answers judged",
        f"max_usd_per_day = {cfg.score_max_usd_per_day}   # the judge's own daily cap",
        "",
        "[router]",
        f'goal = "{cfg.goal}"          # auto (slot order) | best | cheapest | fastest',
        f"escalate = {str(cfg.escalate).lower()}        # after an error, an empty answer or bad JSON, try the next model",
        f"max_steps = {cfg.max_steps}",
        "",
        f"# Prices in USD per million tokens. Built in for {', '.join(KNOWN)} (list prices, {KNOWN_DATE});",
        "# add one for any other model so /cost and the per-call cap can count it:",
        '# [prices."openrouter:vendor/model"]',
        "# input = 1.0",
        "# output = 5.0",
    ]
    return "\n".join(lines) + "\n"


def load_env() -> list[str]:
    """Read keys from ``./.env`` and ``~/.config/crossvet/.env`` (the environment wins); return the files read."""
    from dotenv import load_dotenv

    read = []
    for file in (Path(".env"), HOME / ".env"):
        if file.is_file():
            load_dotenv(file, override=False)
            read.append(str(file))
    return read
