# Chat benchmark, 2026-11-25

| | |
|---|---|
| Date | 2026-11-25 |
| Models | `openai:gpt-6-luna`, `anthropic:claude-haiku-5-5`, `openai:gpt-6.1-terra`, `anthropic:claude-sonnet-5-5`, `openai:gpt-6.1-sol`, `anthropic:claude-opus-5-5` |
| Suite | `all`: 28 cases, 168 calls, 0 failed |
| Code answers | run in a separate process and checked |
| Cost | $0.4778 (as reported by each provider) |
| Command | `crossvet chat bench -m openai:gpt-6-luna -m anthropic:claude-haiku-5-5 -m openai:gpt-6.1-terra -m anthropic:claude-sonnet-5-5 -m openai:gpt-6.1-sol -m anthropic:claude-opus-5-5 --suite all --run-code` |

## Score by kind of task

Mean score from 0 to 1 per kind, scored in code against each case's answer key; cost is the total for that kind.

```
kind       openai:gpt-6-luna            anthropic:claude-haiku-5-5   openai:gpt-6.1-terra         anthropic:claude-sonnet-5-5  openai:gpt-6.1-sol           anthropic:claude-opus-5-5    
code       1.00 $0.0005                 1.00 $0.0005                 1.00 $0.0057                 1.00 $0.0121                 1.00 $0.0082                 1.00 $0.0270                 
extract    1.00 $0.0002                 1.00 $0.0003                 1.00 $0.0012                 1.00 $0.0067                 1.00 $0.0021                 0.50 $0.0127                 
long       1.00 $0.0022                 1.00 $0.0039                 1.00 $0.0214                 1.00 $0.0745                 1.00 $0.0430                 1.00 $0.1524                 
quick      1.00 $0.0001                 1.00 $0.0001                 1.00 $0.0008                 1.00 $0.0022                 1.00 $0.0015                 1.00 $0.0050                 
reasoning  1.00 $0.0004                 1.00 $0.0007                 1.00 $0.0034                 1.00 $0.0089                 1.00 $0.0057                 1.00 $0.0183                 
summarize  0.83 $0.0002                 1.00 $0.0005                 0.83 $0.0036                 0.83 $0.0037                 1.00 $0.0020                 1.00 $0.0165                 
writing    1.00 $0.0002                 0.88 $0.0001                 0.88 $0.0016                 0.88 $0.0036                 1.00 $0.0044                 0.88 $0.0196                 
```

## Best value per slot

The cheapest model within 10% of the best score on the slot's kinds of task.

- `quick`: `openai:gpt-6-luna`, `anthropic:claude-haiku-5-5`, `openai:gpt-6.1-sol`, `openai:gpt-6.1-terra`, `anthropic:claude-sonnet-5-5`
- `balanced`: `openai:gpt-6-luna`, `openai:gpt-6.1-sol`
- `strong`: `openai:gpt-6-luna`, `anthropic:claude-haiku-5-5`, `openai:gpt-6.1-terra`, `openai:gpt-6.1-sol`, `anthropic:claude-sonnet-5-5`, `anthropic:claude-opus-5-5`
- `long`: `openai:gpt-6-luna`, `anthropic:claude-haiku-5-5`, `openai:gpt-6.1-terra`, `openai:gpt-6.1-sol`, `anthropic:claude-sonnet-5-5`, `anthropic:claude-opus-5-5`

## Limits

- Every case is synthetic and small; a kind's score rests on 1 to 6 case(s).
- One run per model and case: a single answer can move a kind's score by a lot.
- Scores say which models fail a job, and on the hard suite which fall for its traps; they are not a general ranking.
- `results.jsonl` next to this page has every row: model, case, kind, score, cost, any error and the start of the answer.
