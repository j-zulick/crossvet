# Evaluations

This page records how Crossvet is evaluated and what the results were. **No results are published yet.** Tables below are filled only from real runs with `crossvet-compare` and human grading; nothing here is estimated.

## Questions this evaluation answers

1. Does cross-vendor review reduce unsupported claims and unread citations compared with no review?
2. Does deliberation (`REVIEW_DELIBERATION_ROUNDS=2`) improve on a single review round, and how often do reviewers change position without evidence?
3. How does the Deep Agents edition compare with the LangGraph edition on the same models?
4. Does early stopping (v1.1) cut deliberation calls and tokens without changing what review finds? (`deliberation-3-fixed` vs `deliberation-3-early-stop`: compare `deliberation_calls`, tokens, `flagged_url_rate`, critic outcomes and grounded position changes.)
5. Does the blind pass (v1.2) surface omissions that human graders confirm, and what does it cost? (`review` vs `blind-pass`: `blind_omissions`, tokens, grader agreement on a sample of omissions.)
6. How often does Jev reject a grounded position change or endorsement, and do human graders agree with those rejections? (`deliberation-2` vs `deliberation-2-jev`: `support_checked`, `support_rejected`, grader agreement on a sample of rejected pairs.)
7. Do domain packs change what reviewers catch? (`seo` pack vs none on SEO questions: dated-claim and primary-source findings, grader agreement.)
8. Does a LoRA-tuned local reviewer (from `crossvet-dataset`) review better than its base model?

## Protocol

- **Questions.** 15 research questions with checkable answers, fixed before any run, mixed across science, policy and technology, and published with the results and the setup files used.
- **Setups.** One TOML file per question above (starting from `examples/compare/setups.toml`, `deliberation.toml` and `editions.toml`, plus a base vs fine-tuned reviewer file). The same models are used wherever a comparison is meant to isolate one change.
- **Repeats.** Three runs per question and setup (`--repeats 3`) to show run-to-run variation.
- **Automatic metrics** (from `summary.csv`): finished runs, latency, tokens, share of cited URLs never read by research, critic drops and disputes, grounded and ungrounded position changes, failed reviewers, and for deliberation the rounds run and saved, agreement rate and model calls.
- **Human grading.** For a random sample of about 20 claims per setup, a grader who does not see which setup produced the report labels each claim *supported*, *partly supported* or *unsupported* by its cited source.
- **Reporting.** Every setup's numbers are published, including the ones where Crossvet does not help. Costs are reported from provider dashboards or Langfuse.

## Results

| Comparison | Status |
|---|---|
| Review vs no review | not run |
| Deliberation vs single round | not run |
| Deep Agents vs LangGraph edition | not run |
| Early stopping vs fixed rounds | not run |
| Blind pass vs review | not run |
| Jev support checks vs quote check alone | not run |
| Domain pack vs none | not run |
| Fine-tuned vs base local reviewer | not run |

## Model fit (v1.6)

`crossvet-bench` complements these comparisons: it measures each pipeline role on its own (orchestration, research, compression, report writing, review, critic, revision) on synthetic cases scored by answer keys, and recommends a model per role. Its method, formulas and limits are in [MODEL-SELECTION.md](MODEL-SELECTION.md); its results are published there, under the same rule: only from real runs, with date, model ids, cases, repeats and cost.

## Limitations

- URL matching shows a citation was read, not that it supports the claim; human grading covers that.
- Reviewer scores come from each panel and are comparable only between setups with the same panel.
- Results depend on model versions and search results on the day of the run; the run date and model strings are recorded with every result.
