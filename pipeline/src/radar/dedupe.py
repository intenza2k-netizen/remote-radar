"""Cross-board job deduplication key.

``dedupe_key`` is designed so the same posting syndicated to several boards collides
("Senior Backend Engineer (m/w/d)" at "Acme GmbH" vs "Senior Backend Engineer - Remote" at
"ACME") while genuinely different roles at one company stay apart.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from radar.normalize import clean_company, clean_title

__all__ = ["dedupe_key", "normalize_company", "normalize_title"]

# Legal-form suffixes, compared after punctuation removal ("s.a." -> "sa", "b.v." -> "bv").
_LEGAL_SUFFIXES = frozenset(
    {
        "gmbh",
        "inc",
        "incorporated",
        "ltd",
        "limited",
        "llc",
        "llp",
        "lp",
        "corp",
        "corporation",
        "company",
        "co",
        "sa",
        "bv",
        "nv",
        "ag",
        "se",
        "kg",
        "ug",
        "ohg",
        "oy",
        "ab",
        "as",
        "plc",
        "srl",
        "sas",
        "sarl",
        "pty",
        "pte",
    }
)
# "as" is a real word, so it is only removed when other tokens remain and it is last.

_LOCATION_WORDS = """
    berlin munich munchen hamburg frankfurt cologne koln dusseldorf stuttgart leipzig dresden
    hannover nuremberg bremen london manchester edinburgh dublin paris lyon marseille toulouse
    madrid barcelona lisbon porto amsterdam rotterdam utrecht brussels antwerp vienna wien zurich
    geneva basel bern copenhagen stockholm oslo helsinki warsaw krakow prague budapest bucharest
    sofia athens rome milan turin tallinn riga vilnius kyiv kiev istanbul tel aviv dubai singapore
    sydney melbourne toronto vancouver montreal ottawa calgary new york nyc boston chicago austin
    seattle denver atlanta miami dallas houston portland san francisco sf los angeles la diego
    jose washington dc mexico city bogota lima santiago buenos aires sao paulo rio bangalore
    bengaluru mumbai delhi hyderabad pune chennai manila jakarta bangkok tokyo seoul
    germany deutschland france spain portugal italy netherlands holland belgium austria
    switzerland denmark sweden norway finland poland czechia czech republic hungary romania
    bulgaria greece ireland uk united kingdom england scotland wales britain usa us united states
    america canada mexico brazil argentina chile colombia india australia new zealand nz japan
    korea singapore israel turkey ukraine estonia latvia lithuania serbia croatia
    europe european eu emea apac latam dach nordics nordic anz americas na north south east west
    central western eastern southern northern worldwide anywhere global remote
"""
_LOCATIONS = frozenset(_LOCATION_WORDS.split())
# "global" and "remote" appear here only so they can be chained ("Remote - Europe");
# location stripping requires at least one real place, see _strip_location_tail.
_PLACE_WORDS = _LOCATIONS - {"global", "remote", "north", "south", "east", "west", "central"}

_REMOTE_PAREN_RE = re.compile(r"[(\[{][^)\]}]*\bremote\b[^)\]}]*[)\]}]")
_REMOTE_WORD_RE = re.compile(
    r"\b(?:100\s?%\s*|fully\s+|totally\s+)?remote(?:ly)?(?:[- ]first)?"
    r"(?!\s+(?:sensing|access|control))\b|\bwork\s+from\s+home\b|\bwfh\b|\bhome\s?-?office\b|\btelecommut\w*\b",
    re.IGNORECASE,
)
_COMPOUND_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(front|back)[\s-]+end\b"), r"\1end"),
    (re.compile(r"\bfull[\s-]+stack\b"), "fullstack"),
    (re.compile(r"\be[\s-]+commerce\b"), "ecommerce"),
    (re.compile(r"\bdev[\s-]+ops\b"), "devops"),
    (re.compile(r"\bsr\b"), "senior"),
    (re.compile(r"\bjr\b"), "junior"),
    (re.compile(r"\bsnr\b"), "senior"),
]
_NON_WORD_RE = re.compile(r"[^\w+#]+")
_WS_RE = re.compile(r"\s+")


def _fold(text: str) -> str:
    """Lowercase, fold accents (é -> e, ß -> ss) and unify dash/space variants."""
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_company(company: str | None) -> str:
    """Normalised company name: lowercase, no accents/punctuation, no legal suffix."""
    text = _fold(clean_company(company))
    text = text.replace("&", " ")
    text = re.sub(r"[.'’`]", "", text)  # "s.a." -> "sa", "o'brien" -> "obrien"
    text = _NON_WORD_RE.sub(" ", text)
    tokens = _WS_RE.sub(" ", text).strip().split(" ")
    tokens = [t for t in tokens if t and t != "and"]
    if tokens and tokens[0] == "the" and len(tokens) > 1:
        tokens = tokens[1:]
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _is_location_phrase(phrase: str) -> bool:
    words = [w for w in re.split(r"[\s,/&+-]+", phrase.strip()) if w and w != "and"]
    if not words or not all(w in _LOCATIONS for w in words):
        return False
    return any(w in _PLACE_WORDS for w in words)


_PAREN_RE = re.compile(r"\s*[(\[]([^()\[\]]*)[)\]]")
_TAIL_SEP_RE = re.compile(
    r"^(.*\S)\s*(?:[-–—|,:/@]|\bin\b|\bbased\s+in\b|\bat\b)\s*([^-–—|,:/@]+)$"
)


def _strip_location_tail(title: str) -> str:
    """Drop trailing location markers: "- Berlin", "| London", "(France)", "in Germany"."""
    prev = None
    while prev != title:
        prev = title
        for pm in _PAREN_RE.finditer(title):
            if pm.end() == len(title) and _is_location_phrase(pm.group(1)):
                title = title[: pm.start()].rstrip()
                break
        sm = _TAIL_SEP_RE.match(title)
        if sm and _is_location_phrase(sm.group(2)):
            title = sm.group(1).rstrip()
    return title


def normalize_title(title: str | None) -> str:
    """Normalised job title used for deduplication (see module docstring)."""
    text = _fold(clean_title(title))
    text = _REMOTE_PAREN_RE.sub(" ", text)
    text = _REMOTE_WORD_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip(" -–—|,:;/")
    text = _strip_location_tail(text)
    text = text.replace("&", " ")
    text = re.sub(r"[.'’`]", "", text)
    for pattern, repl in _COMPOUND_RULES:
        text = pattern.sub(repl, text)
    text = _NON_WORD_RE.sub(" ", text)
    return " ".join(t for t in text.split() if t != "and")


def dedupe_key(company: str, title: str) -> str:
    """40-char sha1 hex of ``normalised company | normalised title``.

    Normalisation (both parts): lowercase, accent folding, HTML entities, whitespace.
    Company: legal suffixes (GmbH, Inc, Ltd, LLC, Corp, S.A., B.V., AG, Oy, AB, PLC, Co ...)
    and punctuation are dropped. Title: gender markers (m/w/d), "remote" markers ("-
    Remote", "(Remote)"), trailing location tails ("- Berlin", "| London", "(France)"),
    punctuation and front-end/back-end/full-stack spelling variants are normalised; "Sr."
    and "Jr." expand to senior/junior. Seniority itself is kept, as are ``+`` and ``#`` so
    "C++" and "C#" roles remain distinct.
    """
    payload = f"{normalize_company(company)}|{normalize_title(title)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
