# Broader injection patterns: false alarms on real pages (2026-11-19)

**Question.** v1.10 widens the injection check and adds hidden-text channels to `crossvet-scan`. Do these
changes flag ordinary pages?

The widened check adds:
- Italian and Dutch;
- more translated phrasings;
- commands about the reader's reply;
- look-alike letters, letter-spaced words and fragments joined across sentences;
- ROT13 and reversed text.

The new channels in `crossvet-scan` are stylesheet-hidden text, `<template>`, SVG titles, hidden inputs,
JSON-LD and noscript.

**Pages.** The 608 public pages in [`urls.txt`](urls.txt) are ordinary homepages, articles, forum, Q&A and issue
pages, and pages in Spanish, French, German, Portuguese, Italian and Dutch.
- They were fetched once on Nov 19, 2026, with robots.txt respected, and saved locally. The HTML is not
  published.
- Nobody labelled them in advance. They are assumed to be ordinary pages, so any flag is treated as a false
  alarm unless reading the page shows otherwise.
- The run also covered 132 pages from a privately supplied list. Those pages are left out of the figures and
  data here.

**Runs.** Each run used no model, no API key and cost nothing.
- **crossvet-scan:** [`chanscan.py`](chanscan.py) ran `scan_text` on every saved page. It ran once with v1.9
  (commit `693d48e`) and once with v1.10 (commit `90c6f18`).
- **Research-notes flag:** `injection_check.scan` ran on each page's visible text. This is the check that writes
  a flag line into the research notes, and it ran once with each version.

## Results

| | v1.9 | v1.10 |
|---|---:|---:|
| `crossvet-scan`: pages with a finding | 24 | **1** |
| ...of which only "mostly one repeated claim" | 23 | 0 |
| Research-notes flag: pages flagged | 6 | 6 |

**`crossvet-scan`.**
- The drop from 24 to 1 comes from one change: a channel whose only finding is a repeated claim is no longer
  reported unless you pass `--include-repetition`.
- In v1.9, all 23 of those findings were menus, icon labels and template boilerplate in comments, hidden
  elements, attributes or visible text.
- The one page left is a Hacker News discussion that addresses AI models. v1.9 flags it too.
- The new channels and patterns added no finding on these pages.

**Research-notes flag.**
- v1.10 flags the same six pages as v1.9: five homepages for repetition and the same discussion page.
- The flag in the notes still counts repetition, as before.

**Not on these pages.** On the 132 privately supplied pages, v1.10 added one flag: a forum's "add your reply"
box matched the reply-command pattern. That page is not in the published data.

## Speed

On one very long page (3.1 MB of visible text), v1.9's repetition check did not finish in 20 seconds. The cause
was a search repeated for every sentence. v1.10 has two fixes:
- it judges repetition on the first 20,000 words;
- it skips sentences whose opening words can't recur often enough.

A test builds 60,000 sentences on purpose to hit the old slow path. v1.10 finishes it in about two seconds
(`tests/unit/test_injection_patterns.py`).

## Limits

- **Detection rates:** this run measures false alarms only. The tests show that each added disguise is caught,
  but this run does not measure catch rates on held-out attacks.
- **Rendering:** pages were read as fetched HTML, without JavaScript rendering.
- **Coverage:** 608 pages, mostly English, collected on one day.
