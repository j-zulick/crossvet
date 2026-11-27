# Review benchmark (hard set, three runs), 2026-11-27

Run on 2026-11-27 between 07:33 and 07:35 UTC with the 3.6.0 code: 324 reviews (6 reviewers, 18 changes, 3 runs each), calling `review_bench.run` once per reviewer, change and run, up to 16 at a time (the command below runs the same reviews one after another). Spend: $0.6354. The changes are the same as in the [first hard-set run](../2026-11-26-review-hard/README.md).

Command: `crossvet bench --review --set hard --repeat 3 -m anthropic:claude-opus-5-5 -m openai:gpt-6.1-sol -m anthropic:claude-sonnet-5-5 -m openai:gpt-6.1-terra -m anthropic:claude-haiku-5-5 -m openai:gpt-6-luna`

12 changes to Crossvet's own code, each with one planted bug, and 6 clean changes with no bug; each reviewer reviewed each change 3 times. A bug counts as caught when a finding that passed the checks in `review.check` points at its line (one line either side). On a clean change, a kept finding marked blocker or major is a false alarm.

| Reviewer | Caught | Other findings | Dropped by the checks | Cost | Cost per bug caught | Bugs caught every run | Bugs caught in some runs | False alarms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `anthropic:claude-opus-5-5` | 24 of 36 | 0 | 12 | $0.2880 | $0.0120 | 4 of 12 | 7 | 0 of 18 |
| `openai:gpt-6.1-sol` | 32 of 36 | 0 | 1 | $0.0869 | $0.0027 | 10 of 12 | 1 | 0 of 18 |
| `anthropic:claude-sonnet-5-5` | 34 of 36 | 0 | 2 | $0.1699 | $0.0050 | 11 of 12 | 1 | 0 of 18 |
| `openai:gpt-6.1-terra` | 36 of 36 | 0 | 0 | $0.0672 | $0.0019 | 12 of 12 | 0 | 0 of 18 |
| `anthropic:claude-haiku-5-5` | 36 of 36 | 0 | 0 | $0.0136 | $0.0004 | 12 of 12 | 0 | 0 of 18 |
| `openai:gpt-6-luna` | 34 of 36 | 0 | 0 | $0.0097 | $0.0003 | 11 of 12 | 1 | 0 of 18 |

## Per case

| Case | Kind | `anthropic:claude-opus-5-5` | `openai:gpt-6.1-sol` | `anthropic:claude-sonnet-5-5` | `openai:gpt-6.1-terra` | `anthropic:claude-haiku-5-5` | `openai:gpt-6-luna` |
|---|---|---|---|---|---|---|---|
| ladder-trim | off-by-one | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| explore-flip | inverted test | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| private-scores | privacy | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| reviewer-vendor | inverted test | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| lock-fetch | race | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| judge-bool | type check | 1/3 | 3/3 | 1/3 | 3/3 | 3/3 | 3/3 |
| sample-salt | ignored argument | 1/3 | 0/3 | 3/3 | 3/3 | 3/3 | 1/3 |
| trust-flip | inverted test | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| standard-error | wrong formula | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| rollback-sign | comparison | 0/3 | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| week-unit | wrong unit | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| prune-running | lost filter | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| clean-rename | clean | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms |
| clean-names | clean | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms |
| clean-day | clean | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms |
| clean-split | clean | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms |
| clean-rubric | clean | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms |
| clean-comment | clean | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms | 0/3 false alarms |

## What this shows

- **Still no false alarms.** Of 108 reviews of clean changes (6 reviewers, 6 changes, 3 runs), none raised a blocker or major finding; one left a single minor note.
- **Steady catches separate the reviewers.** Claude Haiku and GPT-6.1 Terra caught all 12 bugs in every run; Claude Sonnet and GPT-6 Luna caught 11 of 12 every run; GPT-6.1 Sol 10; Claude Opus 4. A single run hid most of that spread.
- **Opus loses catches to format, not sight.** All 12 of Opus's misses were findings the checks dropped because the severity was empty. Of the 20 misses in all, 15 were dropped findings (Opus 12 for a missing severity, Sonnet 2 for an answer that was not the JSON asked for, Sol 1 for a file not in the diff) and 5 were bugs left unseen.
- **One bug is genuinely hard.** `sample-salt` (a hash that stops using its `salt` argument, so the judge and the shadow model sample the same turns) was missed in all three runs by GPT-6.1 Sol and in two of three by GPT-6 Luna: the only bug any reviewer failed to flag at all.
- **Cheapest per steady catch:** Haiku, all 12 every run for $0.0136 in total ($0.0004 per catch), against Opus's $0.2880 for 24 catches.

## Limits

- 18 small changes (12 bugs, 6 clean), one bug per change, all in Crossvet's own code; 3 runs per reviewer and case.
- The checks drop a finding without a severity rather than guess one (design decision 13); that rule decides most of Opus's result.
- Reviews ran up to 16 at a time; a provider's rate limits did not show as errors (0 of 324).
- A reviewer that names the right problem on a different line counts as a miss; one that flags the line for another reason counts as a catch.
- `results.jsonl` next to this page has every row.
