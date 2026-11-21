"""Render docs/SETTINGS.md from configuration.py, so the settings reference cannot drift.

    uv run python -m open_deep_research.settings_doc > docs/SETTINGS.md

A unit test compares the file with this output.
"""

from __future__ import annotations

from enum import Enum

from open_deep_research.configuration import Configuration

# Read from the environment directly rather than through Configuration.
ENV_ONLY = {
    "OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY": "Model provider keys; set the ones you use.",
    "OPENROUTER_API_KEY": "One key for many models: `openrouter:<maker>/<model>` anywhere a model is set.",
    "OPENROUTER_PROVIDER_ORDER, OPENROUTER_ALLOW_FALLBACKS, OPENROUTER_DATA_COLLECTION":
        "Which OpenRouter hosts serve a model, whether others may, and whether prompts may be stored.",
    "OPENROUTER_APP_TITLE, OPENROUTER_APP_URL": "App name and URL sent to OpenRouter (default Crossvet and the repository URL).",
    "LOCAL_LLM_BASE_URL, LOCAL_LLM_API_KEY": "Any OpenAI-compatible server, for `local:<model>`.",
    "TAVILY_API_KEY": "Tavily search, when `SEARCH_API=tavily`.",
    "RESEARCH_GATEWAY_URL, RESEARCH_GATEWAY_TOKEN, RESEARCH_GATEWAY_TOOL": "The self-hosted research gateway, when `SEARCH_API=gateway`.",
    "TYPESAFE_API_KEY, TYPESAFE_DEFAULT_MODEL": "Jev support checks (billed by TypeSafe); the model defaults to jev-latest.",
    "CRAWLEE_SERVER_URL, CRAWLEE_SERVER_TOKEN": "A crawlee-server instance, for `crossvet-scan --crawl`.",
    "CROSSVET_CHECKPOINTS, DATABASE_URL": "Where CLI runs keep checkpoints: SQLite path (default `.crossvet/checkpoints.sqlite`) or Postgres.",
    "CROSSVET_CACHE_DIR": "Cache for the OpenRouter model catalog (default `~/.cache/crossvet`).",
    "LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL": "Langfuse tracing with cost per model.",
    "LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGSMITH_TRACING": "LangSmith tracing (upstream).",
    "GET_API_KEYS_FROM_CONFIG, SUPABASE_URL, SUPABASE_KEY": "Hosted deployments only (upstream): keys from the run config, and auth.",
}


# What most setups need; `crossvet setup` writes these. Everything else is listed as advanced.
ESSENTIAL = ("search_api", "cross_vendor_review_enabled", "review_models", "review_reviser_model", "research_model")
ESSENTIAL_ENV = ("OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY", "OPENROUTER_API_KEY", "TAVILY_API_KEY")


def _default(value: object) -> str:
    if isinstance(value, Enum):
        value = value.value
    if value is None or value == "":
        return "(empty)"
    return f"`{value}`"


def _description(field: object) -> str:
    extra = getattr(field, "json_schema_extra", None)
    ui = extra.get("x_oap_ui_config", {}) if isinstance(extra, dict) else {}
    text = ui.get("description") or getattr(field, "description", "") or ""
    return " ".join(text.split()).replace("|", "\\|")


def render() -> str:
    """Return the settings reference as Markdown."""
    lines = [
        "# Settings",
        "",
        "Every setting is an environment variable (the upper-case name), usually set in `.env`; copy "
        "`.env.example` to start. An empty value means the default. Generated from "
        "`src/open_deep_research/configuration.py` by `python -m open_deep_research.settings_doc`; "
        "do not edit by hand.",
        "",
        "## Essential settings",
        "",
        "These are all most setups need, and `crossvet setup` writes them for you. Set at least one provider key.",
        "",
        "| Setting | Default | What it does |",
        "|---|---|---|",
    ]
    lines += [f"| `{k.replace(', ', '`, `')}` | (empty) | {ENV_ONLY[k]} |" for k in ESSENTIAL_ENV]
    fields = Configuration.model_fields
    lines += [f"| `{n.upper()}` | {_default(fields[n].default)} | {_description(fields[n])} |" for n in ESSENTIAL]
    lines += ["", "## Advanced run settings", "", "| Setting | Default | What it does |", "|---|---|---|"]
    for name, field in fields.items():
        if name not in ESSENTIAL:
            lines.append(f"| `{name.upper()}` | {_default(field.default)} | {_description(field)} |")
    lines += ["", "## Advanced: read from the environment directly", "", "| Variables | What they do |", "|---|---|"]
    lines += [f"| `{k.replace(', ', '`, `')}` | {v} |" for k, v in ENV_ONLY.items() if k not in ESSENTIAL_ENV]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys

    sys.stdout.write(render())
