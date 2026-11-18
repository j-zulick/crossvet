# Jev support checks, on vs off (Nov 18, 2026)

**Question.** What do Jev support checks change in a review, and is the claim Jev is asked about the right one?

**Setup.** The review stage of two Nov 17 pilot questions (Paris Agreement NDCs; the Federal Reserve's mandate) was re-run from checkpoints taken just before review, so every run reviews the same draft against the same notes. A third pilot question was left out: its review took longer than the 3-minute limit per command of the machine that ran this, in every mode.
- **Review panel:** `openai:gpt-5.4-mini` and `anthropic:claude-sonnet-5-5`. Reviser: `openai:gpt-5.4-mini`. Deliberation: 2 rounds, blind pass on.
- **Jev:** `jev-latest`, served by `jev-1.14.0`, threshold 0.5.
- **Modes:**
  - off;
  - on (default, `REVIEW_SUPPORT_CLAIM=finding`: Jev is asked whether the passage supports the reviewer's finding);
  - on with `REVIEW_SUPPORT_CLAIM=fact` (Jev is asked whether the passage supports the one-sentence fact the reviewer says it states).
- **Runs:** 28 in all, each question run 2 to 6 times per mode.
- **Model cost:** $7.82 for 28 runs. Jev calls are not included: they are billed by TypeSafe and were not priced here.

Running `jev_ab.py` reproduces a run. The `q*.json` files hold each run's review summary and token use, and `pairs-*.json` hold every (claim, passage) pair Jev scored in the last four runs per mode, with its score.

## Results

| Per mode (runs) | Off (8) | On, finding (12) | On, finding, new prompt (4) | On, fact (4) |
|---|---|---|---|---|
| Passages Jev scored / rejected | — | 140 / 122 (87%) | 70 / 54 (77%) | 63 / 18 (29%) |
| AGREE verdicts that counted as grounded | 75 of 154 | 5 of 170 | 5 of 69 | 27 of 61 |
| Position changes accepted (with evidence) | 15 | 7 | 5 | 7 |
| Position changes rejected | 8 | 21 | 18 | 9 |
| Blind-pass points rejected as unsupported | 0 of 96 | 44 of 144 | 18 of 48 | 10 of 43 |
| Model cost per review | $0.29 | $0.27 | $0.29 | $0.28 |

"New prompt" runs use the 1.8 deliberation prompt, which also asks reviewers for a one-sentence `fact` with every quote. Older runs used the 1.7 prompt; both use the default mode.

**What this shows.**
- **Default mode.** Jev rejected most passages, between 77% and 87%. That made almost every endorsement ungrounded: 5 grounded AGREE verdicts against 75 with Jev off. Jev also blocked most position changes. In this mode Jev mostly undoes the endorsements the quote check would accept.
- **Why.** The rejected pairs show the claim and the passage don't match in kind. A reviewer's finding is usually a statement about the draft ("the draft overstates X", "the quote is truncated"). A source passage can't state that, so Jev answers no, as its question asks it to.
- **Fact mode.** Asking about the reviewer's stated fact instead cut rejections to 29%. Jev's scores on those pairs track the passages: high where the passage states the fact, low where the "fact" adds something the passage doesn't say.
- **Cost.** Model cost per review was about the same in every mode.

**What it doesn't show.**
- **No answer key.** These are real questions without one, so the runs show how strict each mode is, not which verdicts were right.
- **Fact mode is a weaker test.** The reviewer writes the fact, so Jev checks that the passage says it, not that it justifies the verdict.
- **Small sample.** Two questions, one review panel, and large differences between repeats of the same mode.

**Decision for now.** The default stays `finding`, and `fact` is available as an opt-in. Changing the default needs a run with an answer key: the hard benchmark cases could be extended to deliberation with Jev.
