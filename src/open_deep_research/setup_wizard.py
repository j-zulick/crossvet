"""Set up Crossvet's .env from the models your keys can actually use.

Model names change often and retired names fail only at run time, so instead of
hard-coding them this command asks each provider which models your key can call,
picks a review panel from different vendors and a reviser from a vendor outside the
panel, and writes the choices to ``.env``.

    uv run crossvet-setup              # prompt for missing keys, discover, write .env
    uv run crossvet-setup --list       # show the models each key can use
    uv run crossvet-setup --check      # also send one tiny test request to every chosen model
    uv run crossvet-setup --dry-run    # show what would change without writing
    uv run crossvet-setup --compare-plan my-setups.toml   # also write crossvet-compare setups

Keys are read with hidden input, written only to ``.env`` (permissions 600) and never
printed. Discovery covers OpenAI, Anthropic, Google (Gemini API), OpenRouter, Ollama
and any OpenAI-compatible local server.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field

from open_deep_research.models import save_openrouter_catalog, unmet_needs

KEY_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
SEARCH_KEY = "TAVILY_API_KEY"
STAGE_VARS = ("RESEARCH_MODEL", "SUMMARIZATION_MODEL", "COMPRESSION_MODEL", "FINAL_REPORT_MODEL")
STAGE_DEFAULTS = {
    "RESEARCH_MODEL": "openai:gpt-5.5",
    "SUMMARIZATION_MODEL": "openai:gpt-5.4-mini",
    "COMPRESSION_MODEL": "openai:gpt-5.5",
    "FINAL_REPORT_MODEL": "openai:gpt-5.5",
}
# Words that mark models unsuited to text review (audio, images, embeddings, previews, ...).
EXCLUDE = re.compile(
    r"(audio|realtime|transcribe|tts|whisper|image|dall|embed|moderation|search|computer|codex|cyber|"
    r"preview|exp|live|instruct|vision|robotics|aqa|learnlm|nano|lite|chat-latest|davinci|babbage|daybreak|oss|"
    r"-\d{4}-\d{2}-\d{2}|-\d{8}$|-\d{3}$)",
    re.I,
)
TIMEOUT = httpx.Timeout(15.0)


@dataclass
class Discovery:
    """Models found per provider, and why a provider was skipped."""

    models: dict[str, list[str]] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# .env handling
# ---------------------------------------------------------------------------
def read_env(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines (comments and blanks ignored)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
        if m and not line.lstrip().startswith("#"):
            values[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return values


def write_env(path: Path, updates: dict[str, str], template: Path | None = None) -> None:
    """Update KEY=VALUE lines in place (or append them), keeping comments and order."""
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    elif template and template.exists():
        lines = template.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    done: set[str] = set()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            done.add(m.group(1))
    extra = [f"{k}={v}" for k, v in updates.items() if k not in done]
    if extra:
        lines += ["", "# --- Set by crossvet-setup ---", *extra]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
async def _get(client: httpx.AsyncClient, url: str, **kw: Any) -> Any:
    r = await client.get(url, **kw)
    r.raise_for_status()
    return r.json()


async def discover(env: dict[str, str], transport: httpx.AsyncBaseTransport | None = None) -> Discovery:
    """Ask every configured provider which models are available."""
    out = Discovery()
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:

        async def openai() -> None:
            data = await _get(client, "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {env['OPENAI_API_KEY']}"})
            out.models["openai"] = sorted(m["id"] for m in data.get("data", []))

        async def anthropic() -> None:
            data = await _get(client, "https://api.anthropic.com/v1/models", params={"limit": 1000},
                              headers={"x-api-key": env["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
            out.models["anthropic"] = sorted(m["id"] for m in data.get("data", []))

        async def google() -> None:
            data = await _get(client, "https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 1000},
                              headers={"x-goog-api-key": env["GOOGLE_API_KEY"]})
            out.models["google_genai"] = sorted(
                m["name"].split("/", 1)[-1] for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])
            )

        async def openrouter() -> None:
            data = await _get(client, "https://openrouter.ai/api/v1/models")
            out.models["openrouter"] = sorted(m["id"] for m in data.get("data", []))
            save_openrouter_catalog(data.get("data", []))  # tools / structured output / price per model

        async def ollama() -> None:
            host = env.get("OLLAMA_HOST") or "http://localhost:11434"
            host = host if host.startswith("http") else f"http://{host}"
            data = await _get(client, f"{host.rstrip('/')}/api/tags")
            out.models["ollama"] = sorted(m["name"] for m in data.get("models", []))

        async def local() -> None:
            bases = [env.get("LOCAL_LLM_BASE_URL") or "", "http://localhost:8080/v1", "http://localhost:1234/v1"]
            for base in dict.fromkeys(b.rstrip("/") for b in bases if b):
                try:
                    data = await _get(client, f"{base}/models")
                except Exception:
                    continue
                out.models["local"] = sorted(m["id"] for m in data.get("data", []))
                out.notes["local_base_url"] = base
                return
            raise RuntimeError("no OpenAI-compatible server on LOCAL_LLM_BASE_URL, :8080 or :1234")

        jobs: dict[str, Callable[[], Any]] = {"ollama": ollama, "local": local}
        for provider, fn in (("openai", openai), ("anthropic", anthropic), ("google_genai", google), ("openrouter", openrouter)):
            if env.get(KEY_VARS[provider]):
                jobs[provider] = fn
            else:
                out.notes[provider] = f"skipped: {KEY_VARS[provider]} not set"

        async def run(name: str, fn: Callable[[], Any]) -> None:
            try:
                await fn()
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                out.notes[name] = f"key rejected (HTTP {code})" if code in (401, 403) else f"HTTP {code}"
            except Exception as exc:  # network errors, servers not running
                if name == "local" and isinstance(exc, RuntimeError):
                    out.notes[name] = str(exc)
                else:
                    out.notes[name] = "not running" if name == "ollama" else f"not reachable ({type(exc).__name__})"

        await asyncio.gather(*(run(n, f) for n, f in jobs.items()))
    return out


# ---------------------------------------------------------------------------
# Choosing models
# ---------------------------------------------------------------------------
def _version(name: str) -> tuple[float, ...]:
    nums = re.findall(r"\d+(?:\.\d+)?", name.replace("-", "."))
    return tuple(float(n) for n in nums[:3]) or (0.0,)


def rank(provider: str, ids: list[str]) -> list[str]:
    """Order a provider's models from most to least suitable as a reviewer."""
    if provider in ("ollama", "local"):
        return list(ids)
    if provider == "openrouter":
        return []  # handled by pick_openrouter
    if provider == "openai":
        cands = [i for i in ids if re.match(r"^(gpt-\d|o\d)", i) and not EXCLUDE.search(i) and "mini" not in i]
        return sorted(cands, key=lambda i: (i.startswith("gpt-"), _version(i), "-sol" in i, -len(i)), reverse=True)
    if provider == "anthropic":
        cands = [i for i in ids if i.startswith("claude-") and not EXCLUDE.search(i)]
        tier = {"sonnet": 3, "opus": 2, "haiku": 1}
        return sorted(cands, key=lambda i: (_version(i), next((v for k, v in tier.items() if k in i), 0)), reverse=True)
    if provider == "google_genai":
        cands = [i for i in ids if i.startswith("gemini-") and not EXCLUDE.search(i) and "latest" not in i]
        return sorted(cands, key=lambda i: (_version(i), "pro" in i, "flash" in i, -len(i)), reverse=True)
    return list(ids)


OPENROUTER_VENDORS = ("openai", "anthropic", "google", "deepseek", "mistralai", "qwen", "meta-llama", "x-ai", "z-ai", "moonshotai")


def pick_openrouter(ids: list[str], exclude_vendors: set[str]) -> list[str]:
    """Best model per vendor on OpenRouter, for vendors not already on the panel."""
    picks = []
    for vendor in OPENROUTER_VENDORS:
        if vendor in exclude_vendors:
            continue
        cands = [i for i in ids if i.startswith(vendor + "/") and not EXCLUDE.search(i.split("/", 1)[1].replace("instruct", "")) and ":" not in i
                 and not unmet_needs("openrouter:" + i, "reviewer")]
        if vendor == "google":  # Google's flagship line is Gemini; Gemma (open weights) has its own numbering
            cands = [i for i in cands if i.startswith("google/gemini")] or cands
        if cands:
            picks.append("openrouter:" + sorted(cands, key=lambda i: (_version(i.split("/", 1)[1]), -len(i)), reverse=True)[0])
    return picks


CHEAP = {"openai": r"^gpt-\d[\d.]*-mini$", "anthropic": r"^claude-haiku-", "google_genai": r"^gemini-[\d.]+-flash$"}


def cheap_model(provider: str, ids: list[str]) -> str | None:
    """Return a smaller, cheaper model from the same provider, for summarizing pages."""
    pattern = CHEAP.get(provider)
    if not pattern:
        return None
    cands = [i for i in ids if re.match(pattern, i) and not re.search(r"-\d{4}-\d{2}-\d{2}|-\d{8}$", i)]
    return f"{provider}:{max(cands, key=_version)}" if cands else None


@dataclass
class Plan:
    """Chosen models and the .env changes that follow."""

    panel: list[str]
    reviser: str
    stages: dict[str, str]
    warnings: list[str]


def plan(found: Discovery, env: dict[str, str], panel_size: int = 3) -> Plan:
    """Choose a cross-vendor panel, an independent reviser and working stage models."""
    from open_deep_research.cross_vendor_review import vendor_of

    best = {p: rank(p, ids) for p, ids in found.models.items() if p not in ("openrouter",)}
    hosted_order = [p for p in ("openai", "anthropic", "google_genai") if best.get(p)]
    candidates = [f"{p}:{best[p][0]}" for p in hosted_order]
    vendors = {vendor_of(m) for m in candidates}
    if found.models.get("openrouter"):
        candidates += pick_openrouter(found.models["openrouter"], vendors)
    warnings: list[str] = []
    panel = candidates[:panel_size]
    rest = [m for m in candidates[panel_size:] if vendor_of(m) not in {vendor_of(p) for p in panel}]
    if len(panel) < 2:
        warnings.append("Fewer than two vendors are available, so review needs another key (or OpenRouter).")
    if rest:
        reviser = rest[0]
    elif len(panel) >= 3:
        reviser = panel.pop()  # keep the reviser outside the panel: two reviewers + an independent reviser
    else:
        reviser = panel[0] if panel else ""
        if panel:
            warnings.append("No vendor is left for an independent reviser; the review notes will show a warning.")

    stages: dict[str, str] = {}
    primary = (f"openai:{best['openai'][0]}" if best.get("openai") else candidates[0] if candidates else "")
    primary_provider = primary.split(":", 1)[0]
    small = cheap_model(primary_provider, found.models.get(primary_provider, [])) or primary
    for var in STAGE_VARS:
        current = env.get(var) or STAGE_DEFAULTS[var]
        provider, _, name = current.partition(":")
        listed = found.models.get(provider)
        replacement = small if var == "SUMMARIZATION_MODEL" else primary
        if listed is not None and name not in listed and replacement:
            stages[var] = replacement
            warnings.append(f"{var}={current} is not available to your key; using {replacement}.")
        elif listed is None and provider in KEY_VARS and replacement and replacement != current:
            rejected = "rejected" in found.notes.get(provider, "")
            if rejected or not env.get(KEY_VARS[provider]):
                stages[var] = replacement
                why = "was rejected" if rejected else "is not set"
                warnings.append(f"{var}={current}: {KEY_VARS[provider]} {why}; using {replacement}.")
    return Plan(panel, reviser, stages, warnings)


def availability(model: str, found: Discovery) -> bool | None:
    """True/False when the provider's model list was discovered, None when it could not be checked."""
    provider, _, name = (model or "").strip().partition(":")
    ids = found.models.get(provider)
    if ids is None or not name:
        return None
    return name in ids


def user_plan(found: Discovery, env: dict[str, str], panel: list[str], reviser: str | None, source: str = "you chose") -> Plan:
    """Keep the models a user picked; check them, and fill in only what is missing (reviser, stage models)."""
    from open_deep_research.cross_vendor_review import reviser_conflicts, vendor_of

    auto = plan(found, env)
    warnings = [w for w in auto.warnings if "review" not in w.lower()]
    for m in panel + ([reviser] if reviser else []):
        ok = availability(m, found)
        if ok is False:
            warnings.append(f"{m} ({source}) is not in the model list for its key; check the name or the key.")
        elif ok is None:
            warnings.append(f"{m} ({source}) could not be checked: its provider was not discovered.")
    vendors = {vendor_of(m) for m in panel}
    if len(panel) < 2:
        warnings.append("Review needs at least two reviewer models.")
    elif len(vendors) < 2:
        warnings.append(f"All reviewers are from one vendor ({', '.join(vendors)}); cross-vendor review needs at least two.")
    if not reviser:
        candidates = [auto.reviser, *auto.panel]
        reviser = next((m for m in candidates if m and vendor_of(m) not in vendors), "")
        if not reviser:
            warnings.append("No reviser from a vendor outside the panel was found; set --reviser.")
    if reviser and reviser_conflicts(reviser, panel):
        warnings.append(f"The reviser {reviser} shares a vendor with the panel; the review notes will show a warning.")
    return Plan(list(panel), reviser, auto.stages, warnings)


def choose_search(env: dict[str, str], found: Discovery, chosen: Plan) -> tuple[dict[str, str], str]:
    """Keep the configured search if it can work; otherwise fall back to a model's built-in search."""
    current = env.get("SEARCH_API") or "tavily"
    if current != "tavily" or env.get(SEARCH_KEY):
        return {}, ""
    for provider in ("openai", "anthropic"):
        ranked = rank(provider, found.models.get(provider, []))
        if ranked:
            research = env.get("RESEARCH_MODEL") or STAGE_DEFAULTS["RESEARCH_MODEL"]
            research = chosen.stages.get("RESEARCH_MODEL", research)
            updates = {"SEARCH_API": provider}
            if not research.startswith(f"{provider}:"):
                updates["RESEARCH_MODEL"] = f"{provider}:{ranked[0]}"
            return updates, (f"No TAVILY_API_KEY: using {provider}'s built-in web search (SEARCH_API={provider}). "
                             "Add a Tavily key or a research gateway later to also capture full page text.")
    return {}, "TAVILY_API_KEY is not set; research needs it (or SEARCH_API=gateway / openai / anthropic)."


# ---------------------------------------------------------------------------
# Comparison plan for crossvet-compare
# ---------------------------------------------------------------------------
def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-")[:40] or "model"


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def compare_plan(found: Discovery, chosen: Plan, max_local: int = 4) -> list[dict[str, Any]]:
    """Setups that answer the usual questions with the models actually available."""
    from open_deep_research.configuration import Configuration

    fields = Configuration.model_fields
    panel = ",".join(chosen.panel)
    setups: list[dict[str, Any]] = [
        {"name": "review", "comment": "your .env: cross-vendor panel and reviser", "config": {"cross_vendor_review_enabled": True}},
        {"name": "no-review", "comment": "same research, no review: what review adds", "config": {"cross_vendor_review_enabled": False}},
    ]
    if "review_deliberation_rounds" in fields:
        setups.append({"name": "deliberation-2", "comment": "two deliberation rounds before the vote",
                       "config": {"cross_vendor_review_enabled": True, "review_deliberation_rounds": 2}})
        if "review_deliberation_early_stop" in fields:
            setups.append({"name": "deliberation-3-fixed", "comment": "three rounds, no early stop: the baseline for early stopping",
                           "config": {"cross_vendor_review_enabled": True, "review_deliberation_rounds": 3, "review_deliberation_early_stop": False}})
            setups.append({"name": "deliberation-3-early-stop", "comment": "three rounds with early stopping: compare tokens and outcomes with the fixed baseline",
                           "config": {"cross_vendor_review_enabled": True, "review_deliberation_rounds": 3, "review_deliberation_early_stop": True}})
    if "review_support_checker" in fields and os.getenv("TYPESAFE_API_KEY"):
        setups.append({"name": "deliberation-2-jev", "comment": "deliberation with Jev support checks: compare with 'deliberation-2'",
                       "config": {"cross_vendor_review_enabled": True, "review_deliberation_rounds": 2, "review_support_checker": "jev"}})
    if "review_blind_pass_enabled" in fields:
        setups.append({"name": "blind-pass", "comment": "reviewers outline the answer before reading the draft: compare with 'review'",
                       "config": {"cross_vendor_review_enabled": True, "review_blind_pass_enabled": True}})
    try:
        import open_deep_research.deep_agent  # noqa: F401

        setups.append({"name": "deep-agent", "edition": "deep_agent", "comment": "Deep Agents edition, same review",
                       "config": {"cross_vendor_review_enabled": True}})
    except ImportError:
        pass
    local = [f"ollama:{m}" for m in found.models.get("ollama", [])] + [f"local:{m}" for m in found.models.get("local", [])]
    for model in local[:max_local]:
        slug = _slug(model.split(":", 1)[1])
        setups.append({"name": f"writer-{slug}", "comment": f"{model} writes the report; hosted panel reviews it",
                       "config": {"final_report_model": model, "cross_vendor_review_enabled": True}})
        if chosen.panel:
            setups.append({"name": f"reviewer-{slug}", "comment": f"{model} joins the panel as a reviewer",
                           "config": {"review_models": f"{chosen.panel[0]},{model}", "cross_vendor_review_enabled": True}})
    if panel and len(chosen.panel) < 2:
        setups = [s for s in setups if s["name"] != "review"]
    return setups


def render_plan(setups: list[dict[str, Any]]) -> str:
    """TOML for crossvet-compare."""
    lines = ["# Written by crossvet-setup --compare-plan from the models available to you.",
             "# Run: uv run crossvet-compare --setups <this file> --questions examples/compare/questions-15.txt --repeats 2", ""]
    for setup in setups:
        lines += [f"# {setup['comment']}", "[[setup]]", f"name = {_toml_value(setup['name'])}"]
        if setup.get("edition"):
            lines.append(f"edition = {_toml_value(setup['edition'])}")
        lines.append("[setup.config]")
        lines += [f"{k} = {_toml_value(v)}" for k, v in setup["config"].items()]
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live check
# ---------------------------------------------------------------------------
class _Ping(BaseModel):
    """Structured output used to test a model."""

    ok: bool = Field(description="Always true.")
    word: str = Field(description="The word 'ready'.")


async def check_models(models: list[str], env: dict[str, str]) -> dict[str, str]:
    """Send one tiny structured-output request to each model; return model -> OK or error."""
    from langchain_core.messages import HumanMessage

    from open_deep_research.cross_vendor_review import build_reviewer
    from open_deep_research.utils import structured_output_kwargs

    os.environ.update({k: v for k, v in env.items() if v})

    async def one(m: str) -> tuple[str, str]:
        try:
            llm = build_reviewer(m, 2000, {"configurable": {}}).with_structured_output(_Ping, **structured_output_kwargs(m))  # room for reasoning tokens
            r = await asyncio.wait_for(llm.ainvoke([HumanMessage(content="Return ok=true and word='ready'.")]), 90)
            return m, "OK" if r and r.ok else "answered, but not in the expected format"
        except Exception as exc:
            msg = re.sub(r"(sk|key|token)[-_A-Za-z0-9]{8,}", "[redacted]", str(exc))[:160]
            return m, f"FAIL {type(exc).__name__}: {msg}"

    return dict(await asyncio.gather(*(one(m) for m in dict.fromkeys(models))))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def say(text: str = "") -> None:
    """Write one line to standard output."""
    sys.stdout.write(text + "\n")


def ask_keys(env: dict[str, str], prompt: Callable[[str], str] = getpass.getpass) -> dict[str, str]:
    """Prompt (hidden input) for keys that are not set; Enter skips."""
    updates: dict[str, str] = {}
    for var in (*KEY_VARS.values(), SEARCH_KEY):
        if env.get(var):
            continue
        value = prompt(f"{var} (Enter to skip): ").strip()
        if value:
            updates[var] = value
    return updates


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    p = argparse.ArgumentParser(prog="crossvet-setup", description="Discover available models and write Crossvet's .env.")
    p.add_argument("--env", default=".env", help="path to the .env file (default .env)")
    p.add_argument("--list", action="store_true", help="only list the models each provider makes available")
    p.add_argument("--check", action="store_true", help="send one tiny test request to every chosen model")
    p.add_argument("--dry-run", action="store_true", help="show changes without writing")
    p.add_argument("--no-prompt", action="store_true", help="do not ask for missing keys")
    p.add_argument("--panel-size", type=int, default=3, choices=(2, 3, 4))
    p.add_argument("--compare-plan", metavar="FILE", help="also write crossvet-compare setups for the available models")
    p.add_argument("--panel", metavar="MODELS", help="your own reviewer models, comma-separated provider:model (e.g. openrouter:x-ai/grok-4,anthropic:claude-sonnet-5-5)")
    p.add_argument("--reviser", metavar="MODEL", help="your own reviser model (default: kept from .env, else one from a vendor outside the panel)")
    p.add_argument("--auto", action="store_true", help="re-pick the panel automatically even if REVIEW_MODELS is already set")
    p.add_argument("--list-models", metavar="PROVIDER", help="print every model id one provider offers (openai, anthropic, google_genai, openrouter, ollama, local)")
    p.add_argument("--filter", default="", help="with --list-models: only ids containing this text")
    args = p.parse_args(argv)

    env_path = Path(args.env)
    template = env_path.with_name(".env.example")
    env = {**read_env(template), **read_env(env_path)}
    for var in (*KEY_VARS.values(), SEARCH_KEY, "LOCAL_LLM_BASE_URL", "OLLAMA_HOST"):
        if os.environ.get(var) and not env.get(var):
            env[var] = os.environ[var]

    updates: dict[str, str] = {}
    if not args.list and not args.no_prompt and sys.stdin.isatty():
        updates.update(ask_keys(env))
        env.update(updates)

    found = asyncio.run(discover(env))
    for provider in ("openai", "anthropic", "google_genai", "openrouter", "ollama", "local"):
        ids = found.models.get(provider)
        if ids is not None:
            top = rank(provider, ids)[:5] if provider != "openrouter" else []
            shown = ", ".join(top) if top else f"{len(ids)} models"
            say(f"  {provider:13} {len(ids):4} available  {shown}")
        else:
            say(f"  {provider:13}    -  {found.notes.get(provider, 'not configured')}")
    if args.list:
        return 0
    if args.list_models:
        ids = found.models.get(args.list_models)
        if ids is None:
            say(f"{args.list_models}: {found.notes.get(args.list_models, 'not configured')}")
            return 1
        for i in ids:
            if args.filter.lower() in i.lower():
                say(f"{args.list_models}:{i}")
        return 0

    from open_deep_research.cross_vendor_review import parse_review_models

    if args.panel:
        chosen = user_plan(found, env, parse_review_models(args.panel), args.reviser, "--panel")
    elif env.get("REVIEW_MODELS") and not args.auto:
        chosen = user_plan(found, env, parse_review_models(env["REVIEW_MODELS"]), args.reviser or env.get("REVIEW_REVISER_MODEL"), "from .env")
        chosen.warnings.insert(0, "Kept the panel from REVIEW_MODELS; use --auto to re-pick or --panel to change it.")
    else:
        chosen = plan(found, env, args.panel_size)
        if args.reviser:
            chosen.reviser = args.reviser
    review_updates = {
        "CROSS_VENDOR_REVIEW_ENABLED": "true" if len(chosen.panel) >= 2 else "false",
        "REVIEW_MODELS": ",".join(chosen.panel),
        "REVIEW_REVISER_MODEL": chosen.reviser,
        **chosen.stages,
    }
    from open_deep_research.configuration import Configuration

    if "run_export_path" in Configuration.model_fields and not env.get("RUN_EXPORT_PATH"):
        review_updates["RUN_EXPORT_PATH"] = "runs/review.jsonl"  # every run becomes evaluation data
    if env.get("TYPESAFE_API_KEY") and not env.get("REVIEW_SUPPORT_CHECKER") and "review_support_checker" in Configuration.model_fields:
        review_updates["REVIEW_SUPPORT_CHECKER"] = "jev"
        chosen.warnings.append("TYPESAFE_API_KEY is set: Jev support checks are on (REVIEW_SUPPORT_CHECKER=jev).")
    if found.notes.get("local_base_url") and not env.get("LOCAL_LLM_BASE_URL"):
        review_updates["LOCAL_LLM_BASE_URL"] = found.notes["local_base_url"]
    search_updates, search_note = choose_search(env, found, chosen)
    review_updates.update(search_updates)
    if search_note:
        chosen.warnings.append(search_note)
    updates.update(review_updates)

    say("\nReview panel:  " + (", ".join(chosen.panel) or "(none)"))
    say("Reviser:       " + (chosen.reviser or "(none)"))
    for var, value in chosen.stages.items():
        say(f"{var}: {value}")
    for w in chosen.warnings:
        say(f"note: {w}")

    if args.check:
        models = [*chosen.panel, chosen.reviser, *chosen.stages.values()]
        say("\nTesting each model with one tiny request...")
        for model, result in asyncio.run(check_models([m for m in models if m], env)).items():
            say(f"  {model}: {result}")

    if args.compare_plan:
        Path(args.compare_plan).write_text(render_plan(compare_plan(found, chosen)), encoding="utf-8")
        say(f"Wrote comparison setups to {args.compare_plan}")

    if args.dry_run:
        say("\n(dry run) would set: " + ", ".join(k for k in updates))
        return 0
    if not env_path.exists() and template.exists():
        shutil.copyfile(template, env_path)
    write_env(env_path, updates, template)
    say(f"\nWrote {env_path} (keys hidden). Next: uv run python -m open_deep_research.doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
