# Evaluations

This page records how Crossvet is evaluated and what the results were. **No results are published yet.** Tables below are filled only from real runs with `crossvet-compare` and human grading; nothing here is estimated.

## Questions this evaluation answers

1. Does cross-vendor review reduce unsupported claims and unread citations compared with no review?
2. Does deliberation (`REVIEW_DELIBERATION_ROUNDS=2`) improve on a single review round, and how often do reviewers change position without evidence?
3. How does the Deep Agents edition compare with the LangGraph edition on the same models?
4. Does a LoRA-tuned local reviewer (from `crossvet-dataset`) review better than its base model?

## Protocol

- **Questions.** 15 research questions with checkable answers, fixed before any run, mixed across science, policy and technology, and published with the results and the setup files used.
- **Setups.** One TOML file per question above (starting from `examples/compare/setups.toml`, `deliberation.toml` and `editions.toml`, plus a base vs fine-tuned reviewer file). The same models are used wherever a comparison is meant to isolate one change.
- **Repeats.** Three runs per question and setup (`--repeats 3`) to show run-to-run variation.
- **Automatic metrics** (from `summary.csv`): finished runs, latency, tokens, share of cited URLs never read by research, critic drops and disputes, grounded and ungrounded position changes, failed reviewers.
- **Human grading.** For a random sample of about 20 claims per setup, a grader who does not see which setup produced the report labels each claim *supported*, *partly supported* or *unsupported* by its cited source.
- **Reporting.** Every setup's numbers are published, including the ones where Crossvet does not help. Costs are reported from provider dashboards or Langfuse.

## Results

| Comparison | Status |
|---|---|
| Review vs no review | not run |
| Deliberation vs single round | not run |
| Deep Agents vs LangGraph edition | not run |
| Fine-tuned vs base local reviewer | not run |

## Limitations

- URL matching shows a citation was read, not that it supports the claim; human grading covers that.
- Reviewer scores come from each panel and are comparable only between setups with the same panel.
- Results depend on model versions and search results on the day of the run; the run date and model strings are recorded with every result.
