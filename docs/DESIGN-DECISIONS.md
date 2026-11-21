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
**Cost.** The guard can make a run longer than v1.0's (a silent challenger used to end deliberation at once). Unanimity is the default, so early stops happen less often than with a majority rule; `REVIEW_CONSENSUS_THRESHOLD` trades cost against caution. The saving is measured, not assumed: compare `deliberation-3-fixed` and `deliberation-3-early-stop`.

## 13. A blind pass aimed at omissions
**Context.** Reviewers who read a draft first tend to check its claims and miss what it leaves out.
**Decision.** Each reviewer outlines the answer from the notes before reading the draft, with a supporting passage per point. Code grounds every point in the notes and checks coverage in the draft; only grounded omissions become feedback. The outline is shown to its author during the critique so the point is not forgotten. Opt-in.
**Cost.** One short extra call per reviewer. Coverage is lexical: a correct paraphrase can be flagged as an omission. The flag goes to the reviser as feedback, not into the report, and the run export keeps every outline for audit.

## 14. The user picks the panel; Crossvet checks it
**Context.** Model names change monthly, and people want their own mix: a favourite model, a cheap one, a self-hosted one, or vendors such as Grok, GLM or Kimi reached through OpenRouter.
**Decision.** No fixed vendor list. Setup suggests a panel from what the keys can call, but a panel the user set (`--panel`, or an existing `REVIEW_MODELS`) is kept and only checked: unknown names, a single-vendor panel and a reviser that shares a vendor are reported, not silently fixed. Diversity is judged by the model's maker, so OpenRouter host routing (who serves an open-weight model) is a separate, optional setting. Spare reviewers keep a panel diverse when one vendor is down.
**Cost.** A kept panel can go stale; setup reports names the key can no longer call, and `--auto` re-picks.

## 15. A decision model checks support; code still checks the quote
**Context.** Since v0.5 a position change needs a quote that appears verbatim in the notes. That blocks invented evidence, not real evidence used for the wrong claim, and an LLM asked "does this support that?" answers in prose and is poorly calibrated.
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
**Cost.** Pattern matching misses instructions that are paraphrased, translated or encoded, and it flags honest pages that quote injection examples (articles about prompt injection, for instance). Vendor-hosted search (`SEARCH_API=openai` or `anthropic`) returns no raw page text, so the check covers Tavily and the research gateway only. (Since 1.8, a report sentence whose every cited source is flagged goes to *Disputed*; see #20.)

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
**Decision.** Widen the patterns and undo the disguises before matching; join short fragments and report those matches as `split:<kind>`. Add the hidden channels, including selectors from the page's own `<style>` rules. In `crossvet-scan` (CLI and MCP), drop a channel whose only finding is `repetition` unless `--include-repetition` is passed. The research-notes flag keeps counting repetition, as in v1.9. Repetition is judged on a page's first 20,000 words, so a very long page can't stall the check.
**Cost.** More patterns means more chances of a false alarm: on the 608 pages the notes flag is unchanged (6), but on a privately supplied set one forum reply box now matches the reply-command pattern. Only `<style>` rules on the page are applied; linked stylesheets are not fetched. A page dominated by one claim beyond its first 20,000 words is not flagged for repetition.
