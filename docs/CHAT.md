# Using Crossvet

One chat, any model. You name the model, or name `auto` and Crossvet chooses one and tells you why. Either way it calls that vendor's API, shows what it cost, and logs the turn.

- [Naming a model](#naming-a-model)
- [Letting Crossvet choose: auto](#letting-crossvet-choose-auto)
- [Hermes and other OpenAI-style apps](#hermes-and-other-openai-style-apps)
- [Claude Code, Codex and Cursor (MCP)](#claude-code-codex-and-cursor-mcp)
- [The terminal](#the-terminal)
- [Agents and tools](#agents-and-tools)
- [Costs and caps](#costs-and-caps)
- [The local log](#the-local-log)
- [Ratings and tuning](#ratings-and-tuning)
- [Several vendors at once](#several-vendors-at-once)
- [Code review by another vendor](#code-review-by-another-vendor)
- [Scores from your own use](#scores-from-your-own-use)
- [Routing from scores](#routing-from-scores)
- [Notes, handoffs, reports and backups](#notes-handoffs-reports-and-backups)
- [Settings](#settings)
- [Commands](#commands)

## Naming a model

| You write | Crossvet calls |
|---|---|
| `anthropic:claude-opus-5-5`, `openai:gpt-6.1-sol` | that model, from that vendor's API |
| `google:<model>`, `xai:<model>` | Google's or xAI's OpenAI-compatible API |
| `openrouter:<vendor>/<model>` | that model through OpenRouter (one key for most vendors; real cost reported) |
| `ollama:<model>`, `local:<model>` | a model on your own machine (`OLLAMA_BASE_URL`, `LOCAL_BASE_URL`) |
| a short name (`opus`, `sonnet`, `haiku`, `sol`, `terra`, `luna`, `claude`, `gpt`) | the model it stands for in your settings |
| nothing, `default` or `crossvet` | your `default_model` |
| `auto`, `crossvet/<slot>`, `crossvet/<goal>` | a model Crossvet chooses ([below](#letting-crossvet-choose-auto)) |

`crossvet models` lists your models, their short names, their prices and the default. Any `provider:model` works even if it is not listed. An unknown name is refused with the list of short names; nothing is guessed.

## Letting Crossvet choose: auto

Name `auto` instead of a model (in the app's model menu, with `/model auto`, `ask -m auto`, or the MCP tool `ask`) and Crossvet picks one. The choice is made in code from the request alone (no model is asked), and every choice is explained:

```
$ crossvet route "Fix the race condition in this Go worker pool"
anthropic:claude-opus-5-5 answers. Kind of task: code (difficulty 3): it is about code ("race condition"); it mentions
"race condition". Slot: strong; goal: auto. If it fails, Crossvet tries openai:gpt-6.1-sol.
```

1. **Private first.** A request that looks private (an API key, a card or ID number, "confidential", `[private]`) only goes to the `private` slot, a model on your own machine. With no private slot it is refused and sent nowhere.
2. **Inputs.** Images go to the `vision` slot; a request longer than `[router] long_chars` goes to `long`.
3. **Kind of task.** The rules name one of: code, review, writing, summarize, extract, translate, reasoning, fresh, quick, general, with a difficulty from 1 to 3. `[routes]` maps each kind to a slot (code and reasoning to `strong`; writing and general to `balanced`; quick, summarize, extract and translate to `quick`; review to `reviewer`, which prefers another vendor than the one being reviewed). Hard tasks move up to `strong`.
4. **Your accepted routes.** A route you accepted with `crossvet tune` puts its model first for that kind.
5. **Goal.** `auto` keeps your slot order; `crossvet/cheapest` and `crossvet/best` sort the slot by list price; `crossvet/fastest` by the median time each model took in your own log.

The models after the first are the ladder. After an error, an empty answer or, when JSON was asked for, invalid JSON, Crossvet tries the next one, at most `[router] max_steps` times (`escalate = false` turns this off). A JSON answer is held back until it has been checked, so you never see the one that failed. An answer that has already started streaming is never replaced. A model you named yourself is never switched.

`/why` (or `crossvet why`) shows the last decision: kind, slot, reason, and each attempt with its outcome. `/retry stronger` asks the last question again one slot up (quick → balanced → strong → best). Slots: `quick`, `balanced`, `strong`, `long`, `vision`, `reviewer`, `private`. Without a settings file they are filled from the built-in table with the models your keys can call.

## Hermes and other OpenAI-style apps

Run `crossvet start` and leave it running. It prints:

```
base URL   http://127.0.0.1:8787/v1
API key    any text (not checked on this computer)
model      default, or any name from `crossvet models`
```

In Hermes, set a custom provider in `~/.hermes/config.yaml`:

```yaml
model:
  provider: custom
  base_url: http://127.0.0.1:8787/v1
  default: default
```

Any app that takes an OpenAI base URL (Open WebUI, LibreChat, your own code with the OpenAI SDK) connects the same way.

Which model answers is decided by the request:

1. the latest `/model NAME` typed in the conversation;
2. else the request's `model` field (the app's model menu, filled from Crossvet's `/v1/models`);
3. `default` means your `default_model`;
4. `auto`, `crossvet/<slot>` or `crossvet/<goal>` lets Crossvet choose.

Typed as the whole message, these work in any app and call no model. Crossvet leaves them, and its replies to them, out of what models see:

| Command | What it does |
|---|---|
| `/model NAME` | Use NAME for the rest of this conversation |
| `/model` | Show the model in use |
| `/models` | List your models |
| `/cost` | Spend in this conversation, per model, and today |
| `/why` | Why auto chose the last answer's model |
| `/good`, `/bad [note]` | Rate the last answer |
| `/retry`, `/retry stronger` | Ask the last question again (with the same model, or one slot up) |
| `/help` | This list |

Each response carries a `crossvet` block with the model, the cost, the conversation id, the turn id, any `dropped` request fields, and the `decision` when Crossvet chose. Send `x-crossvet-thread` to set the conversation id yourself, and `x-crossvet-app` to name the app in the log.

## Claude Code, Codex and Cursor (MCP)

```bash
claude mcp add --scope user crossvet -- crossvet mcp     # Claude Code, every project
codex mcp add crossvet -- crossvet mcp                   # Codex
```

Cursor: `crossvet start --no-serve` prints the entry for `~/.cursor/mcp.json`, with the full path to `crossvet` so Cursor finds it.

| Tool | What it does |
|---|---|
| `list_models` | Your models, short names, prices and the default |
| `ask_model(request, model="default", system="")` | Ask one model. The answer ends with a line naming the model, tokens and cost |
| `recent_turns(limit=10)` | The latest questions and answers from every app |
| `ask(request, system="")` | Let Crossvet choose the model (auto); the answer says which and why |
| `explain_route(request)` | Which model auto would choose, and why, without calling one |
| `compare_models(request, models)` | The same request to two to six models (`"opus, sol"`), side by side |
| `challenge(question, answer, author_model="", challenger="")` | A model from another vendor tries to break an answer |
| `rate_answer(turn, rating, note="")` | Rate an answer `good` or `bad` |
| `save_note`, `search_memory`, `load_context` | Notes every app shares, and what Crossvet knows about a topic |
| `handoff_submit(agent, task, cwd)`, `handoff_status`, `handoff_result` | Hand a task to Claude Code or Codex on this computer |

Ask in plain words: "use ask_model with sol to review this function", "ask opus and luna the same question and show both answers". The model you ask does not see your conversation, so include what it needs in `request`. `crossvet mcp --http` serves the same tools over Streamable HTTP on 127.0.0.1:8788.

## The terminal

```bash
crossvet chat --model opus          # chat; /model NAME switches, /why, /good, /bad, /retry, /models, /cost, /new, /quit
crossvet chat --model auto          # let Crossvet choose each time
crossvet ask -m sol "Is 48,000 miles high for a 2019 CR-V?"
git diff | crossvet ask -m sonnet -s "Review this diff for bugs."
```

Answers stream as they arrive, followed by one line: model, tokens in and out, cost, seconds.

## Agents and tools

Hermes and other agents send `tools` and tool results. Crossvet passes the whole request to the model you named and returns its tool calls in the chat-completions shape, streamed as the model writes when the app asks for a stream:

- OpenAI-style providers (Google, xAI, OpenRouter, Ollama, local) get the request as it is.
- Anthropic models get it through Anthropic's OpenAI-compatible endpoint.
- OpenAI models get it through OpenAI's Responses API. On 2026-11-26, gpt-6.1-sol, gpt-6.1-terra and gpt-6-luna all refused tools on chat completions. Crossvet translates each request and reply (text, images, tools, tool choice, parallel calls, output limits, reasoning effort, JSON formats, the older `functions` format) and sends it with `store: false`.
- **Reasoning across tool steps:** when an OpenAI model reasons before calling a tool, its encrypted reasoning is kept in the local log for 7 days, keyed by the tool call, and sent back with the tool's result, so the model continues its train of thought. If OpenAI no longer accepts a kept item, Crossvet sends the same request to the same model once more without it, and says so.
- **Nothing dropped silently:** a field a vendor's API has no place for (for example `seed` or `logprobs` on OpenAI's Responses API) is left out and listed under `crossvet.dropped` in the response and in the log. A request for several answers at once (`n` above 1) is refused with a clear error.

## Costs and caps

- **Cost of each answer:** the vendor's list price times the tokens (`[prices]`, with a built-in table for the models this project tests, dated in `config.py`), or the cost OpenRouter reports. A model with no price shows "price unknown" and counts as $0 for the daily cap; `crossvet doctor` lists such models.
- **Daily cap** (`max_usd_per_day`, default $5): once today's logged spend reaches it, calls stop until midnight.
- **Per-call cap** (`max_usd_per_call`, default $0.50): before each call, the worst case (the request's size plus the full output limit) is priced; a call that could pass the cap is refused before it is made.
- **Refused keys:** a provider that answers 401, 402, or a quota or billing refusal is not called again until you restart Crossvet.
- **Limits:** `max_output_tokens` (4,000), `timeout_seconds` (120) for every call, and `max_request_bytes` (2 MB) for the server.

For a model you named, nothing is retried and no other model is tried: a failed call returns an error that names the model, so you can pick another. With `auto`, the ladder above applies.

## The local log

Every question and answer goes to one SQLite file (`~/.local/share/crossvet/chat.db`, or `CROSSVET_DB`): app, model, tokens, cost, seconds. Turns can't be changed or deleted (SQLite triggers refuse it). The server, the MCP server and the terminal share it, so `crossvet log`, `crossvet cost` and the `recent_turns` tool see every app. It is the same file and table as Crossvet 1.x.

## Ratings and tuning

Rate any answer with `/good` or `/bad [note]` in a chat, `crossvet rate good|bad [--turn N]`, or the `rate_answer` tool. Ratings go to the lab file (below), and to Langfuse when you run `crossvet sync`.

`crossvet tune` shows, per kind of task, how often each model that auto chose was rated good, and proposes putting another model first for a kind when it was rated good clearly more often (at least 5 ratings each and 15 points better). A proposal changes nothing until you run `crossvet tune accept ID`; `crossvet tune rollback ID` undoes an accepted route.

## Several vendors at once

- `crossvet compare -m opus -m sol "..."` (or `compare_models`): the same question to two to six models in parallel, each answer with its cost.
- `crossvet challenge [--turn N]` (or `challenge`): a model from another vendor checks an answer and replies with a verdict, `holds`, `wrong` or `unsure`, and the problems it found. The verdict is read in code; a reply that is not one of those counts as no verdict.
- `crossvet replay -m MODEL [-n 10]`: your recent questions go to another model, and a judge from a third vendor where possible picks the better answer without knowing which is which (the order is shuffled). It prints wins, ties and losses and the cost.
- `crossvet bench [-m MODEL ...] [--suite standard|hard|all] [--run-code]`: 28 tasks from used-car dealer work in Sarasota, Florida, each with an answer key checked in code (no model grades another). It writes a results page and the raw rows to `docs/benchmarks/<date>/`. With `--run-code`, code answers run in a separate Python process with a time limit. The published run of 2026-11-25 is in [benchmarks/2026-11-25](benchmarks/2026-11-25/README.md).

## Code review by another vendor

```bash
crossvet review --staged --task "Stop calls once spend reaches the cap"
crossvet review --base main --task "..."            # this branch against main
git diff | crossvet review --task "..." --json      # any diff
crossvet review --staged --task "..." --fix          # the author model writes a patch; git apply --check must accept it
crossvet review --staged --task "..." --fix --apply --rounds 2   # apply it and review again, at most 3 rounds
```

The reviewer comes from another vendor than the model that wrote the change (`--author`, default your `default_model`; `--reviewer` to name one; otherwise the `reviewer` slot). It gets the task and the diff, fenced as data, and must answer in JSON. Every finding is checked in code before you see it:

- its file must be in the diff;
- its quote must appear word for word on its line, a line the diff shows on the new side (reviewers often miscount by a line: when the quote is on exactly one line within three of the one given, the finding moves there and says so);
- its severity must be `blocker`, `major`, `minor` or `nit`, and it must name a problem.

Findings that fail are dropped and counted, with the reason. With `--fix`, the author model writes one unified diff for the kept findings; it is kept only if `git apply --check` accepts it, and applied only with `--apply`. Each review leaves a decision record in the lab file and in `.crossvet/reviews/` (findings, what was dropped and why, patches, rounds). The MCP tool `review_diff(diff, task, author_model, reviewer)` does the same from any agent.

**Agent packaging.** In Claude Code: `/plugin marketplace add j-zulick/crossvet`, then `/plugin install crossvet@crossvet`, for the `/crossvet-review` command and the `crossvet-review` skill. Codex and Hermes skills are in `integrations/codex/` and `integrations/hermes/` (copy the folder into `~/.codex/skills/` or `~/.hermes/skills/`).

**Review benchmark.** `crossvet bench --review -m MODEL ...` gives each reviewer twelve small changes to Crossvet's own code, each with one planted bug (off-by-one, wrong unit, SQL built from text, a key written to a log, an inverted check, a missing `await`, and others), and counts a catch when a checked finding points at the planted line. The published run is in [benchmarks/2026-11-26-review](benchmarks/2026-11-26-review/README.md). `--set hard` gives twelve subtler bugs (a ladder cut one model short, a lock released before the rows are read, a week written in seconds, a hash that ignores its salt) and six clean changes with no bug; a blocker or major finding on a clean change counts as a false alarm. Its run is in [benchmarks/2026-11-26-review-hard](benchmarks/2026-11-26-review-hard/README.md). `--set all` runs both. `--repeat N` reviews each change N times and adds two columns, bugs caught in every run and bugs caught in only some; [benchmarks/2026-11-27-review-hard-repeat](benchmarks/2026-11-27-review-hard-repeat/README.md) is a three-run result.

## Scores from your own use

Ratings tell you what you liked; a judge can score far more answers. Scoring is off until you turn it on, because the answers go to a second vendor:

```toml
[score]
enabled = true
sample = 0.1             # share of answers judged
max_usd_per_day = 1.0    # the judge's own daily cap
apps = ["terminal", "mcp"]   # only these apps; empty = all
```

- `crossvet score run [--limit 20]` judges a sample of recent answers. Run it on a schedule (launchd, cron, n8n). The judge is `[score] judge`, or the strongest model from another vendor than the answer's; it scores 1 to 5 against a rubric for the kind of task, and its reply is JSON read in code (anything else is kept as "no score"). Which answers are in the sample is decided from the turn id, the same way every time.
- `crossvet score shadow` (with `[score] shadow = true`): for a sample of judged questions a cheaper model (`[score] shadow_model`, else the cheapest in the quick slot) answers too, in the background, and the judge scores it the same way. Nobody sees the shadow answer; it shows whether the cheaper model would have been good enough.
- `crossvet score calibrate` compares the judge with your `/good` and `/bad` on the same answers: agreement and bias, overall and per kind of task. With at least 10 pairs and under 70% agreement, the judge is flagged and its scores are not used for routing.
- `crossvet leaderboard [--days 30]` (or the MCP tool `leaderboard`): per kind of task, each model's mean score, a cautious score (the mean minus one standard error, so a model with few scores ranks lower), and the cost per answer. `crossvet sync` sends judge scores to Langfuse as `judge_score`.

Requests that look private are never judged or shadowed.

## Routing from scores

Once the judge has scored enough of your answers, `auto` can route from those scores instead of the rules:

```toml
[router]
use = "scores"      # rules (default) | scores
margin = 0.3        # score points a cheaper model may trail the best by
min_scores = 20     # judged answers a model needs for a kind before its scores count
explore = 0.05      # share of these requests that try the second choice, so other models keep being scored
```

For each request, among the models with at least `min_scores` judged answers for its kind of task, the cheapest whose cautious score (mean minus one standard error) is within `margin` of the best goes first. About `explore` of the time the second choice goes first instead, and the reason says so. With too few scores, or a judge that `crossvet score calibrate` flagged, the rules decide and the reason says why. A route you accepted with `crossvet tune` still wins.

- `crossvet tune scores` turns the leaderboard into proposals (kind → best-value model), with the evidence; `crossvet tune accept ID` applies one.
- `crossvet tune auto`, for a weekly schedule, changes routes only when `[router] auto_tune = true`. It first rolls back any score route whose model has since scored clearly worse (by more than `margin`) than the model it replaced, then accepts at most one proposal per kind, never for a kind changed in the last seven days. Each change is logged with its evidence.
- `crossvet report --week [--json]`: the last seven days: answers, spend, what the same tokens would have cost on the strongest model (the saving), the mean judged score against the week before, and route changes. `integrations/n8n/crossvet-weekly.json` (an n8n workflow) and `integrations/windmill/crossvet_weekly.py` run `score run`, `tune auto` and `report --week --json` every Monday.

## Notes, handoffs, reports and backups

- **Lab file.** Decisions, ratings, notes, accepted routes and handoffs are kept in a second SQLite file next to the log (`lab.db`, or `CROSSVET_LAB_DB`, or `[lab] path`). The log itself keeps its schema and stays append-only.
- **Notes.** `crossvet note TEXT [--tags T]`, `crossvet notes WORDS`, and the `save_note`, `search_memory` and `load_context` tools: notes every app can find (full-text search).
- **Handoffs.** `crossvet handoff claude-code "TASK" --cwd DIR` (or `codex`) runs that agent headless in the folder with its own defaults (Claude Code in print mode, Codex with a read-only sandbox), so it reads and proposes rather than edits unless you allow it. `handoff status ID` and `handoff result ID` show it; the MCP tools run it in the background.
- **Reports.** `crossvet report [--days 7]` (Markdown), `crossvet dashboard [--out FILE]` (one HTML page, no scripts) and `crossvet export [--out FILE]` (JSON lines with each answer's decision and rating).
- **Langfuse.** `crossvet sync` copies new answers (as traces with a generation), decisions and ratings to Langfuse, and reads back `user_rating` scores added there. Keys: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`. Since 3.6.1 answers go over OpenTelemetry (`/api/public/otel/v1/traces`), which Langfuse v4 requires (Langfuse Cloud turned off the old ingestion for traces on 2026-11-16); scores still use `score-create`, and ratings are read from `/api/public/v3/scores`. A self-hosted Langfuse needs version 3.22 or later for the OpenTelemetry endpoint.
- **Backups.** `crossvet backup DIR` writes consistent copies of both files and their SHA-256 sums; `crossvet restore DIR [--force]` checks the sums before putting them back; `crossvet prune [--days 30]` drops old kept reasoning and finished handoffs. Turns are never removed.

## Settings

Without a settings file, Crossvet uses the models in its built-in table that your keys can call, with short names, and Claude Sonnet 5.5 (or GPT-6.1 Terra) as the default. `crossvet init` writes that as a file you can edit: `~/.config/crossvet/crossvet.toml`, or `./crossvet.toml`, or the path in `CROSSVET_CONFIG`. Example: [crossvet.example.toml](../crossvet.example.toml).

```toml
default_model = "sonnet"
models = ["anthropic:claude-opus-5-5", "anthropic:claude-sonnet-5-5", "openai:gpt-6.1-sol", "openai:gpt-6-luna"]

[names]
opus = "anthropic:claude-opus-5-5"
sonnet = "anthropic:claude-sonnet-5-5"
sol = "openai:gpt-6.1-sol"
luna = "openai:gpt-6-luna"

# The slots auto picks from (first callable model first); private requests only go to "private"
[slots]
quick = ["anthropic:claude-haiku-5-5", "openai:gpt-6-luna"]
strong = ["anthropic:claude-opus-5-5", "openai:gpt-6.1-sol"]
private = ["ollama:gemma3"]

[routes]          # kind of task -> slot (these change the defaults)
writing = "strong"

[router]
goal = "auto"     # auto | best | cheapest | fastest
escalate = true
max_steps = 2

# A price (USD per million tokens) for a model that is not in the built-in table:
# [prices."openrouter:vendor/model"]
# input = 1.0
# output = 5.0

[limits]
max_usd_per_day = 5.0
max_usd_per_call = 0.50
max_output_tokens = 4000
timeout_seconds = 120
max_request_bytes = 2000000
```

Keys come from the environment, `./.env` or `~/.config/crossvet/.env` (the environment wins). [`.env.example`](../.env.example) lists every one.

## Commands

| Command | What it does |
|---|---|
| `crossvet start [--no-serve]` | Check keys, print the settings for each app, serve on 127.0.0.1:8787 |
| `crossvet chat [-m MODEL]` | Chat in this terminal |
| `crossvet ask [-m MODEL] [-s SYSTEM] TEXT` | One question; reads standard input when no text is given |
| `crossvet models` | Your models, short names, prices, the default |
| `crossvet cost [--days N]` | Spend per model |
| `crossvet log [-n N]` | The latest turns from every app |
| `crossvet serve [--host --port]` | The OpenAI-compatible server only |
| `crossvet mcp [--http]` | The MCP server |
| `crossvet init [--path P] [--force]` | Write a settings file from your keys |
| `crossvet doctor` | Check keys, settings and the log; never calls a model |
| `crossvet route [-m auto\|crossvet/SLOT\|crossvet/GOAL] TEXT` | Which model auto would choose, and why; calls nothing |
| `crossvet why` | The latest decision auto made, with each attempt |
| `crossvet rate good\|bad [NOTE] [--turn N]` | Rate an answer (the latest by default) |
| `crossvet tune [accept\|reject\|rollback ID]`, `tune scores`, `tune auto` | Ratings per kind and model; proposals from ratings or scores; accepted routes; weekly automatic changes (opt-in) |
| `crossvet compare -m A -m B TEXT` | The same question to several models |
| `crossvet challenge [--turn N] [-m MODEL]` | Another vendor's model checks an answer |
| `crossvet replay -m MODEL [--judge J] [-n N]` | Past questions on another model, judged blind |
| `crossvet bench [-m M ...] [--suite S] [--limit N] [--run-code] [--out DIR]` | The Sarasota benchmark (`--review [--set planted\|hard\|all] [--repeat N]`: the review benchmark) |
| `crossvet score [run\|shadow\|calibrate] [--limit N] [--all]`, `crossvet leaderboard [--days N]` | Judge a sample of answers (opt-in); score per model and kind |
| `crossvet review --task T [--staged\|--base B] [--author A] [--reviewer R] [--fix [--apply] [--rounds N]] [--json]` | Another vendor reviews a change |
| `crossvet note TEXT [--tags T]`, `crossvet notes [WORDS]` | Save and search notes |
| `crossvet handoff claude-code\|codex TASK [--cwd DIR]`, `handoff status\|result ID` | Hand a task to a coding agent |
| `crossvet report [--days N] [--week [--json]]`, `dashboard [--out F]`, `export [--out F]`, `sync` | Your numbers as Markdown, HTML, JSON lines, or in Langfuse |
| `crossvet backup DIR`, `restore DIR [--force]`, `prune [--days N]` | Look after the local files |
| `crossvet service [install\|status\|uninstall] [--port P] [--weekly] [--no-load]` | Run the server at login, and the weekly job ([DEPLOY.md](DEPLOY.md)) |

Exit codes: 0 success; 1 a failure or problems found; 2 a usage error; 3 a spend cap or a log written by a newer Crossvet.
