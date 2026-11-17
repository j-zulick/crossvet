"""Synthetic cases for ``crossvet-bench``.

Every organization, product, place and number here is invented, and every URL uses the
reserved ``.example`` domain, so a model cannot answer from memory: it has to use the notes.

Each case has:
- ``question`` and ``aspects``: what a complete answer must cover (keywords per aspect), used to
  score orchestration (did the supervisor delegate every aspect?) and research (did the
  queries cover them?);
- ``sources``: the research notes (title, URL, passage);
- ``facts``: values a faithful compression or report must keep, with their source URL;
- ``report``: a clean report that the notes fully support;
- ``plants``: known errors, each a list of ``(find, replace)`` edits to the clean report, the
  strings that show a reviewer caught it (``detect``) and how to tell a revision fixed it
  (``gone`` must disappear, ``back`` must reappear);
- ``false_findings``: plausible findings that the notes contradict (a critic should disagree),
  with a passage that settles each.
"""

from __future__ import annotations

CASES: list[dict] = [
    {
        "id": "seo-ai-answers",
        "domain": "seo",
        "question": "How did AI answer panels on Lumen Search change organic clicks for retail sites in 2026, and what should SEO teams measure?",
        "aspects": [
            {"name": "how often panels appear", "keywords": ["share", "queries", "appear", "frequency", "trigger", "prevalence", "how often"]},
            {"name": "effect on clicks", "keywords": ["click", "ctr", "traffic"]},
            {"name": "citations in panels", "keywords": ["cited", "citation", "source", "mention"]},
            {"name": "what to measure", "keywords": ["measure", "metric", "track", "kpi"]},
        ],
        "sources": [
            {"title": "Lumen Search Panel Study 2026", "url": "https://panelstudy.example/lumen-2026",
             "text": "Across 120,000 retail queries sampled in March 2026, Lumen Search showed an AI answer panel on 38% of queries, up from 21% in March 2025. Panels appeared most often on informational queries (61%) and least on branded queries (9%)."},
            {"title": "Click-through after AI panels", "url": "https://clickdata.example/ctr-ai-panels",
             "text": "When an AI answer panel was present, the click-through rate of the first organic result fell by 27% compared with the same queries without a panel. Results cited inside the panel lost only 8% of clicks."},
            {"title": "Who gets cited", "url": "https://citewatch.example/retail-citations",
             "text": "Retail sites with product pages carrying structured price and availability data were cited in 44% of panels where they ranked in the top ten, versus 17% for sites without that data."},
            {"title": "Measurement guide for AI panels", "url": "https://seoguide.example/measure-ai-panels",
             "text": "The guide recommends tracking three metrics separately: panel presence rate per query group, citation share inside panels, and click-through rate split by panel present versus absent."},
        ],
        "facts": [
            {"value": "38%", "url": "https://panelstudy.example/lumen-2026"},
            {"value": "21%", "url": "https://panelstudy.example/lumen-2026"},
            {"value": "27%", "url": "https://clickdata.example/ctr-ai-panels"},
            {"value": "8%", "url": "https://clickdata.example/ctr-ai-panels"},
            {"value": "44%", "url": "https://citewatch.example/retail-citations"},
        ],
        "report": (
            "# AI answer panels and retail organic clicks in 2026\n\n"
            "Lumen Search showed an AI answer panel on 38% of sampled retail queries in March 2026, up from 21% a year earlier [1]. "
            "Panels were most common on informational queries.\n\n"
            "When a panel appeared, the first organic result's click-through rate fell by 27%, while results cited inside the panel lost only 8% of clicks [2]. "
            "Sites with structured price and availability data were cited in 44% of panels where they ranked in the top ten, compared with 17% without it [3].\n\n"
            "SEO teams should track panel presence rate, citation share inside panels, and click-through rate split by panel present versus absent [4].\n\n"
            "### Sources\n"
            "[1] Lumen Search Panel Study 2026: https://panelstudy.example/lumen-2026\n"
            "[2] Click-through after AI panels: https://clickdata.example/ctr-ai-panels\n"
            "[3] Who gets cited: https://citewatch.example/retail-citations\n"
            "[4] Measurement guide for AI panels: https://seoguide.example/measure-ai-panels\n"
        ),
        "plants": [
            {"type": "wrong_number", "edits": [["fell by 27%", "fell by 47%"]], "detect": ["47%"], "gone": ["47%"], "back": ["27%"]},
            {"type": "unread_citation", "edits": [["lost only 8% of clicks [2]", "lost only 8% of clicks [2][5]"],
                                                   ["[4] Measurement guide for AI panels: https://seoguide.example/measure-ai-panels\n",
                                                    "[4] Measurement guide for AI panels: https://seoguide.example/measure-ai-panels\n[5] Retail SEO Outlook: https://retailoutlook.example/2026\n"]],
             "detect": ["retailoutlook", "[5]", "source 5"], "gone": ["retailoutlook.example"], "back": []},
            {"type": "unsupported_claim", "edits": [["Panels were most common on informational queries.",
                                                     "Panels were most common on informational queries and are expected to cover every retail query by 2027."]],
             "detect": ["2027", "every retail query"], "gone": ["by 2027"], "back": []},
            {"type": "omission", "edits": [[" Sites with structured price and availability data were cited in 44% of panels where they ranked in the top ten, compared with 17% without it [3].", ""]],
             "detect": ["structured", "44%", "price and availability", "schema"], "gone": [], "back": ["44%"]},
        ],
        "false_findings": [
            {"text": "The claim that panels appeared on 38% of queries is unsupported; the notes give no figure for 2026.",
             "settled_by": "Lumen Search showed an AI answer panel on 38% of queries"},
            {"text": "The notes do not say that cited results kept most of their clicks.",
             "settled_by": "Results cited inside the panel lost only 8% of clicks"},
        ],
    },
    {
        "id": "ev-charging-harrow-bay",
        "domain": "policy",
        "question": "What did Harrow Bay's 2025 curbside EV charging pilot achieve, what did it cost, and what problems came up?",
        "aspects": [
            {"name": "usage and adoption", "keywords": ["usage", "sessions", "utilization", "adoption", "drivers", "use"]},
            {"name": "cost", "keywords": ["cost", "budget", "spend", "price", "per charger"]},
            {"name": "problems and reliability", "keywords": ["problem", "reliability", "uptime", "outage", "complaint", "issue"]},
            {"name": "next steps", "keywords": ["expand", "next", "phase", "plan", "future"]},
        ],
        "sources": [
            {"title": "Harrow Bay pilot final report", "url": "https://harrowbay.example/ev-pilot-report",
             "text": "The pilot installed 240 curbside chargers on light poles between February and June 2025. Average utilization reached 31% of available hours by December 2025, and 4,900 residents registered as regular users."},
            {"title": "Council budget papers", "url": "https://council.example/budget-ev-2025",
             "text": "Total pilot spending was 3.1 million dollars, or about 12,900 dollars per charger including installation and two years of maintenance."},
            {"title": "Reliability audit", "url": "https://gridaudit.example/harrow-uptime",
             "text": "Chargers were available 92% of the time. Most downtime came from payment terminal faults, which caused 63% of reported outages."},
            {"title": "Phase two plan", "url": "https://harrowbay.example/ev-phase-two",
             "text": "The council approved a second phase of 600 chargers for 2026, prioritizing streets where fewer than 20% of homes have off-street parking."},
        ],
        "facts": [
            {"value": "240", "url": "https://harrowbay.example/ev-pilot-report"},
            {"value": "31%", "url": "https://harrowbay.example/ev-pilot-report"},
            {"value": "3.1 million", "url": "https://council.example/budget-ev-2025"},
            {"value": "92%", "url": "https://gridaudit.example/harrow-uptime"},
            {"value": "600", "url": "https://harrowbay.example/ev-phase-two"},
        ],
        "report": (
            "# Harrow Bay's curbside EV charging pilot\n\n"
            "Harrow Bay installed 240 curbside chargers on light poles in 2025, and utilization reached 31% of available hours by December, with 4,900 regular users [1].\n\n"
            "The pilot cost 3.1 million dollars, about 12,900 dollars per charger including two years of maintenance [2].\n\n"
            "Chargers were available 92% of the time; payment terminal faults caused 63% of reported outages [3].\n\n"
            "A second phase of 600 chargers is approved for 2026, focused on streets where few homes have off-street parking [4].\n\n"
            "### Sources\n"
            "[1] Harrow Bay pilot final report: https://harrowbay.example/ev-pilot-report\n"
            "[2] Council budget papers: https://council.example/budget-ev-2025\n"
            "[3] Reliability audit: https://gridaudit.example/harrow-uptime\n"
            "[4] Phase two plan: https://harrowbay.example/ev-phase-two\n"
        ),
        "plants": [
            {"type": "wrong_number", "edits": [["The pilot cost 3.1 million dollars", "The pilot cost 1.3 million dollars"]], "detect": ["1.3 million"], "gone": ["1.3 million"], "back": ["3.1 million"]},
            {"type": "unread_citation", "edits": [["with 4,900 regular users [1].", "with 4,900 regular users [1][5]."],
                                                   ["[4] Phase two plan: https://harrowbay.example/ev-phase-two\n",
                                                    "[4] Phase two plan: https://harrowbay.example/ev-phase-two\n[5] National EV Review: https://evreview.example/curbside\n"]],
             "detect": ["evreview", "[5]", "source 5"], "gone": ["evreview.example"], "back": []},
            {"type": "unsupported_claim", "edits": [["payment terminal faults caused 63% of reported outages [3].",
                                                     "payment terminal faults caused 63% of reported outages [3], and the vendor has since been replaced."]],
             "detect": ["vendor", "replaced"], "gone": ["vendor has since been replaced"], "back": []},
            {"type": "omission", "edits": [["\n\nA second phase of 600 chargers is approved for 2026, focused on streets where few homes have off-street parking [4].", ""]],
             "detect": ["phase", "600", "expan", "second", "next step"], "gone": [], "back": ["600"]},
        ],
        "false_findings": [
            {"text": "The 240 charger figure is not in the notes.", "settled_by": "The pilot installed 240 curbside chargers"},
            {"text": "The notes do not mention any second phase or expansion.", "settled_by": "The council approved a second phase of 600 chargers for 2026"},
        ],
    },
    {
        "id": "housing-kestrel-county",
        "domain": "real-estate",
        "question": "How did Kestrel County's housing market change from 2025 to 2026 in prices, inventory and time on market?",
        "aspects": [
            {"name": "prices", "keywords": ["price", "median", "value"]},
            {"name": "inventory", "keywords": ["inventory", "listings", "supply", "months of supply"]},
            {"name": "time on market", "keywords": ["days on market", "time on market", "days", "speed"]},
            {"name": "mortgage rates or affordability", "keywords": ["rate", "mortgage", "afford"]},
        ],
        "sources": [
            {"title": "Kestrel County Realtors Q2 2026", "url": "https://kestrelrealtors.example/q2-2026",
             "text": "The median sale price of single-family homes in Kestrel County was 412,000 dollars in Q2 2026, up 4.2% from Q2 2025. Active listings rose to 2,180, a 19% increase year over year."},
            {"title": "County housing dashboard", "url": "https://kestrelcounty.example/housing-dashboard",
             "text": "Median days on market lengthened from 18 days in June 2025 to 27 days in June 2026. Months of supply rose from 2.1 to 2.9."},
            {"title": "Regional lending survey", "url": "https://lendingsurvey.example/midstate-2026",
             "text": "The average 30-year fixed mortgage rate offered to Kestrel County buyers was 6.4% in June 2026, compared with 6.9% a year earlier."},
        ],
        "facts": [
            {"value": "412,000", "url": "https://kestrelrealtors.example/q2-2026"},
            {"value": "4.2%", "url": "https://kestrelrealtors.example/q2-2026"},
            {"value": "19%", "url": "https://kestrelrealtors.example/q2-2026"},
            {"value": "27 days", "url": "https://kestrelcounty.example/housing-dashboard"},
            {"value": "6.4%", "url": "https://lendingsurvey.example/midstate-2026"},
        ],
        "report": (
            "# Kestrel County housing, 2025 to 2026\n\n"
            "The median single-family sale price reached 412,000 dollars in Q2 2026, up 4.2% from a year earlier, while active listings rose 19% to 2,180 [1].\n\n"
            "Homes took longer to sell: median days on market rose from 18 to 27 days, and months of supply grew from 2.1 to 2.9 [2].\n\n"
            "Borrowing got slightly cheaper, with the average 30-year fixed rate at 6.4% in June 2026 versus 6.9% in 2025 [3].\n\n"
            "### Sources\n"
            "[1] Kestrel County Realtors Q2 2026: https://kestrelrealtors.example/q2-2026\n"
            "[2] County housing dashboard: https://kestrelcounty.example/housing-dashboard\n"
            "[3] Regional lending survey: https://lendingsurvey.example/midstate-2026\n"
        ),
        "plants": [
            {"type": "wrong_number", "edits": [["rose from 18 to 27 days", "rose from 18 to 37 days"]], "detect": ["37"], "gone": ["37 days"], "back": ["27"]},
            {"type": "unread_citation", "edits": [["months of supply grew from 2.1 to 2.9 [2].", "months of supply grew from 2.1 to 2.9 [2][4]."],
                                                   ["[3] Regional lending survey: https://lendingsurvey.example/midstate-2026\n",
                                                    "[3] Regional lending survey: https://lendingsurvey.example/midstate-2026\n[4] Homebuyer Pulse: https://homebuyerpulse.example/2026\n"]],
             "detect": ["homebuyerpulse", "[4]", "source 4"], "gone": ["homebuyerpulse.example"], "back": []},
            {"type": "unsupported_claim", "edits": [["while active listings rose 19% to 2,180 [1].",
                                                     "while active listings rose 19% to 2,180 [1], mainly because investors sold rental homes."]],
             "detect": ["investor", "rental"], "gone": ["investors sold"], "back": []},
            {"type": "omission", "edits": [["\n\nBorrowing got slightly cheaper, with the average 30-year fixed rate at 6.4% in June 2026 versus 6.9% in 2025 [3].", ""]],
             "detect": ["mortgage", "rate", "6.4%", "borrow", "afford"], "gone": [], "back": ["6.4%"]},
        ],
        "false_findings": [
            {"text": "The report's median price of 412,000 dollars is not supported by the notes.", "settled_by": "The median sale price of single-family homes in Kestrel County was 412,000 dollars"},
            {"text": "The notes give no mortgage rate for 2025.", "settled_by": "compared with 6.9% a year earlier"},
        ],
    },
    {
        "id": "datacenter-energy-norrland",
        "domain": "technology",
        "question": "How much electricity do AI data centers in the fictional Norrland grid region use in 2026, and how are operators cutting it?",
        "aspects": [
            {"name": "total electricity use", "keywords": ["terawatt", "twh", "electricity", "consumption", "demand", "use"]},
            {"name": "share of the grid", "keywords": ["share", "percent of", "grid"]},
            {"name": "efficiency measures", "keywords": ["efficien", "cooling", "pue", "cut", "reduce"]},
            {"name": "growth outlook", "keywords": ["growth", "forecast", "2030", "outlook"]},
        ],
        "sources": [
            {"title": "Norrland Grid Operator annual review", "url": "https://norrlandgrid.example/annual-2026",
             "text": "Data centers drew 14.2 terawatt-hours in the year to June 2026, 11% of all electricity on the Norrland grid. AI training and inference clusters accounted for 58% of that data center load."},
            {"title": "Cooling retrofit survey", "url": "https://coolingsurvey.example/norrland",
             "text": "Operators that moved to direct liquid cooling cut average power usage effectiveness (PUE) from 1.38 to 1.12 across 23 surveyed sites."},
            {"title": "Grid outlook 2030", "url": "https://norrlandgrid.example/outlook-2030",
             "text": "The operator's central forecast has data center demand reaching 24 terawatt-hours by 2030."},
        ],
        "facts": [
            {"value": "14.2", "url": "https://norrlandgrid.example/annual-2026"},
            {"value": "11%", "url": "https://norrlandgrid.example/annual-2026"},
            {"value": "58%", "url": "https://norrlandgrid.example/annual-2026"},
            {"value": "1.12", "url": "https://coolingsurvey.example/norrland"},
            {"value": "24", "url": "https://norrlandgrid.example/outlook-2030"},
        ],
        "report": (
            "# AI data center electricity on the Norrland grid\n\n"
            "Data centers used 14.2 terawatt-hours in the year to June 2026, 11% of the grid's electricity; AI clusters made up 58% of that load [1].\n\n"
            "Sites that switched to direct liquid cooling cut average PUE from 1.38 to 1.12 [2].\n\n"
            "The grid operator expects data center demand to reach 24 terawatt-hours by 2030 [3].\n\n"
            "### Sources\n"
            "[1] Norrland Grid Operator annual review: https://norrlandgrid.example/annual-2026\n"
            "[2] Cooling retrofit survey: https://coolingsurvey.example/norrland\n"
            "[3] Grid outlook 2030: https://norrlandgrid.example/outlook-2030\n"
        ),
        "plants": [
            {"type": "wrong_number", "edits": [["11% of the grid's electricity", "21% of the grid's electricity"]], "detect": ["21%"], "gone": ["21%"], "back": ["11%"]},
            {"type": "unread_citation", "edits": [["made up 58% of that load [1].", "made up 58% of that load [1][4]."],
                                                   ["[3] Grid outlook 2030: https://norrlandgrid.example/outlook-2030\n",
                                                    "[3] Grid outlook 2030: https://norrlandgrid.example/outlook-2030\n[4] Green Compute Index: https://greencompute.example/2026\n"]],
             "detect": ["greencompute", "[4]", "source 4"], "gone": ["greencompute.example"], "back": []},
            {"type": "unsupported_claim", "edits": [["Sites that switched to direct liquid cooling cut average PUE from 1.38 to 1.12 [2].",
                                                     "Sites that switched to direct liquid cooling cut average PUE from 1.38 to 1.12 [2], saving operators 40 million dollars a year."]],
             "detect": ["40 million", "saving"], "gone": ["40 million"], "back": []},
            {"type": "omission", "edits": [["\n\nThe grid operator expects data center demand to reach 24 terawatt-hours by 2030 [3].", ""]],
             "detect": ["2030", "forecast", "outlook", "growth", "24 terawatt"], "gone": [], "back": ["24 terawatt"]},
        ],
        "false_findings": [
            {"text": "The notes do not say what share of data center load comes from AI clusters.", "settled_by": "AI training and inference clusters accounted for 58% of that data center load"},
            {"text": "The PUE improvement to 1.12 is not supported.", "settled_by": "cut average power usage effectiveness (PUE) from 1.38 to 1.12"},
        ],
    },
    {
        "id": "newsletter-benchmarks",
        "domain": "marketing",
        "question": "What were typical email newsletter open and click rates for B2B software companies in 2026, and which changes improved them?",
        "aspects": [
            {"name": "open rates", "keywords": ["open"]},
            {"name": "click rates", "keywords": ["click", "ctr"]},
            {"name": "what improved results", "keywords": ["improve", "lift", "increase", "test", "change"]},
            {"name": "measurement caveats", "keywords": ["privacy", "caveat", "inflate", "machine", "bot", "reliab"]},
        ],
        "sources": [
            {"title": "Inbox Metrics B2B Benchmark 2026", "url": "https://inboxmetrics.example/b2b-2026",
             "text": "Across 1,400 B2B software newsletters, the median reported open rate was 41% and the median click rate was 2.3% in the first half of 2026."},
            {"title": "Privacy-inflated opens", "url": "https://mailprivacy.example/open-inflation",
             "text": "Automatic image loading by mail privacy features inflated reported open rates; the study estimates that 35% of recorded opens were machine opens, so click rate is the more reliable engagement measure."},
            {"title": "Subject line and send-time tests", "url": "https://sendtests.example/b2b-results",
             "text": "In 212 controlled tests, plain-text style newsletters lifted click rate by 18% over heavily designed templates, and sending on Tuesday mornings lifted click rate by 6% compared with Friday afternoons."},
        ],
        "facts": [
            {"value": "41%", "url": "https://inboxmetrics.example/b2b-2026"},
            {"value": "2.3%", "url": "https://inboxmetrics.example/b2b-2026"},
            {"value": "35%", "url": "https://mailprivacy.example/open-inflation"},
            {"value": "18%", "url": "https://sendtests.example/b2b-results"},
            {"value": "6%", "url": "https://sendtests.example/b2b-results"},
        ],
        "report": (
            "# B2B software newsletter benchmarks, 2026\n\n"
            "The median B2B software newsletter reported a 41% open rate and a 2.3% click rate in the first half of 2026 [1].\n\n"
            "Open rates overstate engagement: an estimated 35% of recorded opens were automatic machine opens, so click rate is the more reliable measure [2].\n\n"
            "Plain-text style newsletters lifted click rate by 18% over designed templates, and Tuesday morning sends lifted it by 6% versus Friday afternoons [3].\n\n"
            "### Sources\n"
            "[1] Inbox Metrics B2B Benchmark 2026: https://inboxmetrics.example/b2b-2026\n"
            "[2] Privacy-inflated opens: https://mailprivacy.example/open-inflation\n"
            "[3] Subject line and send-time tests: https://sendtests.example/b2b-results\n"
        ),
        "plants": [
            {"type": "wrong_number", "edits": [["lifted click rate by 18%", "lifted click rate by 48%"]], "detect": ["48%"], "gone": ["48%"], "back": ["18%"]},
            {"type": "unread_citation", "edits": [["and a 2.3% click rate in the first half of 2026 [1].", "and a 2.3% click rate in the first half of 2026 [1][4]."],
                                                   ["[3] Subject line and send-time tests: https://sendtests.example/b2b-results\n",
                                                    "[3] Subject line and send-time tests: https://sendtests.example/b2b-results\n[4] Email Marketing Almanac: https://emailalmanac.example/2026\n"]],
             "detect": ["emailalmanac", "[4]", "source 4"], "gone": ["emailalmanac.example"], "back": []},
            {"type": "unsupported_claim", "edits": [["so click rate is the more reliable measure [2].",
                                                     "so click rate is the more reliable measure [2]. Adding emojis to subject lines doubles open rates."]],
             "detect": ["emoji", "doubles"], "gone": ["emoji"], "back": []},
            {"type": "omission", "edits": [[", and Tuesday morning sends lifted it by 6% versus Friday afternoons", ""]],
             "detect": ["tuesday", "send time", "send-time", "timing", "6%", "day of"], "gone": [], "back": ["Tuesday"]},
        ],
        "false_findings": [
            {"text": "The notes give no median click rate.", "settled_by": "the median click rate was 2.3%"},
            {"text": "Send time made no measurable difference according to the notes.", "settled_by": "sending on Tuesday mornings lifted click rate by 6%"},
        ],
    },
    {
        "id": "clinic-wait-times",
        "domain": "health-policy",
        "question": "Did the Ostrava Valley evening clinic program reduce emergency department waits in 2026, and at what cost?",
        "aspects": [
            {"name": "effect on emergency waits", "keywords": ["wait", "emergency", "ed ", "department"]},
            {"name": "clinic usage", "keywords": ["visits", "patients", "usage", "use", "attend"]},
            {"name": "cost", "keywords": ["cost", "budget", "spend", "per visit"]},
            {"name": "limitations of the evidence", "keywords": ["limit", "caveat", "causal", "control", "confound", "evaluation"]},
        ],
        "sources": [
            {"title": "Ostrava Valley Health Board evaluation", "url": "https://ovhealth.example/evening-clinics-eval",
             "text": "After six evening clinics opened in January 2026, the median emergency department wait in the valley fell from 4.6 hours to 3.8 hours by June 2026. The evaluation compared against two neighboring regions without clinics, where waits fell from 4.5 to 4.3 hours."},
            {"title": "Clinic activity report", "url": "https://ovhealth.example/clinic-activity",
             "text": "The clinics handled 52,000 visits in the first half of 2026; 71% of patients said they would otherwise have gone to an emergency department."},
            {"title": "Program budget", "url": "https://ovfinance.example/clinic-budget",
             "text": "Running costs were 9.4 million for the first six months, about 181 per visit."},
        ],
        "facts": [
            {"value": "4.6", "url": "https://ovhealth.example/evening-clinics-eval"},
            {"value": "3.8", "url": "https://ovhealth.example/evening-clinics-eval"},
            {"value": "52,000", "url": "https://ovhealth.example/clinic-activity"},
            {"value": "71%", "url": "https://ovhealth.example/clinic-activity"},
            {"value": "181", "url": "https://ovfinance.example/clinic-budget"},
        ],
        "report": (
            "# Ostrava Valley evening clinics and emergency waits\n\n"
            "After six evening clinics opened in January 2026, the median emergency department wait fell from 4.6 to 3.8 hours by June, while neighboring regions without clinics saw only a small drop, from 4.5 to 4.3 hours [1].\n\n"
            "The clinics handled 52,000 visits in six months, and 71% of patients said they would otherwise have gone to an emergency department [2].\n\n"
            "Running costs were 9.4 million for the first six months, about 181 per visit [3].\n\n"
            "### Sources\n"
            "[1] Ostrava Valley Health Board evaluation: https://ovhealth.example/evening-clinics-eval\n"
            "[2] Clinic activity report: https://ovhealth.example/clinic-activity\n"
            "[3] Program budget: https://ovfinance.example/clinic-budget\n"
        ),
        "plants": [
            {"type": "wrong_number", "edits": [["fell from 4.6 to 3.8 hours", "fell from 4.6 to 2.8 hours"]], "detect": ["2.8"], "gone": ["2.8 hours"], "back": ["3.8"]},
            {"type": "unread_citation", "edits": [["about 181 per visit [3].", "about 181 per visit [3][4]."],
                                                   ["[3] Program budget: https://ovfinance.example/clinic-budget\n",
                                                    "[3] Program budget: https://ovfinance.example/clinic-budget\n[4] Health Systems Weekly: https://healthweekly.example/clinics\n"]],
             "detect": ["healthweekly", "[4]", "source 4"], "gone": ["healthweekly.example"], "back": []},
            {"type": "unsupported_claim", "edits": [["and 71% of patients said they would otherwise have gone to an emergency department [2].",
                                                     "and 71% of patients said they would otherwise have gone to an emergency department [2]. The program will be rolled out nationally in 2027."]],
             "detect": ["national", "2027"], "gone": ["nationally"], "back": []},
            {"type": "omission", "edits": [[", while neighboring regions without clinics saw only a small drop, from 4.5 to 4.3 hours", ""]],
             "detect": ["neighbor", "comparison", "control", "4.3", "other regions", "baseline"], "gone": [], "back": ["4.3"]},
        ],
        "false_findings": [
            {"text": "The notes do not compare the valley with any region that lacked clinics.", "settled_by": "compared against two neighboring regions without clinics"},
            {"text": "The cost per visit is not given anywhere in the notes.", "settled_by": "about 181 per visit"},
        ],
    },
]


def notes_for(case: dict) -> str:
    """Format the research notes as the pipeline would pass them on: one block per source."""
    return "\n\n".join(f"Source: {s['title']} ({s['url']})\n{s['text']}" for s in case["sources"])


def apply_edits(text: str, edits: list[list[str]]) -> str:
    """Apply ``(find, replace)`` edits; every ``find`` must occur in the text."""
    for find, replace in edits:
        if find not in text:
            raise ValueError(f"edit target not found: {find[:60]!r}")
        text = text.replace(find, replace, 1)
    return text


def planted_draft(case: dict) -> str:
    """Return the clean report with every planted error applied."""
    text = case["report"]
    for plant in case["plants"]:
        text = apply_edits(text, plant["edits"])
    return text
