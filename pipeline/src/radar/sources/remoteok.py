"""Remote OK: https://remoteok.com/api

Returns a JSON array whose first element is a legal/metadata object (no ``id``), followed
by the postings. The API terms require a followed link back to the posting on Remote OK
and a mention of "Remote OK" as the source; ``url`` is the Remote OK posting page and
``display_name``/``homepage`` carry the attribution.

``salary_min``/``salary_max`` are annual USD figures; ``0`` means the poster gave none.
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
    to_float,
)

API_URL = "https://remoteok.com/api"
HOMEPAGE = "https://remoteok.com"


class RemoteOKSource:
    name = "remoteok"
    display_name = "Remote OK"
    homepage = HOMEPAGE

    def fetch(self, client: httpx.Client) -> list[SourceJob]:
        data = get_json(client, API_URL)
        if not isinstance(data, list):
            raise ValueError("Remote OK: unexpected response shape (expected a JSON array)")
        jobs = []
        for item in data:
            # The leading legal/metadata row has no id (and no slug); skip it and any
            # other malformed row.
            if not isinstance(item, dict) or "legal" in item:
                continue
            external_id = as_str(item.get("id"))
            if external_id:
                jobs.append(SourceJob(self.name, external_id, item))
        return dedupe_jobs(jobs)

    def to_fields(self, payload: dict) -> JobFields:
        low = to_float(payload.get("salary_min"))
        high = to_float(payload.get("salary_max"))
        has_salary = low is not None or high is not None
        slug = as_str(payload.get("slug"))
        url = as_str(payload.get("url")) or (f"{HOMEPAGE}/remote-jobs/{slug}" if slug else HOMEPAGE)
        posted_at = parse_datetime(payload.get("date")) or parse_datetime(payload.get("epoch"))
        return {
            "title": clean_text(payload.get("position")),
            "company": clean_text(payload.get("company")),
            "url": url,
            "location": clean_or_none(payload.get("location")),
            "is_remote": True,
            "posted_at": posted_at,
            "description_html": payload.get("description") or None,
            "salary_text": None,
            "salary_min": low,
            "salary_max": high,
            "salary_currency": "USD" if has_salary else None,
            "salary_period": "year" if has_salary else None,
            "source_tags": clean_list(payload.get("tags")),
            "source_category": None,
            "employment_type_text": None,
            "seniority_hint": None,
        }
