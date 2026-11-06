"""Pipeline stages 1 and 2: fetch raw postings from the sources, then normalise them into jobs.

Both stages are idempotent. ``fetch`` upserts on (source, external_id); ``ingest`` only
touches raw rows that do not yet have a ``Job``. Each stage records a ``Run`` row through
:func:`track_run`, which the other stages reuse.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from radar.config import HTTP_TIMEOUT, USER_AGENT
from radar.db import session_scope, upsert_raw_jobs
from radar.dedupe import dedupe_key
from radar.models import Job, RawJob, Run, utcnow
from radar.normalize import clean_company, clean_title, html_to_text, parse_salary_text
from radar.sources import ALL_SOURCES, get_source
from radar.sources.base import Source

log = logging.getLogger(__name__)


class StageError(RuntimeError):
    """A fatal, user-facing stage failure. ``run-all`` stops and exits non-zero on it."""


# --------------------------------------------------------------------------- run tracking


@dataclass
class RunHandle:
    """Mutable view of the ``Run`` row for the stage that is executing."""

    id: int
    stats: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None


@contextmanager
def track_run(stage: str, db_path: Path | None = None) -> Iterator[RunHandle]:
    """Record a ``Run`` row: ``running`` on entry, then ``handle.status`` (default ``ok``)
    on success or ``failed`` with the exception text if the block raises."""
    with session_scope(db_path) as session:
        run = Run(stage=stage, status="running", stats={})
        session.add(run)
        session.flush()
        handle = RunHandle(id=run.id)
    try:
        yield handle
    except BaseException as exc:
        _finish_run(db_path, handle, "failed", f"{type(exc).__name__}: {exc}"[:2000])
        raise
    else:
        _finish_run(db_path, handle, handle.status, handle.error)


def _finish_run(db_path: Path | None, handle: RunHandle, status: str, error: str | None) -> None:
    with session_scope(db_path) as session:
        run = session.get(Run, handle.id)
        if run is None:  # pragma: no cover - the row was just created
            return
        run.finished_at = utcnow()
        run.status = status
        run.stats = dict(handle.stats)  # reassign so the JSON column registers the change
        run.error = error


# --------------------------------------------------------------------------- stage 1: fetch


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT, follow_redirects=True
    )


def fetch_sources(
    db_path: Path | None = None,
    sources: Sequence[Source] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch every source and upsert the raw postings.

    A failing source is recorded and skipped; the others still run. The ``Run`` is ``ok``
    when every source succeeded, ``partial`` when some failed, and the stage raises
    :class:`StageError` (run ``failed``) only when all of them failed.
    """
    sources = list(ALL_SOURCES if sources is None else sources)
    owns_client = client is None
    http = client or make_client()
    try:
        with track_run("fetch", db_path) as run:
            per_source: dict[str, dict[str, Any]] = {}
            run.stats = {"sources": per_source, "new": 0, "seen": 0, "errors": 0}
            for source in sources:
                entry: dict[str, Any] = {"new": 0, "seen": 0, "errors": 0, "error": None}
                per_source[source.name] = entry
                try:
                    items = source.fetch(http)
                    with session_scope(db_path) as session:
                        entry["new"], entry["seen"] = upsert_raw_jobs(session, items)
                except Exception as exc:
                    log.warning("fetch failed for %s: %s", source.name, exc)
                    entry["errors"] = 1
                    entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
                run.stats["new"] += entry["new"]
                run.stats["seen"] += entry["seen"]
                run.stats["errors"] += entry["errors"]
            failed = [name for name, e in per_source.items() if e["errors"]]
            if failed:
                run.status = "partial"
                run.error = "failed sources: " + ", ".join(failed)
            if sources and len(failed) == len(sources):
                raise StageError(
                    "every source failed to fetch: "
                    + "; ".join(f"{n}: {per_source[n]['error']}" for n in failed)
                )
            return dict(run.stats)
    finally:
        if owns_client:
            http.close()


# --------------------------------------------------------------------------- stage 2: ingest

_FAR_FUTURE = datetime.max


def _build_job(raw: RawJob, source: Source) -> Job:
    """Map one raw payload onto a ``Job`` (without ``is_duplicate_of``). Raises on bad data."""
    fields = source.to_fields(raw.payload)
    title = clean_title(fields["title"])
    company = clean_company(fields["company"])
    if not title or not company:
        raise ValueError("payload has no title or company")
    salary_min, salary_max = fields["salary_min"], fields["salary_max"]
    currency, period = fields["salary_currency"], fields["salary_period"]
    if salary_min is None and salary_max is None and fields["salary_text"]:
        parsed = parse_salary_text(fields["salary_text"])
        if parsed is not None and (parsed.min is not None or parsed.max is not None):
            salary_min, salary_max = parsed.min, parsed.max
            currency, period = parsed.currency, parsed.period
    return Job(
        raw_job_id=raw.id,
        source=raw.source,
        external_id=raw.external_id,
        title=title,
        company=company,
        url=fields["url"],
        location=fields["location"],
        is_remote=fields["is_remote"],
        posted_at=fields["posted_at"],
        description_text=html_to_text(fields["description_html"]),
        salary_text=fields["salary_text"],
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        salary_period=period,
        source_tags=fields["source_tags"],
        source_category=fields["source_category"],
        employment_type_text=fields["employment_type_text"],
        seniority_hint=fields["seniority_hint"],
        dedupe_key=dedupe_key(company, title),
    )


def ingest_raw_jobs(db_path: Path | None = None) -> dict[str, Any]:
    """Create a ``Job`` for every raw posting that has none, and mark duplicates.

    Within one batch the earliest posting (lowest ``posted_at``, then raw id) becomes the
    canonical one. A posting whose key already has a canonical job is marked a duplicate of
    it, even if it was posted earlier: canonical ids stay stable across runs.
    """
    with track_run("ingest", db_path) as run, session_scope(db_path) as session:
        pending = session.scalars(
            select(RawJob)
            .outerjoin(Job, Job.raw_job_id == RawJob.id)
            .where(Job.id.is_(None))
            .order_by(RawJob.id)
        ).all()

        built: list[tuple[RawJob, Job]] = []
        errors = 0
        for raw in pending:
            try:
                built.append((raw, _build_job(raw, get_source(raw.source))))
            except Exception as exc:
                errors += 1
                log.warning("cannot map %s/%s: %s", raw.source, raw.external_id, exc)
        built.sort(key=lambda rj: (rj[1].posted_at or _FAR_FUTURE, rj[0].id))

        canonical_by_key: dict[str, int] = {}
        rows = session.execute(
            select(Job.dedupe_key, Job.id)
            .where(Job.is_duplicate_of.is_(None))
            .order_by(Job.posted_at.is_(None), Job.posted_at, Job.id)
        )
        for key, job_id in rows:
            canonical_by_key.setdefault(key, job_id)

        duplicates = 0
        for _, job in built:
            canonical_id = canonical_by_key.get(job.dedupe_key)
            if canonical_id is not None:
                job.is_duplicate_of = canonical_id
                duplicates += 1
            session.add(job)
            session.flush()
            if canonical_id is None:
                canonical_by_key[job.dedupe_key] = job.id

        run.stats = {
            "pending": len(pending),
            "new_jobs": len(built),
            "canonical": len(built) - duplicates,
            "duplicates": duplicates,
            "errors": errors,
        }
        if errors:
            run.status = "partial"
            run.error = f"{errors} payload(s) could not be mapped"
        return dict(run.stats)
