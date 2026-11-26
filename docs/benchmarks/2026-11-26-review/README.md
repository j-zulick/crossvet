# Review benchmark, 2026-11-26

Run on 2026-11-26 between 12:19 and 12:24 UTC with the 3.1.0 release code, one `crossvet bench --review -m MODEL` per reviewer (the six rows below are those six runs, concatenated in `results.jsonl`).

Command: `crossvet bench --review -m anthropic:claude-opus-5-5 -m openai:gpt-6.1-sol -m anthropic:claude-sonnet-5-5 -m openai:gpt-6.1-terra -m anthropic:claude-haiku-5-5 -m openai:gpt-6-luna`

12 changes to Crossvet's own code, each with one planted bug. A bug counts as caught when a finding that passed the checks in `review.check` points at its line (one line either side).

| Reviewer | Caught | Other findings | Dropped by the checks | Cost | Cost per bug caught |
|---|---:|---:|---:|---:|---:|
| `anthropic:claude-opus-5-5` | 10 of 12 | 0 | 2 | $0.0764 | $0.0076 |
| `openai:gpt-6.1-sol` | 12 of 12 | 0 | 0 | $0.0227 | $0.0019 |
| `anthropic:claude-sonnet-5-5` | 12 of 12 | 0 | 0 | $0.0418 | $0.0035 |
| `openai:gpt-6.1-terra` | 12 of 12 | 0 | 0 | $0.0159 | $0.0013 |
| `anthropic:claude-haiku-5-5` | 12 of 12 | 1 | 0 | $0.0030 | $0.0003 |
| `openai:gpt-6-luna` | 12 of 12 | 0 | 0 | $0.0021 | $0.0002 |

## Per case

| Case | Kind | `anthropic:claude-opus-5-5` | `openai:gpt-6.1-sol` | `anthropic:claude-sonnet-5-5` | `openai:gpt-6.1-terra` | `anthropic:claude-haiku-5-5` | `openai:gpt-6-luna` |
|---|---|---|---|---|---|---|---|
| turns-limit | off-by-one | caught | caught | caught | caught | caught | caught |
| timeout-unit | wrong unit | caught | caught | caught | caught | caught | caught |
| thread-sql | SQL injection | caught | caught | caught | caught | caught | caught |
| key-in-log | secret leak | caught | caught | caught | caught | caught | caught |
| token-check | auth bypass | caught | caught | caught | caught | caught | caught |
| missing-await | async | caught | caught | caught | caught | caught | caught |
| daily-cap | comparison | missed | caught | caught | caught | caught | caught |
| mutable-default | mutable default | caught | caught | caught | caught | caught | caught |
| swallowed-refusal | error handling | caught | caught | caught | caught | caught | caught |
| input-price | wrong value | missed | caught | caught | caught | caught | caught |
| token-timing | timing leak | caught | caught | caught | caught | caught | caught |
| refused-forever | logic | caught | caught | caught | caught | caught | caught |

## What this shows

- These planted bugs are easy for current models: five of six reviewers caught all twelve. On cases like these the reviewers differ mostly in cost (GPT-6 Luna caught all twelve for $0.0021; Claude Opus 10 for $0.0764) and in following the required format.
- Claude Opus's two misses were not missed bugs: it described both (the doubled cap, the input tokens priced at the output rate) but gave no severity, and the checks drop a finding without one.
- A first run the same morning, before a quote could move a finding to the one nearby line that holds it, had Claude Sonnet at 10 and GPT-6 Luna at 6: their misses were right quotes on a line counted one off. That run led to the change in `review.check`; it is not published as a result.

## Limits

- Twelve small, synthetic changes, each with one obvious bug; one run per reviewer and case. Harder, real-world changes would separate reviewers more.
- A reviewer that names the right problem on a different line counts as a miss; one that flags the line for another reason counts as a catch.
- `results.jsonl` next to this page has every row.
