# Crossvet chat

One chat in front of several vendors' models. Each request is classified and routed to a model suited to it. You can always see why that model was picked and what the answer cost, and a model from another vendor can be asked to break an answer.

`crossvet chat` is a separate tool from the research pipeline. It shares the repository, the install and the rule that outcomes are decided in code.

- [Start](#start)
- [How a request is routed](#how-a-request-is-routed)
- [Routers and Jev](#routers-and-jev)
- [The guard](#the-guard)
- [Use it from other apps](#use-it-from-other-apps)
- [Shared memory](#shared-memory)
- [Recording and ratings](#recording-and-ratings)
- [Tuning the routes](#tuning-the-routes)
- [Replay and datasets](#replay-and-datasets)
- [Handoffs between models, apps and agents](#handoffs-between-models-apps-and-agents)
- [Commands](#commands)
- [Settings](#settings)
- [Limits](#limits)

## Start

```bash
crossvet chat init --openrouter    # write crossvet-chat.toml from OpenRouter's current model list (no key needed for this step)
crossvet chat doctor               # check keys and slots without calling a model
crossvet chat                      # talk; /help lists the commands
```

Set `OPENROUTER_API_KEY` in `.env` (one key reaches most vendors), or the vendors' own keys. `crossvet chat init` without `--openrouter` fills the slots from the keys you have, with dated example model ids.

Every answer ends with one line: the model, the kind of task, the slot, and the cost.

```
> Fix the race condition in this Go worker pool
...
[openrouter:anthropic/claude-... · code → strong · $0.0123]
```

## How a request is routed

Code, not a model, makes the choice:

1. **Kind of task.** Text rules sort the request into code, review, writing, summarize, extract, translate, reasoning, fresh (current events), quick (one short question) or general. An unclear request is "general", never "quick".
2. **Difficulty.** 1 to 3. Words such as "architecture", "security" or "end-to-end", a long request, or three or more parts make it harder.
3. **Slot.** Each kind starts in a slot (`[routes]` in the settings): quick, balanced, strong, fresh, long or reviewer. A hard task moves up to strong; `--effort high` moves up one slot, `--effort low` down one.
4. **Fit.** Models whose context window is too small for the input are skipped; if none fit, the `long` slot is used.

`crossvet chat route "request"` shows the decision without calling a model. In a chat, `/why` shows it for the last answer.

## Routers and Jev

Five routers (`[router] use`, `CROSSVET_CHAT_ROUTER`, `--router`, `/router` in a chat, or the header `x-crossvet-router`):

| Router | Who picks | Cost to decide |
|---|---|---|
| `rules` (default) | The text rules above | Free |
| `jev` | Jev names the kind of task and the difficulty; your slots and routes still pick the model. Below `jev_min_confidence`, or when Jev fails, the rules decide | One small Jev call |
| `openrouter-auto` | OpenRouter's Auto Router (`openrouter/auto`) | Billed at the chosen model's price |
| `openrouter-auto-code` | OpenRouter's router for coding work (`openrouter/auto-code`) | Same |
| `jev-router` | TypeSafe's Jev Router on OpenRouter (`typesafe/jev-router`), which also picks the reasoning effort | Same |

- With a hosted router, the model it chose is recorded (`served by …` in the answer line, `served_by` in Langfuse), and the slot the rules pick is the fallback when the hosted call fails a check.
- A named slot or model skips the router; such turns are recorded with router `manual`.
- Jev is TypeSafe's decision model. It answers typed questions about text (a choice, a yes/no probability) rather than writing text. Crossvet reaches it through OpenRouter's Decisions API with the same `OPENROUTER_API_KEY`; input is billed and output is free. The Decisions API is in alpha.
- The router is recorded on every turn, so `crossvet chat tune` and Langfuse can compare routers on your own use.

**Answer check.** With `[router] check = "jev"`, after an answer passes the code checks, Jev is asked whether it addresses the request. Below `check_threshold` (default 0.2), the guard tries the next model, as for an empty answer. If Jev fails, the answer goes through. Off by default; each check is one small Jev call.

## The guard

The next model in the slot is tried only when the one before fails a check code can make: the call errors, the answer is empty, it stops at the output limit, JSON was asked for and the answer is not valid JSON, or (with the answer check on) Jev's probability is below the threshold. Every attempt and its reason is saved with the turn.

`[limits]` in the settings set a daily cap and a worst-case per-call cap, in USD. Calls whose price is unknown cannot be capped.

## Use it from other apps

**One step:** from the folder that holds your `.env`,

```bash
crossvet chat start                # writes crossvet-chat.toml if there is none, checks your keys,
                                   # prints the Hermes and Cursor settings, then serves (Ctrl-C stops it)
```

`--no-serve` prints the settings only; `--port` changes the port. It stops with what to add when no model in quick, balanced or strong can be called with your keys.

**Hermes.** Add a custom OpenAI-compatible provider:

| Field | Value |
|---|---|
| Base URL | `http://127.0.0.1:8787/v1` |
| Model | `auto` (or `crossvet/quick`, `crossvet/balanced`, `crossvet/strong`, `crossvet/long`, `crossvet/fresh`) |
| API key | any text on this computer; the value of `CROSSVET_CHAT_TOKEN` if you set one |

Keep `crossvet chat start` running while you chat. Answers stream as they are written. Hermes can also reach the MCP tools below. These steps have not yet been checked against a live Hermes install.

**Cursor.** Cursor reaches Crossvet through MCP tools (see why below). Add to `~/.cursor/mcp.json`, with your own folder:

```json
{"mcpServers": {"crossvet": {"command": "bash", "args": ["-lc", "cd ~/crossvet-work && crossvet chat mcp"]}}}
```

The `cd` makes the server read `.env` and `crossvet-chat.toml` from that folder. `crossvet chat start --no-serve` prints this entry with your folder filled in. Then ask Cursor's agent to use the `ask`, `compare_models` or `challenge` tools. Not yet checked against a live Cursor install.

**Any chat app that takes an OpenAI-style URL** (Open WebUI, LibreChat, Hermes, scripts):

```bash
crossvet chat serve                # http://127.0.0.1:8787/v1, model "auto"; activity page at http://127.0.0.1:8787/
```

- **Streaming.** With `"stream": true` each piece of text is sent as it arrives, and a closing chunk carries the model, usage and the `crossvet` object. A model that fails before sending any text is skipped for the next one in the slot, as without streaming. Text already sent can't be taken back, so a later problem (cut off at the output limit, broken JSON, a dropped connection) is recorded on the turn and no other model is tried; the Jev answer check is not run on streamed answers. Requests that fail before any text get an HTTP error, as without streaming. Agent requests with tools are answered in one piece.

- Model names: `auto` (the router decides), `crossvet/<slot>`, or `provider:model`.
- Each response carries a `crossvet` object: model, slot, kind, the reason, cost, thread, turn id.
- **Agents keep their tools.** A request with `tools` (or with tool results) is routed on its latest user message and passed through to the chosen model unchanged. A tool loop stays on the model that started it. Tool calls pass through OpenAI-style APIs only, so use `openrouter:anthropic/<model>` rather than `anthropic:<model>` in slots that agents use.
- Typed as the whole message, `/why`, `/retry stronger`, `/good` and `/bad` work from any chat app.
- The server listens on localhost. Set `CROSSVET_CHAT_TOKEN` to require a bearer token; it refuses any other address without one.

**MCP clients** (Claude Code, Codex, Cursor, Hermes):

```bash
claude mcp add crossvet-chat -- crossvet chat mcp
```

Thirteen tools: `ask`, `ask_model`, `compare_models`, `challenge`, `explain_route`, `save_note`, `load_context`, `search_memory`, `recent_turns`, `rate_answer`, `handoff_submit`, `handoff_result`, `handoff_status`. The assistant you are talking to keeps the conversation; the tools reach the other vendors.

**Cursor's "Override OpenAI Base URL"** is not recommended: Cursor calls that URL from its own servers, so a local address does not work, and the override also redirects Cursor's own models. Use the MCP server in Cursor.

## Hosted: Cursor's chat, the ChatGPT and claude.ai apps, your phone

On your own server, behind HTTPS, the same chat works from anywhere: Cursor can use it as its chat model (its base-URL override needs a public address), and the ChatGPT and claude.ai apps can connect to the MCP server after you sign in. [`deploy/chat/`](../deploy/chat/README.md) has the Docker Compose files: the API, the MCP server with sign-in, and Caddy for the certificate.

- **The API** (`crossvet chat serve --host 0.0.0.0`) requires `Authorization: Bearer <CROSSVET_CHAT_TOKEN>`.
- **The MCP server** (`crossvet chat mcp --http --host 0.0.0.0 --public-url https://your-domain`) signs in its owner over OAuth: an app registers itself, sends you to `/login`, and you enter `CROSSVET_CHAT_TOKEN` (at least 16 characters); only then does the app get a code, which it trades for an access token (1 hour) and a refresh token (30 days, replaced on every use). PKCE is required; only hashes of codes and tokens are stored; tokens are accepted only for this server; requests for any other host are refused; five wrong passphrases in 15 minutes lock sign-in for the rest of that window.
- Without `--public-url`, the HTTP transport only listens on localhost.

The kit has not yet been run on a live server; `deploy/chat/README.md` lists what to check.

## Shared memory

One SQLite file (`~/.local/share/crossvet/chat.db`, or `CROSSVET_CHAT_DB`) holds every turn and every note, from every app. The database refuses updates and deletes. Notes are shown to models inside a marked block, as reference data, never as instructions.

**Backup, restore and retention.**

```bash
crossvet chat backup                       # a consistent copy (safe while the server runs): crossvet-chat-backup-<time>.db
crossvet chat backup ~/Backups/chat.db
crossvet chat restore ~/Backups/chat.db --yes          # the current store is saved next to it first
crossvet chat prune --older-than 180 --yes             # keep the last 180 days of turns; a backup is saved first
```

Every copy is checked (SQLite's integrity check, and that it is a Crossvet chat store) before it is used. The store refuses deletes, so `prune` builds a new file with the turns of the last N days and their ratings, keeps every note, the routing table, its evidence and handoffs, keeps the store's id (so Langfuse trace ids still match), and puts it in place of the old one. Stop `crossvet chat serve`, `start` and any MCP server before `restore` or `prune`: a process that keeps the old file open would go on writing to it. Without `--yes`, both say what they would do and stop.

## Recording and ratings

Every turn and every rating is written to the local store first. Copies go to Langfuse, a JSON-lines file, or both (`[record]` in the settings). A copy that fails never breaks a turn.

**Langfuse.** Install with the `langfuse` (or `all`) extra, then set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and, for a self-hosted instance, `LANGFUSE_BASE_URL` in `.env`. `crossvet chat doctor` says when the keys are set but the package is missing. With the default `sink = "auto"`, each answer becomes one generation on its own trace:

- the model, and the model a hosted router picked;
- metadata: kind of task, difficulty, slot, router, the reason in words, every attempt, seconds, and whether tools were called;
- tokens and cost;
- the thread as the Langfuse session, the app as the user, and tags `kind:…`, `slot:…`, `router:…`, `escalated`.

**Ratings.** Each is a score on the answer's trace:

| Score | Value | Given by |
|---|---|---|
| `user-feedback` | 1 good, 0 bad | `/good`, `/bad [comment]` in any chat; `crossvet chat feedback good\|bad [--turn ID]`; `POST /api/feedback {"turn": ID, "value": "good"}`; the MCP tool `rate_answer` |
| `retried` | 1 | `/retry` |
| `switched` | 1 | the next turn in the thread asked for a different model |
| `escalated` | 1 or 0 | set when the answer is recorded: the first model failed a check |

A turn's trace id is derived from its id and the store's own id, so a rating given later, from another app, lands on the same trace.

**Privacy.** `content = "metadata"` leaves request, answer and comment text out of the copies; the local store keeps them.

**OpenRouter Broadcast** can also send every OpenRouter call to Langfuse without code. If both are on, each call appears twice; only Crossvet's trace carries the routing reason and the ratings.

`crossvet chat log --thread ID` shows each answer's turn id and its ratings.

**Ratings added in Langfuse.** Scores you add in Langfuse's interface (on a trace, or through an annotation queue) count too:

```bash
crossvet chat sync                  # read the last 30 days of Langfuse scores named user-feedback; save new ones here
crossvet chat sync --days 7 --score my-score
crossvet chat tune --sync           # sync first, then tune
```

Only scores people added in Langfuse (source `ANNOTATION`) are read; the ones Crossvet sent are skipped, and each score is saved once. A score is matched to its answer by trace id, so only answers saved by this store can be matched. Its value becomes good or bad in code: a number from 0 to 1 (0.5 and above is good), true or false, or a label such as good, bad, positive, negative, yes, no, up, down, or a thumbs-up or thumbs-down sign. Anything else is listed and not saved. Create the score in Langfuse with the same name (`user-feedback`) as a numeric 0–1, boolean or categorical good/bad score.

**Weekly report.**

```bash
crossvet chat report                # the last 7 days: answers and cost, cost per model, ratings per kind of task, proposals
crossvet chat report --days 30 --out report.md
crossvet chat report --langfuse     # also post it to Langfuse as a trace named crossvet-weekly-report
```

Every number is counted from the local store; proposals use the same rule as `crossvet chat tune`.

## Tuning the routes

The routing table says, per kind of task, which slot to use, which vendors come first, which models to try first and which to avoid. It lives in the chat store with every version kept. Code never changes it on its own: you do, by one of three routes.

**The starting table** (version 0) is judgment, not measurement, dated 2026-11-23. It reorders the models within a slot by vendor; slots still come from `[routes]`:

| Kind | Vendors first | Why |
|---|---|---|
| code | anthropic, openai | These vendors' top models are the common choice of coding agents |
| reasoning | openai, google, anthropic | They lead the public reasoning benchmarks |
| writing | anthropic, openai | Their mid-tier models are widely used for prose |
| translate | google, openai | Large multilingual training data |
| fresh | x-ai, perplexity, google | Live search or real-time data |
| quick, summarize, extract, general, review | (slot order) | Cheap first, checked in code; review's vendor rule is in code |

`crossvet chat routes show` prints the table with each line's reason, date and author; every answer's `/why` names the version that shaped it.

**1. Your own choice.**

```bash
crossvet chat routes set code --models openrouter:anthropic/claude-... --prefer anthropic,openai --why "best on my repos"
crossvet chat routes set fresh --slot fresh --avoid grok-2 --why "stale results"
crossvet chat routes history          # every version, who and why
crossvet chat routes rollback 3       # restore version 3 as a new version
crossvet chat routes reset code       # back to the starting line for code
```

**2. Evidence from other people's posts or your notes.**

```bash
crossvet chat routes import saved-post.html notes.txt https://example.com/post
crossvet chat routes import ~/model-posts/                # every .txt, .md and .html file in the folder (up to 500)
crossvet chat routes import --urls reading-list.txt       # one URL or file path per line; lines starting with # are skipped
crossvet chat routes import --manual my-claims.jsonl      # rows: kind, model, verdict (good/bad), vendor, model_id, quote
crossvet chat routes evidence                             # pending claims, each with what accepting it would change
crossvet chat routes accept 4 7       # or: reject 5; --one decides only that claim, not its repeats
```

For each post, in this order:

1. The prompt-injection check (the same one as `crossvet scan`) reads it. If it matches, the post is not sent to a model.
2. A model from your balanced slot lists claims ("model X is good or bad at task Y") with an exact quote.
3. Code keeps a claim only if its kind is known, its verdict is good or bad, and its quote appears in the post verbatim.
4. Kept claims wait as pending evidence.

After each post, every kept claim is listed with what accepting it would change, and whether it repeats or contradicts a claim from an earlier post.

**Repeats and conflicts.** Claims with the same kind, model and verdict are the same claim, whichever post they came from; provider prefixes are ignored (`openrouter:openai/gpt-x`, `openai/gpt-x` and `gpt-x` are one model). `routes evidence` shows each claim once with the number of posts that made it, and marks claims that another post contradicts (same kind and model, opposite verdict). Accepting or rejecting a claim decides its repeats too, with one change to the table; `--one` decides only the claim named.

Accepting a "good" claim puts the matching model from your slots first for that kind, or its vendor first if no configured model matches (`--model provider:model` overrides). Accepting a "bad" claim adds the model to the kind's avoid list. A post already imported is skipped unless `--again` is given. Posts and claims stay in the local store; nothing is sent anywhere but the extraction call. Sites that refuse automated reads can be saved from the browser and imported as files.

**3. Your own ratings.**

```bash
crossvet chat tune                  # per kind and model: answers, rated, share rated good, trouble, escalations, cost per answer
crossvet chat tune --days 30
crossvet chat tune --apply code     # accept the proposal for code
```

"Trouble" is the share of answers that were retried, switched away from, or rated bad. A proposal names the best-rated model for a kind when it beats the current first choice by 10 points (ties go to the cheaper one). Proposals resting on fewer than `[tuning] min_ratings` ratings (3) are marked weak; whether to apply them is your call.

**Exploration.** `[tuning] explore = 0.05` makes 5% of routed requests try the second choice first, so models that rarely answer still collect ratings. Off by default; at most 0.5; never applied to a named slot or model or a hosted router.

## Replay and datasets

**Would another router or table have done better on my own history?**

```bash
crossvet chat replay                                      # the rules and your current table
crossvet chat replay --router rules --router jev --yes    # jev costs one small Jev call per question
crossvet chat replay --table 0 --table 4                  # the starting table and version 4, with the rules router
```

For every saved answer (tool-call turns excluded), each setup's first choice is compared with the model that actually answered:

- **same model**: how often it agrees with what happened;
- **keeps good answers**: of the answers you rated good, how many it would send to the same model;
- **moves troubled ones**: of the answers retried, switched away from or rated bad, how many it would send elsewhere;
- the most common changes, as "from → to".

No answering model is called. Hosted routers pick at answer time, so they never match a past model here.

**Judged re-answers** (costs money):

```bash
crossvet chat replay --router openrouter-auto --run --sample 20 --max-usd 2 --out duels.jsonl
```

For a sample of questions where a setup would pick a different model, that model answers again. A judge from a third vendor (reviewer slot first, then strong, then balanced) compares the new answer with the original, in random order and without names. Code tallies the verdicts per setup and stops before the cap. Nothing is saved as a chat turn.

**Datasets.**

```bash
crossvet chat export --dataset chat-ratings              # a Langfuse dataset (created if missing; re-exporting updates items)
crossvet chat export --jsonl ratings.jsonl --only all     # JSON lines: all, rated (default), good or bad
```

Each item holds the request, kind and difficulty as input; the answer as expected output when you rated it good; the model, router, rating and cost as metadata; and a link to its trace. With `[record] content = "metadata"`, text is left out unless `--full` is given.

## Handoffs between models, apps and agents

A handoff passes one piece of work, as a versioned JSON packet, to a worker from another vendor, and accepts the result only after code checks it.

```bash
crossvet chat handoff pilot ./pilot          # the synthetic pilot: packet, result schema, digest file, run-claude.sh, run-codex.sh
sh ./pilot/run-claude.sh                     # on a machine with Claude Code signed in
crossvet chat handoff import ./pilot/claude-result.json --exit "$(cut -d' ' -f2 ./pilot/claude-exit.txt)"
crossvet chat handoff show assistant-handoff-001
```

**Packets.** A packet needs `task_id` and `revision`; a claim review also has `source`, `claim` and `instruction`. Missing request fields are filled: `schema_version`, `parent_revision`, `project`, the packet's SHA-256 as `artifact_digest`, `objective`, `acceptance`, `allowed_tools`, `role`, a deadline (one hour), `attempt_limit` (2) and `data_scope` (synthetic). `crossvet chat handoff new packet.json [--kit DIR]` queues your own packet.

**Workers** (`crossvet chat handoff send TASK --worker ...`):

| Worker | What happens |
|---|---|
| `model` (default) | A model answers through `crossvet chat`: `--model provider:model`, else a reviewer from another vendor than the packet's `author_model`, else the reviewer slot |
| `claude-code` | `claude -p` with JSON output, the result schema, no tools and an empty MCP configuration, where Claude Code is installed |
| `codex` | `codex exec --json --sandbox read-only --output-schema … --output-last-message …`, where Codex is installed |
| `file` | Writes the kit; give `packet.json` to any chat or agent, save its JSON reply, and `import` it |

**Checks in code** before a result is accepted: the task id and revision match the request and the revision is the newest; the reviewed digest, when given, matches; for a claim review, the verdict is supported, contradicted or unknown, and the quote is in the source verbatim. Otherwise the result is recorded as `rejected` with the reasons.

**Queue.** Every step is an append-only event in the chat store: queued, claimed, succeeded, failed, rejected, uncertain, reconciled, cancelled. A duplicate packet (same task, revision and content) returns the existing request; an older revision is refused; claims are atomic; attempts stop at the limit; a claim past its deadline is refused. An attempt with no result (a timeout, a missing file) becomes `uncertain`; `crossvet chat handoff reconcile` marks long-running ones, and `resolve TASK` records that you checked it did not finish before another attempt starts. A CLI worker's exit status is kept apart from the verdict its model declares. Claude Code session ids are kept only as a shortened reference.

**From other apps.** The MCP server has `handoff_submit`, `handoff_result` and `handoff_status`, so Claude, Codex, Cursor, Hermes or a ChatGPT connector can share one queue.

## Commands

| Command | What it does |
|---|---|
| `crossvet chat` | Talk in one thread. `/model`, `/slot`, `/why`, `/retry [stronger]`, `/good`, `/bad`, `/challenge`, `/note`, `/cost`, `/new`, `/quit` |
| `crossvet chat ask "request"` | Answer once |
| `crossvet chat route "request"` | The routing decision, free |
| `crossvet chat compare "request" -m A -m B` | Several models side by side |
| `crossvet chat challenge` | A model from another vendor tries to break the last answer; only objections that name a concrete failure case are kept |
| `crossvet chat note add KEY "text"` / `list` / `search` | Shared notes |
| `crossvet chat log [--thread ID] [--why]` | What was asked, who answered, why, the cost, turn ids and ratings |
| `crossvet chat feedback good\|bad [--turn ID] [--comment TEXT]` | Rate an answer (default: the latest) |
| `crossvet chat bench -m A -m B [--apply]` | Twelve code-scored cases per model; `--apply` writes the best-value models into the slots |
| `crossvet chat routes show\|history\|set\|reset\|rollback` | The routing table you tune |
| `crossvet chat routes import\|evidence\|accept\|reject` | Evidence from posts and notes |
| `crossvet chat tune [--days N] [--apply KIND] [--sync]` | How each model did per kind of task, from your ratings, with proposals |
| `crossvet chat sync [--days N] [--score NAME]` | Save ratings people added in Langfuse as ratings here |
| `crossvet chat report [--days 7] [--out FILE] [--langfuse]` | Cost per model, ratings per kind of task and proposals |
| `crossvet chat start [--no-serve]` | Config, key check, Hermes and Cursor settings, then the server |
| `crossvet chat backup [PATH]` / `restore PATH --yes` / `prune --older-than DAYS --yes` | Copy, restore or trim the store |
| `crossvet chat replay [--router R] [--table V] [--run]` | How other routers or table versions would have routed your history |
| `crossvet chat export --dataset NAME \| --jsonl FILE` | Answers and ratings as a Langfuse dataset or JSON lines |
| `crossvet chat handoff pilot\|new\|send\|import\|show\|list\|kit\|reconcile\|resolve\|cancel` | Versioned packets between models, apps and agents |
| `crossvet chat serve` | The OpenAI-style server |
| `crossvet chat mcp [--http]` | The MCP server |

## Settings

`crossvet-chat.toml` in the working folder, else `~/.config/crossvet/chat.toml`, else the path in `CROSSVET_CHAT_CONFIG`. [`crossvet-chat.example.toml`](../crossvet-chat.example.toml) lists every section. Keys stay in the environment.

| Environment variable | What it does |
|---|---|
| `CROSSVET_CHAT_CONFIG` | Path of the settings file |
| `CROSSVET_CHAT_DB` | Path of the shared memory |
| `CROSSVET_CHAT_TOKEN` | Bearer token the server requires; the passphrase for signing in to the hosted MCP server |
| `CROSSVET_CHAT_ROUTER` | Override the router for every request |
| `CROSSVET_CHAT_PUBLIC_URL` | Hosted MCP server: the https:// address apps reach; turns on sign-in |
| `CROSSVET_CHAT_OAUTH_DB` | Where sign-in clients and token hashes are kept |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Langfuse, shared with the research pipeline |

`[limits]` in the settings file: `max_usd_per_day` and `max_usd_per_call` (spend caps; 0 = none), `max_output_tokens` (4000), `timeout_seconds` (120: one model call, start to finish) and `max_request_bytes` (2,000,000: larger requests to the server get HTTP 413).

## Limits

- The task rules and the starting table are judgment, written from common requests and public reputation. They have not been measured against a labelled set.
- The Claude Code and Codex workers have been tested with a stand-in for the command; their flags follow the integration handoff of Nov 22 and should be checked against `claude --help` and `codex exec --help` on the machine that runs them.
- The replay judge is one model's opinion; verdicts are counted in code but not checked against an answer key.
- Extraction from posts depends on a model finding the claims; the verbatim-quote check stops invented claims, not missed ones.
- Agent requests with tools are not streamed: the finished reply, tool calls included, is sent as one chunk.
- Tool calls cannot pass through the direct Anthropic API.
- Jev's answers and the hosted routers have been tested only against stand-ins. The Decisions API is in alpha and may change shape.
- Not yet run against real models: only the offline tests, and `init --openrouter` against OpenRouter's public model list.
