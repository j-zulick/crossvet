# Changelog

All notable changes to Crossvet. Versions follow [Semantic Versioning](https://semver.org/). Release notes for each version are in [docs/releases/](docs/releases/).

## [Unreleased]

## [3.6.1] - 2026-11-27

`crossvet sync` works with Langfuse v4 again.

### Fixed
- Langfuse Cloud removed its legacy ingestion for traces on 2026-11-16, so `crossvet sync` failed with HTTP 410. Answers now go to `/api/public/otel/v1/traces` as OTLP/HTTP JSON spans of type `generation` (model, input, output, token usage, cost, session, tags, Crossvet's decision as metadata); scores still go as `score-create` events; ratings added in Langfuse are read from `/api/public/v3/scores`.
- Score ids sent to Langfuse now include a per-install id. Langfuse upserts scores by id, so two Crossvet installs (or a reset log) sharing a project overwrote each other's ratings.
- A refused trace upload stops before any score is sent and leaves the sync cursor where it was.

### Added
- A live check that a synced answer and its rating show up in Langfuse.

## [3.6.0] - 2026-11-27

Repeated benchmark runs, so a steady catch can be told from a lucky one.

### Added
- `crossvet bench --review --repeat N`: each change is reviewed N times; rows carry a `run` number, and the results page adds "bugs caught every run" and "bugs caught in some runs" per reviewer and an N-of-N cell per case.
- Three runs of the hard set: [docs/benchmarks/2026-11-27-review-hard-repeat](docs/benchmarks/2026-11-27-review-hard-repeat/README.md).

### Changed
- GitHub Actions: gitleaks-action 2 → 3 (Dependabot #23).

## [3.5.0] - 2026-11-26

A harder review benchmark that also counts false alarms.

### Added
- `crossvet bench --review --set hard`: twelve subtler planted bugs and six clean changes, each cut from Crossvet's real source (a test checks every context line against the file). A blocker or major finding on a clean change counts as a false alarm; the results page has a false-alarm column. `--set all` runs both sets.
- Benchmark rows record why each dropped finding was dropped (`why_dropped`).
- The hard set's first run: [docs/benchmarks/2026-11-26-review-hard](docs/benchmarks/2026-11-26-review-hard/README.md).
- The README shows a real `crossvet chat` session switching models mid-conversation.

## [3.4.0] - 2026-11-26

The daily driver: run Crossvet in the background on your computer, or on a server.

### Added
- `crossvet service install|status|uninstall`: launchd agents on macOS and systemd user units on Linux for the server (127.0.0.1, started at login, restarted if it stops) and, with `--weekly`, a Monday job that runs `score run`, `tune auto` and `report --week --json` and keeps the report (`service.py`).
- A `Dockerfile` (non-root, health check; refuses to listen beyond localhost without a 16+ character `CROSSVET_TOKEN`) and a `compose.yaml` (port on 127.0.0.1, data in a volume), with a Komodo note, in [docs/DEPLOY.md](docs/DEPLOY.md).
- `.crossvet/` (review records) is ignored in this repository.

## [3.3.0] - 2026-11-26

Route from scores: the cheapest model that your judged answers show is good enough.

### Added
- `[router] use = "scores"`: `auto` puts first, for each kind of task, the cheapest model whose cautious judged score is within `margin` of the best, among models with at least `min_scores` judged answers; `explore` (5%) of these requests try the second choice. Too few scores or an untrusted judge, and the rules decide; the reason says which. Accepted routes still win.
- `crossvet tune scores`: proposals from the leaderboard, with evidence. `crossvet tune auto` (only with `[router] auto_tune = true`): rolls back score routes that did worse than the model they replaced, then accepts at most one proposal per kind a week.
- `crossvet report --week [--json]`: answers, spend, the saving against the strongest model at list price, the mean judged score against the week before, and route changes.
- A weekly n8n workflow and a Windmill script in `integrations/`.
- `[router]` settings `use`, `margin`, `explore`, `min_scores`, `auto_tune`.

## [3.2.0] - 2026-11-26

Scores from your own use: an opt-in judge, shadow answers, calibration and a leaderboard.

### Added
- `crossvet score run`: a judge from another vendor scores a sample of recent answers 1 to 5 against a rubric for the kind of task; its JSON is read in code; its spend has its own daily cap (`score.py`).
- `crossvet score shadow`: a cheaper model answers a sample of judged questions in the background and is judged the same way.
- `crossvet score calibrate`: the judge's agreement and bias against your ratings, overall and per kind; a judge that agrees less than 70% (10+ pairs) is flagged and not used for routing.
- `crossvet leaderboard` and the MCP tool `leaderboard`: mean and cautious score and cost per answer, per model and kind of task.
- `[score]` settings (`enabled` off by default, `sample`, `judge`, `max_usd_per_day`, `apps`, `shadow`, `shadow_sample`, `shadow_model`); judge scores sync to Langfuse as `judge_score`.

### Changed
- "Answer in one sentence" no longer makes a question count as a summary (found by the live run: the judge graded a plain question against the summary rubric).

## [3.1.0] - 2026-11-26

Another vendor reviews your change, and only findings that match the diff are shown.

### Added
- `crossvet review` (`--staged`, `--base`, or a diff on standard input) and the MCP tool `review_diff`: a reviewer from another vendor than the author model answers in JSON; each finding is kept only when its file, new-side line, quote and severity check out against the diff (`review.py`). Dropped findings are counted with the reason.
- `--fix`: the author model writes a patch for the kept findings, kept only if `git apply --check` accepts it; `--apply --rounds N` applies it and reviews again (at most 3 rounds). Every review leaves a decision record (lab file and `.crossvet/reviews/`).
- The review benchmark, `crossvet bench --review`: twelve changes to Crossvet's own code with one planted bug each, catches counted in code (`review_bench.py`), with the run of 2026-11-26 in `docs/benchmarks/`.
- A Claude Code plugin (`/crossvet-review` and the `crossvet-review` skill; `.claude-plugin/marketplace.json`), and skills for Codex and Hermes, in `integrations/`.

## [3.0.0] - 2026-11-26

Pick the model yourself, or let Crossvet choose and show why. Everything 2.x did still works the same; choosing is opt-in per request. Moving from 2.x or 1.x: [docs/MIGRATING.md](docs/MIGRATING.md).

### Added
- `auto`, `crossvet/<slot>` and `crossvet/<goal>` as model names (`routing.py`): the kind of task (from text rules, `classify.py`) picks a slot, the goal orders it, and each choice is explained (`/why`, `crossvet route`, `crossvet why`, the `decision` block in responses) and recorded with every attempt.
- Escalation for `auto`: after an error, an empty answer or invalid JSON (JSON answers are held back until checked), the next model on the ladder is tried, at most `[router] max_steps` times. A named model is never switched.
- Private requests under `auto` (keys, card and ID numbers, "confidential", `[private]`) only go to the `private` slot, and are refused when it is empty.
- Settings `[slots]`, `[routes]`, `[router]` (`goal`, `escalate`, `max_steps`, `private_auto`, `long_chars`) and `[lab]`; built-in slots from the models your keys can call.
- A second local file, `lab.db` (`lab.py`): decisions, ratings, notes, accepted routes and handoffs, keyed by turn id; the log keeps its schema.
- Ratings: `/good`, `/bad`, `crossvet rate`, `rate_answer`. Tuning: `crossvet tune` proposes routes from ratings; nothing changes until you accept, and accepted routes roll back.
- Several vendors: `crossvet compare` and `compare_models`; `crossvet challenge` and `challenge` (another vendor's verdict, read in code); `crossvet replay` (past questions on another model, blind judge).
- The Sarasota used-car benchmark: `crossvet bench` (28 cases scored in code, optional `--run-code` in a separate process), with the run of 2026-11-25 in `docs/benchmarks/`.
- Notes (`note`, `notes`, `save_note`, `search_memory`, `load_context`), handoffs to Claude Code and Codex (`handoff`, `handoff_submit`, `handoff_status`, `handoff_result`), `report`, `dashboard`, `export`, Langfuse `sync` (and ratings read back), `backup`, `restore` (checks SHA-256 sums) and `prune` (never removes a turn).
- `/retry` and `/retry stronger` in chats; the terminal chat gains `/why`, `/good`, `/bad`, `/retry`.
- 11 MCP tools next to the 3 from 2.x.

### Changed
- "ZIP code", "promo code" and the like no longer count as program code when naming the kind of task, and a short fact followed by one short question counts as a quick task (both found by the live run).
- `crossvet chat route` and the other 1.x spellings work again instead of printing "removed"; `routes`, `feedback` and `learn` point to `tune` and `rate`.

### Fixed
- The log can be used from several threads at once: the server's thread pool and `compare`'s parallel calls share one connection, and simultaneous queries could fail ("bad parameter or other API misuse") or return no row, because sqlite3 reuses one prepared statement for the same SQL. Every statement now runs and is read under one lock (`store.LockedDB`); the lab file uses the same. Found by a live run of `compare`.
