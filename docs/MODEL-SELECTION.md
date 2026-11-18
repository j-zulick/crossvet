# Which model for which job

A research pipeline is not one job. Planning the research, searching, compressing notes, writing the report, reviewing it, judging the reviews and revising are different tasks, and the model that is best at one is often overpriced for another. `crossvet-bench` measures each role separately, then turns the results into a configuration.

```bash
uv run crossvet-bench suggest                                    # your models + the newest per vendor on OpenRouter
uv run crossvet-bench run --models <comma-separated ids> --dry-run
uv run crossvet-bench run --models <comma-separated ids> --max-usd 5
uv run crossvet-bench run --models <comma-separated ids> --suite hard   # long notes, conflicting sources, subtler errors
uv run crossvet-bench apply --preset best-value                  # write the winners to .env
uv run crossvet-doctor                                           # check the result
```

Any model Crossvet can call can be benchmarked: `openai:`, `anthropic:`, `google_genai:`, `openrouter:<maker>/<model>` (one key, most vendors), `ollama:` and `local:` for models on your own machine.

## Method

**One role at a time, on frozen inputs.** Every candidate gets the same notes, the same draft and the same findings, built from synthetic cases: six standard ones (`--suite standard`, the default) and three hard ones with long notes, conflicting sources and subtler errors (`--suite hard`; `--suite all` runs both). Each role is called with the prompt and schema Crossvet uses in a real run, with the same output limits and turn caps, so the benchmark measures the work Crossvet actually asks for.

**Synthetic cases.** Every organization, place and number is invented, and every URL is on the reserved `.example` domain, so a model can't answer from memory and has to use the notes. The cases cover SEO, public policy, real estate, technology, marketing and health policy (`src/open_deep_research/bench_cases.py`).

**Scored by code, not by a judge model.** Using a model to grade models brings the biases Crossvet exists to counter: favoring its own style, position effects, overconfidence. Every score here comes from an answer key or a string check:

| Role | What the model does | Quality score (0 to 1) |
|---|---|---|
| Orchestration (`supervisor`) | Plans and delegates research with `ConductResearch` / `ResearchComplete`, against scripted research results | 0.6 × share of the question's aspects delegated + 0.2 if it ended research cleanly + 0.2 × (1 − share of near-duplicate delegations) |
| Research (`researcher`) | Searches with a scripted search tool that returns matching sources | 0.5 × share of key facts whose source it retrieved + 0.3 × share of aspects its queries covered + 0.2 if it finished before the cap |
| Compression | Cleans up research notes for the report writer | mean of key facts kept and source URLs kept |
| Report writing (`writer`) | Writes the report from the notes | 0.7 × key facts covered + 0.3 × sources cited − 0.25 per cited URL that is not in the notes |
| Review (`reviewer`) | Critiques a draft with four planted errors, then the clean draft | catch rate × 1 / (1 + 0.1 × findings raised against the clean draft) |
| Critic | Judges true findings (the planted errors) and false findings the notes contradict | balanced accuracy: mean of true findings agreed and false findings rejected (agreeing with everything scores 0.5); a contradicting quote that isn't in the notes counts as wrong |
| Revision (`reviser`) | Revises the planted draft using the true findings | share of planted errors fixed − 0.25 per unread URL − 0.25 if it narrates its edits |

The four planted errors in every case are a wrong number, a citation to a source the research never read, an unsupported claim and an omitted finding: the failures the cross-vendor review is built to catch.

**Cost.** OpenRouter returns the real cost of every call, and the bench records it. For other providers, cost is estimated from tokens and a price you pass with `--price model=input,output` (USD per million tokens), or from OpenRouter's catalog price for the same model. Models with no known price show "-" and are left out of the value ranking. To compare on real cost, run candidates through OpenRouter.

**Safety rails.** `--dry-run` prints the plan and an upper-bound cost estimate and calls nothing. `--max-usd` (default 5) stops new jobs once the budget is spent. Runs resume: re-running skips finished jobs. Before any call, a model that OpenRouter's catalog says can't call tools (or return structured output) is skipped for the roles that need it.

## Outputs

`bench-results/` contains:

- `leaderboard.md`: one table per role, with quality ± standard error, the role's key sub-metric, cost per case, median latency and failure rate. Models on the cost-quality frontier are starred.
- `quality-vs-cost.svg`: one panel per role, with the frontier joined.
- `role-map.json`: per role, the **best-quality** model and the **best-value** model (the cheapest within 10% of the top score).
- `leaderboard.csv`, `leaderboard.json`, `results.jsonl`: every job with its metrics, tokens, cost, and what the model actually said, so any score can be audited.

With Langfuse configured, every bench call is traced (one session per bench run, tagged by role and model).

## From results to configuration

`crossvet-bench apply --preset best-value` (or `best-quality`) writes the role map to `.env`:

| Setting | Comes from |
|---|---|
| `SUPERVISOR_MODEL` | orchestration winner |
| `RESEARCHER_MODEL` | research winner |
| `COMPRESSION_MODEL`, `SUMMARIZATION_MODEL` | compression winner |
| `FINAL_REPORT_MODEL` | writer winner |
| `REVIEW_MODELS` | the top reviewers, at most one per vendor (diversity is the point of the panel) |
| `REVIEW_REVISER_MODEL` | the top reviser from a vendor not on the panel |

The critic is chosen per finding from the panel (always a different model from the finding's author), so the critic results inform which models to put on the panel rather than setting a variable.

## Full-run checks

The benchmark isolates roles. To check that a winner also helps end to end, `crossvet-bench live-plan --role supervisor --models a,b` writes a `crossvet-compare` file in which only that role's model changes. Run it on real questions and compare citations, critic outcomes, cost and latency:

```bash
uv run crossvet-bench live-plan --role supervisor --models anthropic:claude-opus-5-5,openrouter:qwen/qwen4-max --out supervisor.toml
uv run crossvet-compare --setups supervisor.toml --questions examples/compare/questions-15.txt --repeats 2
```

## Limitations

- Six cases is a small sample: treat differences within the standard error as ties, and add `--repeats` for stable rankings.
- The scripted search and research results are simpler than the live web. The bench measures the decision quality of a role, not the reach of a search engine.
- String checks are strict: a reviewer who describes a planted error without naming the wrong value, the source or the claim isn't credited. `results.jsonl` keeps every output so this can be checked.
- Reviewer noise is measured as findings against a draft that the notes fully support. Some of those findings are fair caveats (for example "correlational"), which is why the penalty is small.
- Prices and model behavior change. Every result records the run date and the exact model ids.

## Results

Results are added here only from real runs, with the date, model ids, cases, repeats and total cost, following the [evaluation protocol](EVALS.md).

### November 17, 2026: four models, two vendors

`openai:gpt-6.1-sol`, `openai:gpt-5.4-mini`, `anthropic:claude-sonnet-5-5` and `anthropic:claude-haiku-5-5`, called through each vendor's own API; all seven roles, all six cases, one repeat. 168 jobs, no failures, $1.49 in total (estimated from tokens and list prices). Full tables, chart and every model output: [benchmarks/2026-11-17](benchmarks/2026-11-17/).

| Role | Best quality | Best value | What separated the models |
|---|---|---|---|
| Orchestration | gpt-6.1-sol (0.97) | claude-haiku-5-5 (0.95) | aspect coverage: gpt-5.4-mini delegated a single broad topic in five of six cases (0.90) |
| Research | gpt-5.4-mini, claude-haiku-5-5, claude-sonnet-5-5 (0.88) | claude-haiku-5-5 | gpt-6.1-sol's queries covered fewer aspects (0.83) |
| Compression | all four (1.00) | claude-haiku-5-5 | nothing: every model kept every fact and URL |
| Report writing | gpt-5.4-mini, gpt-6.1-sol, claude-sonnet-5-5 (1.00) | claude-haiku-5-5 (0.98) | almost nothing |
| Review | gpt-5.4-mini (0.91) | gpt-5.4-mini | noise, not recall: all four caught every planted error; on the clean drafts the Claude models raised 5.7 (Sonnet) and 6.5 (Haiku) findings per draft against 1.2 (gpt-5.4-mini) and 2.0 (gpt-6.1-sol) |
| Critic | claude-haiku-5-5, claude-sonnet-5-5 (1.00) | claude-haiku-5-5 | gpt-5.4-mini accepted some findings the notes contradict and rejected some true ones (0.90) |
| Revision | claude-haiku-5-5, gpt-6.1-sol, claude-sonnet-5-5 (1.00) | claude-haiku-5-5 | gpt-5.4-mini kept the unread citation in one case (0.92) |

What this run says:

- **The smallest model was enough for most of the pipeline.** Claude Haiku 5.5 was within 0.03 of the best score in six of seven roles (all but review), at 7 to 19 times lower cost per case than Claude Sonnet 5.5 or GPT-6.1 Sol. Across the whole run it cost $0.05, against $0.53 for GPT-6.1 Sol and $0.74 for Claude Sonnet 5.5.
- **The larger models' extra cost bought little on these cases.** They led outright only in orchestration: GPT-6.1 Sol scored 0.97 against Haiku's 0.95, at about 13 times the cost.
- **Review quality differed in precision, not recall.** Every model found every planted error; what differed was how much it flagged on a draft with nothing wrong. Claude's extra findings were mostly caveats (correlation versus causation, single-month samples) rather than mistakes, so whether they count as noise depends on the reader. The penalty is deliberately small for that reason.
- **Mixing vendors is cheap.** `apply --preset best-value` builds a panel of gpt-5.4-mini (the most precise reviewer) and Claude Sonnet 5.5, with Haiku for orchestration, compression, writing and revision: the cross-vendor design Crossvet uses anyway, at small-model prices.

Caveats:

- **Most roles saturate on these cases.** Compression, writing, revision and critique sit at or near 1.00 for every model, so they don't separate models yet; harder cases (longer notes, conflicting sources, subtler planted errors) are the next step.
- One repeat on six cases: differences of a few hundredths are within the standard errors shown in the leaderboard.
- Costs are estimates from list prices (OpenRouter's catalog, which matches Anthropic's published Haiku 5.5 price), not invoices. Haiku 5.5 is priced higher above 100,000 prompt tokens; every bench prompt is far below that.
- Synthetic notes are short and clean. A full-run check with `live-plan` is the way to confirm a role choice on real questions.

### November 18, 2026 (UTC): three newer models added

`openai:gpt-6-luna`, `openai:gpt-6.1-terra` and `anthropic:claude-opus-5-5` were added to the run above. The bench resumed from it, so the four earlier models were not run again. That makes 294 jobs with no failures; the new jobs cost $1.98 (estimated from tokens and list prices). Full tables, chart and every output: [benchmarks/2026-11-18](benchmarks/2026-11-18/).

| Role | Best quality | Best value | What changed with the new models |
|---|---|---|---|
| Orchestration | gpt-6.1-sol (0.97) | claude-haiku-5-5 (0.95) | nothing: gpt-6-luna stopped researching cleanly in only 2 of 6 cases (0.82); Opus 5.5 scored 0.93 at about 2.6 times Sol's cost |
| Research | gpt-5.4-mini (0.88) | claude-haiku-5-5 | gpt-6-luna ran 10.5 searches per case and hit the turn cap in 4 of 6 (0.78) |
| Compression | all seven (1.00) | gpt-6-luna | gpt-6-luna is the cheapest model that kept every fact and URL |
| Report writing | six of seven (1.00) | gpt-6-luna | gpt-6-luna matched the best at about a ninth of gpt-5.4-mini's cost per case, with a slower median (13 s against 6 s) |
| Review | gpt-5.4-mini (0.91) | gpt-6-luna (0.85) | every model again caught every planted error; the Claude models, Opus included, raised the most findings on clean drafts |
| Critic | Claude Haiku, Sonnet and Opus 5.5, GPT-6.1 Terra (1.00) | gpt-6-luna (0.98) | gpt-5.4-mini remains the weakest critic (0.90) |
| Revision | six of seven (1.00) | gpt-6-luna | gpt-5.4-mini kept an unread citation in one case (0.92) |

What this run says:

- **GPT-6 Luna takes over the cheap roles.** It scored the top mark in compression, report writing and revision at the lowest cost of any model. It shouldn't plan or search, though: as orchestrator and researcher it kept searching instead of finishing.
- **Claude Opus 5.5 won no role.** It tied for the top score in compression, writing, critique and revision, and was the most expensive model in each.
- **The earlier picks hold where Luna is weak:** GPT-6.1 Sol leads orchestration, gpt-5.4-mini review, and Claude Haiku 5.5 is the best value for orchestration and research.

The caveats above apply here too: most roles saturate on these cases, and one repeat on six cases leaves differences of a few hundredths within the standard errors.

### November 18, 2026 (UTC): hard suite

On the standard cases most roles saturate, so three harder cases were added (`--suite hard`; see the [benchmark folder](benchmarks/2026-11-18-hard/) for how they're built). Same seven models, 147 jobs with no failures, $2.19.

| Role | Best quality | Best value | What the hard cases showed |
|---|---|---|---|
| Orchestration | gpt-6.1-sol (0.92) | gpt-6-luna (0.84) | the spread widened from 0.82–0.97 to 0.68–0.92; gpt-5.4-mini delegated one broad topic and covered under half the aspects (0.68) |
| Research | gpt-6.1-terra (0.82) | claude-haiku-5-5 (0.76) | gpt-6-luna again ran out of turns in one case in three |
| Compression | six of seven (1.00) | gpt-6-luna | still saturated; gpt-5.4-mini dropped a URL once (0.98) |
| Report writing | gpt-5.4-mini, claude-sonnet-5-5, claude-opus-5-5 (1.00) | gpt-6-luna (0.97) | the rest missed one fact in one case, within the standard error |
| Review | gpt-6.1-sol (0.79) | gpt-6-luna (0.75) | gpt-6.1-sol caught every planted error; gpt-5.4-mini missed the look-alike unread source in one case (0.59); the Claude models caught everything but raised the most findings on clean drafts |
| Critic | GPT-6.1 Terra and Sol, Claude Sonnet and Opus 5.5 (1.00) | gpt-6-luna (0.92) | gpt-5.4-mini is again the weakest critic (0.88) |
| Revision | five of seven (1.00) | gpt-6-luna | gpt-5.4-mini and GPT-6.1 Terra each missed restoring one caveat (0.92) |

What this run says:

- **Harder cases separate the planning, research and review roles.** Writing, compression and revision stay close to 1.00 even with distractors and conflicting sources, so those roles are still cheap to fill.
- **gpt-5.4-mini is the weakest reviewer and critic once errors get subtle.** It was the most precise reviewer on the standard cases, but here it missed a citation to a source with a look-alike title. The critic is picked from the review panel, so this matters twice. The example panel in `.env.example` now uses gpt-6.1-sol instead (v1.7).
- **GPT-6 Luna stays the value pick** for every role except research, where Claude Haiku 5.5 is cheaper for nearly the same score.

Caveats: three cases with one repeat each, so a single miss moves a score by 0.08 or more. Treat differences under about 0.1 as ties. Every score can be checked against the model output saved in `results.jsonl`.

### Default models

The built-in defaults use only OpenAI models, so one OpenAI key runs the research pipeline (review still needs a second vendor). They come from the runs above (updated in v1.6.1 and v1.7):

| Setting | Default | Why |
|---|---|---|
| `RESEARCH_MODEL` (also orchestration and research unless set separately) | `openai:gpt-6.1-sol` | best orchestration score (0.97); orchestration is the role where a larger model leads |
| `SUMMARIZATION_MODEL`, `COMPRESSION_MODEL`, `FINAL_REPORT_MODEL` | `openai:gpt-6-luna` | top score in compression and report writing (1.00) at the lowest cost per case of any model measured |
| `REVIEW_MODELS` in `.env.example` | `openai:gpt-6.1-sol,anthropic:claude-sonnet-5-5` | the best reviewer on the hard suite, a perfect critic on both suites, plus a second vendor (v1.7; v1.6 used gpt-5.4-mini) |

v1.6.0 used `openai:gpt-5.4-mini` for the three cheap roles; the [review pilot](evals/2026-11-17-pilot/) ran on those. `crossvet-setup` replaces defaults your keys can't call, and `crossvet-bench apply` replaces them with your own measured picks.

### Not yet measured

Google's models (Gemini) have not been benchmarked yet, and neither has any model through OpenRouter. To measure your own candidates:

```bash
uv run crossvet-bench run --models <comma-separated ids> --dry-run
uv run crossvet-bench run --models <same list> --max-usd 5
```

Prices are list prices as of November 2026; check each vendor's page before spending.
