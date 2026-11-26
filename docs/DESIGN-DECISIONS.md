# Design decisions

Each entry: the context, the decision, and what it costs.

## 1. You name the model, unless you ask Crossvet to choose (3.0)
**Context.** People who use several models usually know which one they want, and a router that guesses silently is hard to trust. But for routine work ("summarize this", "fix this bug") naming a model every time is friction, and the right choice can be learned from your own ratings.
**Decision.** A request names its model, or gets `default_model`, and a named model is never switched. Choosing is opt-in per request: the name `auto` (or `crossvet/<slot>`, `crossvet/<goal>`). Every choice is made in code from the request alone, is explained in words (`/why`, `crossvet route`), and is recorded with each attempt.
**Cost.** Two ways of working in one tool. The rules are simple text patterns: they err upward (an unclear request is "general", never "quick") and they can be wrong, which is why the explanation is always one command away.

## 2. Meet each chat where it is: an OpenAI-compatible server, MCP tools, and a terminal
**Context.** Hermes and most chat apps take an OpenAI base URL; Claude Code, Codex and Cursor take MCP servers.
**Decision.** One core (`core.py`) behind three thin entry points. The server lists your models at `/v1/models` so the app's own model menu works, and accepts `/model NAME` typed in any app.
**Cost.** `/model` typed in the chat has to be found in the history the app sends back; Crossvet strips those commands and its replies before a model sees the conversation.

## 3. Pass agents' tools through; translate only where a vendor requires it
**Context.** Agents such as Hermes send tools and tool results on every request. On 2026-11-26, OpenAI's gpt-6.1-sol, gpt-6.1-terra and gpt-6-luna all refused tools on chat completions (Sol refused them with any reasoning setting); Anthropic's native API uses a different tool format.
**Decision.** Requests with tools go through whole, streamed when the app streams (`relay.py`): OpenAI-style providers as they are, Anthropic through its OpenAI-compatible endpoint, OpenAI through the Responses API with a translation in each direction and `store: false`. In addition:
- OpenAI's encrypted reasoning is requested (`include: reasoning.encrypted_content`), kept per tool-call id for 7 days, and sent back with the tool results, which is how a stateless client keeps a reasoning model's chain of thought across tool steps. Checked live on 2026-11-26: Sol at high effort reasoned before its tool call, and the kept reasoning was accepted on the next step.
- A field the Responses API has no place for is dropped and reported (`crossvet.dropped`), never silently.
- The translation is tested against replies recorded from the real APIs (`tests/unit/fixtures/`).
**Cost.** One exception to "nothing is resent": when OpenAI rejects kept reasoning (`invalid_encrypted_content`, for example after a key or organization change), the same request goes to the same model once more without it, and the response says so. Responses-only features beyond the chat-completions shape are not exposed.

## 4. Guards are code, and run before the call
**Context.** Spending money is the main way a multi-vendor chat goes wrong: a runaway agent loop, an expensive model on a huge input, a revoked key that keeps being called.
**Decision.** A daily cap, a per-call worst-case cap at list price, and a per-process block on a provider that refused the account (401, 402, or a quota or billing refusal, decided from the HTTP status and the error text). All three raise before the request leaves.
**Cost.** The caps are only as good as the prices: a model with no price counts as $0 (`doctor` lists them). The per-call estimate assumes the full output limit, so it is deliberately pessimistic.

## 5. One local, append-only log shared by every app, and a separate lab file
**Context.** Knowing what was asked, of which model, at what cost, matters more when several apps share one set of keys. Decisions, ratings and notes change over time; the record of what was asked must not.
**Decision.** One SQLite file in WAL mode, with triggers that refuse updates and deletes, for turns. Decisions, ratings, notes, accepted routes and handoffs go to a second SQLite file keyed by turn id (`lab.py`), so the log keeps its schema and older releases can still open it. `backup` copies both with SHA-256 sums; `prune` frees side tables and never removes a turn.
**Cost.** Two files to look after instead of one; `backup` and `restore` handle both together.

## 6. A dated built-in model table; names and the default are yours
**Context.** A new user should get a working setup from their keys alone, and model ids and prices go stale.
**Decision.** `config.KNOWN` lists the models this project calls in its live tests, with list prices and the date they were checked. Without a settings file, the models your keys can call are offered with short names and a default. `crossvet init` writes that as a file you edit.
**Cost.** The table needs updating as vendors release models; anything not in it works by its full name, with a price you add.

## 7. Install from GitHub; keys from the environment or `.env`
**Context.** MCP apps start `crossvet mcp` in a folder of their choosing, so a `.env` only in a working folder is missed.
**Decision.** Keys come from the environment, then `./.env`, then `~/.config/crossvet/.env` (python-dotenv, never overriding the environment). Releases install from tags on GitHub.
**Cost.** No PyPI package; `uv tool install` takes the GitHub URL.

## 8. A major version for a change of model, with every earlier spelling kept working
**Context.** 3.0 changes the promise of the tool (it can now choose) and adds settings and MCP tools.
**Decision.** A major version and a [migration guide](MIGRATING.md). Nothing a 2.x user relies on changes: named models behave as before, every 2.x command, tool and setting works, and `crossvet chat <command>` spellings still work. 1.x names that moved (`routes`, `feedback`, `learn`) say where they went.
**Cost.** The command line is larger. `crossvet` with no arguments groups the commands by job.

## 9. Escalation is narrow and decided in code
**Context.** Trying another model after a failure is useful; silently replacing an answer the user has started reading is not, and a model's own "I'm not sure" is not a failure signal anyone can check.
**Decision.** Only an error, an empty answer, or invalid JSON (when the request asked for JSON) counts as a failure, and only before anything has been streamed. JSON answers are held back until they have been checked. Each attempt is recorded with its outcome. A model you named is never switched.
**Cost.** A weak but well-formed answer is not escalated: that is what `/retry stronger` and ratings are for.

## 10. Private requests never fall back to the cloud
**Context.** A request with an API key, a card or ID number, or marked confidential should not reach a cloud vendor because a router picked one.
**Decision.** With `auto`, such a request only goes to the `private` slot (a model on your machine), and is refused with an explanation when that slot is empty. The check is a pattern match, done before anything is sent. `private_auto = false` turns it off.
**Cost.** Patterns miss some private text and flag some harmless text (a 16-digit order number). Naming a model yourself bypasses the check, as it should.

## 11. Verdicts from models are read in code, and judges are blind
**Context.** `challenge`, `replay` and the benchmark use a model's output to judge another's. A judge that can be talked into a verdict, or that knows which answer is whose, measures little.
**Decision.** Verdicts are JSON with a fixed set of values; anything else counts as no verdict. Judges and challengers come from another vendor than the answer they check where possible; replay shuffles the order and hides which model wrote which answer. The benchmark uses answer keys checked in code, not a judge.
**Cost.** A judge that answers in prose is wasted. The benchmark's cases are small and synthetic: they show which models fail a job, not a general ranking.

## 13. A review finding is shown only if it matches the diff
**Context.** Model reviewers invent line numbers, quote code that isn't there, and report the same style nits over and over. A second vendor helps only if its findings can be trusted to point at real code.
**Decision.** The reviewer must answer in JSON; code keeps a finding only when its file is in the diff, its quote is word for word on a new-side line the diff shows (the stated line, or the one line within three of it that holds the quote, since reviewers miscount lines), and its severity is one of four. A finding without a severity is dropped, not guessed. Dropped findings are counted with the reason, so a noisy reviewer is visible. Fixes are patches that `git apply --check` must accept, applied only when asked, in at most three rounds. The benchmark plants bugs in real code from this repository and counts catches in code.
**Cost.** A reviewer that describes a real problem on a line the diff does not show is dropped. Twelve planted bugs are a small sample.

## 14. The judge is opt-in, capped, from another vendor, and checked against you
**Context.** Scoring real answers is the only way to know which model is good enough for your own work, but it sends your answers to a second vendor, costs money every day, and a judge model can be biased or simply disagree with you.
**Decision.** Off by default (`[score] enabled`), limited to the apps you list, never for private-looking requests, with its own daily cap. The judge comes from another vendor than the answer, scores against a rubric per kind of task, and its JSON is read in code. Calibration compares it with your ratings; a judge that agrees with you less than 70% of the time (on at least 10 pairs) is flagged and not used for routing. The leaderboard ranks by a cautious score so a handful of lucky answers can't top it.
**Cost.** Two weeks of use before the leaderboard means much. A rubric of one sentence per kind is coarse.

## 15. Routing from scores is cautious, explores a little, and rolls itself back
**Context.** Scores make "the cheapest model that is good enough" measurable per kind of task. A router that follows them blindly would chase a few lucky answers, never rescore the models it stopped using, and keep a bad change.
**Decision.** Off unless `[router] use = "scores"`. A model counts only with `min_scores` judged answers for the kind, ranked by a cautious score (mean minus one standard error); the cheapest within `margin` of the best goes first. About 5% of requests try the second choice. An untrusted judge (see 14) hands the decision back to the rules. Your accepted routes still win. Automatic changes are a separate switch: at most one per kind a week, each recorded with the score before, and rolled back by the next weekly run if the new model scores clearly worse.
**Cost.** Weeks of judged traffic before it routes anything, and a judge bill while it learns. The weekly saving is measured against list prices for the same tokens, which is not exactly what the strongest model would have spent.

## 12. Tuning proposes; only you change the routes
**Context.** Ratings show which model you were happy with for which kind of task. Changing routes automatically on a handful of ratings would chase noise.
**Decision.** `crossvet tune` proposes a change only with at least 5 ratings for each model and a 15-point lead, records the evidence, and changes nothing until you accept it. Every accepted route can be rolled back.
**Cost.** Routes improve only as fast as you rate and accept.

## 16. A review benchmark counts false alarms, not only catches
**Context.** The planted set showed five of six reviewers catching all twelve bugs, which says little: a reviewer that flags every line would score the same. A reviewer's cost to a team is its false alarms as much as its misses.
**Decision.** The hard set adds clean changes with no bug. On a clean change, any kept finding marked blocker or major is a false alarm; minor and nit findings are counted as notes. Every change is cut from the real source, and a test checks each context line against the file, so a reviewer sees code that exists. The checks in `review.check` are not changed to suit the benchmark: a finding without a severity is still dropped.
**Cost.** Six clean changes are a small sample, and refactors this small are easy to leave alone. A dropped finding counts as a miss even when it named the bug.
