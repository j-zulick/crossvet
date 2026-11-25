"""More than one model on the same thing: side-by-side answers, and a second model trying to break the first's work.

``challenge`` is built on what people who run two models report works:

- ask the second model to *break* the work, not to "review" it (a plain review mostly agrees);
- the reviewer comes from a different vendor than the author, enforced in code;
- an objection only counts if it names a concrete failure case; the rest are dropped in code;
- the reviewer finds suspects, it does not give the verdict: the kept objections go back to the
  author (``revise``), and the user decides.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from crossvet.chat.hub import Hub, strip_fences
from crossvet.chat.memory import new_thread
from crossvet.chat.providers import ProviderError, vendor_of

CHALLENGE_PROMPT = """Another AI model produced the work below for this request. Your job is to break it, not to praise it.

Find where it fails. For each problem give:
- "claim": the specific statement, step or assumption that is wrong or risky;
- "failure_case": a concrete situation, input or fact in which it fails, specific enough that someone could check it;
- "severity": "high", "medium" or "low".

Also list, under "assumptions", what the work depends on being true without saying so.
Do not comment on style. If you find no real problem, return an empty list.

Reply with JSON only: {{"objections": [{{"claim": "...", "failure_case": "...", "severity": "..."}}], "assumptions": ["..."]}}

<request>
{request}
</request>

<work>
{work}
</work>"""
REVISE_PROMPT = """A reviewer from another AI vendor raised the objections below about your earlier answer. For each one, either
fix the answer or say briefly why the objection does not hold. Then give the full revised answer.

<objections>
{objections}
</objections>

<your-earlier-answer>
{work}
</your-earlier-answer>"""
# An objection needs a failure case with some substance; these phrases say nothing checkable.
_VAGUE = re.compile(r"^(n/?a|none|unknown|unclear|it (may|might|could) (fail|be wrong)|various|many cases|in some cases|"
                    r"depends|not sure|could be improved|needs more detail)\W*$", re.IGNORECASE)
MIN_FAILURE_CASE_CHARS = 25


@dataclass
class Objection:
    """One problem a reviewer raised."""

    claim: str
    failure_case: str
    severity: str = "medium"


@dataclass
class Challenge:
    """The outcome of one model trying to break another's work."""

    author_model: str
    reviewer_model: str
    kept: list[Objection] = field(default_factory=list)
    dropped: list[Objection] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    revised: str = ""
    cost: float | None = None
    problem: str = ""   # set when the reviewer's reply could not be read

    def report(self) -> str:
        """Return the challenge as readable text."""
        lines = [f"Reviewer: {self.reviewer_model} (author: {self.author_model or 'not a model'})"]
        if self.problem:
            lines.append(f"Could not read the review: {self.problem}")
        if not self.kept and not self.problem:
            lines.append("No objection named a concrete failure case.")
        for i, o in enumerate(self.kept, 1):
            lines.append(f"{i}. [{o.severity}] {o.claim}\n   Fails when: {o.failure_case}")
        if self.dropped:
            lines.append(f"Dropped {len(self.dropped)} objection(s) with no concrete failure case.")
        if self.assumptions:
            lines.append("Unstated assumptions:\n" + "\n".join(f"- {a}" for a in self.assumptions))
        if self.revised:
            lines.append("\nRevised answer:\n" + self.revised)
        return "\n".join(lines)


def concrete(objection: Objection) -> bool:
    """Whether an objection names a failure case someone could check."""
    case = objection.failure_case.strip()
    return bool(objection.claim.strip()) and len(case) >= MIN_FAILURE_CASE_CHARS and not _VAGUE.match(case)


def parse_objections(text: str) -> tuple[list[Objection], list[str]]:
    """Read the reviewer's JSON; raise ``ValueError`` when it is not the expected shape."""
    data = json.loads(strip_fences(text))
    if not isinstance(data, dict) or not isinstance(data.get("objections", []), list):
        raise ValueError("expected an object with an 'objections' list")
    objections = [
        Objection(str(o.get("claim", "")), str(o.get("failure_case", "")), str(o.get("severity", "medium")).lower())
        for o in data.get("objections", []) if isinstance(o, dict)
    ]
    assumptions = [str(a) for a in data.get("assumptions", []) if str(a).strip()] if isinstance(data.get("assumptions"), list) else []
    return objections, assumptions


def pick_reviewer(hub: Hub, author_model: str) -> str:
    """Return the first reviewer-slot model from a different vendor than the author; raise when there is none."""
    author_vendor = vendor_of(author_model) if author_model else ""
    cfg = hub.config
    ordered = cfg.slots.get("reviewer", []) + cfg.slots.get("strong", []) + cfg.slots.get("balanced", []) + cfg.all_models()
    for model in dict.fromkeys(ordered):  # reviewer slot first, then the strongest models
        if vendor_of(model) != author_vendor:
            return model
    raise ProviderError(f"no configured model comes from a different vendor than {author_model}; add one to the 'reviewer' slot")


def challenge(hub: Hub, request: str, work: str, *, author_model: str = "", reviewer: str | None = None,
              revise: bool = False, thread: str | None = None, author: str = "cli") -> Challenge:
    """Have a model from another vendor try to break ``work``; optionally send the result back to the author."""
    if not work.strip():
        raise ValueError("there is no work to challenge")
    reviewer_model = reviewer or pick_reviewer(hub, author_model)
    if author_model and vendor_of(reviewer_model) == vendor_of(author_model):
        raise ProviderError(f"reviewer {reviewer_model} is from the same vendor as the author {author_model}")
    thread = thread or new_thread()
    review = hub.ask(CHALLENGE_PROMPT.format(request=request or "(not given)", work=work), thread=thread, model=reviewer_model,
                     author=author, use_memory=False, want_json=True, save=False)
    result = Challenge(author_model, review.model, cost=review.cost)
    try:
        objections, result.assumptions = parse_objections(review.text)
    except ValueError as exc:
        limit = hub.config.max_output_tokens
        cut_off = review.output_tokens >= limit - 5
        result.problem = (f"the review was cut off at the output limit ([limits] max_output_tokens = {limit}); raise it and "
                          "try again" if cut_off else f"the review was not valid JSON: {exc}")
        objections = []
    result.kept = [o for o in objections if concrete(o)]
    result.dropped = [o for o in objections if not concrete(o)]
    hub.memory.add_turn(thread, author, "review", result.report(), model=review.model, cost=review.cost,
                        meta={"kept": len(result.kept), "dropped": len(result.dropped), "author_model": author_model})
    if revise and result.kept and author_model:
        listed = "\n".join(f"{i}. {o.claim} Fails when: {o.failure_case}" for i, o in enumerate(result.kept, 1))
        revision = hub.ask(REVISE_PROMPT.format(objections=listed, work=work), thread=thread, model=author_model,
                           author=author, use_memory=False, save=False)
        result.revised = revision.text
        costs = [c for c in (result.cost, revision.cost) if c is not None]
        result.cost = sum(costs) if costs else None
        hub.memory.add_turn(thread, author, "assistant", revision.text, model=revision.model, cost=revision.cost,
                            meta={"revision_after_review": True})
    return result


def compare(hub: Hub, prompt: str, models: list[str], *, author: str = "cli", thread: str | None = None) -> list[dict]:
    """Ask several models the same thing at once; one result per model, in the order given."""
    if not models:
        raise ValueError("name at least one model")
    thread = thread or new_thread()

    def one(model: str) -> dict:
        try:
            answer = hub.ask(prompt, thread=thread, model=model, author=author, save=False)
            return {"model": model, "ok": True, "text": answer.text, "cost": answer.cost, "cost_usd": answer.cost,
                    "seconds": answer.attempts[-1].seconds}
        except (ProviderError, RuntimeError) as exc:
            return {"model": model, "ok": False, "text": "", "error": str(exc)[:300], "cost": None, "cost_usd": None,
                    "seconds": 0.0}

    with ThreadPoolExecutor(max_workers=min(8, len(models))) as pool:
        results = list(pool.map(one, models))
    hub.memory.add_turn(thread, author, "user", prompt)
    for r in results:
        if r["ok"]:
            hub.memory.add_turn(thread, author, "assistant", r["text"], model=r["model"], cost=r["cost"], meta={"compare": True})
    return results
