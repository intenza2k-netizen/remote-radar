"""Jobicy: https://jobicy.com/api/v2/remote-jobs

Cursor-paginated JSON. Each response carries ``nextCursor`` and ``hasMore``; the cursor is
passed back unchanged as the ``cursor`` query parameter (see https://jobi.cy/apidocs).
Jobicy's terms require crediting Jobicy and sending applicants to the original job URL,
which is what ``url`` holds.
"""

from __future__ import annotations

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

API_URL = "https://jobicy.com/api/v2/remote-jobs"
PAGE_SIZE = 100  # documented maximum per page

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

    def fetch(self, client: httpx.Client) -> list[SourceJob]:
        jobs: list[SourceJob] = []
        cursor: str | None = None
        for _ in range(JOBICY_PAGES):
            params: dict[str, object] = {"count": PAGE_SIZE}
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
        return dedupe_jobs(jobs)

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
