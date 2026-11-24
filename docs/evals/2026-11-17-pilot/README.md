# Pilot: review vs. no review, November 17, 2026

A first, small run of evaluation question 1 ([EVALS.md](../../EVALS.md)): the same research pipeline with and without cross-vendor review. It is a pilot, not the full protocol: 3 questions, 1 run per question and setup, and no human grading yet.

| | |
|---|---|
| Date | 2026-11-17 |
| Questions | 3, from `examples/compare/questions-15.txt` (Paris Agreement, GDPR, Federal Reserve mandate): [questions.txt](questions.txt) |
| Setups | [setups.toml](setups.toml): `gpt-6.1-sol` plans, `gpt-5.4-mini` researches, compresses and writes (the [Nov 17 benchmark](../../benchmarks/2026-11-17/) role map), OpenAI built-in web search. `review` adds a panel of `gpt-5.4-mini` and `claude-sonnet-5-5` with the critic; no deliberation, blind pass or Jev. The reviser was `gpt-6.1-sol`, which shares a vendor with one reviewer (the Review notes warn about it). |
| Code | Crossvet v1.6 before the content-filter fix below |
| Cost | $1.63 for the six published runs, from token counts and list prices: GPT-6.1 Sol $2 / $10, GPT-5.4 mini $0.75 / $4.50, Claude Sonnet 5.5 $2 / $10 per million input / output tokens. OpenAI's per-call web search fees are not included. |

## Results

| | No review | Review |
|---|---|---|
| Runs finished | 3 / 3 | 3 / 3 |
| Cost per report (mean) | $0.19 | $0.36 |
| Time per report (mean) | 100 s | 171 s |
| Draft score from the panel (mean, out of 10) | — | 5.2 (6.5, 5.5, 3.5) |
| Reviewer findings dropped because the notes contradict them | — | 8 (0, 2, 6) |
| Reviewer findings the critic could not confirm, listed for a human | — | 32 (15, 13, 4) |
| Cited URLs the research never read | not checked | 0 of 10 |
| Report that stopped mid-sentence | 0 | 1 (see below) |

Per-run metrics with token counts per model: `*.result.json`. Every report, with its Review notes: [reports/](reports/).

## What it shows

- **Review roughly doubles the cost and adds about a minute** at these model choices: about $0.17 and 70 seconds per report.
- **The critic does real filtering.** It dropped 8 reviewer findings that the research notes contradict, so they never reached the revision, and listed 32 it could not confirm for a human instead of applying them.
- **Review caught a broken draft.** In one review run, OpenAI's content filter stopped the report writer (`gpt-5.4-mini`) mid-quote of the Federal Reserve Act, after 881 characters and before the Sources section (`finish_reason: content_filter`, read from the run's checkpoint). Both reviewers scored that draft 3–4 out of 10. The reviser couldn't restore what was never written, and nothing flagged the report as incomplete. **Fixed in v1.6:** a report stopped by an output limit or a content filter is now written again, asking for paraphrase over long quotes. If it stops again, it ends with an "Incomplete report" notice. A revision stopped by a filter no longer replaces the draft (`tests/unit/test_stopped_early.py`).

## What it doesn't show

- **Whether reviewed reports are more accurate.** That needs a blind grader labelling claims, as in the protocol. The two setups ran their research separately, so their drafts differ; the table compares setups, not the same draft before and after review.
- **Anything statistical.** Three questions with one run each is a smoke test. The full protocol is 15 questions × 3 runs with grading.

## How it was run

Claude ran it on the author's Mac through the Claude desktop app, with keys read from the local `.env` by Crossvet itself. That shell allows about three minutes per command. So [sliced_run.py](sliced_run.py) runs each job in slices on top of LangGraph's SQLite checkpoints, stopping before the review step so review starts on a fresh slice. It adds up tokens and time across slices and records the same metrics as `crossvet-compare`. On a normal machine, one command does the same:

```bash
uv run crossvet-compare --setups docs/evals/2026-11-17-pilot/setups.toml --questions docs/evals/2026-11-17-pilot/questions.txt
```

Earlier attempts that day are not counted in the cost above:
- A run killed when its shell call ended.
- Runs that used `gpt-6.1-sol` as the researcher, abandoned because one research step took longer than a slice.
