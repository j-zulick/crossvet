# Changelog

All notable changes to Crossvet. Versions follow [Semantic Versioning](https://semver.org/); dates are release dates.

## [0.1.0]

First release, built on LangChain's Open Deep Research (upstream `1b7d2e8`).

### Added
- **Cross-vendor review stage** (`cross_vendor_review`) after the draft report: parallel typed critiques from reviewers at different vendors, anonymized and shuffled peer ranking combined with a confidence-weighted Borda count, a deterministic citation check against the research notes, and a revised report ending in *Review notes* (scores, peer-voted best critique, dissent, flagged citations, failed reviewers). Quorum of two.
- Self-hosted models: `ollama:<model>` for any pipeline stage, and `local:<model>` reviewers on any OpenAI-compatible server (llama.cpp, LM Studio, MLX, vLLM). `openrouter:<model>` reviewers with one key.
- Agent Chat UI web frontend (`web/`, Next.js 16 / React 19 / Tailwind 4) and `langgraph.local.json` for local development without auth.
- Offline unit tests (no API keys, no network) and a GitHub Actions CI workflow (lint, graph build, tests, web build); Dependabot for uv, npm and GitHub Actions.

### Changed
- Upgraded to LangGraph 1.2 and LangChain 1.x; Python 3.13 lockfile.
- Configuration moved to Pydantic v2 idioms (`json_schema_extra`, `ConfigDict`), removing deprecation warnings; new options appear in LangGraph Studio's configuration panel.
- Researcher prompt no longer assumes a specific search tool.

### Removed
- Upstream workflows that required the upstream maintainers' secrets.
