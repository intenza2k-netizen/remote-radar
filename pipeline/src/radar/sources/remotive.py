"""Remotive: https://remotive.com/api/remote-jobs

The public endpoint returns a single JSON object ``{"jobs": [...]}`` (currently capped at
10 postings; ``limit`` and ``category`` params make no difference, verified), so one
request per run is all there is. Remotive asks API users to stay at a couple of requests
per day and to link back to the posting on remotive.com, which ``url`` does.
"""

from __future__ import annotations

import httpx

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

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource:
    name = "remotive"
    display_name = "Remotive"
    homepage = "https://remotive.com"

    def fetch(self, client: httpx.Client) -> list[SourceJob]:
        data = get_json(client, API_URL)
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Remotive: unexpected response shape (no 'jobs' list)")
        jobs = []
        for item in data["jobs"]:
            external_id = as_str(item.get("id")) if isinstance(item, dict) else None
            if external_id:
                jobs.append(SourceJob(self.name, external_id, item))
        return dedupe_jobs(jobs)

    def to_fields(self, payload: dict) -> JobFields:
        return {
            "title": clean_text(payload.get("title")),
            "company": clean_text(payload.get("company_name")),
            "url": (payload.get("url") or "").strip(),
            "location": clean_or_none(payload.get("candidate_required_location")),
            "is_remote": True,
            "posted_at": parse_datetime(payload.get("publication_date")),
            "description_html": payload.get("description") or None,
            "salary_text": clean_or_none(payload.get("salary")),
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "source_tags": clean_list(payload.get("tags")),
            "source_category": clean_or_none(payload.get("category")),
            "employment_type_text": clean_or_none(payload.get("job_type")),
            "seniority_hint": None,
        }
