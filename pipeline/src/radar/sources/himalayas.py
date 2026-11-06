"""Himalayas: https://himalayas.app/jobs/api/search (docs: https://himalayas.app/api)

Free public JSON API, no key. The search endpoint takes ``q`` (free text) and ``page``
(1-based); every page holds 20 jobs except the last, and a page without jobs means "done"
(``totalCount`` is an estimate and must not be used to stop). This is a *targeted* source:
instead of crawling the whole feed we run a list of keyword queries aimed at data roles
(:data:`SEARCH_QUERIES`), up to :data:`MAX_PAGES_PER_QUERY` pages each, and merge the
results by ``guid`` (the same job turns up under several queries and may shift between
pages while we walk).

Politeness: requests are strictly sequential with :data:`REQUEST_SPACING_SECONDS` (1 s)
between any two of them, the config User-Agent, and the one-retry ``get_json``. A query
stops early when a page brings no job we have not already seen. If a request still fails
after its retry (for example a 429 from the shared public allowance) the run stops and
returns what it has, provided it already has jobs; a failure before the first job raises.

Terms (https://himalayas.app/api, "API terms"): "Use the applicationLink for every Apply
button, unchanged." Jobs must also carry a visible link to Himalayas as the source, must
only be shown on sites we operate, and must be removed once they expire. Decision:
``url`` is ``applicationLink`` **unchanged** (it carries ``?utm_source=api`` and is *not*
the same string as ``guid``); it falls back to ``guid`` only when the link is missing.
``external_id`` is ``guid``, the stable canonical job URL. Attribution comes from
``display_name``/``homepage``. Removal of expired jobs is the "active listing" rule
elsewhere in the pipeline; ``expiryDate`` (the latest the job stays listed) is kept in the
raw payload but not mapped.

Dates: ``pubDate`` is when the job was *last updated*, not when it was first posted, and
the payload has no better field (``expiryDate`` is a listing cut-off, 38 to 60 days after
``pubDate`` in the samples, not a posting date). It is used as ``posted_at`` because
nothing better exists, so ages may be understated for refreshed jobs.

Location: every Himalayas job is remote. ``locationRestrictions`` lists the countries
candidates must be in; an empty list means "Worldwide". Long lists are shortened to the
first :data:`LOCATION_MAX_COUNTRIES` countries plus a ``+N more`` marker.

Salary: ``minSalary``/``maxSalary`` with ``salaryPeriod`` (hourly, weekly, fortnightly,
monthly, annual; annual is the documented default) and ``currency``. Weekly and
fortnightly amounts are converted to a yearly figure (x52, x26) because the shared
contract only knows year/month/hour.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Literal

import httpx

from radar.sources.base import (
    JobFields,
    SourceJob,
    as_str,
    clean_list,
    clean_or_none,
    clean_text,
    get_json,
    parse_datetime,
    to_float,
)

log = logging.getLogger(__name__)

SEARCH_URL = "https://himalayas.app/jobs/api/search"
HOMEPAGE = "https://himalayas.app"

# Keyword queries aimed at data roles. Order matters a little: earlier queries claim
# jobs first, later ones mostly add near-duplicates and stop early.
SEARCH_QUERIES: tuple[str, ...] = (
    "data analyst",
    "data engineer",
    "analytics engineer",
    "data scientist",
    "business intelligence",
    "machine learning engineer",
)
MAX_PAGES_PER_QUERY = 10
REQUEST_SPACING_SECONDS = 1.0
LOCATION_MAX_COUNTRIES = 5

# period -> (contract period, multiplier applied to the amounts)
_PERIODS: dict[str, tuple[str, float]] = {
    "annual": ("year", 1.0),
    "yearly": ("year", 1.0),
    "year": ("year", 1.0),
    "monthly": ("month", 1.0),
    "month": ("month", 1.0),
    "hourly": ("hour", 1.0),
    "hour": ("hour", 1.0),
    "weekly": ("year", 52.0),
    "fortnightly": ("year", 26.0),
}


def _location(restrictions: object) -> str:
    countries = clean_list(restrictions)
    if not countries:
        return "Worldwide"
    if len(countries) <= LOCATION_MAX_COUNTRIES:
        return ", ".join(countries)
    extra = len(countries) - LOCATION_MAX_COUNTRIES
    return ", ".join(countries[:LOCATION_MAX_COUNTRIES]) + f" +{extra} more"


def _tag(category: str) -> str:
    """Himalayas categories are slugs ("Business-Intelligence-Analyst"); show them as words."""
    return category.replace("-", " ")


class HimalayasSource:
    name = "himalayas"
    display_name = "Himalayas"
    homepage = HOMEPAGE
    # The fetch is keyword-filtered toward data roles, so counts are not market-wide.
    scope: Literal["broad", "targeted"] = "targeted"

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self._sleep = sleep

    def fetch(self, client: httpx.Client) -> list[SourceJob]:
        jobs: list[SourceJob] = []
        seen: set[str] = set()
        requests_made = 0
        for query in SEARCH_QUERIES:
            for page in range(1, MAX_PAGES_PER_QUERY + 1):
                if requests_made:
                    self._sleep(REQUEST_SPACING_SECONDS)
                requests_made += 1
                try:
                    data = get_json(client, SEARCH_URL, params={"q": query, "page": page})
                except httpx.HTTPError as exc:
                    if not jobs:
                        raise
                    log.warning(
                        "himalayas: stopping after %d jobs, %r page %d failed: %s",
                        len(jobs),
                        query,
                        page,
                        exc,
                    )
                    return jobs
                if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                    raise ValueError("Himalayas: unexpected response shape (no 'jobs' list)")
                page_jobs = data["jobs"]
                if not page_jobs:
                    break
                new = 0
                for item in page_jobs:
                    guid = as_str(item.get("guid")) if isinstance(item, dict) else None
                    if guid and guid not in seen:
                        seen.add(guid)
                        jobs.append(SourceJob(self.name, guid, item))
                        new += 1
                if not new:
                    break
        return jobs

    def to_fields(self, payload: dict) -> JobFields:
        low = to_float(payload.get("minSalary"))
        high = to_float(payload.get("maxSalary"))
        has_salary = low is not None or high is not None
        period, factor = _PERIODS.get(
            str(payload.get("salaryPeriod") or "annual").strip().lower(), (None, 1.0)
        )
        if has_salary and period is not None and factor != 1.0:
            low = low * factor if low is not None else None
            high = high * factor if high is not None else None
        currency = clean_or_none(payload.get("currency"))
        guid = as_str(payload.get("guid"))
        categories = [_tag(c) for c in clean_list(payload.get("categories"))]
        parents = clean_list(payload.get("parentCategories"))
        return {
            "title": clean_text(payload.get("title")),
            "company": clean_text(payload.get("companyName")),
            "url": as_str(payload.get("applicationLink")) or guid or HOMEPAGE,
            "location": _location(payload.get("locationRestrictions")),
            "is_remote": True,
            "posted_at": parse_datetime(payload.get("pubDate")),  # last updated, see docstring
            "description_html": payload.get("description") or payload.get("excerpt") or None,
            "salary_text": None,
            "salary_min": low,
            "salary_max": high,
            "salary_currency": currency.upper() if has_salary and currency else None,
            "salary_period": period if has_salary else None,
            "source_tags": categories,
            "source_category": parents[0] if parents else None,
            "employment_type_text": clean_or_none(payload.get("employmentType")),
            "seniority_hint": ", ".join(clean_list(payload.get("seniority"))) or None,
        }
