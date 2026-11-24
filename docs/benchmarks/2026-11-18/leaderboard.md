# Model fit leaderboard (2026-11-18)

7 models x 7 roles x 6 synthetic cases x 1 repeat(s). Total spend: $3.47. Scores come from code (answer keys, kept facts, checklists), not from a judge model.

## Recommended role map

| Role | Best quality | Best value (within 10% of the top score, cheapest) |
|---|---|---|
| supervisor | `openai:gpt-6.1-sol` | `anthropic:claude-haiku-5-5` |
| researcher | `openai:gpt-5.4-mini` | `anthropic:claude-haiku-5-5` |
| compression | `openai:gpt-6-luna` | `openai:gpt-6-luna` |
| writer | `openai:gpt-6-luna` | `openai:gpt-6-luna` |
| reviewer | `openai:gpt-5.4-mini` | `openai:gpt-6-luna` |
| critic | `anthropic:claude-haiku-5-5` | `openai:gpt-6-luna` |
| reviser | `openai:gpt-6-luna` | `openai:gpt-6-luna` |

## supervisor

| # | Model | Quality | aspects delegated | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-sol` * | 0.97 ± 0.03 | 0.96 | $0.0257 (est.) | 29.02 | 0% |
| 2 | `anthropic:claude-haiku-5-5` * | 0.95 ± 0.03 | 0.92 | $0.0019 (est.) | 10.48 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 0.95 ± 0.03 | 0.92 | $0.0325 (est.) | 13.54 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 0.93 ± 0.03 | 0.88 | $0.0681 (est.) | 16.36 | 0% |
| 5 | `openai:gpt-5.4-mini` | 0.90 ± 0.03 | 0.83 | $0.0056 (est.) | 4.6 | 0% |
| 6 | `openai:gpt-6.1-terra` | 0.90 ± 0.03 | 0.83 | $0.0124 (est.) | 18.01 | 0% |
| 7 | `openai:gpt-6-luna` * | 0.82 ± 0.01 | 0.92 | $0.0014 (est.) | 21.29 | 0% |

## researcher

| # | Model | Quality | facts retrieved | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-5.4-mini` * | 0.88 ± 0.03 | 0.97 | $0.0049 (est.) | 3.17 | 0% |
| 2 | `anthropic:claude-haiku-5-5` * | 0.88 ± 0.03 | 1.00 | $0.0012 (est.) | 6.91 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 0.88 ± 0.03 | 1.00 | $0.0174 (est.) | 9.32 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 0.88 ± 0.03 | 1.00 | $0.0452 (est.) | 16.14 | 0% |
| 5 | `openai:gpt-6.1-terra` | 0.87 ± 0.04 | 1.00 | $0.0080 (est.) | 17.9 | 0% |
| 6 | `openai:gpt-6.1-sol` | 0.83 ± 0.03 | 0.97 | $0.0149 (est.) | 19.5 | 0% |
| 7 | `openai:gpt-6-luna` * | 0.78 ± 0.04 | 1.00 | $0.0011 (est.) | 14.18 | 0% |

## compression

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0003 (est.) | 3.8 | 0% |
| 2 | `anthropic:claude-haiku-5-5` | 1.00 | 1.00 | $0.0004 (est.) | 2.26 | 0% |
| 3 | `openai:gpt-5.4-mini` | 1.00 | 1.00 | $0.0021 (est.) | 1.38 | 0% |
| 4 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0026 (est.) | 5.3 | 0% |
| 5 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0050 (est.) | 5.77 | 0% |
| 6 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0077 (est.) | 4.14 | 0% |
| 7 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0248 (est.) | 9.66 | 0% |

## writer

| # | Model | Quality | facts covered | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0008 (est.) | 12.82 | 0% |
| 2 | `openai:gpt-5.4-mini` | 1.00 | 1.00 | $0.0077 (est.) | 5.97 | 0% |
| 3 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0084 (est.) | 20.08 | 0% |
| 4 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0216 (est.) | 34.97 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0274 (est.) | 17.79 | 0% |
| 6 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0722 (est.) | 28.55 | 0% |
| 7 | `anthropic:claude-haiku-5-5` | 0.98 ± 0.02 | 0.97 | $0.0018 (est.) | 14.66 | 0% |

## reviewer

| # | Model | Quality | planted errors caught | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-5.4-mini` * | 0.91 ± 0.04 | 1.00 | $0.0048 (est.) | 4.46 | 0% |
| 2 | `openai:gpt-6.1-terra` | 0.89 ± 0.03 | 1.00 | $0.0058 (est.) | 16.1 | 0% |
| 3 | `openai:gpt-6-luna` * | 0.85 ± 0.02 | 1.00 | $0.0009 (est.) | 17.79 | 0% |
| 4 | `openai:gpt-6.1-sol` | 0.84 ± 0.02 | 1.00 | $0.0111 (est.) | 17.03 | 0% |
| 5 | `anthropic:claude-opus-5-5` | 0.69 ± 0.02 | 1.00 | $0.0460 (est.) | 20.54 | 0% |
| 6 | `anthropic:claude-sonnet-5-5` | 0.65 ± 0.03 | 1.00 | $0.0256 (est.) | 17.99 | 0% |
| 7 | `anthropic:claude-haiku-5-5` | 0.61 ± 0.02 | 1.00 | $0.0015 (est.) | 14.21 | 0% |

## critic

| # | Model | Quality | balanced accuracy | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `anthropic:claude-haiku-5-5` * | 1.00 | 1.00 | $0.0007 (est.) | 4.92 | 0% |
| 2 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0027 (est.) | 5.18 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0080 (est.) | 3.94 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0164 (est.) | 4.58 | 0% |
| 5 | `openai:gpt-6-luna` * | 0.98 ± 0.02 | 0.98 | $0.0004 (est.) | 5.19 | 0% |
| 6 | `openai:gpt-6.1-sol` | 0.98 ± 0.02 | 0.98 | $0.0056 (est.) | 4.85 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.90 ± 0.04 | 0.90 | $0.0022 (est.) | 1.59 | 0% |

## reviser

| # | Model | Quality | errors fixed | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0002 (est.) | 4.14 | 0% |
| 2 | `anthropic:claude-haiku-5-5` | 1.00 | 1.00 | $0.0005 (est.) | 3.13 | 0% |
| 3 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0017 (est.) | 3.46 | 0% |
| 4 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0035 (est.) | 3.21 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0051 (est.) | 2.17 | 0% |
| 6 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0106 (est.) | 2.83 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.92 ± 0.08 | 0.96 | $0.0014 (est.) | 1.02 | 0% |

\* on the cost-quality frontier: no other model is both better and cheaper.
Scoring formulas: see `docs/MODEL-SELECTION.md` or `uv run python -m open_deep_research.bench --help`.
