"""Shared types and helpers for the job-board source adapters.

Each adapter has two halves:

* ``fetch(client)`` talks to the network and returns :class:`SourceJob` records whose
  ``payload`` is the job object exactly as the API returned it.
* ``to_fields(payload)`` is a pure function mapping such a payload onto the common
  :class:`JobFields` shape. It never touches the network and never calls
  ``radar.normalize`` (free-text salary parsing and HTML-to-text happen later).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict

import httpx
from dateutil import parser as _dateparser
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_fixed

# Seconds to wait before the single retry of a failed request. Tests set this to 0.
RETRY_WAIT_SECONDS: float = 2.0
# One initial attempt plus one retry.
RETRY_ATTEMPTS: int = 2


@dataclass(frozen=True)
class SourceJob:
    source: str  # "remotive" | "remoteok" | "arbeitnow" | "jobicy"
    external_id: str  # stable id from the API, as str
    payload: dict  # the job object exactly as returned (JSON-serialisable)


class JobFields(TypedDict):
    title: str
    company: str
    url: str  # canonical posting URL on the source site
    location: str | None
    is_remote: bool
    posted_at: datetime | None  # naive UTC
    description_html: str | None  # as provided (may be entity-escaped)
    salary_text: str | None  # free-text salary if the source only gives text
    salary_min: float | None  # only from structured source fields
    salary_max: float | None
    salary_currency: str | None  # ISO 4217
    salary_period: str | None  # "year" | "month" | "hour" | None
    source_tags: list[str]
    source_category: str | None
    employment_type_text: str | None
    seniority_hint: str | None  # e.g. Jobicy jobLevel


class Source(Protocol):
    name: str
    display_name: str  # "Remote OK"
    homepage: str  # for attribution links

    def fetch(self, client: httpx.Client) -> list[SourceJob]: ...

    def to_fields(self, payload: dict) -> JobFields: ...


# --------------------------------------------------------------------------- helpers

_WS = re.compile(r"\s+")
_MOJIBAKE_MARKERS = ("Ã", "â€", "Â")


def _repair_mojibake(text: str) -> str:
    """Undo UTF-8 text that was wrongly decoded as cp1252/latin-1 upstream."""
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text
    for codec in ("cp1252", "latin-1"):
        try:
            return text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def clean_text(value: Any) -> str:
    """Short single-line text (title, company, location): unescape entities, fix
    mojibake, collapse whitespace, strip. Non-strings and empty values give ``""``."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _repair_mojibake(text)
    return _WS.sub(" ", text).strip()


def clean_or_none(value: Any) -> str | None:
    return clean_text(value) or None


def clean_list(values: Any) -> list[str]:
    """Clean a list of short strings, dropping empties and exact duplicates."""
    if not isinstance(values, list | tuple):
        return []
    out: list[str] = []
    for v in values:
        text = clean_text(v)
        if text and text not in out:
            out.append(text)
    return out


def to_float(value: Any) -> float | None:
    """Positive number or ``None`` (zero, negatives and junk all mean 'unknown')."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def as_str(value: Any) -> str | None:
    """Stringify an identifier; ``None`` or blank gives ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO string or epoch (seconds or milliseconds) to a naive UTC datetime.

    Timestamps without a timezone are assumed to already be UTC. Returns ``None``
    for missing or unparseable input.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, int | float) or (isinstance(value, str) and value.strip().isdigit()):
            seconds = float(value)
            if seconds > 1e11:  # milliseconds
                seconds /= 1000.0
            return datetime.fromtimestamp(seconds, tz=UTC).replace(tzinfo=None)
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = _dateparser.parse(text)
    except (ValueError, OverflowError, OSError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, httpx.TransportError)


def get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    """GET ``url`` and return decoded JSON. One request per call, with a single retry on
    transport errors, HTTP 429 and 5xx. Raises :class:`httpx.HTTPError` otherwise."""
    retrying = Retrying(
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_fixed(RETRY_WAIT_SECONDS),
        retry=retry_if_exception(_should_retry),
        reraise=True,
    )
    for attempt in retrying:
        with attempt:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    raise AssertionError("unreachable")  # pragma: no cover


def dedupe_jobs(jobs: list[SourceJob]) -> list[SourceJob]:
    """Drop repeated (source, external_id) pairs, keeping the first occurrence."""
    seen: set[tuple[str, str]] = set()
    out: list[SourceJob] = []
    for job in jobs:
        key = (job.source, job.external_id)
        if key not in seen:
            seen.add(key)
            out.append(job)
    return out
