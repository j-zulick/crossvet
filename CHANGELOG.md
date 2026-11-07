# Changelog

All notable changes to Crossvet. Versions follow [Semantic Versioning](https://semver.org/); dates are release dates.

## [0.1.0]

First release, built on LangChain's Open Deep Research (upstream `1b7d2e8`).

### Added
- **Cross-vendor review stage** (`cross_vendor_review`) after the draft report: parallel typed critiques from reviewers at different vendors, anonymized and shuffled peer ranking combined with a confidence-weighted Borda count, a deterministic citation check against the research notes, and a revised report ending in *Review notes* (scores, peer-voted best critique, dissent, flagged citations, failed reviewers, or a failed revision, in which case the draft is kept). Quorum of two.
- Reviewer independence: `REVIEW_REVISER_MODEL` selects the model that revises the report, with a warning in the Review notes when it shares a vendor with a reviewer (vendor detection covers direct, OpenRouter and self-hosted routes). Reviewer and vote prompts tell models to keep evidence-based positions rather than defer to confident wording or to other reviewers.
- Self-hosted models: `ollama:<model>` for any pipeline stage, and `local:<model>` reviewers on any OpenAI-compatible server (llama.cpp, LM Studio, MLX, vLLM). `openrouter:<model>` reviewers with one key.
- Agent Chat UI web frontend (`web/`, Next.js 16 / React 19 / Tailwind 4) and `langgraph.local.json` for local development without auth.
- Security policy (`SECURITY.md`) and release notes in `docs/releases/`.
- Setup checker (`python -m open_deep_research.doctor`): reports missing API keys, too few or single-vendor reviewers, a reviser sharing a vendor with the panel, and missing search settings — without printing key values.
- `crossvet-setup`: asks each provider which models the key can use, picks a cross-vendor panel and an independent reviser, replaces stage models the key cannot use, optionally tests every chosen model with one tiny request, and writes `.env` (keys hidden, permissions 600). `crossvet-try` runs one question and saves the report, review summary and a key-free `share.md`. `scripts/quickstart.sh` chains tools check, install, setup, doctor and a first run.
- Built-in web search works without a Tavily key: OpenAI uses the current `web_search` tool and returns every consulted source into the research notes; native search is detected in current langchain-openai content blocks; the citation check ignores tracking parameters, scheme, `www.` and trailing slashes. `crossvet-setup` falls back to built-in search when no Tavily key is set.
- Offline end-to-end test: a scripted model drives the full research graph and review.
- Offline unit tests (no API keys, no network) and a GitHub Actions CI workflow (lint, graph build, tests, web build); Dependabot for uv, npm and GitHub Actions.

### Changed
- Upgraded to LangGraph 1.2 and LangChain 1.x; Python 3.13 lockfile.
- Configuration moved to Pydantic v2 idioms (`json_schema_extra`, `ConfigDict`), removing deprecation warnings; new options appear in LangGraph Studio's configuration panel.
- Researcher prompt no longer assumes a specific search tool.

### Removed
- Upstream workflows that required the upstream maintainers' secrets.
