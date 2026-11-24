"""Text cleaning helpers shared by the extractor and analysis services."""

from __future__ import annotations

import re
from collections.abc import Iterable

_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_whitespace(text: str) -> str:
    text = _CONTROL_RE.sub(" ", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _MULTI_NEWLINE_RE.sub("\n\n", text).strip()


def dedupe_preserve_order(items: Iterable[str], *, min_length: int = 1) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in items:
        item = clean_whitespace(raw)
        if len(item) < min_length:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def truncate_text(text: str, max_chars: int, suffix: str = "\n\n[Content truncated]") -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    budget = max(1, max_chars - len(suffix))
    candidate = text[:budget]
    # Prefer a sentence or word boundary near the end.
    boundary = max(candidate.rfind(". "), candidate.rfind("! "), candidate.rfind("? "))
    if boundary >= int(budget * 0.6):
        candidate = candidate[: boundary + 1]
    else:
        space = candidate.rfind(" ")
        if space >= int(budget * 0.8):
            candidate = candidate[:space]
    return candidate.rstrip() + suffix


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def compact(value: str | None, limit: int = 500) -> str | None:
    if value is None:
        return None
    cleaned = clean_whitespace(value)
    if not cleaned:
        return None
    return truncate_text(cleaned, limit, suffix="")
