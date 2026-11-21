# Working on Crossvet

Instructions for coding agents (Claude Code, Codex, Cursor) and for people. `CLAUDE.md` points here.

## What this repository is
Crossvet is a fork of LangChain's Open Deep Research (MIT). It writes a research report, then has models from several AI vendors review it. Code checks the review: cited URLs must appear in the research notes, a quote used as evidence must appear verbatim in the notes, and stop decisions in deliberation are made by code, not by a model. `crossvet-bench` measures which model to use for each role.

## Layout
- `src/open_deep_research/`: the package
  - `deep_researcher.py`: LangGraph edition (graph `deep_researcher`)
  - `deep_agent.py`: Deep Agents edition (graph `deep_agent`), same review
  - `cross_vendor_review.py`: critiques, anonymized Borda vote, citation check, critic, revision
  - `deliberation.py`, `blind_pass.py`, `support_check.py`: debate rounds and early stopping, the blind first pass, Jev support checks
  - `injection_check.py`, `scan_cli.py`, `review_doc.py`: the prompt-injection check, `crossvet-scan`, and `crossvet review` for existing reports
  - `effort.py`, `guard.py`: effort tiers (`EFFORT`, `--effort`), escalation to a stronger model after a failed check, and the spend cap
  - `models.py`: the model factory (`provider:model`, OpenRouter, local servers) and the capability catalog
  - `bench.py`, `bench_cases.py`: the role benchmark and its synthetic cases
  - `configuration.py`: every setting (environment variable = upper-case field name)
  - `cli.py`, `api.py`, `mcp_server.py`, `compare.py`, `doctor.py`, `setup_wizard.py`, `context.py`, `followup.py`, `dataset.py`, `gateway_search.py`, `tracing.py`
- `src/security/auth.py`: auth handler for LangGraph deployments
- `tests/unit/`: the offline test suite (no keys, no network)
- `tests/*.py`, `tests/expt_results/`: upstream's Deep Research Bench evaluation scripts and results, kept for reference
- `docs/`: design decisions, architecture, evaluation protocol, model selection, benchmark results, release notes
- `web/`: Agent Chat UI (Next.js)

## Commands
```bash
uv sync                          # install
uv run pytest tests/unit -q      # tests: offline, must pass before any commit
uvx ruff@0.17.4 check <files>    # lint: CI's file list is in .github/workflows/ci.yml
uv run crossvet-doctor           # check a configuration without spending tokens
uv run crossvet scan <url|file>  # check a page for prompt injection (no model, no key); `crossvet --help` lists every tool
uvx langgraph dev                # LangGraph Studio
```

## Rules
- Never read, print or commit `.env` or any key. `.env.example` lists every setting with an empty value.
- A claim in the README, a release note or a doc must match the code and the tests in the same commit. Results are published only from real runs, with date, model ids and cost (`docs/EVALS.md`).
- Checks that decide outcomes (citations, quotes, stop rules, support thresholds) stay in code. Don't replace them with a model's judgment.
- A new design choice gets an entry in `docs/DESIGN-DECISIONS.md` (context, decision, cost).
- New setting: add it to `configuration.py`, `.env.example` (empty or default value) and the README, and test it.
- Model names go stale. Defaults come from a benchmark run and are labelled with its date; don't change one without new results.
