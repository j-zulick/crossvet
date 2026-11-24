# Model fit leaderboard (2026-11-18)

7 models x 4 roles x 4 synthetic cases x 1 repeat(s). Total spend: $1.72. Scores come from code (answer keys, kept facts, checklists), not from a judge model.

## Recommended role map

| Role | Best quality | Best value (within 10% of the top score, cheapest) |
|---|---|---|
| compression | `anthropic:claude-haiku-5-5` | `anthropic:claude-haiku-5-5` |
| writer | `openai:gpt-6.1-sol` | `openai:gpt-6.1-sol` |
| reviewer | `openai:gpt-6.1-sol` | `openai:gpt-6-luna` |
| reviser | `openai:gpt-6-luna` | `openai:gpt-6-luna` |

## compression

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `anthropic:claude-haiku-5-5` * | 0.88 ± 0.12 | 1.00 | $0.0011 (est.) | 7.66 | 0% |
| 2 | `anthropic:claude-sonnet-5-5` | 0.88 ± 0.12 | 1.00 | $0.0178 (est.) | 11.17 | 0% |
| 3 | `anthropic:claude-opus-5-5` | 0.88 ± 0.12 | 1.00 | $0.0369 (est.) | 13.86 | 0% |
| 4 | `openai:gpt-6.1-terra` | 0.75 ± 0.14 | 1.00 | $0.0049 (est.) | 10.12 | 0% |
| 5 | `openai:gpt-6.1-sol` | 0.75 ± 0.14 | 1.00 | $0.0111 (est.) | 11.88 | 0% |
| 6 | `openai:gpt-5.4-mini` | 0.62 ± 0.12 | 1.00 | $0.0049 (est.) | 4.2 | 0% |
| 7 | `openai:gpt-6-luna` * | 0.50 | 1.00 | $0.0006 (est.) | 9.0 | 0% |

## writer

| # | Model | Quality | facts covered | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-sol` * | 0.97 ± 0.03 | 0.96 | $0.0288 (est.) | 46.59 | 0% |
| 2 | `anthropic:claude-sonnet-5-5` | 0.88 ± 0.12 | 1.00 | $0.0385 (est.) | 23.11 | 0% |
| 3 | `anthropic:claude-opus-5-5` | 0.88 ± 0.12 | 1.00 | $0.0760 (est.) | 34.09 | 0% |
| 4 | `openai:gpt-6-luna` * | 0.86 ± 0.14 | 0.96 | $0.0012 (est.) | 19.83 | 0% |
| 5 | `anthropic:claude-haiku-5-5` | 0.85 ± 0.12 | 0.96 | $0.0026 (est.) | 22.52 | 0% |
| 6 | `openai:gpt-6.1-terra` | 0.85 ± 0.12 | 0.96 | $0.0122 (est.) | 30.37 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.84 ± 0.12 | 0.97 | $0.0099 (est.) | 11.78 | 0% |

## reviewer

| # | Model | Quality | planted errors caught | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-sol` * | 0.80 ± 0.02 | 1.00 | $0.0161 (est.) | 26.46 | 0% |
| 2 | `openai:gpt-6-luna` * | 0.76 ± 0.06 | 0.90 | $0.0014 (est.) | 19.81 | 0% |
| 3 | `openai:gpt-6.1-terra` | 0.69 ± 0.03 | 0.90 | $0.0086 (est.) | 21.04 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 0.68 ± 0.03 | 1.00 | $0.0635 (est.) | 26.44 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 0.65 ± 0.03 | 1.00 | $0.0377 (est.) | 24.66 | 0% |
| 6 | `openai:gpt-5.4-mini` | 0.61 ± 0.11 | 0.85 | $0.0080 (est.) | 9.69 | 0% |
| 7 | `anthropic:claude-haiku-5-5` | 0.57 ± 0.02 | 1.00 | $0.0024 (est.) | 20.3 | 0% |

## reviser

| # | Model | Quality | errors fixed | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0006 (est.) | 10.07 | 0% |
| 2 | `anthropic:claude-haiku-5-5` | 1.00 | 1.00 | $0.0010 (est.) | 6.92 | 0% |
| 3 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0041 (est.) | 7.18 | 0% |
| 4 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0069 (est.) | 5.43 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0092 (est.) | 4.37 | 0% |
| 6 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0217 (est.) | 6.72 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.95 ± 0.05 | 0.95 | $0.0024 (est.) | 1.92 | 0% |

\* on the cost-quality frontier: no other model is both better and cheaper.
Scoring formulas: see `docs/MODEL-SELECTION.md` or `uv run python -m open_deep_research.bench --help`.
