"""Greenhouse job boards: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

Public board API for embedding career pages (https://developers.greenhouse.io/job-board.html).
Greenhouse has no remote flag, so a job counts as remote when its location (or one of its
offices, or a location-like metadata field) says "remote" or "anywhere". ``content`` is
entity-escaped HTML and is passed through untouched. Salaries are only ever in the text, so
``salary_text`` is a short range snippet when a clear one is present.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from radar.sources.ats_boards import (
    BoardSource,
    extract_salary_snippet,
    mentions_remote,
    plain_text,
    radar_meta,
)
from radar.sources.base import (
    JobFields,
    clean_list,
    clean_or_none,
    clean_text,
    parse_datetime,
)

_LOCATION_META = ("location", "workplace", "work type", "work arrangement", "work model")
_FALSEY = {"", "no", "false", "none", "n/a", "0"}


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _location_candidates(job: dict) -> Iterator[str]:
    location = job.get("location")
    if isinstance(location, dict):
        yield from _strings(location.get("name"))
    for office in job.get("offices") or []:
        if isinstance(office, dict):
            yield from _strings(office.get("name"))
            yield from _strings(office.get("location"))
    for item in job.get("metadata") or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("name") or "").lower()
        if "remote" in field:
            # a yes/no style flag such as "Remote eligible: No"
            if any(s.strip().lower() not in _FALSEY for s in _strings(item.get("value"))):
                yield "remote"
        elif any(key in field for key in _LOCATION_META):
            yield from _strings(item.get("value"))


def _metadata_text(job: dict, *names: str) -> str | None:
    for item in job.get("metadata") or []:
        if isinstance(item, dict) and str(item.get("name") or "").strip().lower() in names:
            for s in _strings(item.get("value")):
                if clean_text(s):
                    return clean_text(s)
    return None


class GreenhouseSource(BoardSource):
    ats = "greenhouse"
    name = "greenhouse"
    display_name = "Greenhouse boards"
    homepage = "https://www.greenhouse.com"
    api_url = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    api_params = {"content": "true"}

    def extract_jobs(self, data: Any) -> list[Any]:
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Greenhouse: unexpected response shape (no 'jobs' list)")
        return data["jobs"]

    def is_remote(self, job: dict) -> bool:
        return any(mentions_remote(text) for text in _location_candidates(job))

    def to_fields(self, payload: dict) -> JobFields:
        location = payload.get("location")
        location_name = location.get("name") if isinstance(location, dict) else None
        departments = [
            d.get("name") for d in payload.get("departments") or [] if isinstance(d, dict)
        ]
        categories = clean_list(departments)
        content = payload.get("content") or None
        company = clean_text(radar_meta(payload).get("company")) or clean_text(
            payload.get("company_name")
        )
        return {
            "title": clean_text(payload.get("title")),
            "company": company,
            "url": (payload.get("absolute_url") or "").strip(),
            "location": clean_or_none(location_name),
            "is_remote": self.is_remote(payload),
            "posted_at": parse_datetime(payload.get("first_published"))
            or parse_datetime(payload.get("updated_at")),
            "description_html": content,
            "salary_text": extract_salary_snippet(plain_text(content)) if content else None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "source_tags": categories,
            "source_category": categories[0] if categories else None,
            "employment_type_text": _metadata_text(
                payload, "employment type", "job type", "employment status"
            ),
            "seniority_hint": None,
        }
