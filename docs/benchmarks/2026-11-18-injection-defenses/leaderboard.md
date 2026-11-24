# Model fit leaderboard (2026-11-19)

7 models x 3 roles x 4 synthetic cases x 1 repeat(s). Total spend: $1.09. Scores come from code (answer keys, kept facts, checklists), not from a judge model.

## Recommended role map

| Role | Best quality | Best value (within 10% of the top score, cheapest) |
|---|---|---|
| summarizer | `openai:gpt-6.1-terra` | `openai:gpt-6.1-terra` |
| compression | `openai:gpt-6-luna` | `openai:gpt-6-luna` |
| writer | `anthropic:claude-opus-5-5` | `openai:gpt-6.1-terra` |

## summarizer

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-terra` * | 1.00 | 1.00 | $0.0095 (est.) | 16.36 | 0% |
| 2 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0189 (est.) | 17.66 | 0% |
| 3 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0712 (est.) | 20.3 | 0% |
| 4 | `anthropic:claude-sonnet-5-5` | 0.88 ± 0.12 | 1.00 | $0.0359 (est.) | 17.52 | 0% |
| 5 | `openai:gpt-6-luna` * | 0.75 ± 0.14 | 1.00 | $0.0011 (est.) | 16.59 | 0% |
| 6 | `anthropic:claude-haiku-5-5` | 0.75 ± 0.14 | 1.00 | $0.0018 (est.) | 12.73 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.75 ± 0.14 | 1.00 | $0.0082 (est.) | 8.65 | 0% |

## compression

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0007 (est.) | 11.03 | 0% |
| 2 | `anthropic:claude-haiku-5-5` | 1.00 | 1.00 | $0.0012 (est.) | 6.9 | 0% |
| 3 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0050 (est.) | 10.46 | 0% |
| 4 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0104 (est.) | 8.17 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0168 (est.) | 10.74 | 0% |
| 6 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0361 (est.) | 12.62 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.75 ± 0.14 | 1.00 | $0.0043 (est.) | 3.97 | 0% |

## writer

| # | Model | Quality | facts covered | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | - | 36.94 | 50% |
| 2 | `anthropic:claude-haiku-5-5` | 0.99 ± 0.01 | 1.00 | - | 25.04 | 50% |
| 3 | `openai:gpt-6.1-terra` * | 0.97 ± 0.03 | 0.96 | $0.0124 (est.) | 31.08 | 0% |
| 4 | `openai:gpt-6.1-sol` | 0.97 ± 0.03 | 0.96 | $0.0284 (est.) | 51.7 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 0.97 ± 0.03 | 0.96 | - | 22.6 | 50% |
| 6 | `openai:gpt-5.4-mini` * | 0.88 ± 0.12 | 1.00 | $0.0102 (est.) | 12.25 | 0% |
| 7 | `openai:gpt-6-luna` * | 0.84 ± 0.13 | 0.93 | $0.0014 (est.) | 25.41 | 0% |

\* on the cost-quality frontier: no other model is both better and cheaper.
Scoring formulas: see `docs/MODEL-SELECTION.md` or `uv run python -m open_deep_research.bench --help`.
