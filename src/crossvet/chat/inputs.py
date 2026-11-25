"""What a request carries besides text, and whether it should stay on your own machine.

``detect`` reads an OpenAI-style message (``content`` may be a list of parts) and counts images,
audio and PDFs, and notices pasted code. Routing uses it: images go to the ``vision`` slot,
audio to ``audio`` (or is transcribed first), PDFs to ``long``, and models that say in the
settings which inputs they take (``[models."x"] takes = ["image"]``) are preferred, while models
that say they don't take an input are skipped.

``looks_private`` finds requests that should not leave the machine: API keys, card and ID
numbers, private keys, and the words "confidential" or "private". It is a pattern check in
code, so it errs toward keeping a request local; ``/private`` or the ``x-crossvet-private``
header marks a request private by hand.

``to_anthropic`` turns OpenAI-style parts into the shapes Anthropic's API takes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from crossvet.chat.classify import _CODE_BLOCK

IMAGE_PARTS = ("image_url", "input_image")
AUDIO_PARTS = ("input_audio",)
FILE_PARTS = ("file", "input_file")

_PRIVATE = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}"  # API keys
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"  # chat app tokens
    r"|\d{3}-\d{2}-\d{4}"  # US social security numbers
    r"|(?:\d[ -]?){13,16}"  # card numbers
    r"|confidential|private and confidential|do not share|attorney[- ]client)\b"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.I,
)


@dataclass
class Inputs:
    """What a request carries besides its text."""

    images: int = 0
    audio: int = 0
    pdfs: int = 0
    other_files: int = 0
    code: bool = False
    parts: list[dict[str, Any]] = field(default_factory=list)  # the message's parts, when it had any besides text

    def types(self) -> list[str]:
        """Return the input types present, in routing order (image, audio, pdf)."""
        return [t for t, n in (("image", self.images), ("audio", self.audio), ("pdf", self.pdfs)) if n]

    def describe(self) -> str:
        """Return the non-text inputs in words, e.g. "2 images and a PDF" ("" when there are none)."""
        words = [f"{n} {name}{'s' if n > 1 else ''}" if n > 1 else f"{'an' if name[0] in 'aeiou' else 'a'} {name}"
                 for name, n in (("image", self.images), ("audio clip", self.audio), ("PDF", self.pdfs), ("file", self.other_files))
                 if n]
        return " and ".join(", ".join(words[:-1]) and [", ".join(words[:-1]), words[-1]] or words)


def _is_pdf(part: dict[str, Any]) -> bool:
    file = part.get("file") or part
    name = str(file.get("filename", "")).lower()
    data = str(file.get("file_data", "") or file.get("file_url", ""))
    return name.endswith(".pdf") or data.startswith("data:application/pdf") or data.lower().endswith(".pdf")


def detect(content: Any, text: str = "") -> Inputs:
    """Count the images, audio and files in a message's ``content`` and notice pasted code in its text."""
    found = Inputs(code=bool(_CODE_BLOCK.search(text or "")))
    if not isinstance(content, list):
        return found
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind in IMAGE_PARTS:
            found.images += 1
        elif kind in AUDIO_PARTS:
            found.audio += 1
        elif kind in FILE_PARTS:
            if _is_pdf(part):
                found.pdfs += 1
            else:
                found.other_files += 1
    if found.images or found.audio or found.pdfs or found.other_files:
        found.parts = [p for p in content if isinstance(p, dict)]
    return found


def looks_private(text: str) -> str:
    """Return what makes ``text`` look private (a short label), or "" when nothing does."""
    match = _PRIVATE.search(text or "")
    if not match:
        return ""
    value = match.group(0).lower()
    if value.startswith(("sk-", "akia", "gh", "xox")):
        return "an API key or token"
    if "private key" in value:
        return "a private key"
    if re.fullmatch(r"\d{3}-\d{2}-\d{4}", value):
        return "an ID number"
    if re.fullmatch(r"(?:\d[ -]?){13,16}", value):
        return "a card-like number"
    return f'the word "{match.group(0)}"'


def to_anthropic(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn OpenAI-style content parts into Anthropic content blocks. Audio is refused (Anthropic doesn't take it)."""
    out: list[dict[str, Any]] = []
    for part in parts:
        kind = part.get("type")
        if kind in (None, "text", "input_text"):
            out.append({"type": "text", "text": str(part.get("text", ""))})
        elif kind in IMAGE_PARTS:
            url = part.get("image_url")
            url = url.get("url", "") if isinstance(url, dict) else str(url or "")
            out.append({"type": "image", "source": _source(url, "image/png")})
        elif kind in FILE_PARTS and _is_pdf(part):
            file = part.get("file") or part
            out.append({"type": "document", "source": _source(str(file.get("file_data", "") or file.get("file_url", "")),
                                                               "application/pdf")})
        elif kind in AUDIO_PARTS:
            raise ValueError("Anthropic models don't take audio")
        else:
            raise ValueError(f"Anthropic models don't take {kind} parts")
    return out


def _source(url: str, default_type: str) -> dict[str, str]:
    match = re.match(r"data:([^;,]+)?(;base64)?,(.*)", url, re.S)
    if match:
        return {"type": "base64", "media_type": match.group(1) or default_type, "data": match.group(3)}
    return {"type": "url", "url": url}


def text_of(content: Any) -> str:
    """Return the text in a message's content, whether a string or a list of parts."""
    if isinstance(content, list):
        return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") in (None, "text", "input_text"))
    return str(content or "")


__all__ = ["Inputs", "detect", "looks_private", "text_of", "to_anthropic"]
