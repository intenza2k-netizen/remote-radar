"""Pipeline stage 4: aggregate extracted jobs into the published snapshot (PLAN.md section 4).

The statistics are pure functions over :class:`JobRecord` lists, so they can be unit tested
without a database. :func:`load_records` and :func:`aggregate` are the thin database layer.

Window: the last ``window_days // 7`` ISO weeks, aligned to Mondays and ending with the
current (partial) week, so every weekly bucket except the last is a full week. The window
therefore spans at most ``window_days`` days. The "last 4 weeks" and "previous 4 weeks" used
for ``change_4w`` are the two halves of those eight buckets.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property
from typing import Any

from sqlalchemy import func, select

from radar import config, embed
from radar.dedupe import normalize_company
from radar.extract_stage import current_backend_model, current_model
from radar.fx import to_usd
from radar.insights import build_skill_vocab, compute_companies, compute_insights
from radar.models import Extraction, Job, RawJob, Run, utcnow
from radar.normalize import annualize
from radar.skills import normalize_skills, skill_info
from radar.sources import ALL_SOURCES

WINDOW_DAYS = 56
JOBS_LIST_DAYS = 60
MIN_SALARY_N = 5  # minimum salaried jobs for any published salary statistic
MIN_HALF_JOBS = 20  # minimum jobs in each 4-week half for change_4w
MIN_SKILL_COUNT = 3  # skills mentioned in fewer jobs are too noisy to publish
MAX_SKILLS = 300
COOCCURRING = 8
MIN_ANNUAL_USD = 5_000
MAX_ANNUAL_USD = 1_000_000
SENIORITY_ORDER = ["intern", "junior", "mid", "senior", "lead", "principal", "unspecified"]


# --------------------------------------------------------------------------- data classes


@dataclass(frozen=True)
class RawSalary:
    """A salary as stored: bounds in ``currency`` per ``period`` (not annualised)."""

    min: float | None
    max: float | None
    currency: str | None
    period: str | None


@dataclass(frozen=True)
class ResolvedSalary:
    raw: RawSalary
    annual_usd_min: float | None
    annual_usd_max: float | None
    annual_usd_mid: float


@dataclass
class JobRecord:
    """One population member: a canonical remote job with its current ok extraction."""

    id: str
    source: str
    title: str
    company: str
    url: str
    location: str | None
    posted_at: datetime  # naive UTC; posting date, else first_seen_at
    role: str
    seniority: str
    employment_type: str
    remote_regions: list[str]
    skills: list[str]  # canonical slugs, deduped
    salaries: list[RawSalary] = field(default_factory=list)  # preference order
    db_id: int = 0  # jobs.id, for joining cached embeddings
    description: str = field(default="", repr=False)  # never published; embedded only

    @cached_property
    def salary(self) -> ResolvedSalary | None:
        return resolve_salary(self.salaries)


# --------------------------------------------------------------------------- salary maths


def annual_usd(salary: RawSalary) -> ResolvedSalary | None:
    """Annualise and convert to USD. ``None`` if there is no amount, the period or currency
    is unknown, or any bound falls outside the plausible range."""
    bounds = [b for b in (salary.min, salary.max) if b is not None]
    if not bounds:
        return None
    usd: list[float] = []
    for bound in bounds:
        yearly = annualize(bound, salary.period)
        value = to_usd(yearly, salary.currency)
        if value is None or not MIN_ANNUAL_USD <= value <= MAX_ANNUAL_USD:
            return None
        usd.append(value)
    lo = to_usd(annualize(salary.min, salary.period), salary.currency)
    hi = to_usd(annualize(salary.max, salary.period), salary.currency)
    return ResolvedSalary(
        raw=salary,
        annual_usd_min=lo,
        annual_usd_max=hi,
        annual_usd_mid=sum(usd) / len(usd),
    )


def resolve_salary(candidates: list[RawSalary]) -> ResolvedSalary | None:
    """First candidate (structured Job salary before extraction salary) that is usable."""
    for candidate in candidates:
        resolved = annual_usd(candidate)
        if resolved is not None:
            return resolved
    return None


def percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolation percentile (``p`` in 0..100) of an ascending list."""
    if not sorted_values:
        raise ValueError("percentile of an empty list")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * p / 100
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


def median_or_none(values: list[float]) -> int | None:
    if len(values) < MIN_SALARY_N:
        return None
    return round(statistics.median(values))


def distribution(key: str, values: list[float]) -> dict[str, Any] | None:
    if len(values) < MIN_SALARY_N:
        return None
    s = sorted(values)
    return {
        "key": key,
        "n": len(s),
        "p10": round(percentile(s, 10)),
        "p25": round(percentile(s, 25)),
        "median": round(percentile(s, 50)),
        "p75": round(percentile(s, 75)),
        "p90": round(percentile(s, 90)),
    }


def _num(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(float(value), 2)


# --------------------------------------------------------------------------- weeks


def iso_week(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def week_starts(now: datetime, n_weeks: int) -> list[datetime]:
    """Mondays 00:00 of the last ``n_weeks`` ISO weeks, oldest first, ending with ``now``'s."""
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return [monday - timedelta(weeks=n_weeks - 1 - i) for i in range(n_weeks)]


def _iso_z(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat() + "Z"


# --------------------------------------------------------------------------- statistics


def compute_snapshot(
    records: list[JobRecord],
    *,
    now: datetime,
    window_days: int = WINDOW_DAYS,
    sources: list[Any] | None = None,
    backend: str = "",
    model: str = "",
    last_run_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the snapshot documents from ``records``: ``meta``, ``skills``, ``roles``,
    ``salary``, ``jobs`` (section 4) plus ``insights``, ``companies`` and ``skill_vocab``
    (section 5). ``job_vectors`` needs the embedding cache and is added by :func:`aggregate`.

    ``records`` may be a superset of the window (the jobs list reaches back 60 days); the
    statistics only use records posted inside the window.
    """
    sources = list(ALL_SOURCES if sources is None else sources)
    n_weeks = max(1, window_days // 7)
    starts = week_starts(now, n_weeks)
    window_start = starts[0]
    labels = [iso_week(s) for s in starts]
    week_index = {label: i for i, label in enumerate(labels)}

    population = [r for r in records if window_start <= r.posted_at <= now]
    n = len(population)
    weekly_jobs = [0] * n_weeks
    for rec in population:
        weekly_jobs[week_index[iso_week(rec.posted_at)]] += 1

    skills_json = _skills(population, labels, week_index, weekly_jobs)
    salaried = [r for r in population if r.salary is not None]

    meta = {
        "generated_at": _iso_z(now),
        "last_run_at": _iso_z(last_run_at or now),
        "window_days": window_days,
        "backend": backend,
        "model": model,
        "totals": {
            "jobs": n,
            "companies": len({normalize_company(r.company) for r in population}),
            "with_salary": len(salaried),
            "skills": len(skills_json),
        },
        "sources": [
            {
                "name": s.name,
                "display_name": s.display_name,
                "homepage": s.homepage,
                "jobs": sum(1 for r in population if r.source == s.name),
            }
            for s in sources
        ],
        "weekly": [{"week": w, "jobs": c} for w, c in zip(labels, weekly_jobs, strict=True)],
    }

    return {
        "meta": meta,
        "skills": skills_json,
        "roles": _roles(population),
        "salary": _salary(population),
        "jobs": _jobs(records, now),
        "insights": compute_insights(population),
        "companies": compute_companies(population),
        "skill_vocab": build_skill_vocab(),
    }


def _skills(
    population: list[JobRecord],
    labels: list[str],
    week_index: dict[str, int],
    weekly_jobs: list[int],
) -> list[dict[str, Any]]:
    n = len(population)
    n_weeks = len(labels)
    by_skill: dict[str, list[JobRecord]] = {}
    for rec in population:
        for slug in rec.skills:
            by_skill.setdefault(slug, []).append(rec)

    ranked = sorted(by_skill.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ranked = [(s, recs) for s, recs in ranked if len(recs) >= MIN_SKILL_COUNT][:MAX_SKILLS]
    published = {slug for slug, _ in ranked}

    pairs: dict[str, Counter[str]] = {slug: Counter() for slug in published}
    for rec in population:
        present = [s for s in rec.skills if s in published]
        for a in present:
            for b in present:
                if a != b:
                    pairs[a][b] += 1

    half = 4
    recent_jobs = sum(weekly_jobs[-half:])
    previous_jobs = sum(weekly_jobs[-2 * half : -half]) if n_weeks >= 2 * half else 0

    out: list[dict[str, Any]] = []
    for slug, recs in ranked:
        weekly = [0] * n_weeks
        for rec in recs:
            weekly[week_index[iso_week(rec.posted_at)]] += 1
        change: float | None = None
        if n_weeks >= 2 * half and recent_jobs >= MIN_HALF_JOBS and previous_jobs >= MIN_HALF_JOBS:
            recent_share = sum(weekly[-half:]) / recent_jobs
            previous_share = sum(weekly[-2 * half : -half]) / previous_jobs
            change = round((recent_share - previous_share) * 100, 1)
        info = skill_info(slug)
        cooc = sorted(pairs[slug].items(), key=lambda kv: (-kv[1], kv[0]))[:COOCCURRING]
        out.append(
            {
                "slug": slug,
                "name": info.display,
                "category": info.category,
                "count": len(recs),
                "share": round(len(recs) / n, 4) if n else 0.0,
                "change_4w": change,
                "median_salary_usd": median_or_none(
                    [r.salary.annual_usd_mid for r in recs if r.salary is not None]
                ),
                "trend": [
                    {
                        "week": labels[i],
                        "count": weekly[i],
                        "share": round(weekly[i] / weekly_jobs[i], 4) if weekly_jobs[i] else 0.0,
                    }
                    for i in range(n_weeks)
                ],
                "cooccurring": [{"slug": s, "count": c} for s, c in cooc],
            }
        )
    return out


def _roles(population: list[JobRecord]) -> list[dict[str, Any]]:
    groups: dict[str, list[JobRecord]] = {}
    for rec in population:
        groups.setdefault(rec.role, []).append(rec)
    rows = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [
        {
            "role": role,
            "count": len(recs),
            "median_salary_usd": median_or_none(
                [r.salary.annual_usd_mid for r in recs if r.salary is not None]
            ),
        }
        for role, recs in rows
    ]


def _salary(population: list[JobRecord]) -> dict[str, list[dict[str, Any]]]:
    by_seniority: dict[str, list[float]] = {}
    by_role: dict[str, list[float]] = {}
    for rec in population:
        if rec.salary is None:
            continue
        by_seniority.setdefault(rec.seniority, []).append(rec.salary.annual_usd_mid)
        by_role.setdefault(rec.role, []).append(rec.salary.annual_usd_mid)

    def rank(key: str) -> int:
        return SENIORITY_ORDER.index(key) if key in SENIORITY_ORDER else len(SENIORITY_ORDER)

    seniority_rows = [
        d
        for key in sorted(by_seniority, key=lambda k: (rank(k), k))
        if (d := distribution(key, by_seniority[key]))
    ]
    role_rows = [d for key, vals in by_role.items() if (d := distribution(key, vals))]
    role_rows.sort(key=lambda d: (-d["n"], d["key"]))
    return {"by_seniority": seniority_rows, "by_role": role_rows}


def listed_records(records: list[JobRecord], now: datetime) -> list[JobRecord]:
    """The records published in ``jobs.json``: posted in the last 60 days, newest first."""
    cutoff = now - timedelta(days=JOBS_LIST_DAYS)
    recent = [r for r in records if cutoff <= r.posted_at <= now]
    recent.sort(key=lambda r: (r.posted_at, r.id), reverse=True)
    return recent


def _jobs(records: list[JobRecord], now: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in listed_records(records, now):
        resolved = rec.salary
        salary = None
        if resolved is not None:
            raw = resolved.raw
            salary = {
                "min": _num(raw.min),
                "max": _num(raw.max),
                "currency": (raw.currency or "").upper(),
                "period": raw.period or "year",
                "annual_usd_mid": round(resolved.annual_usd_mid),
            }
        rows.append(
            {
                "id": rec.id,
                "title": rec.title,
                "company": rec.company,
                "url": rec.url,
                "source": rec.source,
                "posted_at": _iso_z(rec.posted_at),
                "location": rec.location,
                "remote_regions": rec.remote_regions,
                "role": rec.role,
                "seniority": rec.seniority,
                "employment_type": rec.employment_type,
                "skills": rec.skills,
                "salary": salary,
            }
        )
    return rows


# --------------------------------------------------------------------------- database layer


def load_records(
    session,
    *,
    backend: str,
    model: str,
    prompt_version: str,
    since: datetime,
    now: datetime,
) -> list[JobRecord]:
    """Canonical remote jobs posted since ``since`` with their latest ok extraction for the
    given backend/model/prompt version."""
    when = func.coalesce(Job.posted_at, RawJob.first_seen_at)
    rows = session.execute(
        select(Job, RawJob.first_seen_at, Extraction)
        .join(RawJob, RawJob.id == Job.raw_job_id)
        .join(Extraction, Extraction.job_id == Job.id)
        .where(
            Job.is_duplicate_of.is_(None),
            Job.is_remote.is_(True),
            Extraction.ok.is_(True),
            Extraction.backend == backend,
            Extraction.model == model,
            Extraction.prompt_version == prompt_version,
            when >= since,
        )
        .order_by(Extraction.id)
    )
    latest: dict[int, tuple[Job, datetime, Extraction]] = {}
    for job, first_seen, extraction in rows:
        latest[job.id] = (job, first_seen, extraction)  # later extractions override

    records: list[JobRecord] = []
    for job, first_seen, extraction in latest.values():
        data = extraction.data or {}
        posted = min(job.posted_at or first_seen, now)
        salaries = [
            RawSalary(job.salary_min, job.salary_max, job.salary_currency, job.salary_period),
            RawSalary(
                data.get("salary_min"),
                data.get("salary_max"),
                data.get("salary_currency"),
                data.get("salary_period"),
            ),
        ]
        records.append(
            JobRecord(
                id=f"{job.source}-{job.external_id}",
                source=job.source,
                title=job.title,
                company=job.company,
                url=job.url,
                location=job.location,
                posted_at=posted,
                role=data.get("role_category") or "other",
                seniority=data.get("seniority") or "unspecified",
                employment_type=data.get("employment_type") or "unspecified",
                remote_regions=list(data.get("remote_regions") or []),
                skills=normalize_skills(data.get("skills") or []),
                salaries=salaries,
                db_id=job.id,
                description=job.description_text or "",
            )
        )
    return records


def latest_fetch_time(session) -> datetime | None:
    """Finish time of the latest fetch run that got data from at least one source."""
    return session.scalar(
        select(func.max(Run.finished_at)).where(
            Run.stage == "fetch", Run.status.in_(["ok", "partial"])
        )
    )


def load_snapshot_records(
    session,
    *,
    backend: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
) -> tuple[list[JobRecord], str, str, datetime]:
    """Records for the snapshot (window plus the 60-day jobs list), with the resolved
    backend, model and ``now``. ``backend``/``model`` default to the current extraction."""
    default_backend, _ = current_backend_model()
    backend = backend or default_backend
    model = model or current_model(backend)
    now = now or utcnow()
    since = now - timedelta(days=max(window_days, JOBS_LIST_DAYS) + 7)
    records = load_records(
        session,
        backend=backend,
        model=model,
        prompt_version=prompt_version or config.PROMPT_VERSION,
        since=since,
        now=now,
    )
    return records, backend, model, now


def aggregate(
    session,
    *,
    backend: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
    sources: list[Any] | None = None,
    embed_model_key: str | None = None,
) -> dict[str, Any]:
    """Aggregate the database into the snapshot documents (see :func:`compute_snapshot`)
    plus ``job_vectors`` from the embedding cache (``embed_model_key``, default fp32 model).

    ``backend``/``model`` default to the current extraction backend and model. The result
    also carries ``missing_vectors``: listed jobs without a cached vector yet.
    """
    records, backend, model, now = load_snapshot_records(
        session,
        backend=backend,
        model=model,
        prompt_version=prompt_version,
        now=now,
        window_days=window_days,
    )
    snapshot = compute_snapshot(
        records,
        now=now,
        window_days=window_days,
        sources=sources,
        backend=backend,
        model=model,
        last_run_at=latest_fetch_time(session),
    )
    vectors, missing = embed.job_vectors_document(
        session, listed_records(records, now), embed_model_key or embed.current_model_key()
    )
    snapshot["job_vectors"] = vectors
    snapshot["missing_vectors"] = missing
    return snapshot
