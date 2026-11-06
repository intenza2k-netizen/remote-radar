"""Lever job boards: https://api.lever.co/v0/postings/{token}?mode=json

Public postings API (https://github.com/lever/postings-api). A job is remote when
``workplaceType == "remote"``. Lever has no company name in the payload (it comes from the
YAML list) and splits the description into ``description`` (opening + body), ``lists``
(titled bullet sections) and ``additional``; they are recombined into one HTML string.
"""

from __future__ import annotations

import html
import re
from typing import Any

from radar.sources.ats_boards import BoardSource, extract_salary_snippet, radar_meta
from radar.sources.base import (
    JobFields,
    clean_list,
    clean_or_none,
    clean_text,
    parse_datetime,
    to_float,
)

_PERIOD_RE = re.compile(r"(year|month|hour)", re.IGNORECASE)


def _paragraphs(plain: str) -> str:
    return "".join(f"<p>{html.escape(line)}</p>" for line in plain.splitlines() if line.strip())


def description_html(job: dict) -> str | None:
    """Combine Lever's description fragments into one HTML string (``None`` if empty)."""
    main = job.get("description") or "".join(
        str(job.get(k) or "") for k in ("opening", "descriptionBody")
    )
    parts: list[str] = []
    if main.strip():
        parts.append(main)
    elif job.get("descriptionPlain"):
        parts.append(_paragraphs(str(job["descriptionPlain"])))
    for item in job.get("lists") or []:
        if not isinstance(item, dict):
            continue
        heading = clean_text(item.get("text"))
        body = str(item.get("content") or "")
        if heading:
            parts.append(f"<h3>{html.escape(heading)}</h3>")
        if body.strip():
            parts.append(f"<ul>{body}</ul>")
    if job.get("additional"):
        parts.append(str(job["additional"]))
    elif job.get("additionalPlain"):
        parts.append(_paragraphs(str(job["additionalPlain"])))
    return "\n".join(parts) or None


class LeverSource(BoardSource):
    ats = "lever"
    name = "lever"
    display_name = "Lever boards"
    homepage = "https://www.lever.co"
    api_url = "https://api.lever.co/v0/postings/{token}"
    api_params = {"mode": "json"}

    def extract_jobs(self, data: Any) -> list[Any]:
        if not isinstance(data, list):
            raise ValueError("Lever: unexpected response shape (expected a list of postings)")
        return data

    def is_remote(self, job: dict) -> bool:
        return str(job.get("workplaceType") or "").strip().lower() == "remote"

    def to_fields(self, payload: dict) -> JobFields:
        cats = payload.get("categories")
        cats = cats if isinstance(cats, dict) else {}
        team = clean_or_none(cats.get("team"))
        department = clean_or_none(cats.get("department"))
        location = clean_or_none(cats.get("location")) or (
            ", ".join(clean_list(cats.get("allLocations"))) or None
        )

        rng = payload.get("salaryRange")
        rng = rng if isinstance(rng, dict) else {}
        low, high = to_float(rng.get("min")), to_float(rng.get("max"))
        period_match = _PERIOD_RE.search(str(rng.get("interval") or ""))
        period = period_match.group(1).lower() if period_match else None
        has_structured = (low is not None or high is not None) and period is not None
        currency = clean_or_none(rng.get("currency"))

        salary_text = None
        if not has_structured:
            low = high = None
            salary_text = extract_salary_snippet(
                str(payload.get("salaryDescriptionPlain") or ""), require_context=False
            ) or extract_salary_snippet(str(payload.get("additionalPlain") or ""))

        return {
            "title": clean_text(payload.get("text")),
            "company": clean_text(radar_meta(payload).get("company")),
            "url": (payload.get("hostedUrl") or "").strip(),
            "location": location,
            "is_remote": self.is_remote(payload),
            "posted_at": parse_datetime(payload.get("createdAt")),
            "description_html": description_html(payload),
            "salary_text": salary_text,
            "salary_min": low,
            "salary_max": high,
            "salary_currency": currency.upper() if has_structured and currency else None,
            "salary_period": period if has_structured else None,
            "source_tags": clean_list([team, department]),
            "source_category": department or team,
            "employment_type_text": clean_or_none(cats.get("commitment")),
            "seniority_hint": None,
        }
