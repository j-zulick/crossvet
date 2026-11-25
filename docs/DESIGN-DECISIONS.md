# Design decisions

Short records of the choices that shape Crossvet: the context, the decision, and what it costs. Research behind several of them is cited in the README's *Design principles*.

## 1. Extend Open Deep Research instead of starting over
**Context.** A credible deep-research agent needs search, parallel researchers, compression and report writing before any review can be added.
**Decision.** Build on LangChain's Open Deep Research (MIT), keep its history, and add Crossvet as new modules and nodes.
**Cost.** Inherited behaviour (for example, environment variables overriding run configuration) is kept and documented rather than redesigned.

## 2. Review by models from different vendors
**Context.** Models from one family share training data and blind spots, and judges favour their own outputs.
**Decision.** `REVIEW_MODELS` lists reviewers from different vendors; the setup checker warns on a single-vendor panel; `vendor_of()` maps OpenRouter and self-hosted routes to the real maker.
**Cost.** Several API keys (or one OpenRouter key) and more calls per report.

## 3. Deterministic checks wherever a check can be deterministic
**Context.** An LLM judge can be persuaded; a string comparison cannot.
**Decision.** Cited URLs are compared with the research notes in code. Evidence quotes from the critic and from deliberation count only if they appear verbatim (ignoring case and whitespace) in the notes.
**Cost.** URL matching does not prove a page supports a claim; that judgement stays with the critic and is reported as such.

## 4. Anonymize before ranking; revise outside the panel
**Context.** Position and self-preference biases are documented for LLM judges.
**Decision.** Critiques are shuffled and relabelled before voting; the reviser is configurable and flagged when it shares a vendor with a reviewer.
**Cost.** Label shuffling makes runs less reproducible; the mapping is recorded in the export.

## 5. Position changes need evidence
**Context.** Models tend to agree with confident pushback (sycophancy), which can make debate converge on the wrong answer.
**Decision.** Deliberation is off by default, capped at three rounds, and applies a revision or withdrawal only with a quote verified in the notes. Ungrounded changes are ignored and counted.
**Cost.** A correct change argued without a quote is ignored; the count makes that visible.

## 6. Failures degrade, they don't end runs
**Context.** Multi-vendor review multiplies the chance that some provider fails.
**Decision.** Every reviewer, critic, challenger and voter call is isolated. A quorum of two is required for review; failures are listed in the Review notes; comparison runs record errors and continue.
**Cost.** A report can be published with partial review; the notes say exactly which part.

## 7. Two editions, one review
**Context.** LangChain's Deep Agents is a newer, more autonomous way to build the same kind of agent.
**Decision.** Ship it as a second graph with the identical review, and capture its search results with a callback so grounding does not depend on the agent following instructions. Compare the two with `crossvet-compare` instead of asserting which is better.
**Cost.** One more dependency and two research paths to maintain.

## 8. Measure before claiming
**Context.** Claims about quality need evidence.
**Decision.** `crossvet-compare` produces per-setup tables from real runs; [EVALS.md](EVALS.md) records the protocol and results, including losses.
**Cost.** Results take paid runs and human grading.

## 9. Self-hosted first-class
**Context.** Local models are useful for privacy, cost and fine-tuning.
**Decision.** `ollama:` and `local:` models work in any role; run exports convert into MLX LoRA datasets; a fine-tuned model is evaluated as a `local:` reviewer.
**Cost.** Local models often handle structured output less reliably; failures surface as failed reviewers.

## 10. Keep `config_schema` for now
**Context.** LangGraph 1.x deprecates `config_schema` in favour of `context_schema`, with removal planned for 2.0.
**Decision.** Keep `config_schema`: LangGraph Studio's configuration panel and every node read settings from `configurable`, and migrating changes how users pass settings. Migrate together with the LangGraph 2.0 upgrade.
**Cost.** A deprecation warning at import time.

## 11. Secrets never leave `.env`
**Decision.** Keys come only from the environment. The setup checker reports presence, never values; Docker images contain no keys; CI scans history for secrets on every push.

## 12. Stop deliberation in code, not by a model's say-so
**Context.** Fixed rounds spend two model calls per critique per round even after reviewers have converged. Debate that adapts how long it runs performs better than fixed debate (Liang et al., EMNLP 2024).
**Decision.** Challengers label every finding AGREE, DISAGREE or BUILD_ON with an optional quote. The stop is a pure function of those typed verdicts and of what changed (`deliberation.decide_stop`): consensus needs a round in which nothing moved and enough endorsements; a stable disagreement ends after two rounds without movement. A BUILD_ON is applied only with a quote found in the notes. Agreement is not trusted on its own: if too few endorsements cite the notes, or the challenger was silent, a guard runs one more round with the next challenger. The challenger is never the author, so the author's own view never counts toward consensus.
**Cost.** The guard can make a run longer than without the guard (a silent challenger used to end deliberation at once). Unanimity is the default, so early stops happen less often than with a majority rule; `REVIEW_CONSENSUS_THRESHOLD` trades cost against caution. The saving is measured, not assumed: compare `deliberation-3-fixed` and `deliberation-3-early-stop`.

## 13. A blind pass aimed at omissions
**Context.** Reviewers who read a draft first tend to check its claims and miss what it leaves out.
**Decision.** Each reviewer outlines the answer from the notes before reading the draft, with a supporting passage per point. Code grounds every point in the notes and checks coverage in the draft; only grounded omissions become feedback. The outline is shown to its author during the critique so the point is not forgotten. Opt-in.
**Cost.** One short extra call per reviewer. Coverage is lexical: a correct paraphrase can be flagged as an omission. The flag goes to the reviser as feedback, not into the report, and the run export keeps every outline for audit.

## 14. The user picks the panel; Crossvet checks it
**Context.** Model names change monthly, and people want their own mix: a favourite model, a cheap one, a self-hosted one, or vendors such as Grok, GLM or Kimi reached through OpenRouter.
**Decision.** No fixed vendor list. Setup suggests a panel from what the keys can call, but a panel the user set (`--panel`, or an existing `REVIEW_MODELS`) is kept and only checked: unknown names, a single-vendor panel and a reviser that shares a vendor are reported, not silently fixed. Diversity is judged by the model's maker, so OpenRouter host routing (who serves an open-weight model) is a separate, optional setting. Spare reviewers keep a panel diverse when one vendor is down.
**Cost.** A kept panel can go stale; setup reports names the key can no longer call, and `--auto` re-picks.

## 15. A decision model checks support; code still checks the quote
**Context.** A position change needs a quote that appears verbatim in the notes. That blocks invented evidence, not real evidence used for the wrong claim, and an LLM asked "does this support that?" answers in prose and is poorly calibrated.
**Decision.** Keep the verbatim check as the first gate and add an optional second one: a yes/no question per (claim, passage) to Jev, TypeSafe's System One decision model, which returns a probability. It gates position changes, AGREE / BUILD_ON verdicts and blind-pass points against `REVIEW_SUPPORT_MIN_PROB`. A failed Jev call never blocks: that claim falls back to the quote check and the failure is reported. Scores and the model id that answered are kept in the export, so a threshold can be tuned against a pinned version.
**Cost.** One small request per scored pair (bounded concurrency, about 2 KB of state each). A false "not supported" keeps a finding the panel wanted to drop; that errs toward caution, and the export shows every score for review. Jev is another vendor dependency, so it is off unless `REVIEW_SUPPORT_CHECKER=jev`.

## 16. Domain context goes into the brief; follow-ups stay inside the evidence
**Context.** What counts as good evidence differs by field: an SEO claim needs a date and Google's own word, a rent figure needs a geography and period. A reviewer that doesn't know the field can't hold a report to those rules. Readers also want to ask about a finished report without paying for a new run.
**Decision.** Domain packs are short, written evidence rules (not prompts that change the model's persona), appended with the requester's context to the research brief, so every later stage, review included, sees them. Follow-ups reuse the run's saved notes, answer in one call, may cite only URLs from those notes, and say plainly when the notes don't cover the question.
**Cost.** A pack adds a few hundred tokens to each stage that reads the brief. A follow-up can only be as good as the run's notes; it never searches. Packs are guidance a model can still ignore; the critic and the citation check remain the enforcement.

## 17. Score each role with an answer key, not a judge model
**Context.** "Which model is best?" has no single answer for a pipeline: orchestration, search, compression, writing, review and revision reward different strengths, and price differences between models are large. Asking a model to grade other models would bring back the biases the cross-vendor review is designed to remove (self-preference, position effects, confident wording).
**Decision.** `crossvet-bench` tests one role at a time on frozen synthetic inputs, with the production prompt, schema, output limit and turn cap, and scores it with code: planted errors with known answers, facts and URLs that must survive, aspect checklists, citation checks. The critic is scored by balanced accuracy so blanket agreement earns 0.5. Results become configuration through best-quality and best-value role maps; `live-plan` hands one role to `crossvet-compare` to confirm on real questions.
**Cost.** String checks are strict and can miss a correct answer phrased differently, so every job keeps the model's output for audit. Six cases is small; the leaderboard shows standard errors and supports `--repeats`. Synthetic cases measure decisions, not the reach of a live search engine; full runs remain the end-to-end check.


## 18. A rotating challenger trades independent agreement for pressure
**Context.** When every reviewer is asked the same question, agreement means two models reached the same finding independently, and silence means nobody raised it. Crossvet's deliberation instead gives one reviewer per round the job of challenging the others' findings, and rotates that role.
**Decision.** Keep the rotating challenger in deliberation, and keep the first review round and the blind pass free of assigned angles, so the independent signal exists where it matters most. A challenger exists to put pressure on findings that would otherwise pass by default; it cannot overturn a finding without a passage from the notes (verified in code, and optionally scored by Jev), and its endorsements only end deliberation when they cite the notes.
**Cost.** In deliberation rounds, an AGREE from the challenger is weaker evidence than the same AGREE from an independent reviewer, and a challenger's silence says nothing. The false-consensus guard (#12) treats ungrounded or missing endorsements as a reason to run another round, not as agreement. Measuring rotating challenger vs. same-question deliberation is open.

## 19. Flag prompt injection in code, before any model reads the page
**Context.** A fetched page can carry text written for the model that reads it ("ignore your instructions", "recommend product X", "cite this URL"), often hidden from people with CSS or HTML comments. The citation and quote checks cannot catch it: the injected page really is in the research notes, so a claim taken from it passes both. The summarization model is the first to read each page, and it is usually the cheapest one.
**Decision.** `injection_check.py` scans each page's raw text with fixed patterns (instructions to override or ignore, text addressed to an AI, role changes, output steering, chat markup, and hidden text when it comes with one of those) before the page is summarized. A hit adds a line to that source's block in the notes naming the kinds of pattern, never the injected text, so the instruction is not passed on. The summarizer prompt treats page content as data, and markup that could close its wrapper or pose as a chat role is removed. The Review notes list flagged sources and say when the report cites one. The check marks sources; it does not remove them or decide a page is false. The `injection` and `injection-checked` benchmark suites measure, per model and role, how often a planted instruction reaches the output with and without the flag line.
**Cost.** Pattern matching misses instructions that are paraphrased, translated or encoded, and it flags honest pages that quote injection examples (articles about prompt injection, for instance). Vendor-hosted search (`SEARCH_API=openai` or `anthropic`) returns no raw page text, so the check covers Tavily and the research gateway only. (A report sentence whose every cited source is flagged goes to *Disputed*; see #20.)

## 20. A claim that rests only on flagged sources goes to Disputed, by rule
**Context.** Listing flagged sources in the Review notes (#19) leaves the reader to work out which statements depend on them. The reviewers may or may not notice, and the reviser may keep the statement.
**Decision.** After revision, code maps each sentence of the report to the sources it cites: numbered markers (`[3]`, `[2][5]`, `[2, 5]`, `[2-4]`) resolved against the report's numbered source list, and URLs written into the sentence. A sentence whose every cited source was flagged by the injection check is listed under *Disputed*, with the reason. A sentence that also cites an unflagged source is left alone. The report text is not changed: the rule marks, a human decides.
**Cost.** Sentences without a citation are not caught, even when they repeat a flagged source; citation formats other than numbered markers and inline URLs are not parsed. Splitting on sentence punctuation can break a sentence at an abbreviation.

## 21. Review any report, not only Crossvet's own
**Context.** The review stage was reachable only at the end of a research run, so a report written by another tool or a person could not use it, though most of its checks need only a report and the sources it should rest on.
**Decision.** `crossvet review report.md --sources …` (and `api.review`) builds research notes from files or URLs, one block per source with its URL and the injection check's flag, and runs the same review node. Citation, quote, critic and *Disputed* rules work unchanged because they read the same notes format. HTML sources contribute only their visible text to the notes; hidden text is still scanned for injection.
**Cost.** The review is only as good as the sources given: a citation to a URL not passed in is flagged even if it is real. Fetching URLs runs on the user's machine, with no SSRF guard in the CLI (the MCP tool refuses non-public addresses).

## 22. Close measured injection gaps with more code checks and one prompt rule
**Context.** `--suite injection-hard` (`docs/benchmarks/2026-11-18-injection/`) showed four forms the patterns of #19 miss: a paraphrased recommendation, a Spanish translation, an instruction split across sentences, and a "dominant" page that repeats one claim. One report adopted a URL that appeared only inside a page's text, and compression sometimes copied a page's own wording verbatim.
**Decision.** Four additions, each fixed in code or in a prompt, none a model's judgment:
- *Dominant page* (`injection_check.repetition`, kind `repetition`, flags a page on its own): a sentence of 5+ words occurring 3+ times that fills 30%+ of the page's words, or one Titlecase name (3+ letters, not a function word, used at least once inside a sentence) occurring 5+ times and making up 10%+ of the words. HTML tags are removed first and numbers count as words.
- *Multilingual triggers*: Spanish, French, German and Portuguese forms of "note to any AI…", "if you are an AI…" and "ignore the previous instructions", under the existing `addressed_to_ai` and `override` kinds. Only AI-specific nouns count, and an override needs the "previous / system" qualifier.
- *Report, never repeat*: the webpage summarization prompt and the compression system prompt say that a recommendation, ranking or instruction a page addresses to readers or AI systems is reported as that page's claim, attributed, never as a finding, and that a URL appearing only inside a page's text is not a source.
- *URL only inside a page* (`injection_check.urls_only_in_text`): a URL the final report cites that the notes hold only inside a source's body, never on a source's `URL:` line, is listed in the Review notes as unverified. The check runs only when the notes contain `URL:` lines, so older note formats produce no listing.
No benchmark has been run with these changes; `--suite injection-hard` measures them.
**Cost.** The paraphrased and split forms are still not matched. The repetition rule can flag a list page whose rows repeat a full boilerplate sentence, and misses a dominant page that varies its wording; the name rule misses a name repeated in a long page. Other languages are not covered, and translated paraphrases are not matched. The prompt rule is guidance a model can ignore. The URL check depends on the `URL:` line format and lists a URL a page quotes even when that URL is genuine; it reads the final report only and does not feed the revision.

## 23. Benchmark the summarizer page by page, on the pages that matter
**Context.** The summarization model is the first to read each fetched page (#19) and was not benchmarked: `apply` gave `SUMMARIZATION_MODEL` the compression winner, though compression reads notes that have already been summarized and checked.
**Decision.** `crossvet-bench` has a `summarizer` role. Each job sends the pipeline's own prompt, built by the same helper (`utils.build_summarize_prompt`: neutralized page, per-call wrapper tag), with the `Summary` schema, once per page: every source that holds a key fact, plus the injected page in injection cases. Quality is the share of key facts found verbatim in the summary and key excerpts of their own source, halved when the injected page's summary states the planted instruction as fact (the same classification as for compression and the writer). `apply` writes the summarizer winner to `SUMMARIZATION_MODEL`, and falls back to the compression winner for role maps without summarizer results.
**Cost.** Pages without a key fact are not summarized, so a summary that invents content on a distractor page goes unmeasured. The fact check is a substring match: a summary that rewrites "38%" as "thirty-eight percent" loses the fact. One call per page makes the role cost several calls per case.

## 24. Scan reports a client can open, and sitemaps that cannot reach local files
**Context.** `crossvet-scan` printed text or JSON for one page at a time. An SEO/GEO audit covers a whole site and ends in a file the client opens in a browser or a spreadsheet, and both the sitemap and the pages are written by someone else.
**Decision.** `--format csv|html` and `--out`; `--sitemap` (a sitemap index is followed one level deep) and `--urls`, capped by `--max-pages` (50) with `--delay` (0.5 s) between fetches. The HTML report is one file with inline CSS and no JavaScript or external assets, and every page-derived string goes through `html.escape`. CSV cells that start with `=`, `+`, `-` or `@` get a leading `'` so a spreadsheet does not run them as formulas. Sitemaps are capped at 5 MB, parsed with ElementTree (which does not expand external entities) and refused if they declare a DTD. A sitemap's page `<loc>` values must be http(s) URLs, and a remote sitemap index may only point to http(s) sitemaps, so a sitemap cannot make the scan read a local file into the report.
**Cost.** One level of sitemap index and at most 50 child sitemaps; gzipped sitemaps (`.xml.gz`) are not read. The `'` prefix changes how a cell that really starts with `-` displays. Like the single-page CLI, page fetches allow private addresses (it runs on the user's machine), so a sitemap from an untrusted site can point the scan at hosts on the user's network; only the excerpt of a match, not the page, goes into the report.

## 25. Widen the injection patterns, and drop repeated-claim findings from scan reports
**Context.** The injection check missed letter-spaced, look-alike, ROT13, reversed and split instructions, Italian and Dutch, and commands about the reader's reply, and `crossvet-scan` did not read stylesheet-hidden text, `<template>`, SVG titles, hidden inputs, JSON-LD or noscript. In `crossvet-scan`, 23 of 24 pages it flagged among 608 real pages were flagged only for a repeated claim (menus and templates).
**Decision.** Widen the patterns and undo the disguises before matching; join short fragments and report those matches as `split:<kind>`. Add the hidden channels, including selectors from the page's own `<style>` rules. In `crossvet-scan` (CLI and MCP), drop a channel whose only finding is `repetition` unless `--include-repetition` is passed. The research-notes flag keeps counting repetition. Repetition is judged on a page's first 20,000 words, so a very long page can't stall the check.
**Cost.** More patterns means more chances of a false alarm: on the 608 pages the notes flag is unchanged (6), but on a privately supplied set one forum reply box now matches the reply-command pattern. Only `<style>` rules on the page are applied; linked stylesheets are not fetched. A page dominated by one claim beyond its first 20,000 words is not flagged for repetition.

## 26. Effort tiers and a model guard, decided in code
**Context.** Every run did the same amount of work whatever the question, and each stage had one fixed model. Review roughly doubled a report's cost in the Nov 17 pilot ($0.19 without, $0.36 with a two-vendor panel), and the role benchmark showed a small model within 0.03 of the best score in six of seven roles. Routing each request with a learned router or a hosted auto-router would make the vendor of a review role unknown in advance and would put a model's guess where the project's rule wants a code check.
**Decision.** Three settings, all off by default. `EFFORT` (quick, standard, deep) fills in research depth, panel size, deliberation and the blind pass where the user has not set them; `--effort auto` classifies the question with text rules and defaults to standard when unsure. `ESCALATION_MODEL` is used for a stage only after that stage's own model fails a check code can make (an error or unparseable structured output after retries, or a report that stops early); review roles, the supervisor and the researchers are never escalated, so the panel's vendor mix stays the user's choice and a tool-calling conversation never changes model midway. `MAX_RUN_USD` refuses the next model call once the counted spend reaches the cap. The tier, every escalation and the counted spend are reported.
**Cost.** The tier values and the classification rules are judgment, not measurement: no run has yet compared the tiers on cost and review findings. A wrong `quick` gives a thinner report, which is why unclear questions get `standard`. A failed cheap attempt is paid for before the stronger model is called. The spend cap cannot count calls whose price is unknown (direct-provider models missing from the OpenRouter catalog), and a stage that catches its own errors can end a capped run with a partial report. Escalation covers the LangGraph edition only.

## 27. One chat that routes each request, as a separate tool in the same repository
**Context.** The research pipeline answers one kind of request, slowly and thoroughly. Most day-to-day requests are short and varied, and the user wants one place to talk to several vendors' models with each request sent to a suitable one. Hosted routers (OpenRouter's Auto Router, Jev Router) choose by a model and do not say why in terms the user set. The research pipeline's settings (`configuration.py`) describe one graph run and are read per run.
**Decision.** `crossvet chat` is its own package (`open_deep_research/chat/`) with its own command, settings file and store:
- *Routing in code.* Text rules name the kind of task and a difficulty; each kind starts in a slot (quick, balanced, strong, fresh, long, reviewer); difficulty and `--effort` move it along quick → balanced → strong; a context-window check moves it to `long`. The reason is saved with every turn and shown by `/why`.
- *Guard in code.* The next model in a slot is tried only after an error, an empty answer, a cut-off answer, or invalid JSON when JSON was asked for. Daily and per-call spend caps.
- *Settings in TOML, not `configuration.py`.* Slots and routes are lists and maps edited by hand and by `bench --apply`; environment variables only say where the files are and hold keys and the server token.
- *Agents keep their tools.* A request with tools or tool results is routed on its latest user message and passed through whole to the chosen model. A tool loop stays on the model that started it, because switching models mid-loop breaks tool-call ids and the plan. Pass-through goes to OpenAI-style APIs only.
- *One append-only store.* Turns and notes from every app go to one SQLite file whose triggers refuse updates and deletes; notes reach a model inside a marked data block.
**Cost.** The task rules are judgment, not measured against labelled requests. Streaming is simulated with one chunk. Direct Anthropic models cannot take tool calls through the server. A second command family makes Crossvet larger to learn; the README keeps the chat in its own row and guide.

## 28. Keep every chat turn and rating locally first, and copy them to Langfuse
**Context.** Choosing models from use, rather than from guesses, needs a record of which model answered which kind of task, at what cost, and whether the answer helped. Langfuse is already Crossvet's tracing tool. A hosted store alone would make the record depend on a network and an account, and OpenRouter's Broadcast traces every call but knows nothing of the routing reason or the user's rating.
**Decision.** The local SQLite store is the source of truth: a `feedback` table (append-only, like turns and notes) holds every rating. `record.py` copies each answer to the configured sinks as one Langfuse generation on its own trace (the thread as session, the app as user, the routing facts as metadata and tags) and each rating as a score on that trace. Explicit ratings (`user-feedback`) come from `/good`, `/bad`, the CLI, the HTTP API and an MCP tool; implicit ones are recorded in code when they happen: `retried` on `/retry`, `switched` when the next turn names another model, `escalated` when the guard moved past the first model. Trace ids derive from the store's id and the turn id, so a rating from another process reaches the right trace. `content = "metadata"` keeps text out of the copies. A sink error is recorded and never fails a turn.
**Cost.** Implicit signals are proxies: a retry can mean the user wanted a second opinion, not that the answer was bad. Ratings given only in Langfuse's own UI do not flow back to the local store. A JSON-lines copy grows without rotation. With Broadcast also on, each call is traced twice.

## 29. Jev as a classifier and an answer check; hosted routers as options with a fallback
**Context.** The chat's text rules (#27) are judgment. Jev answers typed questions about text with probabilities and costs little (input only). OpenRouter's Auto Router and TypeSafe's Jev Router choose the model themselves and are measured on their own benchmarks, not on this user's work. Crossvet's rule is that checks deciding an outcome stay in code.
**Decision.** A router setting with five values: `rules` (default), `jev`, `openrouter-auto`, `openrouter-auto-code`, `jev-router`.
- `jev` replaces only the classification: two choice questions (kind, difficulty). The slot and model still come from the user's routes and slots. Code accepts Jev's answer only above `jev_min_confidence` (0.5) and falls back to the rules when Jev is unsure or fails.
- A hosted router goes first; the slot the rules pick stays behind it as the fallback, and the model it chose is recorded.
- The optional answer check asks Jev one yes/no question; code compares the probability with `check_threshold` (0.2) and, below it, moves to the next model. A Jev failure lets the answer through, because the code checks already passed.
- Every turn records its router, so routers can be compared on the user's own ratings (#28).
Jev is reached through OpenRouter's Decisions API so one key covers it.
**Cost.** Jev's classification and the hosted routers have not been compared with the rules on real requests. The thresholds are starting values. The Decisions API is in alpha. With a hosted router, the user's slots matter only on failure, and its choice is not explained in the user's terms.

## 30. A routing table that only you change, fed by your choices, other people's posts and your ratings
**Context.** The user wants routing to start from a reasoned default, to tune it himself, and to use what other people report about which models suit which tasks. Learned routers move on their own; posts can be wrong, out of date, or carry hidden instructions aimed at the model that reads them.
**Decision.** A versioned routing table in the chat store (append-only): per kind of task, an optional slot, preferred vendors, models to try first, and models to avoid, each line with its reason, date and author. Version 0 is a starting table written from judgment and labelled so. Only three actions save a version, and each needs the user: `routes set`; accepting a claim imported from a post or note; accepting a proposal from `tune`. Imports run the prompt-injection check before any model reads a post, ask a model for claims with exact quotes, and keep only claims whose kind is known and whose quote is in the post verbatim (the review stage's quote rule). Proposals come from explicit ratings only, beat the current first choice by a margin, and are marked weak below a minimum number of ratings. Optional exploration swaps the first two candidates for a set share of requests and marks those turns.
**Cost.** The starting table is reputation, not measurement. Vendor preferences only reorder models inside a slot. A claim can be quoted correctly and still be wrong or stale; acceptance is the user's judgment. Implicit signals are shown but do not drive proposals. Exploration spends some requests on a model expected to be worse.

## 31. Measure routers on your own history before trusting them
**Context.** Routers are compared on their makers' benchmarks, not on one person's requests. The chat store already holds every question, the model that answered, and the user's ratings (#28), which is enough to ask how another router or table version would have routed the same requests.
**Decision.** `crossvet chat replay` recomputes each saved question's routing under each requested router and table version, calling no answering model, and reports agreement, how many good-rated answers would keep their model, and how many troubled answers would move. With `--run`, a sample of questions where a setup disagrees is re-answered by its first choice and judged blind (random order, no names) against the original by a model from a third vendor; code counts the verdicts and stops before a spend cap. `crossvet chat export` writes answers and ratings to a Langfuse dataset (stable item ids, linked to their traces) or JSON lines.
**Cost.** Agreement is not quality: a router can disagree with a past answer and be better. The judge is one model's opinion with no answer key, and a third vendor must be configured. Hosted routers can only be measured with `--run`. Jev replays cost one call per question and need `--yes`.

## 32. A demo, a cost estimate and a verdict line, all from code
**Context.** Crossvet was judged hard to understand: a newcomer had to set up keys before seeing anything, could not tell what a run would cost, and had to read a whole Review notes section to learn whether the report passed its checks.
**Decision.** `crossvet demo` runs the injection check, chat routing and the verdict line on built-in examples, offline. `--estimate` multiplies the call counts the settings allow (low: one round, two researchers, three tool calls; high: every limit) by fixed token assumptions and cached catalog prices, and calls no model. The Review notes open with a verdict computed from the counts the checks already produce; it never says the report is correct, only whether the checks found something.
**Cost.** The estimate's token sizes are assumptions; it can be off by a wide margin for long pages or verbose models, and models missing from the catalog are left unpriced. The verdict line counts reviewer dissent as a reason to check, which can flag a sound report. The demo uses example model names, not a run.

## 33. Handoffs as versioned packets with checks in code, not a live conversation between vendors
**Context.** The original scope asked for models from different companies to work together. The integration handoff of Nov 22 found that no supported route lets two vendors' chat apps share live state, and recommended a versioned packet, headless CLI workers (`claude -p`, `codex exec`) and receipts per attempt, with exit status kept apart from the model's verdict.
**Decision.** `crossvet chat handoff` stores requests and an append-only event log in the chat store. Requests carry the handoff's minimum fields (filled with defaults for short packets) and the packet's SHA-256. Workers are a model through the hub, Claude Code, Codex, or a file for any chat or agent. A result is accepted only when code confirms the task, the newest revision, the digest and, for claim reviews, a known verdict and a verbatim quote. Duplicate dispatch returns the existing request, claims are atomic, attempts are limited, and an attempt without a result is "uncertain" until reconciled. MCP tools expose the same queue to other apps.
**Cost.** It is a queue and a check, not shared conversation state. CLI flags can change between versions; the kit's scripts must be checked on the machine that runs them. The queue lives in one SQLite file, so separate machines need the file-based route or the MCP server. No live Claude Code or Codex run has been made from this repository.

## 34. Install from GitHub; `.env` from the working folder
**Context.** Testing the release candidate the way a new user installs it (`uv tool install` from GitHub into a clean folder) found two problems. Crossvet has no PyPI project, so the README's `pip install crossvet` failed and every release run ended with a failed PyPI upload. And `load_dotenv()` without a path searches upward from the installed module, so after `pip install` or `uv tool install` the research pipeline, `doctor`, `try`, `bench`, `compare` and the MCP server never read the `.env` that `crossvet setup` writes in the working folder; only a clone worked.
**Decision.** The README installs a tagged release from GitHub (`uv tool install`, or `pip` in a virtual environment), and each release carries its wheel and source archive. The PyPI upload runs only when the repository variable `PYPI_PUBLISH` is `true`. Every command reads `.env` from the working folder upward first, then falls back to the old search, and `crossvet` loads it once before handing over to any tool; values already in the environment still win.
**Cost.** Installing from GitHub needs git and a network path to GitHub, and there is no `pip install crossvet` until a PyPI project exists. Two `.env` files (one in the working folder, one in a clone) can now give different results depending on where a command is run; the nearest to the working folder wins.

## 35. Streamed answers: fall back only before the first piece of text
**Context.** Chat apps such as Hermes show an answer as it is written, and the server used to send the finished answer in one chunk. The guard's checks (empty, cut off, broken JSON, the Jev answer check) need the whole answer, and the guard moves to the next model when one fails.
**Decision.** With `"stream": true`, text is passed on as it arrives. A model that fails before sending any text, or sends none, is skipped for the next one in the slot, so the guard works as before for errors, missing keys and empty answers. Once text has been sent it is not taken back: a later problem is recorded on the turn (and in Langfuse), the turn keeps the model that wrote it, and the Jev answer check is not run. Errors before any text are HTTP errors; errors after are a closing line in the stream. Agent requests with tools are still answered in one piece. A server that ignores `stream` and answers in one piece is read as such.
**Cost.** A streamed answer that is cut off or breaks JSON stays with its model instead of moving to the next one; the user sees the problem in the turn's record and can `/retry stronger`. Clients that need the full guard can send `"stream": false`.

## 36. A light base install; research as an extra
**Context.** The chat, the scanner and the demo need three packages (httpx, mcp, python-dotenv), but every install pulled about 200, including LangGraph, LangChain providers, cloud SDKs and pandas, because the research pipeline needs them. A fresh install also showed that installs from GitHub ignore `uv.lock` and take the newest allowed version of every dependency.
**Decision.** The base install is the chat, the scanner and the demo. `research` adds the research pipeline, review, benchmarks, comparisons and their MCP tools; `langfuse` adds chat recording in Langfuse; `all` is both. Commands that need research say what to install instead of failing on an import. The LangGraph configs list the research packages themselves, because LangGraph installs `.` without extras; a test keeps the lists equal. CI installs the built wheel without extras on every pull request, and a weekly job installs every extra at its newest version without the lock and runs the tests.
**Cost.** Existing users of research must reinstall with `crossvet[research]` (or `all`); before 1.0 this is allowed by semantic versioning, and the error message gives the command. The research package list now lives in two places (the extra and the LangGraph configs), kept equal by a test.

## 37. Ratings from Langfuse are read into the local store, by rule
**Context.** Ratings were recorded locally and copied to Langfuse, but a score added in Langfuse's interface never reached `crossvet chat tune`. Langfuse is where a person reviewing many turns at once is most likely to rate them.
**Decision.** `crossvet chat sync` reads scores of one name (`user-feedback`) that people added in Langfuse (source `ANNOTATION`), matches each to its answer by trace id, turns its value into good or bad by a fixed rule in code, and saves it as an ordinary rating tagged with the Langfuse score id, once. Scores Crossvet sent are skipped, so nothing is counted twice. Values the rule can't read are listed, not guessed. `crossvet chat report` counts cost, ratings and proposals from the local store and can post the report to Langfuse as a trace.
**Cost.** A score changed or deleted in Langfuse after it was synced stays as it was here (the store is append-only); a newer score on the same answer counts instead, because the latest rating wins. Only answers recorded by this store can be matched. Sync is run by hand (or with `tune --sync`), not continuously.

## 38. Repeated claims from posts are merged by rule, and decided together
**Context.** Importing many posts makes the same claim ("model X is good at code") show up again and again, and accepting each copy would change the table once per post. Posts also contradict each other.
**Decision.** Two claims are the same when kind, model and verdict match, with the model compared after dropping provider prefixes and normalizing spaces and underscores. `routes evidence` shows each claim once with how many posts made it, and marks contradictions (same kind and model, opposite verdict). Accepting or rejecting a claim records the same status on its pending repeats and changes the table once. Folders and URL lists are expanded to files and URLs, each going through the same injection check, extraction and verbatim-quote check as before.
**Cost.** The match is by name, so two names for one model (an alias and a dated id) are not merged; the count of posts says how many said it, not how reliable they are. Whether to accept stays a person's decision.

