"""Pre-flight check for a Crossvet configuration.

Reads the environment (and .env) the same way a run does and reports problems before
any model is called: missing API keys, too few reviewers, reviewers from a single
vendor, a reviser that shares a vendor with a reviewer, or missing search settings.

    uv run python -m open_deep_research.doctor

Exit code 0 when there are no failures (warnings are allowed), 1 otherwise.
Key values are never printed; only whether each one is set.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from open_deep_research.configuration import Configuration
from open_deep_research.cross_vendor_review import (
    parse_review_models,
    reviser_conflicts,
    vendor_of,
)
from open_deep_research.models import unmet_needs

PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "google_vertexai": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistralai": "MISTRAL_API_KEY",
}
SELF_HOSTED = {"ollama", "local"}


@dataclass
class Finding:
    """One check result."""

    level: str  # OK | WARN | FAIL
    message: str


def required_key(model: str) -> str | None:
    """Environment variable a model needs, or None for self-hosted / unknown providers."""
    provider = (model or "").split(":", 1)[0]
    if provider in SELF_HOSTED:
        return None
    return PROVIDER_KEYS.get(provider)


def check(config: Configuration | None = None) -> list[Finding]:
    """Run every check against the current environment."""
    cfg = config or Configuration.from_runnable_config({"configurable": {}})
    out: list[Finding] = []

    stages = {
        "research": cfg.research_model,
        **({"orchestration (supervisor)": cfg.supervisor_model} if cfg.supervisor_model else {}),
        **({"researcher": cfg.researcher_model} if cfg.researcher_model else {}),
        "summarization": cfg.summarization_model,
        "compression": cfg.compression_model,
        "final report": cfg.final_report_model,
    }
    reviewers = parse_review_models(cfg.review_models)
    review_on = cfg.cross_vendor_review_enabled
    reviser = cfg.review_reviser_model or cfg.final_report_model

    models: dict[str, str] = {f"{stage} model": m for stage, m in stages.items()}
    if review_on:
        models.update({f"reviewer {i}": m for i, m in enumerate(reviewers, start=1)})
        models["reviser"] = reviser

    for role, model in models.items():
        key = required_key(model)
        provider = model.split(":", 1)[0]
        if provider in SELF_HOSTED:
            where = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:1234/v1") if provider == "local" else "Ollama (localhost:11434)"
            out.append(Finding("OK", f"{role}: {model} is self-hosted; make sure {where} is running"))
        elif key is None:
            out.append(Finding("WARN", f"{role}: {model}: unknown provider '{provider}'; cannot check its API key"))
        elif os.getenv(key):
            out.append(Finding("OK", f"{role}: {model} ({key} is set)"))
        else:
            out.append(Finding("FAIL", f"{role}: {model} needs {key}, which is not set"))

    # Capabilities known before any call (OpenRouter catalog or model profile): a role that
    # must call tools, or parse typed output, cannot run on a model that can't.
    role_of = {"research model": "researcher", "orchestration (supervisor) model": "supervisor",
               "researcher model": "researcher", "summarization model": "summarization"}
    role_of.update({r: "reviewer" for r in models if r.startswith("reviewer ")})
    for role, model in models.items():
        missing = unmet_needs(model, role_of.get(role, ""))
        if missing:
            out.append(Finding("FAIL", f"{role}: {model} does not support {' or '.join(missing)}, which this role needs"))

    search = getattr(cfg.search_api, "value", str(cfg.search_api))
    if search == "tavily":
        out.append(Finding("OK", "search: tavily (TAVILY_API_KEY is set)") if os.getenv("TAVILY_API_KEY") else Finding("FAIL", "search: tavily needs TAVILY_API_KEY, which is not set"))
    elif search == "gateway":
        missing = [v for v in ("RESEARCH_GATEWAY_URL", "RESEARCH_GATEWAY_TOKEN") if not os.getenv(v)]
        out.append(Finding("FAIL", f"search: gateway needs {', '.join(missing)}") if missing else Finding("OK", "search: research gateway (URL and token are set)"))
    elif search in ("openai", "anthropic"):
        if not cfg.model_for("researcher").startswith(f"{search}:"):
            out.append(Finding("FAIL", f"search: native {search} web search needs a {search}: researcher model (got {cfg.model_for('researcher')})"))
        else:
            out.append(Finding("OK", f"search: {search} built-in web search (cited sources are checked; Tavily or a gateway also captures page text)"))
    else:
        out.append(Finding("WARN", f"search: '{search}': research will run without web search"))
    if cfg.search_also:
        also = cfg.search_also.strip().lower()
        if also not in ("openai", "anthropic"):
            out.append(Finding("FAIL", f"search: SEARCH_ALSO must be openai or anthropic (got {cfg.search_also})"))
        elif not cfg.model_for("researcher").startswith(f"{also}:"):
            out.append(Finding("WARN", f"search: SEARCH_ALSO={also} is ignored because the researcher model is {cfg.model_for('researcher')}"))
        else:
            out.append(Finding("OK", f"search: {also} built-in web search is added next to {search}"))

    if review_on:
        vendors = {vendor_of(m) for m in reviewers}
        if len(reviewers) < 2:
            out.append(Finding("FAIL", f"review: needs at least 2 REVIEW_MODELS, got {len(reviewers)}"))
        elif len(vendors) < 2:
            out.append(Finding("WARN", f"review: all reviewers are from one vendor ({vendors.pop()}); use different vendors for a real cross-check"))
        else:
            out.append(Finding("OK", f"review: {len(reviewers)} reviewers from {len(vendors)} vendors"))
        conflicts = reviser_conflicts(reviser, reviewers)
        if conflicts:
            out.append(Finding("WARN", f"review: reviser {reviser} shares a vendor with {', '.join(conflicts)}; set REVIEW_REVISER_MODEL to another vendor"))
        else:
            out.append(Finding("OK", f"review: reviser {reviser} is independent of the panel"))
    else:
        out.append(Finding("WARN", "review: cross-vendor review is off (CROSS_VENDOR_REVIEW_ENABLED=false); `crossvet setup` turns it on with a panel your keys can call"))

    pack = (getattr(cfg, "context_pack", "") or "").strip().lower()
    if pack:
        from open_deep_research.context import available_packs

        if pack in available_packs():
            out.append(Finding("OK", f"context: pack '{pack}' is added to every research brief"))
        else:
            out.append(Finding("FAIL", f"context: unknown CONTEXT_PACK '{pack}' (choose one of: {', '.join(available_packs())})"))

    checker = (getattr(cfg, "review_support_checker", "") or "").strip().lower()
    if checker == "jev":
        try:
            import typesafe_sdk  # noqa: F401

            sdk = True
        except ImportError:
            sdk = False
        if not os.getenv("TYPESAFE_API_KEY"):
            out.append(Finding("FAIL", "support check: REVIEW_SUPPORT_CHECKER=jev needs TYPESAFE_API_KEY (console.typesafe.ai)"))
        elif not sdk:
            out.append(Finding("FAIL", "support check: Jev needs the typesafe-sdk package (uv sync)"))
        else:
            model = cfg.review_support_model or os.getenv("TYPESAFE_DEFAULT_MODEL") or "jev-latest"
            out.append(Finding("OK", f"support check: Jev ({model}); run `uv run crossvet-doctor --jev` for a live test"))
    elif checker:
        out.append(Finding("FAIL", f"support check: unknown REVIEW_SUPPORT_CHECKER '{checker}' (use jev, or leave it empty)"))
    return out


JEV_SAMPLES = [
    ("The plant opened in March 2024.", "The plant opened in March 2024 and employs 1,200 people.", True),
    ("The plant employs 5,000 people.", "The plant opened in March 2024 and employs 1,200 people.", False),
]


def jev_live_check(min_prob: float = 0.5) -> int:
    """Ask Jev two questions with known answers; return an exit code."""
    import asyncio

    from open_deep_research.support_check import JevChecker

    cfg = Configuration.from_runnable_config({"configurable": {}})
    if not os.getenv("TYPESAFE_API_KEY"):
        sys.stdout.write("[FAIL] TYPESAFE_API_KEY is not set\n")
        return 1
    checker = JevChecker(model=cfg.review_support_model)
    probs = asyncio.run(checker.check([(c, p) for c, p, _ in JEV_SAMPLES]))
    ok = True
    for (claim, _, expected), prob in zip(JEV_SAMPLES, probs):
        if prob is None:
            sys.stdout.write(f"[FAIL] Jev call failed for: {claim}\n")
            ok = False
            continue
        right = (prob >= min_prob) == expected
        ok &= right
        sys.stdout.write(f"[{'OK' if right else 'WARN':4}] {'supported' if expected else 'not supported'} pair: P(support)={prob:.2f}  {claim}\n")
    served = ", ".join(sorted(checker.served_by)) or checker.model
    sys.stdout.write(f"\nJev ({served}): {'working' if ok else 'check the results above'}.\n")
    return 0 if ok else 1


NEXT_HINT = "it asks for your keys with hidden input and writes .env"


def main() -> int:
    """Print the findings and return an exit code (``--jev``: live Jev test)."""
    try:
        from open_deep_research.envfile import load_env

        load_env()
    except ImportError:
        pass
    if "--jev" in sys.argv[1:]:
        return jev_live_check()
    findings = check()
    for f in findings:
        sys.stdout.write(f"[{f.level:4}] {f.message}\n")
    failures = sum(f.level == "FAIL" for f in findings)
    if failures:
        sys.stdout.write(f"\n{failures} problem(s) to fix before running.\n")
        sys.stdout.write(f"Next: run `crossvet setup` in this folder ({NEXT_HINT}), then `crossvet doctor` again.\n")
    else:
        sys.stdout.write("\nReady to run.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
