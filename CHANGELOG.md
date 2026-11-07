# Changelog

All notable changes to Crossvet. Versions follow [Semantic Versioning](https://semver.org/); dates are release dates.

## [0.4.0]

### Added
- **Model comparison harness** `crossvet-compare`: runs every question under every named setup (TOML) with optional repeats and writes per-run JSONL, a per-setup summary (Markdown and CSV) and all reports. Records latency, tokens per model from usage metadata, cited and flagged URLs, reviewer scores, critic outcomes and failed reviewers; failed runs are recorded without stopping the comparison. Example setups and questions in `examples/compare/`.
- `crossvet-setup --compare-plan FILE` writes comparison setups from the models your keys and local servers offer; `examples/compare/questions-15.txt` adds 15 questions with checkable answers.

### Changed
- Python 3.11 or newer is required (the lockfile already targeted 3.13).

## [0.3.0]

### Added
- **Human approval step** (`REQUIRE_APPROVAL`): the run pauses after research with a LangGraph interrupt in Agent Chat UI's HITL format (approve / edit instructions / reject). Rejection stops before report generation; unrecognized answers are treated as reject.
- **Durable CLI** `crossvet run | resume | status` with SQLite checkpoints by default or Postgres (`DATABASE_URL`, extra `postgres`); crashed runs resume without repeating completed model calls.
- **Langfuse tracing** for CLI runs when credentials are set (tokens and cost per model); off and silent otherwise.

## [0.2.0]

### Added
- **Evidence-grounded critic** before the vote: each reviewer finding is judged by a different model as AGREE, DISAGREE_EVIDENCE (exact quote from the research notes, verified in code; unverifiable quotes are downgraded) or DISAGREE_CONCERN. Contradicted findings are dropped; unresolved ones appear in a new **Disputed** section. Critic failures keep findings unchecked and are reported.
- **Run export**: `RUN_EXPORT_PATH` appends each reviewed run (draft, critiques, verdicts, ballots, revision) as JSONL.
- **MCP server** `crossvet-mcp` (stdio) with `ask_model` and `compare_models`, input limits and per-model error isolation.

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
- Example report from a live OpenAI + Claude run in `docs/examples/`.
- Offline end-to-end test: a scripted model drives the full research graph and review.
- Offline unit tests (no API keys, no network) and a GitHub Actions CI workflow (lint, graph build, tests, web build); Dependabot for uv, npm and GitHub Actions.

### Changed
- Upgraded to LangGraph 1.2 and LangChain 1.x; Python 3.13 lockfile.
- Configuration moved to Pydantic v2 idioms (`json_schema_extra`, `ConfigDict`), removing deprecation warnings; new options appear in LangGraph Studio's configuration panel.
- Researcher prompt no longer assumes a specific search tool.

### Removed
- Upstream workflows that required the upstream maintainers' secrets.
