"""Decide what kind of task a request is, from its text alone. No model is asked.

The result names a kind (code, review, writing, summarize, extract, translate, reasoning, fresh,
quick, general), a difficulty from 1 to 3, and the reason in plain words, so every routing
decision can be shown to the user. The rules are deliberately simple and err upward: when a
request is unclear it is "general" at difficulty 2, never "quick".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = ("code", "review", "writing", "summarize", "extract", "translate", "reasoning", "fresh", "quick", "general")


@dataclass(frozen=True)
class Task:
    """What a request is and how hard it looks."""

    kind: str
    difficulty: int   # 1 easy, 2 normal, 3 hard
    reason: str
    wants_json: bool = False


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_CODE_BLOCK = re.compile(r"```|^\s{4,}\S.*[;{}()]\s*$|\b(def|class|function|import|SELECT|const|let|var)\b[^.\n]{0,60}[({=:;]", re.M)
_CODE_WORDS = _rx(r"\b(code|function|bug|stack ?trace|traceback|exception|compile|refactor|unit tests?|regex|sql|api endpoint|"
                  r"python|javascript|typescript|rust|golang|java|kotlin|swift|php|ruby|c\+\+|c#|html|css|react component|"
                  r"bash script|shell script|dockerfile|docker compose|kubernetes|terraform|pull request|"
                  r"git (rebase|merge|commit)|race condition|goroutine|worker pool|null pointer|segfault|memory leak|"
                  r"debug|compile error|type error|database (query|migration|schema)|go (code|func|module|routine))\b")
_REVIEW = _rx(r"\b(review|critique|second opinion|find (the )?(flaws|holes|problems|where .* fails)|what('s| is) wrong with|"
              r"poke holes|challenge (this|my)|sanity[- ]check|red[- ]team|list the assumptions)\b")
_SUMMARIZE = _rx(r"\b(summari[sz]e|summary|tl;?dr|key (points|takeaways)|condense|shorten|recap|in (one|two|three|\d+) (sentences?|bullets?|lines?))\b")
_EXTRACT = _rx(r"\b(extract|pull out|list (all|every|the) [\w ]{0,30}(names|dates|emails|numbers|prices|urls|links)|parse|"
               r"convert .* (to|into) (json|csv|a table)|classify|categori[sz]e|label (each|these)|as json|in json)\b")
_TRANSLATE = _rx(r"\b(translate|translation|in (spanish|french|german|italian|portuguese|dutch|japanese|chinese|korean)|"
                 r"(to|into) (english|spanish|french|german|italian|portuguese|dutch|japanese|chinese|korean))\b")
_WRITING = _rx(r"\b(write|draft|rewrite|reword|proofread|edit (this|my)|email|cover letter|blog post|linkedin post|headline|"
               r"tagline|press release|product description|make (this|it) (sound|more|less))\b")
_REASONING = _rx(r"\b(prove|derive|calculate|compute|solve|how many|probability|optimi[sz]e|trade-?offs?|compare|versus|vs\.?|"
                 r"pros and cons|step by step|why does|explain why|analy[sz]e|analysis|strategy|plan (for|to)|architecture|design a)\b")
_FRESH = _rx(r"\b(today|right now|currently|this (week|morning|month)|latest|breaking|trending|just (announced|released|changed)|"
             r"what('s| is) (happening|new)|stock price|score of|weather|news (on|about)|as of (now|today)|recent(ly)? (changes?|news|updates?))\b")
_QUICK_START = _rx(r"^\s*(who|what|when|where|which|is|are|was|were|does|do|did|can|define|how (many|much|old|long|tall|far|do you spell))\b")
_HARD = _rx(r"\b(architecture|design|refactor|migrate|concurren\w+|race condition|security|performance|scal\w+|prove|derive|"
            r"comprehensive|in[- ]depth|end[- ]to[- ]end|from scratch|production|edge cases)\b")
_JSON = _rx(r"\b(json|as a json|valid json|return json)\b")

QUICK_MAX_CHARS = 140
LONG_CHARS = 1500


def classify(text: str) -> Task:
    """Name the kind of task ``text`` is, with a difficulty and the reason."""
    body = (text or "").strip()
    wants_json = bool(_JSON.search(body))
    hard = _HARD.search(body)
    parts = body.count("?") + len(re.findall(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+\S", body))

    def task(kind: str, base: int, why: str) -> Task:
        difficulty = base
        notes = [why]
        if hard:
            difficulty = max(difficulty, 3)
            notes.append(f'it mentions "{hard.group(0)}"')
        elif len(body) > LONG_CHARS and base < 3:
            difficulty = base + 1
            notes.append(f"the request is long ({len(body)} characters)")
        elif parts >= 3 and base < 3:
            difficulty = base + 1
            notes.append(f"it has {parts} parts")
        return Task(kind, min(difficulty, 3), "; ".join(notes), wants_json)

    # Order matters: the most specific signal wins.
    if _REVIEW.search(body):
        return task("review", 2, f'it asks for a critique ("{_REVIEW.search(body).group(0)}")')
    if _CODE_BLOCK.search(body) or _CODE_WORDS.search(body):
        match = _CODE_WORDS.search(body)
        return task("code", 2, f'it is about code ("{match.group(0)}")' if match else "it contains code")
    if _FRESH.search(body):
        return task("fresh", 2, f'it asks about something current ("{_FRESH.search(body).group(0)}")')
    if _TRANSLATE.search(body):
        return task("translate", 1, f'it asks for a translation ("{_TRANSLATE.search(body).group(0)}")')
    if _SUMMARIZE.search(body):
        return task("summarize", 1, f'it asks for a summary ("{_SUMMARIZE.search(body).group(0)}")')
    if _EXTRACT.search(body):
        return task("extract", 1, f'it asks to pull out or restructure information ("{_EXTRACT.search(body).group(0)}")')
    if _WRITING.search(body):
        return task("writing", 2, f'it asks for writing ("{_WRITING.search(body).group(0)}")')
    if _REASONING.search(body):
        return task("reasoning", 2, f'it asks for analysis or a calculation ("{_REASONING.search(body).group(0)}")')
    if body and len(body) <= QUICK_MAX_CHARS and parts <= 1 and _QUICK_START.match(body):
        return Task("quick", 1, "it is one short question", wants_json)
    return task("general", 2, "no specific kind of task was recognized")
