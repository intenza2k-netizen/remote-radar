"""Display names for skills that are not in ``aliases.yaml``.

An unknown skill only has a slug ("meddpicc", "b2b-saas", "business-strategy"), and the
extraction stage stores every skill lower-cased, so the casing the model saw is gone.
It survives in the posting text, though ("MEDDPICC", "B2B SaaS", "CPaaS"). :func:`pick_display`
therefore looks at how the skill is actually written in the descriptions that mention it and
takes the most common spelling when that spelling has real casing (an acronym or an internal
capital); otherwise it falls back to a plain title-cased version of the slug.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping

__all__ = ["find_spellings", "is_distinctive", "pick_display", "spelling_pattern", "titleize"]

_SMALL_WORDS = frozenset(
    {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs"}
)
_WORD_SPLIT = re.compile(r"[\s\-–/]+")
_DIGIT_LETTER = re.compile(r"(?<=\d)[a-z](?![a-z])")  # "b2b" -> "B2B", "k8s" -> "K8S"


def _upper(match: re.Match[str]) -> str:
    return match.group(0).upper()


def titleize(text: str) -> str:
    """Capitalise the first letter of every word, keeping small joining words lower-case
    ("Go to Market Strategy"). A single letter after a digit is capitalised too ("b2b" ->
    "B2B", "s3" -> "S3"); the rest of each word is left alone."""
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    return " ".join(
        w if (i and w.lower() in _SMALL_WORDS) else _DIGIT_LETTER.sub(_upper, w[:1].upper() + w[1:])
        for i, w in enumerate(words)
    )


def is_distinctive(spelling: str) -> bool:
    """True when the spelling carries casing information: an acronym of two or more capital
    letters ("OSINT", "ISO") or a capital inside a word ("CPaaS", "B2B", "iOS", "GraphQL").
    Plain lower-case, "Title Case" and "Sentence case" are not."""
    for word in _WORD_SPLIT.split(spelling):
        letters = [c for c in word if c.isalpha()]
        if len(letters) >= 2 and all(c.isupper() for c in letters):
            return True
        if any(c.isupper() for c in word[1:]):
            return True
    return False


def spelling_pattern(slug: str) -> re.Pattern[str] | None:
    """Case-insensitive pattern for the words of a slug, tolerant of the separator
    ("go-to-market", "go to market", "go/to/market"). ``None`` for slugs without letters."""
    words = [w for w in slug.split("-") if w]
    if not words or not any(c.isalpha() for c in slug):
        return None
    body = r"[\s\-–/]*".join(re.escape(w) for w in words)
    return re.compile(rf"(?<![A-Za-z0-9_-]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def find_spellings(slug: str, texts: Iterable[str]) -> Counter[str]:
    """How the skill is written in ``texts``: exact spelling (whitespace collapsed) -> count."""
    pattern = spelling_pattern(slug)
    found: Counter[str] = Counter()
    if pattern is None:
        return found
    for text in texts:
        for match in pattern.finditer(text):
            found[re.sub(r"\s+", " ", match.group(0))] += 1
    return found


def _capitalise_plain_words(spelling: str) -> str:
    """Capitalise the all-lower-case words of a spelling that has casing elsewhere:
    "AI tools" -> "AI Tools", "enterprise SaaS" -> "Enterprise SaaS". Words that already
    carry casing ("macOS", "SaaS") and small joining words ("of") stay as they are."""
    words = spelling.split(" ")
    return " ".join(
        w if (i and w in _SMALL_WORDS) or w != w.lower() else titleize(w)
        for i, w in enumerate(words)
    )


def pick_display(slug: str, spellings: Mapping[str, int] | None = None) -> str:
    """Display name for an unknown skill.

    The most common spelling in the postings wins when it has distinctive casing; a tie
    between spellings goes to the distinctive one, then alphabetically. Everything else
    (nothing found, or the usual spelling is plain lower/Title case) gives the slug's words
    title-cased."""
    fallback = titleize(slug.replace("_", "-").replace("-", " "))
    if not spellings:
        return fallback
    ranked = sorted(spellings.items(), key=lambda kv: (-kv[1], not is_distinctive(kv[0]), kv[0]))
    top = ranked[0][0]
    return _capitalise_plain_words(top) if is_distinctive(top) else fallback
