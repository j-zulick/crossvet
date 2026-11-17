"""Research context: who is asking, why, and domain packs with field-specific evidence rules.

``RESEARCH_CONTEXT`` is free text (the requester, the purpose, constraints). ``CONTEXT_PACK``
picks a domain pack: guidance on which sources count as primary, which claims go stale,
and what reviewers should check in that field. Both are appended to the research brief,
so the researchers, the critique, the critic, deliberation and the reviser all see them.
"""

from __future__ import annotations

PACKS: dict[str, dict[str, str]] = {
    "seo": {
        "title": "SEO and generative engine optimization (GEO)",
        "guidance": """- Primary sources: Google Search Central documentation and blog, statements by Google's Search Liaison or Search Relations team, Bing Webmaster guidelines, and the site's own first-party data (Search Console, server logs).
- Patents show what a search engine *could* do, not what it does; say so whenever one is cited.
- Studies from SEO tool vendors are usually correlation studies on their own data sets; report them as correlations, with sample size and date, never as confirmed ranking factors.
- Date every claim about rankings, algorithms or AI features: core updates and AI Overviews / AI Mode change often, and older claims may no longer hold. Prefer sources from the last 12 months and flag older ones.
- AI assistant and AI Overview citations vary by query, location, session and time; a measurement needs its sample, date and method.
- Separate what Google has confirmed, what it has denied, and what is practitioner opinion.""",
    },
    "marketing": {
        "title": "Marketing and go-to-market",
        "guidance": """- Primary sources: platform documentation (ad platforms, analytics tools), company filings and earnings calls, government statistics, and surveys that publish their method.
- Vendor and agency reports are marketing material: name the vendor, the sample size, the geography and the date for every figure taken from one.
- Benchmarks (conversion, click-through, open rates, CAC) depend on industry, channel and period; state those, and whether a figure is a median or an average.
- Treat round, unsourced statistics that circulate between blogs as unsupported until an original source is found.
- Distinguish measured results (experiments, A/B tests) from case studies and testimonials.""",
    },
    "real-estate": {
        "title": "Real estate",
        "guidance": """- Primary sources: MLS or brokerage data with its date range, public records (assessor, recorder, permits), government data (Census, HUD, FHFA, local planning departments), and lender or regulator publications.
- Markets are local: name the geography (city, county, ZIP, neighborhood) and the period for every price, rent, inventory or days-on-market figure.
- Distinguish list prices, sale prices and price per square foot, and medians from averages.
- Zoning, disclosure, tax and landlord-tenant rules vary by state and municipality; cite the jurisdiction's own source.
- Reports are research, not legal, tax or investment advice; say so where a reader might act on them.""",
    },
}


def available_packs() -> list[str]:
    """Names accepted by CONTEXT_PACK."""
    return sorted(PACKS)


def context_block(pack: str = "", research_context: str = "") -> str:
    """Return the text appended to the research brief ('' when neither is set)."""
    parts: list[str] = []
    if research_context and research_context.strip():
        parts.append("Requester's context:\n" + research_context.strip())
    name = (pack or "").strip().lower()
    if name:
        if name not in PACKS:
            raise ValueError(f"Unknown CONTEXT_PACK {pack!r}; choose one of: {', '.join(available_packs())}")
        p = PACKS[name]
        parts.append(f"Evidence rules for this field ({p['title']}). Researchers and reviewers apply them:\n{p['guidance']}")
    return "\n\n".join(parts)


def with_context(brief: str, pack: str = "", research_context: str = "") -> str:
    """Append the context block to a research brief (unchanged when there is none)."""
    block = context_block(pack, research_context)
    if not block or block in (brief or ""):
        return brief
    return f"{brief.rstrip()}\n\n{block}"
