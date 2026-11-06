"""Text normalisation helpers: HTML to text, salary parsing, title/company cleanup.

Everything here is pure (no I/O) so it is cheap to unit test and safe to call from any
pipeline stage.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser

__all__ = [
    "SalaryParse",
    "annualize",
    "clean_company",
    "clean_title",
    "html_to_text",
    "parse_salary_text",
]

# --------------------------------------------------------------------------------------
# Shared text helpers
# --------------------------------------------------------------------------------------

_ZERO_WIDTH_RE = re.compile("[​-‍⁠﻿]")
_WS_RE = re.compile(r"\s+")


def _fix_mojibake(text: str) -> str:
    """Repair UTF-8 text that was wrongly decoded as latin-1 (e.g. "â\\x80\\x94" -> "—").

    Only applies when the round trip succeeds, so genuine accented text is left alone.
    """
    if not re.search("[ÂÃâ]", text):
        return text
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return fixed


def _unescape(text: str) -> str:
    """Unescape HTML entities, up to twice (feeds sometimes double-escape)."""
    for _ in range(2):
        new = html.unescape(text)
        if new == text:
            break
        text = new
    return text


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", _ZERO_WIDTH_RE.sub("", text)).strip()


# --------------------------------------------------------------------------------------
# HTML -> text
# --------------------------------------------------------------------------------------

_ESCAPED_TAG_RE = re.compile(r"&lt;\s*/?\s*[a-zA-Z]")
_REAL_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z]")

_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "iframe", "head", "svg", "object", "embed"}
)
# Tags that separate paragraphs (blank line before and after).
_PARAGRAPH_TAGS = frozenset(
    {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "pre", "hr"}
)
# Tags that only force a line break before and after.
_LINE_TAGS = frozenset(
    {
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "figure",
        "figcaption",
        "form",
        "fieldset",
        "dl",
        "dt",
        "dd",
        "address",
        "tr",
        "caption",
        "thead",
        "tbody",
        "tfoot",
    }
)
_MAX_DEPTH = 200

# Inline images: "data:image/png;base64,AAAA..." URIs, plus any whitespace-free run of 200+
# base64-alphabet characters (a blob pasted as raw text or split off its data: prefix).
_DATA_URI_RE = re.compile(r"data:[\w/+.\-]*;base64,[A-Za-z0-9+/=_\-]*", re.IGNORECASE)
_BASE64_RUN_RE = re.compile(r"[A-Za-z0-9+/=]{200,}")


def _strip_blobs(text: str) -> str:
    """Remove base64 data URIs and long base64-looking runs."""
    return _BASE64_RUN_RE.sub(" ", _DATA_URI_RE.sub(" ", text))


def _looks_entity_escaped(raw: str) -> bool:
    """True when the markup itself is escaped ("&lt;div&gt;...", as Arbeitnow ships it).

    Arbeitnow appends a real-markup footer to escaped bodies, so the decision is by majority:
    escaped tags must outnumber real tags.
    """
    escaped = len(_ESCAPED_TAG_RE.findall(raw))
    return escaped > 0 and escaped > len(_REAL_TAG_RE.findall(raw))


def _render(node, parts: list[str], depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        parts.append(node.text(deep=True, separator=" "))
        return
    for child in node.iter(include_text=True):
        tag = child.tag
        if tag == "-text":
            text = child.text(deep=False) or ""
            parts.append(_collapse_inline(text))
            continue
        if not tag or tag.startswith("-"):  # comments, doctype, ...
            continue
        if tag in _SKIP_TAGS:
            continue
        if tag == "br":
            parts.append("\n")
        elif tag == "li":
            inner: list[str] = []
            _render(child, inner, depth + 1)
            body = re.sub(r"[ \t]*\n[ \t]*", "\n", "".join(inner))
            body = re.sub(r"\n{2,}", "\n", body).strip()
            if body:
                parts.append("\n" + (body if body.startswith("- ") else "- " + body))
        elif tag in _PARAGRAPH_TAGS:
            parts.append("\n\n")
            _render(child, parts, depth + 1)
            parts.append("\n\n")
        elif tag in _LINE_TAGS:
            parts.append("\n")
            _render(child, parts, depth + 1)
            parts.append("\n")
        elif tag in {"td", "th"}:
            _render(child, parts, depth + 1)
            parts.append(" ")
        else:
            _render(child, parts, depth + 1)


def _collapse_inline(text: str) -> str:
    """Collapse whitespace inside a text node the way a browser would (keeps edge spaces)."""
    return _WS_RE.sub(" ", _ZERO_WIDTH_RE.sub("", text))


def html_to_text(html_str: str | None) -> str:
    """Convert (possibly entity-escaped) HTML into readable plain text.

    * Entity-escaped markup ("&lt;p&gt;...") is unescaped first, but only when escaped tags
      outnumber real tags, so literal code samples in normal HTML are preserved.
    * ``script``/``style`` (and similar) content is dropped.
    * Paragraphs and headings are separated by a blank line, ``br``/``div`` by a newline,
      and list items become lines prefixed with ``"- "``.
    * Runs of spaces and blank lines are collapsed and the result is stripped.

    Returns ``""`` for ``None`` or empty input.
    """
    if not html_str or not isinstance(html_str, str):
        return ""
    raw = html_str
    if _looks_entity_escaped(raw):
        raw = _unescape(raw)
    raw = _strip_blobs(_fix_mojibake(raw))
    if not raw.strip():
        return ""

    tree = LexborHTMLParser(raw)
    body = tree.body
    if body is None:
        return _collapse_ws(raw)
    parts: list[str] = []
    try:
        _render(body, parts)
    except RecursionError:  # pathological nesting: fall back to flat text
        parts = [body.text(deep=True, separator="\n")]
    text = "".join(parts)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", _strip_blobs(text))
    return text.strip()


# --------------------------------------------------------------------------------------
# Salary parsing
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SalaryParse:
    """Result of :func:`parse_salary_text`.

    ``min``/``max`` are plain numbers in ``currency`` per ``period`` (not annualised).
    ``currency`` is an ISO 4217 code or ``None`` when the text has no currency marker.
    ``period`` is ``"hour"``, ``"month"`` or ``"year"`` (always set on a successful parse).
    """

    min: float | None
    max: float | None
    currency: str | None
    period: str | None


_SYMBOL_CURRENCY = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "¥": "JPY",
    "₪": "ILS",
    "₩": "KRW",
}
_PREFIXED_DOLLAR = {
    "CA": "CAD",
    "C": "CAD",
    "AU": "AUD",
    "A": "AUD",
    "NZ": "NZD",
    "US": "USD",
    "S": "SGD",
    "HK": "HKD",
    "R": "BRL",
}
_WORD_CURRENCY = {"dollar": "USD", "dollars": "USD", "euro": "EUR", "euros": "EUR", "pounds": "GBP"}
_CODE_WORDS = (
    "USD EUR GBP CAD AUD NZD INR CHF SEK NOK DKK PLN CZK HUF RON BGN BRL MXN ARS JPY CNY SGD "
    "HKD ZAR AED ILS KRW THB"
)
_CODES = frozenset(_CODE_WORDS.split())
# Codes safe to recognise in any case ("80-100k eur"); the rest must be upper case.
_ANYCASE_CODES = frozenset(_CODE_WORDS.split()[:8])  # USD .. CHF

_CURRENCY_RE = re.compile(
    r"\b(?P<prefix>CA|C|AU|A|NZ|US|S|HK|R)\$"
    r"|(?P<sym>[$€£₹¥₪₩])"
    r"|(?<![A-Za-z])(?P<code>[A-Za-z]{3})(?![A-Za-z])"
    r"|\b(?P<word>dollars?|euros?|pounds)\b",
    re.IGNORECASE,
)


def _detect_currency(text: str) -> str | None:
    for m in _CURRENCY_RE.finditer(text):
        if m.group("prefix"):
            return _PREFIXED_DOLLAR[m.group("prefix").upper()]
        if m.group("sym"):
            return _SYMBOL_CURRENCY[m.group("sym")]
        if m.group("code"):
            tok = m.group("code")
            if tok.upper() in _ANYCASE_CODES or tok in _CODES:
                return tok.upper()
            continue
        if m.group("word"):
            return _WORD_CURRENCY[m.group("word").lower()]
    return None


_NUM_RE = re.compile(
    r"(?<![\d.,])"
    r"(?P<num>\d{1,2}(?:,\d{2})+,\d{3}|\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?)"
    r"(?P<k>\s?[kK](?![A-Za-z]))?"
)
_NOT_SALARY_AFTER_RE = re.compile(r"\s*(?:%|years\b|yrs\b|weeks\b|days\b|hours\b|months\b)", re.I)
_NOT_SALARY_BEFORE_RE = re.compile(r"(?:\+|\b(?:v|version|top|iso|ios)\s?)$", re.I)

_PERIOD_RE = re.compile(
    r"\b(?P<hour>hours?|hrs?|hourly|stunde|std|uur)\b"
    r"|\b(?P<month>months?|mos?|mth|monthly|monat|monatlich|maand)\b"
    r"|\b(?P<year>years?|yrs?|yearly|annual(?:ly)?|annum|jahr|jährlich|jaar|jaarlijks)\b"
    r"|(?P<pa>\bp\.a\b|/\s*pa\b)",
    re.IGNORECASE,
)
# Piece-rate or short-interval pay cannot be annualised sensibly, so such text is rejected.
_UNSUPPORTED_PERIOD_RE = re.compile(
    r"(?:\bper\s+|/\s*|\ba\s+)"
    r"(?:task|project|word|article|post|piece|video|page|day|week|wk|item|lead|sale|call|"
    r"delivery|order|session|class|lesson|shift|gig|unit|click|hit)s?\b"
    r"|\b(?:daily|weekly|biweekly|bi-weekly|per\s+diem|commission[- ]only)\b",
    re.IGNORECASE,
)

_RANGE_DASHES = {"-", "–", "—", "‒", "−", "~", "to", "bis", "and", "und", "à"}
_GAP_STRIP_RE = re.compile(
    r"per|hours?|hrs?|months?|mos?|years?|yrs?|annum|monthly|yearly|hourly|"
    r"usd|eur|gbp|cad|aud|nzd|inr|chf|sek|nok|dkk|pln|czk|brl|mxn|jpy|cnys?|sgd|hkd|zar|aed"
)

_MAX_SANE = 50_000_000.0


def _parse_number(num: str, has_k: bool) -> float | None:
    """Parse a number token handling US/EU separators and the "k" suffix.

    "35,3k" -> 35300 (decimal comma before k); "60.000" -> 60000 (EU thousands dot);
    "1.234,56" -> 1234.56; "50,000" -> 50000; "3.5" -> 3.5.
    """
    has_dot, has_comma = "." in num, "," in num
    if has_dot and has_comma:
        dec = "." if num.rfind(".") > num.rfind(",") else ","
        thou = "," if dec == "." else "."
        cleaned = num.replace(thou, "").replace(dec, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        parts = num.split(sep)
        if len(parts) > 2:
            cleaned = "".join(parts)
        else:
            head, tail = parts
            if len(tail) == 3 and not has_k and head != "0":
                cleaned = head + tail
            else:
                cleaned = head + "." + tail
    else:
        cleaned = num
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value * 1000 if has_k else value


@dataclass
class _Amount:
    start: int
    end: int
    value: float
    has_k: bool
    raw: str


def _find_amounts(text: str) -> list[_Amount]:
    amounts: list[_Amount] = []
    for m in _NUM_RE.finditer(text):
        if _NOT_SALARY_AFTER_RE.match(text, m.end()):
            continue
        head = text[: m.start()]
        if _NOT_SALARY_BEFORE_RE.search(head):
            continue
        if head[-1:].isalpha() and head[-3:].upper() not in _CODES:
            continue  # glued to a word ("h264"), not to a currency code ("USD120k")
        has_k = bool(m.group("k"))
        value = _parse_number(m.group("num"), has_k)
        if value is None:
            continue
        amounts.append(_Amount(m.start(), m.end(), value, has_k, m.group("num")))
    return amounts


def _is_range_gap(gap: str) -> bool:
    letters = re.sub(r"[^a-zA-Z\-–—‒−~à]", "", gap).lower()
    letters = _GAP_STRIP_RE.sub("", letters)
    return letters in _RANGE_DASHES


_MIN_ONLY_PREFIX_RE = re.compile(
    r"(?:\bfrom|\bstarting(?:\s+at)?|\bat\s+least|\bminimum|\bmin|\bover|\babove|"
    r"\bmore\s+than|\bab)\b\W*[^\d]{0,4}$",
    re.IGNORECASE,
)
_MAX_ONLY_PREFIX_RE = re.compile(
    r"(?:\bup\s*to|\bupto|\bmax(?:imum)?|\bbis\s+zu|\bbis|\bnot\s+more\s+than|\bunder|\bbelow)"
    r"\b\W*[^\d]{0,4}$",
    re.IGNORECASE,
)


def _infer_period(reference: float) -> str:
    """Guess the pay period from magnitude: < 300 hour, < 20000 month, otherwise year."""
    if reference < 300:
        return "hour"
    if reference < 20000:
        return "month"
    return "year"


def parse_salary_text(text: str | None) -> SalaryParse | None:
    """Parse free-text salary strings such as "$20k -$35k" or "€60.000–80.000".

    Returns ``None`` when nothing salary-like is found ("Competitive", "DOE", "$1000 per
    task", bare small numbers with no currency or period, percentages).

    Conventions:

    * Only the first amount or the first amount pair (range) is used.
    * A single value gives ``min == max``; "120k+" / "from X" gives ``min`` only;
      "up to X" gives ``max`` only.
    * ``min``/``max`` are swapped when written in reverse order.
    * ``k``/``K`` multiplies by 1000; if only the upper end carries it ("80-100k"), the
      lower end inherits it.
    * Period comes from words (hour/hr/hourly, month/mo/monthly, year/yr/annual/p.a.,
      plus a few German/Dutch words). When no period is stated it is **inferred from the
      magnitude of the larger value: < 300 -> hour, < 20000 -> month, otherwise year**.
      Day/week/per-task rates are not supported and return ``None``.
    * Currency comes from symbols (``$``, ``€``, ``£``, ``₹``) or ISO codes; ``C$``/``A$``
      map to CAD/AUD. It is ``None`` when the text has no currency marker.
    """
    if not text or not isinstance(text, str):
        return None
    s = _fix_mojibake(_unescape(text))
    s = _collapse_ws(s)
    if not s or not re.search(r"\d", s):
        return None
    s = re.sub(r"\b401\s?\(?k\)?", " ", s, flags=re.IGNORECASE)
    if _UNSUPPORTED_PERIOD_RE.search(s):
        return None

    amounts = _find_amounts(s)
    if not amounts:
        return None
    first = amounts[0]
    second: _Amount | None = None
    for cand in amounts[1:]:
        if _is_range_gap(s[first.end : cand.start]):
            second = cand
        break

    v1, v2 = first.value, second.value if second else None
    # "80-100k": the unit on the upper bound applies to the lower bound too.
    if second and second.has_k and not first.has_k and first.value < 1000 <= second.value:
        v1 = first.value * 1000

    lo: float | None
    hi: float | None
    if v2 is not None:
        lo, hi = (v1, v2) if v1 <= v2 else (v2, v1)
    else:
        before = s[: first.start]
        after = s[first.end : first.end + 1]
        if _MAX_ONLY_PREFIX_RE.search(before):
            lo, hi = None, v1
        elif after == "+" or _MIN_ONLY_PREFIX_RE.search(before):
            lo, hi = v1, None
        else:
            lo, hi = v1, v1

    values = [v for v in (lo, hi) if v is not None]
    if not values or any(v <= 0 or v > _MAX_SANE for v in values):
        return None

    currency = _detect_currency(s)
    period_match = _PERIOD_RE.search(s, first.start) or _PERIOD_RE.search(s)
    period: str | None = None
    if period_match:
        for name in ("hour", "month", "year"):
            if period_match.group(name):
                period = name
                break
        else:
            period = "year"  # p.a.

    has_k = first.has_k or (second is not None and second.has_k)
    if currency is None and period is None and not has_k and max(values) < 1000:
        return None
    if period is None:
        period = _infer_period(max(values))
    return SalaryParse(min=lo, max=hi, currency=currency, period=period)


_PERIOD_ALIASES = {
    "year": "year",
    "yearly": "year",
    "annual": "year",
    "annually": "year",
    "yr": "year",
    "month": "month",
    "monthly": "month",
    "mo": "month",
    "hour": "hour",
    "hourly": "hour",
    "hr": "hour",
}
_HOURS_PER_YEAR = 2080


def annualize(amount: float | None, period: str | None) -> float | None:
    """Convert a pay amount to a yearly amount.

    ``hour`` -> x 2080 (40h x 52w), ``month`` -> x 12, ``year`` -> x 1. A ``None`` period is
    treated as ``year``. Common spellings ("yearly", "hourly", "monthly") are accepted.
    ``None`` amounts and unknown periods ("week", "day") return ``None``.
    """
    if amount is None:
        return None
    if period is None:
        return float(amount)
    key = _PERIOD_ALIASES.get(period.strip().lower())
    if key == "hour":
        return float(amount) * _HOURS_PER_YEAR
    if key == "month":
        return float(amount) * 12
    if key == "year":
        return float(amount)
    return None


# --------------------------------------------------------------------------------------
# Title / company cleanup
# --------------------------------------------------------------------------------------

_GENDER_TOKEN = r"(?:[mwfdxhi*]|divers[e]?|non-?binary|nb|gn)"
_GENDER_GROUP = rf"{_GENDER_TOKEN}(?:\s*[/|\\]\s*{_GENDER_TOKEN}){{1,3}}"
_GENDER_WORDS = r"(?:all|alle|any)\s+(?:gender|genders|geschlechter)|gender[- ]?neutral"
_BRACKETED_GENDER_RE = re.compile(
    rf"[(\[{{]\s*(?:{_GENDER_GROUP}|{_GENDER_WORDS}|gn)\s*\*?\s*[)\]}}]",
    re.IGNORECASE,
)
# Unbracketed markers only at the very end ("... Hydrogéologue F/H", "... Entwickler m/w/d").
_TRAILING_GENDER_RE = re.compile(
    r"(?:^|[\s,;:\-–—|])(?:[mwfdxh](?:\s*/\s*[mwfdxh]){1,2})\s*\*?\s*$",
    re.IGNORECASE,
)
_EMPTY_BRACKETS_RE = re.compile(r"[(\[{]\s*[)\]}]")
_EDGE_SEPARATORS = " \t-–—|,:;/·•*_~"


def _strip_edges(text: str) -> str:
    return text.strip(_EDGE_SEPARATORS)


def clean_title(title: str | None) -> str:
    """Tidy a job title.

    Unescapes HTML entities, repairs mojibake, collapses whitespace, removes gender markers
    such as "(m/w/d)", "(f/m/x)", "(all genders)" or a trailing "F/H", and strips stray
    leading/trailing separators and asterisks. Casing is left untouched.
    """
    if not title or not isinstance(title, str):
        return ""
    s = _collapse_ws(_fix_mojibake(_unescape(title)))
    s = _BRACKETED_GENDER_RE.sub(" ", s)
    s = _EMPTY_BRACKETS_RE.sub(" ", s)
    s = _collapse_ws(s)
    s = _strip_edges(s)
    s = _collapse_ws(_TRAILING_GENDER_RE.sub(" ", s))
    s = _strip_edges(s)
    return s


def clean_company(name: str | None) -> str:
    """Trim a company name, unescape entities, repair mojibake and collapse whitespace."""
    if not name or not isinstance(name, str):
        return ""
    return _collapse_ws(_fix_mojibake(_unescape(name)))
