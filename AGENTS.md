# Working on Crossvet

Instructions for coding agents (Claude Code, Codex, Cursor) and for people. `CLAUDE.md` points here.

## What this repository is
Crossvet is one chat, any model: you use Claude, ChatGPT, Gemini, Grok or a local model from Hermes, Cursor, Claude Code, Codex or a terminal. You name the model, or name `auto` and Crossvet chooses one, explains why, and learns from your ratings.

**Scope rules:** a model the user named is never switched. Anything that chooses (routing, escalation, tuning) runs only when the request asks for it, is decided in code, explains itself, and is recorded in the lab file. Verdicts from models are read in code, never trusted as prose.

## Layout
- `src/crossvet/core.py`: the one path every request takes: resolve the name, check the caps, call, log
- `src/crossvet/providers.py`: every vendor through one function
- `src/crossvet/relay.py`: agents' requests with tools, streamed; OpenAI through the Responses API (reasoning kept across tool steps), Anthropic through its OpenAI-compatible endpoint
- `src/crossvet/server.py`: the OpenAI-compatible server; `src/crossvet/mcp_server.py`: the MCP tools
- `src/crossvet/routing.py`: `auto` (kind of task -> slot -> model, ladder, private requests); `src/crossvet/classify.py`: the rules that name the kind of task
- `src/crossvet/lab.py`: the second file: decisions, ratings, notes, accepted routes, handoffs
- `src/crossvet/multi.py`: compare, challenge, replay with a blind judge; `src/crossvet/bench.py`: the Sarasota benchmark
- `src/crossvet/review.py`: second-vendor review, findings checked against the diff, fix rounds; `src/crossvet/review_bench.py`: planted-bug cases
- `integrations/`: the Claude Code plugin (`.claude-plugin/marketplace.json` at the root lists it), Codex and Hermes skills
- `src/crossvet/score.py`: the opt-in judge, shadow answers, calibration against ratings, the leaderboard
- `src/crossvet/service.py`: launchd agents and systemd units for the server and the weekly job; `Dockerfile`, `compose.yaml`, `docs/DEPLOY.md`
- `src/crossvet/tuning.py`: proposals from ratings and scores, `tune auto` with rollback; `integrations/n8n/`, `integrations/windmill/`: the weekly job; `src/crossvet/langfuse.py`: sync; `src/crossvet/care.py`: export, report, dashboard, backup, restore, prune; `src/crossvet/handoff.py`: Claude Code and Codex
- `src/crossvet/config.py`: default model, short names, menu, slots, routes, router settings, prices (a dated built-in table), limits, `.env` loading
- `src/crossvet/store.py`: the local log (SQLite, append-only)
- `src/crossvet/cli.py`: the `crossvet` command
- `tests/unit/`: offline tests (no keys, no network), some built from replies recorded from the real APIs (`tests/unit/fixtures/`, no keys, encrypted reasoning shortened); `tests/live/`: real API calls, skipped unless `CROSSVET_LIVE=1`
- `docs/`: `CHAT.md` (the guide), `SETUP.md`, `ARCHITECTURE.md`, `DESIGN-DECISIONS.md`, `SECURITY-MODEL.md`, `STABILITY.md`, `MIGRATING.md`, `live-runs/` (dated real runs), `benchmarks/` (dated benchmark runs), `releases/`

## Commands
```bash
uv sync --all-extras                               # install
uv run pytest tests/unit -q                        # offline tests: must pass before any commit
uvx ruff@0.17.4 check src tests                    # lint
CROSSVET_LIVE=1 uv run pytest tests/live -q -rs    # real API calls with your keys (about $0.05)
uv run crossvet doctor                             # check keys and settings without calling a model
```

## Rules
- Never read, print or commit `.env` or any key. `.env.example` lists every variable with an empty value.
- A claim in the README, a release note or a doc must match the code and the tests in the same commit. Results are published only from real runs, with date, model ids and cost (`docs/live-runs/`). No made-up examples.
- Guards and decisions that decide outcomes (caps, refused accounts, limits, routing, escalation, verdicts) stay in code.
- A new design choice gets an entry in `docs/DESIGN-DECISIONS.md` (context, decision, cost).
- A new setting goes in `.env.example` or `crossvet.example.toml`, in `docs/CHAT.md`, and in a test. `docs/STABILITY.md` lists what stays compatible across 3.x; a test checks it.
- The built-in model table (`config.KNOWN`) changes only with a live run of the new model and its list price, dated.
