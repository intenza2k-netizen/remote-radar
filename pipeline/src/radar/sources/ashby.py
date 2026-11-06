"""Ashby job boards: https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true

Public posting API (https://developers.ashbyhq.com/docs/public-job-posting-api). A job is
remote only when ``workplaceType == "Remote"``: ``isRemote`` is also true for hybrid roles, so
it is never used on its own. Salary comes from the structured ``compensation`` summary.
"""

from __future__ import annotations

import re
from typing import Any

from radar.sources.ats_boards import BoardSource, radar_meta
from radar.sources.base import (
    JobFields,
    clean_list,
    clean_or_none,
    clean_text,
    parse_datetime,
    to_float,
)

_EMPLOYMENT = {
    "fulltime": "Full-time",
    "parttime": "Part-time",
    "contract": "Contract",
    "intern": "Internship",
    "temporary": "Temporary",
}
_GENERIC_DEPARTMENTS = {"all departments", "all", "general", "other", ""}


_INTERVAL_RE = re.compile(r"^\s*(?:1\s+)?(YEAR|MONTH|HOUR)S?\b", re.IGNORECASE)
_PERIODS = {"YEAR": "year", "MONTH": "month", "HOUR": "hour"}


def _period(interval: Any) -> str | None:
    """Ashby intervals look like ``"1 YEAR"``; weekly/daily ones have no matching period."""
    m = _INTERVAL_RE.match(str(interval or ""))
    return _PERIODS[m.group(1).upper()] if m else None


def _salary_component(compensation: Any) -> dict | None:
    """The first base-salary component with a usable amount, preferring the summary."""
    if not isinstance(compensation, dict):
        return None
    components: list[Any] = list(compensation.get("summaryComponents") or [])
    for tier in compensation.get("compensationTiers") or []:
        if isinstance(tier, dict):
            components.extend(tier.get("components") or [])
    for comp in components:
        if not isinstance(comp, dict) or comp.get("compensationType") != "Salary":
            continue
        if to_float(comp.get("minValue")) is not None or to_float(comp.get("maxValue")) is not None:
            return comp
    return None


class AshbySource(BoardSource):
    ats = "ashby"
    name = "ashby"
    display_name = "Ashby boards"
    homepage = "https://www.ashbyhq.com"
    api_url = "https://api.ashbyhq.com/posting-api/job-board/{token}"
    api_params = {"includeCompensation": "true"}

    def extract_jobs(self, data: Any) -> list[Any]:
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Ashby: unexpected response shape (no 'jobs' list)")
        return data["jobs"]

    def is_remote(self, job: dict) -> bool:
        if job.get("isListed") is False:
            return False
        return str(job.get("workplaceType") or "").strip().lower() == "remote"

    def to_fields(self, payload: dict) -> JobFields:
        department = clean_or_none(payload.get("department"))
        team = clean_or_none(payload.get("team"))
        if department and department.lower() in _GENERIC_DEPARTMENTS:
            department = None
        tags = clean_list([department, team])

        compensation = payload.get("compensation")
        comp = _salary_component(compensation)
        low = high = currency = period = None
        salary_text = None
        if comp:
            period = _period(comp.get("interval"))
            if period:
                low, high = to_float(comp.get("minValue")), to_float(comp.get("maxValue"))
                currency = clean_or_none(comp.get("currencyCode"))
                currency = currency.upper() if currency else None
            else:  # weekly/daily/odd intervals: keep the text, not unlabelled numbers
                salary_text = _compensation_text(compensation)
        elif isinstance(compensation, dict):
            salary_text = _compensation_text(compensation)

        employment = clean_or_none(payload.get("employmentType"))
        return {
            "title": clean_text(payload.get("title")),
            "company": clean_text(radar_meta(payload).get("company")),
            "url": (payload.get("jobUrl") or "").strip(),
            "location": clean_or_none(payload.get("location")),
            "is_remote": self.is_remote(payload),
            "posted_at": parse_datetime(payload.get("publishedAt")),
            "description_html": payload.get("descriptionHtml") or payload.get("descriptionPlain"),
            "salary_text": salary_text,
            "salary_min": low,
            "salary_max": high,
            "salary_currency": currency if low or high else None,
            "salary_period": period if low or high else None,
            "source_tags": tags,
            "source_category": department or team,
            "employment_type_text": (
                _EMPLOYMENT.get(employment.lower(), employment) if employment else None
            ),
            "seniority_hint": None,
        }


def _compensation_text(compensation: dict) -> str | None:
    for key in ("scrapeableCompensationSalarySummary", "compensationTierSummary"):
        text = clean_or_none(compensation.get(key))
        if text and any(ch.isdigit() for ch in text):
            return text
    return None
