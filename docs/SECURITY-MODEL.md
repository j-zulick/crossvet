# Security model

What Crossvet defends against, how, and what it does not cover. Reporting a vulnerability: [SECURITY.md](../SECURITY.md).

Crossvet reads untrusted web pages and passes what it learns between models from several vendors. The main risks are content that misleads the models and output that looks better supported than it is.

| Threat | Defense | Where | Limits |
|---|---|---|---|
| A report cites a URL the research never read | Deterministic citation check; the revision is rejected if it adds one | `cross_vendor_review.check_citations`, `revision_problem` | Checks the URL was read, not that it supports the claim |
| A reviewer or critic overrules a finding with a made-up quote | Quotes must appear verbatim in the notes before they count | `quote_in_notes` | A real quote can still be taken out of context; Jev support checks (opt-in) score that |
| Models agree with each other instead of checking | Anonymized critiques, critic of a different model, stop rules in code, false-consensus guard | `cross_vendor_review`, `deliberation.decide_stop` | Measured on synthetic cases only |
| **Prompt injection in a fetched page** ("ignore your instructions", "recommend X", "cite this URL", hidden text) | Pattern check on each page before summarization; flag line in the notes; page text treated as data in the summarizer prompt, wrapper-breaking markup removed; flagged sources listed in the Review notes, with any the report cites; a sentence citing only flagged sources goes to *Disputed* (1.8); the summarizer's data wrapper carries a per-call marker (1.8) | `injection_check.py`, `utils.tavily_search`, `gateway_search` | Paraphrased or translated instructions are missed (invisible Unicode tag text and base64 are decoded and scanned since 1.8); honest pages that quote injections are flagged; vendor-hosted search returns no raw text to scan |
| Server-side request forgery through the search gateway | Private, loopback and link-local addresses refused | research gateway (v0.8) | Applies to the gateway, not to vendor-hosted search |
| An agent asks the MCP scan tool to fetch an internal address | `scan_for_injection` refuses hosts that resolve to loopback, private, link-local or reserved addresses, on every redirect | `scan_cli._refuse_private` | Applies to the MCP tool; the `crossvet-scan` CLI may fetch local addresses on purpose |
| Leaked keys | Keys only from environment or a gitignored `.env`; `crossvet-doctor` reports presence, never values | `doctor.py`, `.gitignore` | A key pasted into a prompt or a report is outside this |
| Unauthenticated LangGraph server | `src/security/auth.py` for deployments; `langgraph.local.json` is for local use only | `src/security/` | Exposing the local config publicly is unsafe |

## Measuring it
- `crossvet-bench run --suite injection` and `--suite injection-checked` run the same four cases with one injected source each (four injection forms: override, hidden comment, cite-this-URL, role change), without and with the flag line. Writer and compression outputs report `followed_injection` and `flagged_injection`; a followed injection halves the score. The reviewer, critic and reviser see the injected claim as an extra planted error (`caught_injected_claim`, `fixed_injected_claim`).
- First results: [docs/benchmarks/2026-11-18-injection/](benchmarks/2026-11-18-injection/). Results are published only from real runs (`docs/EVALS.md`).

## Next
Measured gaps (`--suite injection-hard`): paraphrased, translated, split and repeated injections are not matched by the patterns, and one of 28 reports adopted a split instruction. Candidates, to be measured before adoption:
- run the summarizer and compression with an instruction to report, never repeat, recommendations and instructions found in a page;
- flag a source whose text is mostly one repeated claim;
- treat a URL that appears only inside a page's text, and nowhere in search results, as unverified when a report cites it.

## Not covered
- A source that is wrong but honest: the checks confirm what the notes say, not that the notes are true.
- Compromise of a model vendor or of a dependency.
- Content filters or refusals by a provider; these are detected and reported (`models.stop_problem`), not defended against.
