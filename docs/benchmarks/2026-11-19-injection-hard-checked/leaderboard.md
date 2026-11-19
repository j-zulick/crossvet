# Model fit leaderboard (2026-11-19)

7 models x 2 roles x 4 synthetic cases x 1 repeat(s). Total spend: $1.00. Scores come from code (answer keys, kept facts, checklists), not from a judge model.

## Recommended role map

| Role | Best quality | Best value (within 10% of the top score, cheapest) |
|---|---|---|
| compression | `openai:gpt-6.1-terra` | `openai:gpt-6.1-terra` |
| writer | `anthropic:claude-sonnet-5-5` | `anthropic:claude-haiku-5-5` |

## compression

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-terra` * | 1.00 | 1.00 | $0.0050 (est.) | 11.01 | 0% |
| 2 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0109 (est.) | 10.77 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0183 (est.) | 9.72 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0369 (est.) | 12.65 | 0% |
| 5 | `openai:gpt-6-luna` * | 0.88 ± 0.12 | 1.00 | $0.0007 (est.) | 11.22 | 0% |
| 6 | `anthropic:claude-haiku-5-5` | 0.88 ± 0.12 | 1.00 | $0.0013 (est.) | 8.02 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.75 ± 0.14 | 1.00 | $0.0047 (est.) | 4.51 | 0% |

## writer

| # | Model | Quality | facts covered | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `anthropic:claude-sonnet-5-5` * | 1.00 | 1.00 | $0.0382 (est.) | 24.37 | 0% |
| 2 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0804 (est.) | 36.76 | 0% |
| 3 | `anthropic:claude-haiku-5-5` * | 0.99 ± 0.01 | 1.00 | $0.0028 (est.) | 23.53 | 0% |
| 4 | `openai:gpt-6.1-terra` | 0.97 ± 0.03 | 0.96 | $0.0114 (est.) | 29.01 | 0% |
| 5 | `openai:gpt-6.1-sol` | 0.97 ± 0.03 | 0.96 | $0.0290 (est.) | 50.38 | 0% |
| 6 | `openai:gpt-5.4-mini` | 0.94 ± 0.04 | 0.93 | $0.0096 (est.) | 16.21 | 0% |
| 7 | `openai:gpt-6-luna` * | 0.86 ± 0.14 | 0.96 | $0.0011 (est.) | 19.45 | 0% |

\* on the cost-quality frontier: no other model is both better and cheaper.
Scoring formulas: see `docs/MODEL-SELECTION.md` or `uv run python -m open_deep_research.bench --help`.
