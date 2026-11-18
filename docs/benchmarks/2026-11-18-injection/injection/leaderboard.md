# Model fit leaderboard (2026-11-18)

7 models x 5 roles x 4 synthetic cases x 1 repeat(s). Total spend: $1.98. Scores come from code (answer keys, kept facts, checklists), not from a judge model.

## Recommended role map

| Role | Best quality | Best value (within 10% of the top score, cheapest) |
|---|---|---|
| compression | `openai:gpt-6-luna` | `openai:gpt-6-luna` |
| writer | `anthropic:claude-sonnet-5-5` | `openai:gpt-6-luna` |
| reviewer | `openai:gpt-6.1-sol` | `openai:gpt-6-luna` |
| critic | `openai:gpt-6.1-terra` | `openai:gpt-6-luna` |
| reviser | `openai:gpt-6-luna` | `openai:gpt-6-luna` |

## compression

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0007 (est.) | 10.0 | 0% |
| 2 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0049 (est.) | 9.86 | 0% |
| 3 | `anthropic:claude-haiku-5-5` | 0.75 ± 0.14 | 1.00 | $0.0012 (est.) | 7.11 | 0% |
| 4 | `openai:gpt-6.1-sol` | 0.75 ± 0.14 | 1.00 | $0.0102 (est.) | 9.11 | 0% |
| 5 | `anthropic:claude-opus-5-5` | 0.75 ± 0.14 | 1.00 | $0.0418 (est.) | 16.24 | 0% |
| 6 | `openai:gpt-5.4-mini` | 0.62 ± 0.12 | 1.00 | $0.0049 (est.) | 5.16 | 0% |
| 7 | `anthropic:claude-sonnet-5-5` | 0.62 ± 0.12 | 1.00 | $0.0176 (est.) | 10.83 | 0% |

## writer

| # | Model | Quality | facts covered | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `anthropic:claude-sonnet-5-5` * | 1.00 | 1.00 | $0.0391 (est.) | 27.03 | 0% |
| 2 | `openai:gpt-6-luna` * | 0.97 ± 0.03 | 0.96 | $0.0012 (est.) | 19.2 | 0% |
| 3 | `anthropic:claude-haiku-5-5` | 0.97 ± 0.03 | 0.96 | $0.0028 (est.) | 22.87 | 0% |
| 4 | `openai:gpt-6.1-terra` | 0.97 ± 0.03 | 0.96 | $0.0119 (est.) | 27.01 | 0% |
| 5 | `openai:gpt-6.1-sol` | 0.97 ± 0.03 | 0.96 | $0.0288 (est.) | 48.33 | 0% |
| 6 | `openai:gpt-5.4-mini` | 0.93 ± 0.05 | 0.93 | $0.0095 (est.) | 11.05 | 0% |
| 7 | `anthropic:claude-opus-5-5` | 0.88 ± 0.12 | 1.00 | $0.0856 (est.) | 37.78 | 0% |

## reviewer

| # | Model | Quality | planted errors caught | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-sol` * | 0.85 ± 0.02 | 1.00 | $0.0164 (est.) | 27.72 | 0% |
| 2 | `openai:gpt-6-luna` * | 0.78 ± 0.05 | 0.95 | $0.0013 (est.) | 20.74 | 0% |
| 3 | `openai:gpt-6.1-terra` | 0.77 ± 0.02 | 1.00 | $0.0087 (est.) | 20.64 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 0.73 ± 0.01 | 1.00 | $0.0628 (est.) | 25.81 | 0% |
| 5 | `openai:gpt-5.4-mini` | 0.62 ± 0.02 | 1.00 | $0.0081 (est.) | 11.03 | 0% |
| 6 | `anthropic:claude-sonnet-5-5` | 0.61 ± 0.01 | 1.00 | $0.0337 (est.) | 22.34 | 0% |
| 7 | `anthropic:claude-haiku-5-5` | 0.58 ± 0.02 | 1.00 | $0.0026 (est.) | 22.92 | 0% |

## critic

| # | Model | Quality | balanced accuracy | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-terra` * | 0.97 ± 0.03 | 0.97 | $0.0044 (est.) | 7.33 | 0% |
| 2 | `openai:gpt-6.1-sol` | 0.97 ± 0.03 | 0.97 | $0.0082 (est.) | 7.58 | 0% |
| 3 | `anthropic:claude-opus-5-5` | 0.95 ± 0.03 | 0.95 | $0.0259 (est.) | 7.61 | 0% |
| 4 | `openai:gpt-6-luna` * | 0.93 ± 0.05 | 0.93 | $0.0006 (est.) | 8.89 | 0% |
| 5 | `anthropic:claude-haiku-5-5` | 0.93 ± 0.03 | 0.93 | $0.0011 (est.) | 7.13 | 0% |
| 6 | `anthropic:claude-sonnet-5-5` | 0.93 ± 0.03 | 0.93 | $0.0113 (est.) | 5.68 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.75 ± 0.05 | 0.75 | $0.0033 (est.) | 3.47 | 0% |

## reviser

| # | Model | Quality | errors fixed | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0006 (est.) | 7.39 | 0% |
| 2 | `anthropic:claude-haiku-5-5` | 1.00 | 1.00 | $0.0010 (est.) | 7.33 | 0% |
| 3 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0036 (est.) | 5.82 | 0% |
| 4 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0076 (est.) | 7.14 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0089 (est.) | 4.79 | 0% |
| 6 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0224 (est.) | 6.8 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.95 ± 0.05 | 0.95 | $0.0024 (est.) | 2.07 | 0% |

\* on the cost-quality frontier: no other model is both better and cheaper.
Scoring formulas: see `docs/MODEL-SELECTION.md` or `uv run python -m open_deep_research.bench --help`.
