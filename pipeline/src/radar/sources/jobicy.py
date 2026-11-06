"""Jobicy: https://jobicy.com/api/v2/remote-jobs

Cursor-paginated JSON. Each response carries ``nextCursor`` and ``hasMore``; the cursor is
passed back unchanged as the ``cursor`` query parameter (see https://jobi.cy/apidocs).
Jobicy's terms require crediting Jobicy and sending applicants to the original job URL,
which is what ``url`` holds.

Scope: ``targeted``. Besides the default feed (``JOBICY_PAGES`` pages, unfiltered) the
fetch also pulls the category feed ``industry=data-science`` (``INDUSTRY_PAGES`` pages,
same cursor logic) and merges both, deduped by job id with the default feed first. The
unfiltered feed is unchanged, but because part of the fetch is now filtered toward data
roles the source no longer reflects the market mix, so counts must not be read as a
share of all Jobicy postings. The extra feed is best-effort: if it fails after the
default feed succeeded, the failure is logged and the default jobs are still returned.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from radar.config import JOBICY_PAGES
from radar.sources.base import (
    JobFields,
    SourceJob,
    as_str,
    clean_list,
    clean_or_none,
    clean_text,
    dedupe_jobs,
    get_json,
    parse_datetime,
    to_float,
)

log = logging.getLogger(__name__)

API_URL = "https://jobicy.com/api/v2/remote-jobs"
PAGE_SIZE = 100  # documented maximum per page
# Category slugs fetched in addition to the default feed (``industry`` query parameter).
DATA_INDUSTRIES: tuple[str, ...] = ("data-science",)
INDUSTRY_PAGES = 2  # pages per extra industry feed

_PERIODS = {
    "yearly": "year",
    "annual": "year",
    "annually": "year",
    "year": "year",
    "monthly": "month",
    "month": "month",
    "hourly": "hour",
    "hour": "hour",
}


def _period(value: object) -> str | None:
    return _PERIODS.get(str(value or "").strip().lower())


class JobicySource:
    name = "jobicy"
    display_name = "Jobicy"
    homepage = "https://jobicy.com"
    # Part of the fetch is filtered toward data roles (see module docstring).
    scope: Literal["broad", "targeted"] = "targeted"

    def fetch(self, client: httpx.Client) -> list[SourceJob]:
        jobs = self._fetch_feed(client, max_pages=JOBICY_PAGES)
        for industry in DATA_INDUSTRIES:
            try:
                jobs += self._fetch_feed(client, max_pages=INDUSTRY_PAGES, industry=industry)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning(
                    "jobicy: industry=%s feed failed, keeping other jobs: %s", industry, exc
                )
        return dedupe_jobs(jobs)

    def _fetch_feed(
        self, client: httpx.Client, *, max_pages: int, industry: str | None = None
    ) -> list[SourceJob]:
        jobs: list[SourceJob] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict[str, object] = {"count": PAGE_SIZE}
            if industry:
                params["industry"] = industry
            if cursor:
                params["cursor"] = cursor
            data = get_json(client, API_URL, params=params)
            if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                raise ValueError("Jobicy: unexpected response shape (no 'jobs' list)")
            for item in data["jobs"]:
                external_id = as_str(item.get("id")) if isinstance(item, dict) else None
                if external_id:
                    jobs.append(SourceJob(self.name, external_id, item))
            cursor = as_str(data.get("nextCursor"))
            if not data["jobs"] or not data.get("hasMore") or not cursor:
                break
        return jobs

    def to_fields(self, payload: dict) -> JobFields:
        low = to_float(payload.get("salaryMin"))
        high = to_float(payload.get("salaryMax"))
        has_salary = low is not None or high is not None
        industries = clean_list(payload.get("jobIndustry"))
        job_types = clean_list(payload.get("jobType"))
        level = clean_or_none(payload.get("jobLevel"))
        if level and level.lower() == "any":
            level = None
        currency = clean_or_none(payload.get("salaryCurrency"))
        return {
            "title": clean_text(payload.get("jobTitle")),
            "company": clean_text(payload.get("companyName")),
            "url": (payload.get("url") or "").strip(),
            "location": clean_or_none(payload.get("jobGeo")),
            "is_remote": True,
            "posted_at": parse_datetime(payload.get("pubDate")),
            "description_html": payload.get("jobDescription") or payload.get("jobExcerpt") or None,
            "salary_text": None,
            "salary_min": low,
            "salary_max": high,
            "salary_currency": currency.upper() if has_salary and currency else None,
            "salary_period": _period(payload.get("salaryPeriod")) if has_salary else None,
            "source_tags": industries,
            "source_category": industries[0] if industries else None,
            "employment_type_text": ", ".join(job_types) or None,
            "seniority_hint": level,
        }
