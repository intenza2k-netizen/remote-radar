"""Arbeitnow: https://www.arbeitnow.com/api/job-board-api?page=N

Paginated JSON (``{"data": [...], "links": {...}, "meta": {...}}``, ~300 postings per
page). Many postings are on-site German jobs; they are kept and flagged with
``is_remote=False``. ``description`` is HTML-entity-escaped and is passed through as is.
Arbeitnow asks for a link back to the site, which ``url`` provides.
"""

from __future__ import annotations

import httpx

from radar.config import ARBEITNOW_PAGES
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
)

API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowSource:
    name = "arbeitnow"
    display_name = "Arbeitnow"
    homepage = "https://www.arbeitnow.com"

    def fetch(self, client: httpx.Client) -> list[SourceJob]:
        jobs: list[SourceJob] = []
        for page in range(1, ARBEITNOW_PAGES + 1):
            data = get_json(client, API_URL, params={"page": page})
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ValueError("Arbeitnow: unexpected response shape (no 'data' list)")
            rows = data["data"]
            for item in rows:
                external_id = as_str(item.get("slug")) if isinstance(item, dict) else None
                if external_id:
                    jobs.append(SourceJob(self.name, external_id, item))
            links = data.get("links")
            has_next = bool(links.get("next")) if isinstance(links, dict) else True
            if not rows or not has_next:
                break
        return dedupe_jobs(jobs)

    def to_fields(self, payload: dict) -> JobFields:
        tags = clean_list(payload.get("tags"))
        # Arbeitnow "tags" are its categories ("Engineering", "Online Marketing", ...) and
        # sometimes include a literal "Remote" marker, which is not a category.
        category = next((t for t in tags if t.lower() != "remote"), None)
        job_types = clean_list(payload.get("job_types"))
        return {
            "title": clean_text(payload.get("title")),
            "company": clean_text(payload.get("company_name")),
            "url": (payload.get("url") or "").strip(),
            "location": clean_or_none(payload.get("location")),
            "is_remote": bool(payload.get("remote")),
            "posted_at": parse_datetime(payload.get("created_at")),
            "description_html": payload.get("description") or None,
            "salary_text": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "source_tags": tags,
            "source_category": category,
            "employment_type_text": ", ".join(job_types) or None,
            "seniority_hint": None,
        }
