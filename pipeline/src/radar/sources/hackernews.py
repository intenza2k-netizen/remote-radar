"""Hacker News "Ask HN: Who is hiring?" monthly threads (via the Algolia HN API).

Every top-level comment in the thread is one hiring post written as free text. By
convention the first line looks like ``Company | Role(s) | Location | REMOTE | Salary |
Full-time`` but the separators (``|``, spaced dashes, bullets) and the field order vary
and about one post in ten ignores the convention altogether.

What this adapter does, and what it deliberately does not do:

* **Fetching.** One search request finds the monthly threads posted by the
  ``whoishiring`` account; one item request per chosen thread returns the whole comment
  tree, of which only the top-level ``children`` (direct replies to the story) are used.
  The latest thread is always fetched, plus the previous month's while the latest is
  younger than ``PREVIOUS_THREAD_IF_YOUNGER_THAN_DAYS`` days (so early-month runs are not
  thin). Replies to hiring posts are dropped, and so are comments without text.
* **Remote filter.** A post is kept only if the first line says REMOTE and does not
  negate it ("no remote", "ONSITE (part remote)", ...); see :func:`looks_remote`.
* **Header parsing.** :func:`parse_first_line` is a heuristic over the first line only.
  It extracts company, title, location, salary text and employment type when the post
  follows the convention, and degrades to ``None`` / a generic title when it does not.
  It is not a general NLP parser and it is wrong on some posts: for example a post that
  puts the location before the company can look like it has no title. Everything else
  (skills, seniority, real salary numbers, per-role detail) is left to the downstream
  LLM extractor, which sees the full comment text in ``description_html``.
* **Several roles in one post** stay one job. When the first line lists more than one
  role the title becomes ``"Multiple roles: <role>, <role>, <role>, ..."`` (at most three
  roles are named); when it names none the title is the generic ``"Multiple roles"``.
  That is a statement about the post, not a verified count of openings.

The payload is the comment object as returned by the API with its nested ``children``
(replies to the post) removed, so a stored payload stays small.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx

from radar.sources.base import (
    JobFields,
    SourceJob,
    as_str,
    clean_text,
    dedupe_jobs,
    get_json,
    parse_datetime,
)

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"
POST_URL = "https://news.ycombinator.com/item?id={id}"

SEARCH_HITS = 10
# The same account posts "Who wants to be hired?" and "Freelancer?" threads; only titles
# starting with this (case-insensitive) are hiring threads.
THREAD_TITLE_PREFIX = "ask hn: who is hiring?"
# Also fetch the previous month's thread while the latest one is younger than this.
PREVIOUS_THREAD_IF_YOUNGER_THAN_DAYS = 10
# Only this much of the first line is inspected for REMOTE.
REMOTE_WINDOW_CHARS = 300
# Titles name at most this many roles in a "Multiple roles: ..." title.
MAX_ROLES_IN_TITLE = 3
GENERIC_TITLE = "Multiple roles"

# ------------------------------------------------------------------ first-line extraction

_BREAK = re.compile(r"<p\b[^>]*>|</p>|<br\s*/?>|\r|\n", re.I)
_TAG = re.compile(r"<[^>]*>")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_BARE_DOMAIN = re.compile(
    r"^[\w-]+(?:\.[\w-]+)*\.(?:com|io|ai|co|dev|org|net|app|so|xyz|tech|cloud|eu|de|uk|nl|fr"
    r"|me|sh|gg|jp|us|ch|se|pl)(?:/\S*)?$",
    re.I,
)
_PAREN = re.compile(r"\([^)]*(?:\)|$)")
_EMPTY_PARENS = re.compile(r"\(\s*\)")


def first_line(text_html: Any) -> str:
    """The first non-empty line of an HN comment as plain text.

    HN comment text is HTML with ``<p>`` between paragraphs. Tags are dropped, entities
    unescaped and whitespace collapsed. A comment starting with ``<p>`` skips the empty
    first paragraph.
    """
    if not isinstance(text_html, str):
        return ""
    for chunk in _BREAK.split(text_html):
        line = clean_text(_TAG.sub("", chunk))
        if line:
            return line
    return ""


# ------------------------------------------------------------------------- remote filter

_REMOTE = re.compile(r"\bremote\b(?!\.(?:com|io|co|ai|so)\b)", re.I)
# Phrases that say the opposite of remote; removed before looking for REMOTE.
_NOT_REMOTE = re.compile(
    r"\b(?:no|not|non|never|without)[\s-]+(?:fully[\s-]+|100%[\s-]+)?remote\b"
    r"|\bremote(?:\s+work)?\s+(?:is\s+)?(?:not|isn'?t|unavailable)\b"
    r"|\bpart(?:ly|ially)?[\s+-]+remote\b",
    re.I,
)


def looks_remote(line: str, limit: int = REMOTE_WINDOW_CHARS) -> bool:
    """True if the first ``limit`` characters of ``line`` say the job is remote.

    URLs are ignored ("remote-first.com"), explicit negations are removed first ("no
    remote", "not remote", "remote not possible", "ONSITE (part remote)"), and a company
    called ``Remote.com`` does not count. "ONSITE or REMOTE (US)" counts as remote.
    """
    head = _URL.sub(" ", line or "")[:limit]
    head = _NOT_REMOTE.sub(" ", head)
    return bool(_REMOTE.search(head))


# --------------------------------------------------------------------- first-line parsing

_SALARY = re.compile(
    r"[$€£¥]\s?\d|\d\s?[$€£¥]|\b\d[\d.,]*\s?k\b|\b\d{2,3}[.,]\d{3}\b"
    r"|\b(?:usd|eur|gbp|cad|aud|chf|sek|pln|inr)\s?\d"
    r"|\d[\d.,]*\s?(?:usd|eur|gbp|cad|aud|chf|sek|pln|inr)\b",
    re.I,
)
_NOT_SALARY = re.compile(
    r"signing|relocat|raised|funding|funded|series\s+[a-z]\b|valuation|revenue|\barr\b"
    r"|\busers\b|customers|employees|\bthe\b|\bbut\b",
    re.I,
)
# "70k - 100k", "$55 - $75/hr": the spaced dash inside a number range must survive the
# dash-separator split.
_RANGE_DASH = re.compile(r"(?<=[\dkKmM])\s+[-–—]\s+(?=[$€£¥]?\d)")
_RANGE_MARK = "\x00"

_ROLE_WORDS = re.compile(
    r"\b(?:engineers?|engineering|eng|developers?|programmers?|analysts?|scientists?"
    r"|managers?|designers?|leads?|heads?|directors?|architects?|administrators?|admins?"
    r"|sysadmins?|devops|sres?|swe|sdet|qa|consultants?|researchers?|specialists?|officers?"
    r"|recruiters?|writers?|sales|marketers?|marketing|technicians?|phd|postdoc|professors?"
    r"|founders?|founding|cto|ceo|cio|ciso|coo|cfo|vp|csms?|pms?|mts|executives?"
    r"|representatives?|accountants?|counsel|attorneys?|strategists?|editors?|producers?"
    r"|coordinators?|generalists?|evangelists?|advocates?|support|staff)\b",
    re.I,
)
_SENTENCE = re.compile(
    r"\b(?:is|are|was|were|we|our|you|your|us|they|their|that|which|who|looking|building"
    r"|hiring|seeking|makes?|provides?)\b",
    re.I,
)
_GENERIC_ROLES = re.compile(
    r"^\W*(?:multiple|various|several|many|all|open)\b.*\b(?:roles?|positions?|openings?|jobs?)\b",
    re.I,
)
_MODE = re.compile(r"\b(?:remote|hybrid|on-?\s?site|in-?\s?office|in-?\s?person)\b", re.I)
_MODE_ONLY = {
    "remote",
    "hybrid",
    "onsite",
    "on-site",
    "on site",
    "in office",
    "in-office",
    "in person",
    "in-person",
    "fully remote",
    "100% remote",
}
_EMPLOYMENT = re.compile(
    r"(?P<ft>full[\s-]?time)|(?P<pt>part[\s-]?time)|(?P<ct>\bcontract\b|\bfreelance\b)"
    r"|(?P<in>\binternships?\b)|(?P<pm>\bpermanent\b)",
    re.I,
)
_EMPLOYMENT_LABELS = {
    "ft": "Full-time",
    "pt": "Part-time",
    "ct": "Contract",
    "in": "Internship",
    "pm": "Permanent",
}
_EMPLOYMENT_START = re.compile(
    r"^\W*(?:full[\s-]?time|part[\s-]?time|contract|permanent|internship|freelance|hourly)\b",
    re.I,
)
_NOISE = re.compile(
    r"visa|relocat|sponsor|equity|\bapply\b|series\s+[a-z]\b|\bseed\b|\byc\b|y combinator"
    r"|hiring|salary|stealth|founded|funded|backed|\bwe\b|\bour\b|\bis\b|\bare\b|\bgmt\b"
    r"|time\s?zones?|\bpay\b|benefits?|\bstock\b|citizen|authori[sz]|applicants?|resume"
    r"|e-?mail|@|\bprofitable\b|\bpmf\b|\bbonus\b|openings?|speaking|agenc|^\W*no\b",
    re.I,
)
_NOT_COMPANY = re.compile(
    r"^\W*(?:location\s*:|apply\s+(?:here|now|at|via|below)|we(?:'re|’re| are)\b"
    r"|hiring\b|looking\b)",
    re.I,
)
_LEADING_MARKS = re.compile(r"^[\s√✓✔✅☑*•·]+")
_PLACE_TAIL = re.compile(
    r",\s*(?:[A-Z]{2}|USA|US|UK|Canada|Germany|France|Spain|Netherlands|Ireland|Portugal"
    r"|Poland|Sweden|Switzerland|Austria|Italy|India|Australia|Brazil|Singapore|Japan"
    r"|Israel|Estonia|Denmark|Norway|Finland|Belgium|Lithuania|Latvia|Romania|Mexico"
    r"|Argentina|UAE)$"
)
_ROLE_SPLIT = re.compile(r"\s*[,;]\s*|\s+[+&/]\s+|\s+and\s+", re.I)
_SEGMENT_SPLIT = re.compile(r"\s+[-–—]\s+|\s*[•·]\s*")
_PROSE_HIRING = re.compile(r"\bhiring\s+(?:for\s+)?(?:(?:an?|the|several|multiple)\s+)?(.+)", re.I)
_PROSE_STOP = re.compile(r"\s+(?:to|who|that|for|in|across|with|at)\s+|[.!:]", re.I)


@dataclass(frozen=True)
class Header:
    """What :func:`parse_first_line` could read from a post's first line."""

    company: str | None
    title: str
    location: str | None
    salary_text: str | None
    employment_type_text: str | None
    multiple_roles: bool


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _plain(seg: str) -> str:
    """The segment without parenthesised text."""
    return _PAREN.sub("", seg).strip()


def _split_outside_parens(text: str, pattern: re.Pattern[str]) -> list[str]:
    masked = _PAREN.sub(lambda m: "\x01" * len(m.group()), text)
    parts: list[str] = []
    start = 0
    for m in pattern.finditer(masked):
        parts.append(text[start : m.start()])
        start = m.end()
    parts.append(text[start:])
    cleaned = (p.strip(" ,;:") for p in parts)
    return [p for p in cleaned if p]


def _is_salary(seg: str) -> bool:
    return bool(_SALARY.search(seg)) and not _NOT_SALARY.search(seg)


# Words that make a whole field a role but are too weak to count a comma-separated piece as
# its own role ("Founding Growth & Sales Lead" is one role, not two).
_WEAK_ROLE_WORDS = re.compile(r"^(?:founding|staff|sales|marketing|support|engineering)$", re.I)


def _is_piece_role(piece: str) -> bool:
    words = (m.group() for m in _ROLE_WORDS.finditer(_plain(piece)))
    return any(not _WEAK_ROLE_WORDS.match(w) for w in words)


def _is_role(seg: str) -> bool:
    plain = _plain(seg)
    return (
        bool(_ROLE_WORDS.search(plain)) and len(plain.split()) <= 14 and not _SENTENCE.search(plain)
    )


def _is_noise(seg: str) -> bool:
    return bool(_NOISE.search(seg))


def _is_place(seg: str) -> bool:
    text = re.sub(r"^location\s*:\s*", "", seg, flags=re.I)
    return (
        0 < len(text) <= 70
        and len(text.split()) <= 8
        and not re.search(r"\d", text)
        and not _is_noise(text)
        and not _SENTENCE.search(text)
    )


def _clean_company(seg: str) -> str | None:
    name = _PAREN.sub("", seg)
    name = re.sub(r"\s+(?:is|are)\s+(?:currently\s+)?hiring\b.*$", "", name, flags=re.I)
    name = _LEADING_MARKS.sub("", name).strip(" -–—:,;|*")
    if not name or _NOT_COMPANY.match(name) or len(name) > 60 or len(name.split()) > 8:
        return None
    if _is_salary(name):
        return None
    return name


def _segments(line: str) -> list[str]:
    """Split a first line into fields: on ``|`` if used, else on spaced dashes and bullets."""
    text = _RANGE_DASH.sub(f" {_RANGE_MARK} ", line)
    parts = re.split(r"\s*\|+\s*", text)
    if len(parts) < 3:
        parts = [p for part in parts for p in _SEGMENT_SPLIT.split(part)]
    out: list[str] = []
    for index, part in enumerate(parts):
        part = part.replace(_RANGE_MARK, "-")
        part = _EMPTY_PARENS.sub("", _URL.sub("", part))
        part = _LEADING_MARKS.sub("", part).strip(" ,;:|*")
        while part.endswith(")") and part.count(")") > part.count("("):
            part = part[:-1].rstrip()
        if not part:
            continue
        if index > 0 and _BARE_DOMAIN.match(part):
            continue
        out.append(part)
    return out


def _title_from_roles(roles: list[str]) -> str:
    if len(roles) == 1:
        return _cap(roles[0], 150)
    shown = ", ".join(roles[:MAX_ROLES_IN_TITLE])
    suffix = ", …" if len(roles) > MAX_ROLES_IN_TITLE else ""
    return _cap(f"{GENERIC_TITLE}: {shown}{suffix}", 150)


def _prose_roles(line: str) -> list[str]:
    """Roles named in a sentence like ``X is hiring a data engineer and an analyst``."""
    m = _PROSE_HIRING.search(line)
    if not m:
        return []
    tail = _PROSE_STOP.split(m.group(1))[0]
    pieces = _split_outside_parens(tail, _ROLE_SPLIT)
    roles: list[str] = []
    for raw in pieces:
        piece = re.sub(r"^(?:and|or)\s+(?:(?:an?|the)\s+)?", "", raw, flags=re.I)
        if len(_plain(piece).split()) <= 8 and _is_role(piece) and piece not in roles:
            roles.append(piece)
    return roles


def parse_first_line(line: str) -> Header:
    """Heuristically read a post's first line (already plain text, see :func:`first_line`).

    Company is the first field with URLs and parentheses removed (``None`` when that
    field is not a plausible name, e.g. a sentence). Fields that look like a salary, an
    employment type or a role are taken out; what remains and looks like a place, or
    that mentions REMOTE / HYBRID / ONSITE with a qualifier, becomes the location (several
    are joined with ``"; "``). A bare "REMOTE" gives no location.
    """
    segs = _segments(line)
    if not segs:
        return Header(None, GENERIC_TITLE, None, None, None, False)

    company = _clean_company(segs[0])
    if company and "|" not in line and len(segs) > 1 and _is_role(segs[0]):
        company = None  # "Software Engineer - Remote - US only": no company field at all
    rest = segs[1:] if company else segs
    location_first: str | None = None
    # "Cologne, Germany | UMH | Product Engineer": a place in front of the real name.
    if (
        company
        and rest
        and _PLACE_TAIL.search(segs[0])
        and not _is_role(segs[0])
        and not _MODE.search(rest[0])
        and not _is_role(rest[0])
        and not _is_salary(rest[0])
        and not _EMPLOYMENT_START.match(rest[0])
        and len(rest[0].split()) <= 4
        and not re.search(r"[,\d]", rest[0])
    ):
        location_first = segs[0]
        company = _clean_company(rest[0])
        rest = rest[1:]

    roles: list[str] = []
    generic: str | None = None
    salary: str | None = None
    places: list[str] = []
    if location_first:
        places.append(location_first)

    for seg in rest:
        plain = _plain(seg)
        has_mode = bool(_MODE.search(seg))
        short_role = len(plain.split()) <= 6 and "," not in seg and "(" not in seg and _is_role(seg)
        if _GENERIC_ROLES.match(plain):
            if generic is None:
                inner = _PAREN.search(seg)
                detail = inner.group().strip("()").strip() if inner else ""
                generic = f"{GENERIC_TITLE}: {_cap(detail, 100)}" if detail else GENERIC_TITLE
        elif _is_role(seg) and (not has_mode or short_role):
            pieces = _split_outside_parens(seg, _ROLE_SPLIT)
            if sum(1 for p in pieces if _is_piece_role(p)) >= 2:
                roles.extend(p for p in pieces if p not in roles)
            else:
                roles.append(seg)
        elif _is_salary(seg) and len(seg) <= 100:
            if salary is None:
                salary = _cap(seg, 120)
        elif _EMPLOYMENT_START.match(seg):
            continue
        elif has_mode:
            if plain.lower().strip(" ()") in _MODE_ONLY and not _PAREN.search(seg):
                continue
            if len(seg) <= 100:
                places.append(seg)
        elif _is_noise(seg):
            continue
        elif _is_place(seg):
            places.append(re.sub(r"^location\s*:\s*", "", seg, flags=re.I))

    if not roles and generic is None:
        roles = _prose_roles(line)

    multiple = len(roles) > 1 or (not roles and generic is not None)
    if roles:
        title = _title_from_roles(roles)
    elif generic is not None:
        title = generic
    else:
        title = GENERIC_TITLE
        multiple = True

    employment: list[str] = []
    scan = " | ".join(rest) if rest else line
    for m in _EMPLOYMENT.finditer(_URL.sub(" ", scan)):
        label = _EMPLOYMENT_LABELS[m.lastgroup or "ft"]
        if label not in employment:
            employment.append(label)

    unique_places = list(dict.fromkeys(places))
    location = _cap("; ".join(unique_places), 120) if unique_places else None
    return Header(
        company=company,
        title=title,
        location=location,
        salary_text=salary,
        employment_type_text=", ".join(employment) or None,
        multiple_roles=multiple,
    )


# ------------------------------------------------------------------------ thread choosing


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _hit_time(hit: dict) -> datetime:
    return (
        parse_datetime(hit.get("created_at_i"))
        or parse_datetime(hit.get("created_at"))
        or (datetime.min)
    )


def select_threads(hits: list[Any], now: datetime | None = None) -> list[dict]:
    """Pick the hiring threads to fetch from search hits, newest first.

    Only titles starting with "Ask HN: Who is hiring?" count. The latest thread is
    always chosen; the one before it is added when the latest is less than
    ``PREVIOUS_THREAD_IF_YOUNGER_THAN_DAYS`` days old.
    """
    threads = [
        h
        for h in hits
        if isinstance(h, dict)
        and str(h.get("title") or "").strip().lower().startswith(THREAD_TITLE_PREFIX)
        and as_str(h.get("objectID") or h.get("story_id"))
    ]
    threads.sort(key=_hit_time, reverse=True)
    if not threads:
        return []
    chosen = [threads[0]]
    current = _naive_utc(now or datetime.now(UTC))
    age = current - _hit_time(threads[0])
    if age < timedelta(days=PREVIOUS_THREAD_IF_YOUNGER_THAN_DAYS) and len(threads) > 1:
        chosen.append(threads[1])
    return chosen


def _thread_id(hit: dict) -> str:
    return as_str(hit.get("objectID") or hit.get("story_id")) or ""


# ------------------------------------------------------------------------------- source


class HackerNewsSource:
    name = "hackernews"
    display_name = "Hacker News: Who is hiring"
    homepage = "https://news.ycombinator.com"
    scope: Literal["broad", "targeted"] = "broad"

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

    def fetch(self, client: httpx.Client) -> list[SourceJob]:
        search = get_json(
            client,
            SEARCH_URL,
            params={"tags": "story,author_whoishiring", "hitsPerPage": SEARCH_HITS},
        )
        if not isinstance(search, dict) or not isinstance(search.get("hits"), list):
            raise ValueError("Hacker News: unexpected search response (no 'hits' list)")
        threads = select_threads(search["hits"], self._now())
        if not threads:
            raise ValueError("Hacker News: no 'Ask HN: Who is hiring?' thread in search results")

        jobs: list[SourceJob] = []
        for thread in threads:
            story = get_json(client, ITEM_URL.format(id=_thread_id(thread)))
            if not isinstance(story, dict) or not isinstance(story.get("children"), list):
                raise ValueError("Hacker News: unexpected item response (no 'children' list)")
            for comment in story["children"]:
                if not isinstance(comment, dict):
                    continue
                external_id = as_str(comment.get("id"))
                line = first_line(comment.get("text"))
                if not external_id or not line or not looks_remote(line):
                    continue
                payload = {k: v for k, v in comment.items() if k != "children"}
                jobs.append(SourceJob(self.name, external_id, payload))
        return dedupe_jobs(jobs)

    def to_fields(self, payload: dict) -> JobFields:
        text = payload.get("text")
        line = first_line(text)
        header = parse_first_line(line)
        author = clean_text(payload.get("author"))
        company = header.company or (f"HN user {author}" if author else "Unknown")
        external_id = as_str(payload.get("id")) or ""
        return {
            "title": header.title,
            "company": company,
            "url": POST_URL.format(id=external_id),
            "location": header.location,
            "is_remote": looks_remote(line),
            "posted_at": parse_datetime(payload.get("created_at") or payload.get("created_at_i")),
            "description_html": text if isinstance(text, str) and text.strip() else None,
            "salary_text": header.salary_text,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "source_tags": [],
            "source_category": None,
            "employment_type_text": header.employment_type_text,
            "seniority_hint": None,
        }
