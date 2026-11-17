# Which model for which job

A research pipeline is not one job. Planning the research, searching, compressing notes, writing the report, reviewing it, judging the reviews and revising are different tasks, and the model that is best at one is often overpriced for another. `crossvet-bench` measures each role separately, then turns the results into a configuration.

```bash
uv run crossvet-bench suggest                                    # your models + the newest per vendor on OpenRouter
uv run crossvet-bench run --models <comma-separated ids> --dry-run
uv run crossvet-bench run --models <comma-separated ids> --max-usd 5
uv run crossvet-bench apply --preset best-value                  # write the winners to .env
uv run crossvet-doctor                                           # check the result
```

Any model Crossvet can call can be benchmarked: `openai:`, `anthropic:`, `google_genai:`, `openrouter:<maker>/<model>` (one key, most vendors), `ollama:` and `local:` for models on your own machine.

## Method

**One role at a time, on frozen inputs.** Every candidate gets the same notes, the same draft and the same findings, built from six synthetic cases. Each role is called with the prompt and schema Crossvet uses in a real run, with the same output limits and turn caps, so the benchmark measures the work Crossvet actually asks for.

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
