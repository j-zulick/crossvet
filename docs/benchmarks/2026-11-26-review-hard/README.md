# Review benchmark (hard set), 2026-11-26

Run on 2026-11-26 between 21:22 and 21:30 UTC with the 3.5.0 code, one reviewer at a time (the six blocks in `results.jsonl`). The planted bugs are subtler than the [planted set](../2026-11-26-review/README.md)'s, each change is cut from the real source (a test checks every context line against the file), and six clean changes measure false alarms. Spend: $0.2119 for the 108 reviews, $0.0420 for the 7 re-runs below.

Command: `crossvet bench --review --set hard -m anthropic:claude-opus-5-5 -m openai:gpt-6.1-sol -m anthropic:claude-sonnet-5-5 -m openai:gpt-6.1-terra -m anthropic:claude-haiku-5-5 -m openai:gpt-6-luna`

12 changes to Crossvet's own code, each with one planted bug, and 6 clean changes with no bug. A bug counts as caught when a finding that passed the checks in `review.check` points at its line (one line either side). On a clean change, a kept finding marked blocker or major is a false alarm.

| Reviewer | Caught | Other findings | Dropped by the checks | Cost | Cost per bug caught | False alarms |
|---|---:|---:|---:|---:|---:|---:|
| `anthropic:claude-opus-5-5` | 7 of 12 | 0 | 5 | $0.0963 | $0.0138 | 0 of 6 |
| `openai:gpt-6.1-sol` | 9 of 12 | 0 | 2 | $0.0307 | $0.0034 | 0 of 6 |
| `anthropic:claude-sonnet-5-5` | 12 of 12 | 0 | 0 | $0.0566 | $0.0047 | 0 of 6 |
| `openai:gpt-6.1-terra` | 12 of 12 | 0 | 0 | $0.0210 | $0.0017 | 0 of 6 |
| `anthropic:claude-haiku-5-5` | 12 of 12 | 0 | 0 | $0.0045 | $0.0004 | 0 of 6 |
| `openai:gpt-6-luna` | 11 of 12 | 0 | 0 | $0.0028 | $0.0003 | 0 of 6 |

## Per case

| Case | Kind | `anthropic:claude-opus-5-5` | `openai:gpt-6.1-sol` | `anthropic:claude-sonnet-5-5` | `openai:gpt-6.1-terra` | `anthropic:claude-haiku-5-5` | `openai:gpt-6-luna` |
|---|---|---|---|---|---|---|---|
| ladder-trim | off-by-one | caught | caught | caught | caught | caught | caught |
| explore-flip | inverted test | caught | caught | caught | caught | caught | caught |
| private-scores | privacy | caught | missed | caught | caught | caught | caught |
| reviewer-vendor | inverted test | caught | caught | caught | caught | caught | caught |
| lock-fetch | race | missed | caught | caught | caught | caught | caught |
| judge-bool | type check | missed | missed | caught | caught | caught | caught |
| sample-salt | ignored argument | missed | missed | caught | caught | caught | missed |
| trust-flip | inverted test | missed | caught | caught | caught | caught | caught |
| standard-error | wrong formula | caught | caught | caught | caught | caught | caught |
| rollback-sign | comparison | missed | caught | caught | caught | caught | caught |
| week-unit | wrong unit | caught | caught | caught | caught | caught | caught |
| prune-running | lost filter | caught | caught | caught | caught | caught | caught |
| clean-rename | clean | quiet | quiet | quiet | quiet | quiet | quiet |
| clean-names | clean | quiet | quiet | quiet | quiet | quiet | quiet |
| clean-day | clean | quiet | quiet | quiet | quiet | quiet | quiet |
| clean-split | clean | quiet | quiet | quiet | quiet | quiet | quiet |
| clean-rubric | clean | quiet | quiet | quiet | quiet | quiet | quiet |
| clean-comment | clean | quiet | quiet | quiet | quiet | quiet | quiet |

## What this shows

- **No false alarms.** None of the six reviewers marked a clean change blocker or major, or left any finding on one. On changes this small, a second-vendor reviewer did not cry wolf.
- **Most misses were dropped findings, not bugs left unseen.** 7 of the 9 misses were a finding the checks dropped (Claude Opus 5, GPT-6.1 Sol 2; this run did not yet record why, the re-run below does). Only `sample-salt` (the hash that silently stops using its `salt` argument, so the judge and the shadow model sample the same turns) went unseen: GPT-6 Luna and GPT-6.1 Sol returned no finding at all.
- **The cheaper reviewers did best here.** Claude Haiku, Claude Sonnet and GPT-6.1 Terra caught all twelve; Haiku did it for $0.0045, about a twentieth of Opus's $0.0963 for seven.
- **Runs vary.** Re-running the 7 cases with dropped findings, with the same code plus a record of each drop reason ([`diagnosis.jsonl`](diagnosis.jsonl), which records why each finding was dropped) caught 3 of them (Sol on `private-scores`, Opus on `lock-fetch` and `trust-flip`); the other 4 were dropped again: no severity (Opus, 3) and a file not in the diff (Sol, 1). One run per case is not enough to rank close reviewers.

## Limits

- 18 small changes (12 bugs, 6 clean), one bug per change, all in Crossvet's own code; one run per reviewer and case.
- The checks drop a finding without a severity rather than guess one (design decision 13). That costs Opus catches here; it is the same rule a real review uses.
- A reviewer that names the right problem on a different line counts as a miss; one that flags the line for another reason counts as a catch.
- `results.jsonl` next to this page has every row.
