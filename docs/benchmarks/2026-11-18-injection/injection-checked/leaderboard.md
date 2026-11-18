# Model fit leaderboard (2026-11-18)

7 models x 5 roles x 4 synthetic cases x 1 repeat(s). Total spend: $1.62. Scores come from code (answer keys, kept facts, checklists), not from a judge model.

## Recommended role map

| Role | Best quality | Best value (within 10% of the top score, cheapest) |
|---|---|---|
| compression | `openai:gpt-6-luna` | `openai:gpt-6-luna` |
| writer | `openai:gpt-5.4-mini` | `openai:gpt-6-luna` |
| reviewer | `openai:gpt-6.1-sol` | `openai:gpt-6-luna` |
| critic | `openai:gpt-6.1-terra` | `openai:gpt-6-luna` |
| reviser | `openai:gpt-6-luna` | `openai:gpt-6-luna` |

## compression

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0007 (est.) | 10.26 | 0% |
| 2 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0407 (est.) | 15.72 | 0% |
| 3 | `anthropic:claude-haiku-5-5` | 0.88 ± 0.12 | 1.00 | $0.0011 (est.) | 7.43 | 0% |
| 4 | `openai:gpt-6.1-terra` | 0.88 ± 0.12 | 1.00 | $0.0053 (est.) | 10.68 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 0.88 ± 0.12 | 1.00 | $0.0182 (est.) | 12.03 | 0% |
| 6 | `openai:gpt-5.4-mini` | 0.62 ± 0.12 | 1.00 | $0.0060 (est.) | 6.32 | 0% |
| 7 | `openai:gpt-6.1-sol` | 0.62 ± 0.12 | 1.00 | $0.0118 (est.) | 10.67 | 0% |

## writer

| # | Model | Quality | facts covered | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-5.4-mini` * | 1.00 | 1.00 | $0.0090 (est.) | 11.39 | 0% |
| 2 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0395 (est.) | 25.57 | 0% |
| 3 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0893 (est.) | 39.57 | 0% |
| 4 | `anthropic:claude-haiku-5-5` * | 0.97 ± 0.03 | 0.96 | $0.0029 (est.) | 22.3 | 0% |
| 5 | `openai:gpt-6.1-terra` | 0.97 ± 0.03 | 0.96 | $0.0128 (est.) | 28.68 | 0% |
| 6 | `openai:gpt-6.1-sol` | 0.97 ± 0.03 | 0.96 | $0.0286 (est.) | 49.02 | 0% |
| 7 | `openai:gpt-6-luna` * | 0.93 ± 0.05 | 0.90 | $0.0012 (est.) | 18.92 | 0% |

## reviewer

| # | Model | Quality | planted errors caught | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-sol` * | 0.80 ± 0.02 | 1.00 | $0.0152 (est.) | 23.93 | 0% |
| 2 | `openai:gpt-6-luna` * | 0.79 ± 0.04 | 0.95 | $0.0012 (est.) | 18.66 | 0% |
| 3 | `openai:gpt-6.1-terra` | 0.77 ± 0.02 | 1.00 | $0.0079 (est.) | 17.49 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 0.75 ± 0.02 | 1.00 | $0.0548 (est.) | 20.52 | 25% |
| 5 | `openai:gpt-5.4-mini` | 0.68 ± 0.05 | 0.85 | $0.0072 (est.) | 8.39 | 0% |
| 6 | `anthropic:claude-haiku-5-5` | 0.59 | 1.00 | $0.0026 (est.) | 22.48 | 75% |
| 7 | `anthropic:claude-sonnet-5-5` | 0.59 | 1.00 | $0.0348 (est.) | 21.95 | 0% |

## critic

| # | Model | Quality | balanced accuracy | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-terra` * | 0.97 ± 0.03 | 0.97 | $0.0041 (est.) | 6.67 | 0% |
| 2 | `openai:gpt-6.1-sol` | 0.97 ± 0.03 | 0.97 | $0.0086 (est.) | 7.99 | 0% |
| 3 | `openai:gpt-6-luna` * | 0.95 ± 0.03 | 0.95 | $0.0006 (est.) | 8.63 | 0% |
| 4 | `openai:gpt-5.4-mini` | 0.93 ± 0.05 | 0.93 | $0.0032 (est.) | 2.98 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | - | - | - | - | 100% |
| 6 | `anthropic:claude-opus-5-5` | - | - | - | - | 100% |
| 7 | `anthropic:claude-haiku-5-5` | - | - | - | - | 100% |

## reviser

| # | Model | Quality | errors fixed | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0005 (est.) | 8.54 | 0% |
| 2 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0033 (est.) | 5.96 | 0% |
| 3 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0075 (est.) | 8.45 | 0% |
| 4 | `openai:gpt-5.4-mini` | 0.95 ± 0.05 | 0.95 | $0.0024 (est.) | 2.09 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | - | - | - | - | 100% |
| 6 | `anthropic:claude-opus-5-5` | - | - | - | - | 100% |
| 7 | `anthropic:claude-haiku-5-5` | - | - | - | - | 100% |

\* on the cost-quality frontier: no other model is both better and cheaper.
Scoring formulas: see `docs/MODEL-SELECTION.md` or `uv run python -m open_deep_research.bench --help`.
