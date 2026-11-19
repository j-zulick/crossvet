"""An answer key for support checks: is Jev right, not just strict?

The Nov 18 Jev measurement (docs/evals/2026-11-18-jev/) found that in the default mode Jev
rejected 77-87% of the passages reviewers cited, and that asking about the reviewer's stated
fact instead (``REVIEW_SUPPORT_CLAIM=fact``) cut that to 29%. A lower rejection rate is not
better unless the rejections were wrong, so this module gives each case a known answer.

Each case is a source passage and two phrasings of what a reviewer drew from it, one per mode:

- ``finding``: the reviewer's finding about the draft ("the draft's 21.7% is wrong; ...");
- ``fact``: the reviewer's one-sentence statement of what the passage says.

``supported`` is the answer: does the passage back the reviewer's point? Half the cases are
supported. The other half are the ways a cited passage fails: a misread number, a passage on
the same topic that doesn't say it, partial support, and a contradiction. Run with
``crossvet-bench support-key`` (needs a Jev key; billed by TypeSafe).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class KeyCase:
    """One labelled support question."""

    id: str
    kind: str        # supported | misread | same_topic | partial | contradicts
    passage: str
    finding: str
    fact: str
    supported: bool


CASES: list[KeyCase] = [
    # --- supported: the passage backs the reviewer's point ---------------------------------------
    KeyCase("returns-rate", "supported",
            "Corvane's online apparel return rate fell to 24.3% in 2026, down from 27.1% in 2025.",
            "The draft says the 2025 return rate was 21.7%, but the source gives 27.1%; the figure should be corrected.",
            "Corvane's online apparel return rate was 27.1% in 2025.", True),
    KeyCase("fare-cap-rise", "supported",
            "After the fare cap was introduced, average weekday journeys rose 9.6% compared with the same months a year earlier.",
            "The draft reports a 6.9% rise in weekday journeys; the source says 9.6%.",
            "Average weekday journeys rose 9.6% year on year after the fare cap.", True),
    KeyCase("review-calls", "supported",
            "Practices that replied to at least half of their reviews received 7% more calls from search listings over six months.",
            "The draft overstates the effect: the source reports 7% more calls, not 17%.",
            "Practices replying to at least half their reviews got 7% more calls over six months.", True),
    KeyCase("ai-panel-clicks", "supported",
            "On queries that showed an AI answer panel, clicks to the first organic result fell by 27%.",
            "The draft's 47% drop in first-result clicks is not what the source says; it reports 27%.",
            "Clicks to the first organic result fell 27% on queries with an AI answer panel.", True),
    KeyCase("panel-share", "supported",
            "Lumen Search displayed an AI answer panel on 38% of sampled retail queries in March 2026, up from 21% a year earlier.",
            "The draft omits that AI answer panels nearly doubled in a year, from 21% to 38% of retail queries; this belongs in the summary.",
            "AI answer panels appeared on 38% of sampled retail queries in March 2026, up from 21%.", True),
    KeyCase("mirror-segments", "supported",
            "The telescope's primary mirror is made of 18 hexagonal beryllium segments coated with a thin layer of gold.",
            "The draft says the mirror has 21 segments; the source gives 18.",
            "The primary mirror has 18 hexagonal beryllium segments.", True),
    KeyCase("survey-size", "supported",
            "The survey covered 1,240 small businesses in three states between January and March.",
            "The draft describes the survey as national, but the source says it covered three states.",
            "The survey covered 1,240 small businesses in three states.", True),
    KeyCase("trial-dropout", "supported",
            "Of the 412 participants enrolled, 61 withdrew before the twelve-week follow-up.",
            "The draft's claim that nearly everyone completed the trial is wrong; 61 of 412 withdrew before follow-up.",
            "61 of 412 enrolled participants withdrew before the twelve-week follow-up.", True),
    KeyCase("battery-life", "supported",
            "In the lab test the battery retained 80% of its capacity after 1,500 full charge cycles.",
            "The draft says capacity fell to 80% after 500 cycles; the source says 1,500.",
            "The battery kept 80% of its capacity after 1,500 full cycles in the lab test.", True),
    KeyCase("policy-date", "supported",
            "The regulation takes effect on 1 March 2027 for companies with more than 250 employees.",
            "The draft gives the start date as 2026; the source says 1 March 2027.",
            "The regulation takes effect on 1 March 2027 for companies with over 250 employees.", True),
    KeyCase("price-change", "supported",
            "The monthly subscription price rose from $12 to $15 in October.",
            "The draft omits the October price increase from $12 to $15, which the question asks about.",
            "The monthly subscription price rose from $12 to $15 in October.", True),
    KeyCase("sample-region", "supported",
            "All interviews were conducted in the city of Leeds.",
            "The draft generalises the results to the whole UK, but the source says every interview was in Leeds.",
            "All interviews were conducted in Leeds.", True),
    # --- misread: the passage gives a different number or date than the reviewer says -------------
    KeyCase("returns-rate-misread", "misread",
            "Corvane's online apparel return rate fell to 24.3% in 2026, down from 27.1% in 2025.",
            "The draft's 2026 return rate is wrong; the source gives 27.1% for 2026.",
            "Corvane's online apparel return rate was 27.1% in 2026.", False),
    KeyCase("fare-cap-misread", "misread",
            "After the fare cap was introduced, average weekday journeys rose 9.6% compared with the same months a year earlier.",
            "The draft understates the change; the source reports weekday journeys doubling.",
            "Weekday journeys doubled after the fare cap.", False),
    KeyCase("battery-misread", "misread",
            "In the lab test the battery retained 80% of its capacity after 1,500 full charge cycles.",
            "The draft is wrong to say 80%; the source says the battery kept 90% of its capacity.",
            "The battery kept 90% of its capacity after 1,500 cycles.", False),
    # --- same topic: the passage is about the subject but doesn't say it ---------------------------
    KeyCase("panel-same-topic", "same_topic",
            "Lumen Search displayed an AI answer panel on 38% of sampled retail queries in March 2026, up from 21% a year earlier.",
            "The draft should say that AI answer panels reduce conversion rates for retailers.",
            "AI answer panels reduce retailers' conversion rates.", False),
    KeyCase("mirror-same-topic", "same_topic",
            "The telescope's primary mirror is made of 18 hexagonal beryllium segments coated with a thin layer of gold.",
            "The draft omits that the mirror cost over a billion dollars to build.",
            "The primary mirror cost over a billion dollars.", False),
    KeyCase("survey-same-topic", "same_topic",
            "The survey covered 1,240 small businesses in three states between January and March.",
            "The draft should report that most surveyed businesses planned to hire this year.",
            "Most surveyed businesses planned to hire this year.", False),
    # --- partial: the passage supports only part of the reviewer's point ---------------------------
    KeyCase("trial-partial", "partial",
            "Of the 412 participants enrolled, 61 withdrew before the twelve-week follow-up.",
            "The draft should say 61 participants withdrew because of side effects.",
            "61 participants withdrew because of side effects.", False),
    KeyCase("policy-partial", "partial",
            "The regulation takes effect on 1 March 2027 for companies with more than 250 employees.",
            "The draft should say the regulation applies to all companies from 1 March 2027.",
            "The regulation applies to all companies from 1 March 2027.", False),
    KeyCase("review-partial", "partial",
            "Practices that replied to at least half of their reviews received 7% more calls from search listings over six months.",
            "The draft should say that replying to reviews caused a 7% rise in calls and in revenue.",
            "Replying to reviews caused 7% more calls and higher revenue.", False),
    # --- contradicts: the passage says the opposite ------------------------------------------------
    KeyCase("clicks-contradicts", "contradicts",
            "On queries that showed an AI answer panel, clicks to the first organic result fell by 27%.",
            "The draft is wrong that clicks fell; the source shows clicks to the first result rose with AI panels.",
            "Clicks to the first organic result rose on queries with an AI answer panel.", False),
    KeyCase("price-contradicts", "contradicts",
            "The monthly subscription price rose from $12 to $15 in October.",
            "The draft should note that the subscription became cheaper in October.",
            "The subscription price fell in October.", False),
    KeyCase("region-contradicts", "contradicts",
            "All interviews were conducted in the city of Leeds.",
            "The draft omits that interviews were held across several UK cities.",
            "Interviews were held in several UK cities.", False),
]

MODES = ("finding", "fact")


def _claim(case: KeyCase, mode: str) -> str:
    return case.finding if mode == "finding" else case.fact


async def _score(checker, mode: str) -> list[float | None]:
    return await checker.check([(_claim(c, mode), c.passage) for c in CASES])


def evaluate(checker, mode: str, min_prob: float = 0.5) -> dict:
    """Score every case with ``checker`` in ``mode``; return accuracy figures and per-case results.

    A probability at or above ``min_prob`` counts as "supported". A failed call (None) counts as
    unsupported, as in the review, and is counted under ``errors``.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    probs = asyncio.run(_score(checker, mode))
    rows = []
    tp = tn = fp = fn = errors = 0
    for case, prob in zip(CASES, probs, strict=True):
        said = prob is not None and prob >= min_prob
        errors += prob is None
        if case.supported and said:
            tp += 1
        elif case.supported:
            fn += 1
        elif said:
            fp += 1
        else:
            tn += 1
        rows.append({"id": case.id, "kind": case.kind, "supported": case.supported, "prob": prob, "said_supported": said})
    pos, neg = tp + fn, tn + fp
    tpr = tp / pos if pos else 0.0
    tnr = tn / neg if neg else 0.0
    return {
        "mode": mode, "min_prob": min_prob, "cases": len(CASES), "errors": errors,
        "accuracy": (tp + tn) / len(CASES),
        "balanced_accuracy": (tpr + tnr) / 2,
        "supported_accepted": tpr,          # true positives / supported cases
        "unsupported_rejected": tnr,        # true negatives / unsupported cases
        "rejection_rate": (tn + fn) / len(CASES),
        "rows": rows,
    }
