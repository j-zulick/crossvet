# Model fit leaderboard (2026-11-17)

4 models x 7 roles x 6 synthetic cases x 1 repeat(s). Total spend: $1.49. Scores come from code (answer keys, kept facts, checklists), not from a judge model.

## Recommended role map

| Role | Best quality | Best value (within 10% of the top score, cheapest) |
|---|---|---|
| supervisor | `openai:gpt-6.1-sol` | `anthropic:claude-haiku-5-5` |
| researcher | `openai:gpt-5.4-mini` | `anthropic:claude-haiku-5-5` |
| compression | `anthropic:claude-haiku-5-5` | `anthropic:claude-haiku-5-5` |
| writer | `openai:gpt-5.4-mini` | `anthropic:claude-haiku-5-5` |
| reviewer | `openai:gpt-5.4-mini` | `openai:gpt-5.4-mini` |
| critic | `anthropic:claude-haiku-5-5` | `anthropic:claude-haiku-5-5` |
| reviser | `anthropic:claude-haiku-5-5` | `anthropic:claude-haiku-5-5` |

## supervisor

| # | Model | Quality | aspects delegated | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-sol` * | 0.97 ± 0.03 | 0.96 | $0.0257 (est.) | 29.02 | 0% |
| 2 | `anthropic:claude-haiku-5-5` * | 0.95 ± 0.03 | 0.92 | $0.0019 (est.) | 10.48 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 0.95 ± 0.03 | 0.92 | $0.0325 (est.) | 13.54 | 0% |
| 4 | `openai:gpt-5.4-mini` | 0.90 ± 0.03 | 0.83 | $0.0056 (est.) | 4.6 | 0% |

## researcher

| # | Model | Quality | facts retrieved | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-5.4-mini` * | 0.88 ± 0.03 | 0.97 | $0.0049 (est.) | 3.17 | 0% |
| 2 | `anthropic:claude-haiku-5-5` * | 0.88 ± 0.03 | 1.00 | $0.0012 (est.) | 6.91 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 0.88 ± 0.03 | 1.00 | $0.0174 (est.) | 9.32 | 0% |
| 4 | `openai:gpt-6.1-sol` | 0.83 ± 0.03 | 0.97 | $0.0149 (est.) | 19.5 | 0% |

## compression

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `anthropic:claude-haiku-5-5` * | 1.00 | 1.00 | $0.0004 (est.) | 2.26 | 0% |
| 2 | `openai:gpt-5.4-mini` | 1.00 | 1.00 | $0.0021 (est.) | 1.38 | 0% |
| 3 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0050 (est.) | 5.77 | 0% |
| 4 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0077 (est.) | 4.14 | 0% |

## writer

| # | Model | Quality | facts covered | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-5.4-mini` * | 1.00 | 1.00 | $0.0077 (est.) | 5.97 | 0% |
| 2 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0216 (est.) | 34.97 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0274 (est.) | 17.79 | 0% |
| 4 | `anthropic:claude-haiku-5-5` * | 0.98 ± 0.02 | 0.97 | $0.0018 (est.) | 14.66 | 0% |

## reviewer

| # | Model | Quality | planted errors caught | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-5.4-mini` * | 0.91 ± 0.04 | 1.00 | $0.0048 (est.) | 4.46 | 0% |
| 2 | `openai:gpt-6.1-sol` | 0.84 ± 0.02 | 1.00 | $0.0111 (est.) | 17.03 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 0.65 ± 0.03 | 1.00 | $0.0256 (est.) | 17.99 | 0% |
| 4 | `anthropic:claude-haiku-5-5` * | 0.61 ± 0.02 | 1.00 | $0.0015 (est.) | 14.21 | 0% |

## critic

| # | Model | Quality | balanced accuracy | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `anthropic:claude-haiku-5-5` * | 1.00 | 1.00 | $0.0007 (est.) | 4.92 | 0% |
| 2 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0080 (est.) | 3.94 | 0% |
| 3 | `openai:gpt-6.1-sol` | 0.98 ± 0.02 | 0.98 | $0.0056 (est.) | 4.85 | 0% |
| 4 | `openai:gpt-5.4-mini` | 0.90 ± 0.04 | 0.90 | $0.0022 (est.) | 1.59 | 0% |

## reviser

| # | Model | Quality | errors fixed | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `anthropic:claude-haiku-5-5` * | 1.00 | 1.00 | $0.0005 (est.) | 3.13 | 0% |
| 2 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0035 (est.) | 3.21 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0051 (est.) | 2.17 | 0% |
| 4 | `openai:gpt-5.4-mini` | 0.92 ± 0.08 | 0.96 | $0.0014 (est.) | 1.02 | 0% |

\* on the cost-quality frontier: no other model is both better and cheaper.
Scoring formulas: see `docs/MODEL-SELECTION.md` or `uv run python -m open_deep_research.bench --help`.
