# Changelog

All notable changes to Crossvet. Versions follow [Semantic Versioning](https://semver.org/). Crossvet was built between November 6 and 17, 2026 in a private repository, one tested version at a time; all versions were published together when the repository went public.

## [Unreleased]

### Added
- The injection check flags a page that is mostly one repeated sentence or one repeated name (kind `repetition`; thresholds in `injection_check.py`).
- Spanish, French, German and Portuguese triggers for text addressed to an AI and for overriding instructions.
- Review notes list cited URLs that appear in the notes only inside another page's text, never as a source's `URL:` line (unverified). Only applied when the notes use `URL:` source lines.
- **`crossvet-bench` summarizer role**: the first model to read each fetched page is benchmarked with the pipeline's summarizer prompt and `Summary` schema, on every source holding a key fact plus the injected page in injection cases. Scored on key facts kept per page, halved when the injected page's summary states the planted instruction as fact. `apply` writes its winner to `SUMMARIZATION_MODEL` (previously the compression winner, still used for role maps without summarizer results). No results yet.
- **`crossvet-scan` reports**: `--format text|json|csv|html` (`--json` kept as an alias) and `--out FILE`. CSV has one row per finding plus one per clean page and per error, with formula-like cells neutralised; HTML is one self-contained page (summary, then a section per page, inline CSS, no JavaScript, all page text escaped) to hand to a client.
- **`crossvet-scan` on many pages**: `--sitemap URL_OR_FILE` (sitemap index followed one level deep, 5 MB cap, DTDs and non-http(s) page locations refused) and `--urls FILE` (one URL per line, `#` comments skipped), with `--max-pages` (default 50) and `--delay` (default 0.5 s). Design decision 24.

- First, partial check of the decision 22 defenses on `injection-hard` (`docs/benchmarks/2026-11-18-injection-defenses/`). With the prompt rule, OpenAI report writers adopted a planted claim in 2 of 16 runs (1 of 16 before). The Claude writing jobs failed for lack of credit.

### Changed
- The webpage summarization and research compression prompts say to report recommendations, rankings and instructions a page addresses to readers or AI systems as that page's claims, never as findings, and that a URL found only inside a page's text is not a source.
- The hard-injection bench test now records which forms the check flags (translated, dominant) and which it still misses (paraphrased, split). No benchmark was run with these changes; `--suite injection-hard` measures them. Design decision 22.
- The summarizer prompt is built by one helper, `utils.build_summarize_prompt`, shared by the pipeline and the benchmark (no change in behaviour).

## [1.8.0] - 2026-11-18

### Added
- **`crossvet-scan`**: check any page, file or pasted text for prompt injection, by channel (visible text, hidden elements, HTML comments, attributes and meta tags), with JSON output and an exit code for CI. Also an MCP tool, `scan_for_injection`, that refuses non-public addresses.
- **`crossvet review`** and `api.review`: run the cross-vendor review on an existing report against files or URLs.
- **Claims resting only on flagged sources go to *Disputed*** (design decision 20).
- The injection check decodes invisible Unicode tag text and base64 blobs and scans what they say.

- `REVIEW_SUPPORT_CLAIM=fact`: Jev is asked whether a passage supports the reviewer's one-sentence statement of what it says, instead of the finding itself. Opt-in.
- First Jev on/off measurement (`docs/evals/2026-11-18-jev/`), and the full injection-checked suite (the Claude jobs that failed for lack of credit were re-run).

- **`--suite injection-hard`**: paraphrased, translated, split and dominant injections the pattern check does not catch, with first results.

### Changed
- The summarizer's data wrapper carries a random per-call marker, so a page cannot close it by guessing the tag.
- Deliberation logs keep the (claim, passage) pair each Jev score was given, so the scores can be audited.
- The injection scorer adds an *attributed* class and skips source-list lines.

## [1.7.0] - 2026-11-18

### Added
- **Hard benchmark suite** (`crossvet-bench run --suite hard`, or `all`). It has three cases, each with:
  - 11 sources, several of them distractors;
  - a secondary source that conflicts with the primary one;
  - a digit-swapped number;
  - an unread source whose title imitates a real one;
  - an unsupported causal claim;
  - a dropped caveat;
  - false findings backed by a distractor.

  Report writing on these cases is scored on citing the clean report's sources. `--cases` accepts ids from any suite.
- First hard-suite results for seven models (`docs/benchmarks/2026-11-18-hard/`).

- **Prompt-injection check** (`injection_check.py`): every page fetched through Tavily or the research gateway is scanned in code before it is summarized. Flagged sources get a line in the research notes, and the Review notes list them and any the report cites. The summarizer prompt treats page text as data and strips markup that could break out of it.
- **Injection benchmark suites** (`--suite injection`, `--suite injection-checked`): four cases with one injected source each (override, hidden comment, cite-this-URL, role change), without and with the check's flag line. Scores whether writing and compression act on the instruction, and whether reviewers, critics and revisers catch the injected claim.
- `docs/SECURITY-MODEL.md`: threats, defenses and limits; design decision 19.

- First injection benchmark results for seven models (`docs/benchmarks/2026-11-18-injection/`).
- Jev support checks live-tested against `jev-1.14.0` (`crossvet-doctor --jev`).

### Changed
- The example review panel in `.env.example` is now `openai:gpt-6.1-sol` + Claude Sonnet 5.5. On the hard suite gpt-5.4-mini was the weakest reviewer and critic.

- The injection scorer separates reported, quoted and followed instructions; bench outputs are saved up to 20,000 characters.

### Removed
- The README's *Related projects* section.

## [1.6.1]

### Changed
- **Default models for summarization, compression and the report are now `openai:gpt-6-luna`** (from `gpt-5.4-mini`). In the November 18 benchmark it matched the top score in compression, report writing and revision at the lowest cost of any model. Research and orchestration stay on `gpt-6.1-sol`, and the example review panel stays `gpt-5.4-mini` + Claude Sonnet 5.5. Results: `docs/benchmarks/2026-11-18/` and `docs/MODEL-SELECTION.md`.
- README shortened: the feature-by-feature sections now live in `docs/FEATURES.md`, and the design-principles table and its references in `docs/DESIGN-PRINCIPLES.md`. A feature table links to each one.

### Added
- Second benchmark run: GPT-6 Luna, GPT-6.1 Terra and Claude Opus 5.5 next to the first run's four models (294 jobs, $1.98 for the new ones).
- `CONTRIBUTING.md`, issue templates (bug, feature) with security reports routed to private advisories, and a pull request checklist.
- Latest-release badge in the README.

### Fixed
- **The Deep Agents edition now flags a report cut off by an output limit or a provider content filter** with an *Incomplete report* notice, as the LangGraph edition does since 1.6.0.
- Dependabot no longer tries to update `setuptools`, the build requirement, which its uv updater can't change.

## [1.6.0]

### Added
- **Any model in any role.** One model factory builds every pipeline stage and review role. `openrouter:<maker>/<model>` uses the official `langchain-openrouter` integration (real per-call cost, provider routing, attribution as Crossvet); `local:<model>` uses any OpenAI-compatible server. Before 1.6, OpenRouter and local models worked only in review roles: in the LangGraph edition's research, summarization, compression and report stages they failed.
- **Separate orchestration and research models**: `SUPERVISOR_MODEL` plans and delegates; `RESEARCHER_MODEL` searches and reads. Both default to `RESEARCH_MODEL`. In the Deep Agents edition the researcher sub-agent can run on its own model.
- **Capability checks before a run**: `crossvet-setup` saves OpenRouter's live catalog (tool calling, structured output, context length, price per model); the doctor fails a role whose model cannot call tools or return typed output, and setup's automatic pick skips such models.
- **`crossvet-bench`**, a per-role benchmark: orchestration, research, compression, report writing, review, critic and revision, each scored by code on six synthetic cases (planted errors with an answer key, kept facts and URLs, aspect checklists). Real or estimated cost per case, a `--max-usd` cap, `--dry-run`, resumable runs, a leaderboard per role, a quality-vs-cost chart with the frontier, and a role map with best-quality and best-value picks. `apply --preset` writes the role map to `.env`; `live-plan` writes a `crossvet-compare` file that swaps one role; `suggest` lists the newest tool-capable model per vendor. Every bench call is traced in Langfuse when configured. See [docs/MODEL-SELECTION.md](docs/MODEL-SELECTION.md).
- **First published benchmark** (`docs/benchmarks/2026-11-17/`): four models from two vendors, all roles and cases, $1.49; findings and caveats in `docs/MODEL-SELECTION.md`.
- Dependency: `langchain-openrouter` (MIT).

### Changed
- Default stage models come from the first benchmark run: `openai:gpt-6.1-sol` for research and orchestration, `openai:gpt-5.4-mini` for summarization, compression and the report (replacing `gpt-4.1`, which OpenAI retires on January 14, 2027). Newer models not yet benchmarked are listed in `docs/MODEL-SELECTION.md`. `crossvet-setup` still replaces defaults your key cannot call.
- Upstream's unused legacy implementations (`src/legacy/`) are removed; `CLAUDE.md` now points to `AGENTS.md`, Crossvet's own guide for coding agents.
- Structured output follows the model: JSON schema where the model supports it (and always for Claude, directly or through OpenRouter), a forced tool call otherwise.
- Context limits for models missing from the built-in table come from OpenRouter's catalog or LangChain's model profiles, so an over-long report is trimmed and retried instead of failing.

### Fixed
- **A Claude reviser or report writer with extended thinking put raw content blocks into the report.** Claude can reply with a list of blocks (a thinking block with a signature, then the text); the revision, the final report, compression and the raw notes took `str(content)` instead of the text. All now use the reply's text only. Found in a live run with Claude as reviser; affects v1.0 to v1.5 when the reviser or report model is a Claude model that returns thinking blocks.
- **A revision cut off at the output limit replaced the complete draft**, losing its end and its source list (seen live with a Claude reviser whose extended thinking shares the output budget). The review now keeps the draft when the revision stopped at the limit, came back empty, or lost most of the draft's sources, and says why in the Review notes.
- The automatic OpenRouter pick chose Gemma (open weights) over Gemini for Google because of its higher version number.
- **A report cut off by a provider's content filter was treated as finished.** Seen in the first pilot: OpenAI stopped the report writer mid-quote of a statute (`finish_reason: content_filter`). The writer now tries again, asking for paraphrase over long quotes; a report that stops early twice ends with an *Incomplete report* notice, and a filtered revision no longer replaces the draft. Anthropic `refusal` and Google `SAFETY` / `RECITATION` count too.

### Docs
- README: TL;DR, *Measured so far* (including what hasn't been measured), *Cost and API keys*, *My role and AI assistance* and *Release history*; `docs/CONTRIBUTIONS.md`; design decision 18 (rotating challenger); `examples/compare/review-vs-none.toml` for the first end-to-end evaluation, and its first pilot results in `docs/evals/2026-11-17-pilot/`.

## [1.5.0]

### Added
- **Context and domain packs**: `RESEARCH_CONTEXT` (who is asking and why) and `CONTEXT_PACK` (`seo`, `marketing`, `real-estate`: which sources count as primary, which claims go stale, what reviewers check) are appended to the research brief in both editions, so research and every review stage work to them. `crossvet-doctor` checks the pack name.
- **Follow-up questions**: `crossvet ask --thread ID "question"` answers from a finished run's notes in one model call, cites only URLs the run read (same citation check as the report), and says when the notes don't cover the question. `--out` appends to a markdown file; exit code 2 flags unread URLs.
- **Python API** `open_deep_research.api`: `run` / `arun` (any setting, either edition, no approval pauses) and `ask` / `aask` for follow-ups.

## [1.4.0]

### Added
- **Support checks with Jev** (`REVIEW_SUPPORT_CHECKER=jev`, needs `TYPESAFE_API_KEY`): a decision model scores whether each quoted passage supports the claim made from it. Below `REVIEW_SUPPORT_MIN_PROB` (0.5), a deliberation position change counts as ungrounded, an AGREE is not grounded, a BUILD_ON is not applied, and a blind-pass point is dropped. The verbatim-quote check stays the first gate; a failed Jev call falls back to it and is reported.
- `REVIEW_SUPPORT_MODEL` pins a Jev version; the version that answered is recorded.
- `crossvet-doctor`, a command for the setup checker (`python -m open_deep_research.doctor` still works), now checks the Jev setup; `crossvet-doctor --jev` asks two questions with known answers.
- Scores in the deliberation log, review state and export (`support_check`); `crossvet-compare` columns and Langfuse scores `support_checked`, `support_rejected`; a `deliberation-2-jev` compare setup when the key is set; `crossvet-setup` turns support checks on when `TYPESAFE_API_KEY` is present.
- Dependency: `typesafe-sdk` (MIT).

## [1.3.0]

### Added
- **Your own models in setup**: `crossvet-setup --panel` and `--reviser` take any `provider:model` your keys can call; `--list-models PROVIDER [--filter TEXT]` prints every id a provider offers. Choices are checked, not replaced: names the key cannot call, single-vendor panels and a reviser sharing a vendor with the panel are reported.
- **Spare reviewers** `REVIEW_FALLBACK_MODELS`: a failed reviewer is replaced by the next spare, preferring a vendor not on the panel; reported in the Review notes, review state (`substitutions`) and export.
- **Per-call time limit** `REVIEW_CALL_TIMEOUT` for every review call (outline, critique, critic, deliberation, vote, revision); a timeout is handled like any other failure.
- **OpenRouter hosting preferences**: `OPENROUTER_PROVIDER_ORDER`, `OPENROUTER_ALLOW_FALLBACKS`, `OPENROUTER_DATA_COLLECTION`.
- **`crossvet sessions`** lists saved runs, newest first, with state and question.
- **Langfuse scores for every CLI run**: with Langfuse configured, `crossvet run` / `resume` attach the same scores as `crossvet-compare` (citations, flagged URLs, reviewer score, critic, deliberation stop reason and rounds saved, blind-pass omissions) to the run's trace.

### Changed
- Re-running `crossvet-setup` keeps an existing `REVIEW_MODELS` (and reviser) instead of re-picking; `--auto` re-picks.
- The automatic OpenRouter pick also considers Z.ai (GLM) and Moonshot (Kimi).

## [1.2.0]

### Added
- **Blind first pass** (`REVIEW_BLIND_PASS_ENABLED`, off by default): before reading the draft, each reviewer outlines the answer from the research notes, with a supporting passage per point (`REVIEW_BLIND_MAX_POINTS`, `REVIEW_BLIND_MAX_TOKENS`). Code drops points whose passage is not in the notes, checks which grounded points the draft covers, and adds the omissions to that reviewer's critique. Each reviewer sees its own outline while critiquing.
- Review notes, review state and run export (`blind_pass`, with every outline); `crossvet-compare` column and Langfuse score `blind_omissions`; a `blind-pass` setup in `crossvet-setup --compare-plan`.

## [1.1.0]

### Added
- **Engagement labels in deliberation**: challengers label every finding AGREE, DISAGREE or BUILD_ON by its anonymous id. DISAGREE is a challenge to the author; BUILD_ON extends a finding only when its quote is found in the research notes, and is otherwise ignored and counted.
- **Early stopping, decided in code**: deliberation stops on `consensus` (no finding moved and enough findings endorsed, `REVIEW_CONSENSUS_THRESHOLD`) or when it is `stable` (nothing moved for two rounds). `REVIEW_DELIBERATION_MIN_ROUNDS` sets a floor.
- **False-consensus guard**: endorsements that mostly cite nothing in the notes (`REVIEW_CONSENSUS_MIN_GROUNDED_SHARE`), or a silent challenger, buy one more round with the next challenger instead of ending deliberation.
- **Measurement**: the Review notes give the stop reason and rounds saved; the run export and review state add `stop_reason`, `rounds_saved`, `agreement_rate`, `guard_rounds`, `model_calls` and per-round stats; `crossvet-compare` adds `mean_deliberation_rounds`, `rounds_saved`, `mean_agreement_rate` and `deliberation_calls`; Langfuse gets matching scores plus a categorical `stop_reason`; `crossvet-setup --compare-plan` adds a fixed vs early-stop pair.

### Changed
- `REVIEW_DELIBERATION_EARLY_STOP` defaults to `true`. Set it to `false` for the v1.0 rule (stop only when no challenger contests anything). With it on, a silent challenger no longer ends deliberation at once.

## [1.0.0]

### Added
- **Docker Compose**: `docker compose up --build` runs the API (both graphs) and the web UI, bound to localhost; the API image runs as a non-root user and reads keys only at runtime.
- **CI**: Docker image builds with a smoke test of both graphs, gitleaks secret scanning over full history, an SPDX SBOM artifact, and CodeQL for Python and TypeScript (public repositories).
- **Docs**: [Architecture](docs/ARCHITECTURE.md), [Design decisions](docs/DESIGN-DECISIONS.md) and an [Evaluations](docs/EVALS.md) protocol (results are published only from real runs).

### Changed
- Web UI title is now Crossvet.

## [0.8.0]

### Added
- **Grounded search on self-hosted infrastructure**: `SEARCH_API=gateway` uses a research gateway over MCP (Streamable HTTP, bearer auth) — SearXNG discovery, layered page reading, per-source engine and read status, tolerant payload parsing, per-query failure isolation. Contract tests mirror the gateway's `search_and_read` reply (per-source rank, engine, snippet and read result with extractor, outcome and truncation); `num_read` is sent when the gateway advertises it.
- **Combined search**: `SEARCH_ALSO=openai|anthropic` adds a model's built-in web search next to the gateway or Tavily, so researchers can use both; the setup checker reports when it is ignored because the research model is from another vendor.

## [0.7.0]

### Added
- **Fine-tuning data path** `crossvet-dataset`: converts run exports into `mlx_lm.lora` chat datasets (`train/valid/test.jsonl`, split by research brief) for two tasks — `critique` (target: the peer-voted critique after the critic and deliberation) and `revise` (target: a successful revision that cites only URLs the research read). Deduplicates, skips malformed lines and reports why each run was skipped.

### Changed
- Run export `schema_version` 2 adds the research notes, critique labels, revision feedback and whether the revision succeeded.

## [0.6.0]

### Added
- **Deep Agents edition** (graph `deep_agent`): a LangChain Deep Agent plans, delegates sub-questions to a researcher sub-agent and writes the report to its virtual filesystem; the same cross-vendor review follows. A callback captures every search result returned to the agent or its sub-agents (and, with built-in model search, the sources in every model reply) as the research notes the review verifies against.
- `crossvet-compare` setups accept `edition = "deep_agent"`; `examples/compare/editions.toml` compares the two editions with the same models.

### Changed
- New dependency: `deepagents` 0.7.

## [0.5.0]

### Added
- **Deliberation rounds** (`REVIEW_DELIBERATION_ROUNDS`, 0 = off, capped at 3): after the critic, a rotating challenger (never the author) contests findings with optional quotes from the notes; authors maintain, revise or withdraw. A change of position is applied only when a quote from the challenger or the author is verified in code to appear in the research notes; ungrounded changes are ignored, the original finding is kept and the change is flagged as possible sycophancy. Rounds stop early when nothing is contested. Results appear in the Review notes, the review state and the run export.
- `crossvet-compare` records grounded and ungrounded position changes; `examples/compare/deliberation.toml` compares a single round with two deliberation rounds.

## [0.4.0]

### Added
- **Model comparison harness** `crossvet-compare`: runs every question under every named setup (TOML) with optional repeats and writes per-run JSONL, a per-setup summary (Markdown and CSV) and all reports. Records latency, tokens per model from usage metadata, cited and flagged URLs, reviewer scores, critic outcomes and failed reviewers; failed runs are recorded without stopping the comparison. Example setups and questions in `examples/compare/`.
- `crossvet-setup --compare-plan FILE` writes comparison setups from the models your keys and local servers offer; `examples/compare/questions-15.txt` adds 15 questions with checkable answers.
- Langfuse: with keys set, each comparison run is traced (session per comparison, `setup:` tags) and scored with its metrics; the trace id is saved in `results.jsonl`.

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
