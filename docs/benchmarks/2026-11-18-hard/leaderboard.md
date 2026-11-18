# Model fit leaderboard (2026-11-18)

7 models x 7 roles x 3 synthetic cases x 1 repeat(s). Total spend: $2.19. Scores come from code (answer keys, kept facts, checklists), not from a judge model.

## Recommended role map

| Role | Best quality | Best value (within 10% of the top score, cheapest) |
|---|---|---|
| supervisor | `openai:gpt-6.1-sol` | `openai:gpt-6-luna` |
| researcher | `openai:gpt-6.1-terra` | `anthropic:claude-haiku-5-5` |
| compression | `openai:gpt-6-luna` | `openai:gpt-6-luna` |
| writer | `openai:gpt-5.4-mini` | `openai:gpt-6-luna` |
| reviewer | `openai:gpt-6.1-sol` | `openai:gpt-6-luna` |
| critic | `openai:gpt-6.1-terra` | `openai:gpt-6-luna` |
| reviser | `openai:gpt-6-luna` | `openai:gpt-6-luna` |

## supervisor

| # | Model | Quality | aspects delegated | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-sol` * | 0.92 ± 0.04 | 0.87 | $0.0300 (est.) | 31.68 | 0% |
| 2 | `openai:gpt-6-luna` * | 0.84 ± 0.04 | 0.73 | $0.0014 (est.) | 16.48 | 0% |
| 3 | `openai:gpt-6.1-terra` | 0.84 ± 0.04 | 0.73 | $0.0142 (est.) | 19.63 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 0.84 ± 0.11 | 0.73 | $0.0418 (est.) | 11.76 | 0% |
| 5 | `anthropic:claude-haiku-5-5` * | 0.80 ± 0.04 | 0.67 | $0.0011 (est.) | 7.01 | 0% |
| 6 | `anthropic:claude-sonnet-5-5` | 0.76 ± 0.07 | 0.60 | $0.0243 (est.) | 8.9 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.68 ± 0.04 | 0.47 | $0.0068 (est.) | 6.79 | 0% |

## researcher

| # | Model | Quality | facts retrieved | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-terra` * | 0.82 ± 0.04 | 0.96 | $0.0098 (est.) | 17.72 | 0% |
| 2 | `anthropic:claude-opus-5-5` | 0.80 ± 0.04 | 0.95 | $0.0490 (est.) | 16.97 | 0% |
| 3 | `openai:gpt-6-luna` * | 0.77 ± 0.06 | 0.95 | $0.0013 (est.) | 14.06 | 0% |
| 4 | `openai:gpt-5.4-mini` | 0.76 ± 0.04 | 0.95 | $0.0049 (est.) | 4.67 | 0% |
| 5 | `anthropic:claude-haiku-5-5` * | 0.76 ± 0.00 | 0.91 | $0.0012 (est.) | 6.77 | 0% |
| 6 | `anthropic:claude-sonnet-5-5` | 0.76 ± 0.00 | 0.91 | $0.0184 (est.) | 10.37 | 0% |
| 7 | `openai:gpt-6.1-sol` | 0.75 ± 0.08 | 0.91 | $0.0151 (est.) | 18.15 | 0% |

## compression

| # | Model | Quality | facts kept | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0006 (est.) | 7.66 | 0% |
| 2 | `anthropic:claude-haiku-5-5` | 1.00 | 1.00 | $0.0010 (est.) | 5.99 | 0% |
| 3 | `openai:gpt-6.1-terra` | 1.00 | 1.00 | $0.0052 (est.) | 9.91 | 0% |
| 4 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0100 (est.) | 7.15 | 0% |
| 5 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0151 (est.) | 7.28 | 0% |
| 6 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0488 (est.) | 19.05 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.98 ± 0.02 | 1.00 | $0.0048 (est.) | 3.48 | 0% |

## writer

| # | Model | Quality | facts covered | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-5.4-mini` * | 1.00 | 1.00 | $0.0086 (est.) | 9.57 | 0% |
| 2 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0471 (est.) | 33.46 | 0% |
| 3 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0873 (est.) | 40.54 | 0% |
| 4 | `openai:gpt-6-luna` * | 0.97 ± 0.03 | 0.95 | $0.0012 (est.) | 17.83 | 0% |
| 5 | `anthropic:claude-haiku-5-5` | 0.97 ± 0.03 | 0.95 | $0.0030 (est.) | 23.26 | 0% |
| 6 | `openai:gpt-6.1-terra` | 0.97 ± 0.03 | 0.95 | $0.0117 (est.) | 27.54 | 0% |
| 7 | `openai:gpt-6.1-sol` | 0.97 ± 0.03 | 0.95 | $0.0291 (est.) | 47.04 | 0% |

## reviewer

| # | Model | Quality | planted errors caught | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-sol` * | 0.79 ± 0.02 | 1.00 | $0.0160 (est.) | 26.51 | 0% |
| 2 | `openai:gpt-6-luna` * | 0.75 ± 0.09 | 0.92 | $0.0014 (est.) | 28.21 | 0% |
| 3 | `anthropic:claude-opus-5-5` | 0.70 ± 0.03 | 1.00 | $0.0672 (est.) | 26.79 | 0% |
| 4 | `openai:gpt-6.1-terra` | 0.67 ± 0.07 | 0.92 | $0.0085 (est.) | 19.51 | 0% |
| 5 | `openai:gpt-5.4-mini` | 0.59 ± 0.04 | 0.83 | $0.0076 (est.) | 8.19 | 0% |
| 6 | `anthropic:claude-sonnet-5-5` | 0.59 | 1.00 | $0.0346 (est.) | 24.03 | 0% |
| 7 | `anthropic:claude-haiku-5-5` | 0.56 ± 0.06 | 1.00 | $0.0019 (est.) | 16.34 | 0% |

## critic

| # | Model | Quality | balanced accuracy | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6.1-terra` * | 1.00 | 1.00 | $0.0041 (est.) | 6.49 | 0% |
| 2 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0082 (est.) | 6.84 | 0% |
| 3 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0106 (est.) | 5.25 | 0% |
| 4 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0232 (est.) | 5.59 | 0% |
| 5 | `anthropic:claude-haiku-5-5` * | 0.96 ± 0.04 | 0.96 | $0.0010 (est.) | 7.71 | 0% |
| 6 | `openai:gpt-6-luna` * | 0.92 ± 0.08 | 0.92 | $0.0006 (est.) | 8.22 | 0% |
| 7 | `openai:gpt-5.4-mini` | 0.88 | 0.88 | $0.0031 (est.) | 2.42 | 0% |

## reviser

| # | Model | Quality | errors fixed | Cost / case | p50 s | Failures |
|---|---|---|---|---|---|---|
| 1 | `openai:gpt-6-luna` * | 1.00 | 1.00 | $0.0006 (est.) | 8.36 | 0% |
| 2 | `anthropic:claude-haiku-5-5` | 1.00 | 1.00 | $0.0012 (est.) | 7.0 | 0% |
| 3 | `openai:gpt-6.1-sol` | 1.00 | 1.00 | $0.0079 (est.) | 8.86 | 0% |
| 4 | `anthropic:claude-sonnet-5-5` | 1.00 | 1.00 | $0.0090 (est.) | 4.25 | 0% |
| 5 | `anthropic:claude-opus-5-5` | 1.00 | 1.00 | $0.0246 (est.) | 9.07 | 0% |
| 6 | `openai:gpt-5.4-mini` | 0.92 ± 0.08 | 0.92 | $0.0025 (est.) | 2.2 | 0% |
| 7 | `openai:gpt-6.1-terra` | 0.92 ± 0.08 | 0.92 | $0.0039 (est.) | 7.21 | 0% |

\* on the cost-quality frontier: no other model is both better and cheaper.
Scoring formulas: see `docs/MODEL-SELECTION.md` or `uv run python -m open_deep_research.bench --help`.
