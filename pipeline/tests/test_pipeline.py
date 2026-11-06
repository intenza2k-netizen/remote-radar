"""Pipeline stage tests: fetch, ingest, extract, aggregate, publish, CLI.

No network and no LLM: sources are served by ``httpx.MockTransport`` from the trimmed
fixtures, and extraction uses a deterministic fake that implements the ``Extractor``
protocol.
"""

from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import httpx
import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from radar import config
from radar.aggregate import (
    JobRecord,
    RawSalary,
    annual_usd,
    compute_snapshot,
    iso_week,
    percentile,
    resolve_salary,
    week_starts,
)
from radar.cli import app
from radar.db import session_scope, upsert_raw_jobs
from radar.extract import ExtractedJob, ExtractionResult, JobInput
from radar.extract.llm import MissingApiKeyError
from radar.extract_stage import run_extract
from radar.fx import to_usd, usd_rate
from radar.ingest import StageError, fetch_sources, ingest_raw_jobs, make_client
from radar.models import Extraction, Job, JobSkill, RawJob, Run
from radar.publish import FILES, publish, write_snapshot
from radar.skills import normalize_skills
from radar.sources import ALL_SOURCES
from radar.sources import base as base_mod
from radar.sources.base import SourceJob

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 7, 12, 0)  # a Saturday, ISO week 2026-W45; fixtures end 2026-11-06


# --------------------------------------------------------------------------- helpers


def fixture(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def fixture_handler(overrides: dict[str, httpx.Response] | None = None):
    """Serve each source's fixture on page 1 and an empty page afterwards."""
    overrides = overrides or {}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        for key, response in overrides.items():
            if key in host:
                return response
        params = dict(request.url.params)
        if "remotive" in host:
            return httpx.Response(200, json=fixture("remotive"))
        if "remoteok" in host:
            return httpx.Response(200, json=fixture("remoteok"))
        if "arbeitnow" in host:
            if params.get("page", "1") != "1":
                return httpx.Response(200, json={"data": [], "links": {}})
            return httpx.Response(200, json=fixture("arbeitnow"))
        if "jobicy" in host:
            if "cursor" in params:
                return httpx.Response(200, json={"jobs": [], "hasMore": False})
            return httpx.Response(200, json=fixture("jobicy"))
        return httpx.Response(404)

    return handler


def mock_client(handler=None) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler or fixture_handler()),
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.HTTP_TIMEOUT,
    )


@pytest.fixture(autouse=True)
def _fast_and_isolated(monkeypatch):
    monkeypatch.setattr(base_mod, "RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(config, "DEFAULT_BACKEND", "ollama")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "fake-current")
    monkeypatch.setattr(config, "CLAUDE_MODEL", "fake-claude")


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "radar.sqlite"


@pytest.fixture
def ingested(db) -> Path:
    fetch_sources(db, client=mock_client())
    ingest_raw_jobs(db)
    return db


def count(db: Path, stmt) -> int:
    with session_scope(db) as s:
        return s.scalar(stmt) or 0


def crafted_remoteok(ext_id: str, title: str, company: str, date: str) -> SourceJob:
    payload = copy.deepcopy(fixture("remoteok")[1])
    payload.update(id=ext_id, position=title, company=company, date=date)
    payload.pop("epoch", None)
    return SourceJob("remoteok", ext_id, payload)


class FakeExtractor:
    """Deterministic ``Extractor``. ``raises`` maps a title substring to an exception that
    ``extract`` raises; ``returns_failure`` lists title substrings that yield ``ok=False``."""

    def __init__(
        self,
        backend: str = "ollama",
        model: str = "fake-current",
        raises: dict[str, BaseException] | None = None,
        returns_failure: tuple[str, ...] = (),
    ):
        self.backend = backend
        self.model = model
        self.prompt_version = config.PROMPT_VERSION
        self.raises = raises or {}
        self.returns_failure = returns_failure
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def extract(self, job: JobInput) -> ExtractionResult:
        with self._lock:
            self.calls.append(job.title)
        for needle, exc in self.raises.items():
            if needle in job.title:
                raise exc
        base = dict(
            backend=self.backend,
            model=self.model,
            prompt_version=self.prompt_version,
            raw_output="{}",
            latency_ms=100 + len(job.title) % 7,
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.001,
        )
        if any(needle in job.title for needle in self.returns_failure):
            return ExtractionResult(ok=False, data=None, error="bad json", **base)
        title = job.title.lower()
        skills = ["Python", "PostgreSQL", "k8s"]
        if "data" in title:
            skills += ["dbt", "SQL"]
        data = ExtractedJob(
            role_category="data"
            if "data" in title
            else "software_engineering"
            if "engineer" in title or "developer" in title
            else "other",
            seniority="senior" if "senior" in title else "unspecified",
            skills=skills,
            employment_type="full_time",
            remote_regions=["worldwide"],
        )
        return ExtractionResult(ok=True, data=data, error=None, **base)


def auth_error() -> anthropic.AuthenticationError:
    response = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com"))
    return anthropic.AuthenticationError("bad key", response=response, body=None)


def permission_error() -> anthropic.PermissionDeniedError:
    response = httpx.Response(403, request=httpx.Request("POST", "https://api.anthropic.com"))
    return anthropic.PermissionDeniedError("denied", response=response, body=None)


def extract(db: Path, extractor=None, **kw):
    kw.setdefault("show_progress", False)
    return run_extract(extractor or FakeExtractor(), db, **kw)


# --------------------------------------------------------------------------- fetch


def test_make_client_uses_config():
    client = make_client()
    try:
        assert client.headers["User-Agent"] == config.USER_AGENT
        assert client.timeout.read == config.HTTP_TIMEOUT
    finally:
        client.close()


def test_fetch_stores_raw_jobs_and_records_run(db):
    stats = fetch_sources(db, client=mock_client())
    assert set(stats["sources"]) == {s.name for s in ALL_SOURCES}
    assert stats["errors"] == 0
    assert stats["new"] == count(db, select(func.count()).select_from(RawJob))
    assert all(e["new"] > 0 for e in stats["sources"].values())
    with session_scope(db) as s:
        run = s.scalars(select(Run).where(Run.stage == "fetch")).one()
        assert run.status == "ok" and run.finished_at is not None
        assert run.stats["sources"]["remoteok"]["new"] == stats["sources"]["remoteok"]["new"]


def test_fetch_is_idempotent(db):
    first = fetch_sources(db, client=mock_client())
    raw_before = count(db, select(func.count()).select_from(RawJob))
    second = fetch_sources(db, client=mock_client())
    assert count(db, select(func.count()).select_from(RawJob)) == raw_before
    assert second["new"] == 0
    assert second["seen"] == first["new"]


def test_one_failing_source_does_not_stop_the_others(db):
    handler = fixture_handler({"remoteok": httpx.Response(500)})
    stats = fetch_sources(db, client=mock_client(handler))
    assert stats["sources"]["remoteok"]["errors"] == 1
    assert "500" in stats["sources"]["remoteok"]["error"]
    for name in ("remotive", "arbeitnow", "jobicy"):
        assert stats["sources"][name]["new"] > 0
    with session_scope(db) as s:
        run = s.scalars(select(Run).where(Run.stage == "fetch")).one()
        assert run.status == "partial" and "remoteok" in run.error
    assert (
        count(db, select(func.count()).select_from(RawJob).where(RawJob.source == "remoteok")) == 0
    )


def test_all_sources_failing_is_fatal(db):
    client = mock_client(lambda request: httpx.Response(503))
    with pytest.raises(StageError, match="every source failed"):
        fetch_sources(db, client=client)
    with session_scope(db) as s:
        run = s.scalars(select(Run).where(Run.stage == "fetch")).one()
        assert run.status == "failed"
        assert run.stats["errors"] == len(ALL_SOURCES)


# --------------------------------------------------------------------------- ingest


def test_ingest_maps_every_raw_job_and_is_idempotent(db):
    fetch_sources(db, client=mock_client())
    raw = count(db, select(func.count()).select_from(RawJob))
    stats = ingest_raw_jobs(db)
    assert stats["new_jobs"] == raw and stats["errors"] == 0
    assert stats["canonical"] + stats["duplicates"] == raw
    again = ingest_raw_jobs(db)
    assert again["new_jobs"] == 0 and again["pending"] == 0
    assert count(db, select(func.count()).select_from(Job)) == raw


def test_ingest_normalises_fields(ingested):
    with session_scope(ingested) as s:
        cron = s.scalars(select(Job).where(Job.title.like("Senior Backend Engineer%"))).first()
        assert "(m/w/d)" not in cron.title
        assert "<" not in cron.description_text
        # structured salary from the source is kept as-is
        scientist = s.scalars(select(Job).where(Job.title == "Data Scientist")).one()
        assert (scientist.salary_min, scientist.salary_max) == (160000.0, 200000.0)
        assert scientist.salary_currency == "USD" and scientist.salary_period == "year"
        # free-text salary is parsed when there is no structured one
        rails = s.scalars(select(Job).where(Job.title.like("Tech Lead Full-Stack Rails%"))).one()
        assert rails.salary_text == "$170k - $200k"
        assert (rails.salary_min, rails.salary_max) == (170000.0, 200000.0)
        assert rails.salary_currency == "USD" and rails.salary_period == "year"


def test_dedupe_within_a_source(ingested):
    with session_scope(ingested) as s:
        pair = s.scalars(select(Job).where(Job.company == "caronsale").order_by(Job.id)).all()
        assert len(pair) == 2
        assert pair[0].is_duplicate_of is None
        assert pair[1].is_duplicate_of == pair[0].id


def test_dedupe_across_sources_in_one_batch(db):
    fetch_sources(db, client=mock_client())
    with session_scope(db) as s:
        # same posting syndicated to Remote OK a week after Remotive had it
        upsert_raw_jobs(
            s,
            [
                crafted_remoteok(
                    "dupe-1",
                    "Tech Lead Full-Stack Rails Engineer (Remote)",
                    "Mitre Media, Inc.",
                    "2026-10-21T10:00:00+00:00",
                )
            ],
        )
    stats = ingest_raw_jobs(db)
    assert stats["duplicates"] >= 2  # the caronsale pair and the cross-source copy
    with session_scope(db) as s:
        copy_ = s.scalars(select(Job).where(Job.external_id == "dupe-1")).one()
        original = s.scalars(
            select(Job).where(Job.source == "remotive", Job.company == "Mitre Media")
        ).one()
        assert original.is_duplicate_of is None
        assert copy_.is_duplicate_of == original.id


def test_earliest_in_batch_is_canonical_and_later_batches_do_not_flip_it(ingested):
    with session_scope(ingested) as s:
        original = s.scalars(select(Job).where(Job.title == "Director of National Accounts")).one()
        assert original.is_duplicate_of is None
        original_id = original.id
        # posted a month before the existing canonical job, ingested later
        upsert_raw_jobs(
            s,
            [
                crafted_remoteok(
                    "dupe-2",
                    "Director of National Accounts",
                    "Access Destination Services",
                    "2026-10-01T10:00:00+00:00",
                )
            ],
        )
    ingest_raw_jobs(ingested)
    with session_scope(ingested) as s:
        late = s.scalars(select(Job).where(Job.external_id == "dupe-2")).one()
        assert late.is_duplicate_of == original_id
        assert s.get(Job, original_id).is_duplicate_of is None


def test_unmappable_payload_is_counted_not_fatal(ingested):
    with session_scope(ingested) as s:
        upsert_raw_jobs(s, [SourceJob("remotive", "broken", {"id": "broken"})])
    before = count(ingested, select(func.count()).select_from(Job))
    stats = ingest_raw_jobs(ingested)
    assert stats["errors"] == 1 and stats["new_jobs"] == 0
    assert count(ingested, select(func.count()).select_from(Job)) == before
    with session_scope(ingested) as s:
        last = s.scalars(select(Run).where(Run.stage == "ingest").order_by(Run.id.desc())).first()
        assert last.status == "partial"


# --------------------------------------------------------------------------- extract


def canonical_remote_count(db: Path) -> int:
    return count(
        db,
        select(func.count())
        .select_from(Job)
        .where(Job.is_duplicate_of.is_(None), Job.is_remote.is_(True)),
    )


def test_extract_only_canonical_remote_jobs_and_is_idempotent(ingested):
    fake = FakeExtractor()
    summary = extract(ingested, fake)
    expected = canonical_remote_count(ingested)
    assert 0 < expected < count(ingested, select(func.count()).select_from(Job))
    assert summary.targets == summary.ok == expected and summary.failed == 0
    assert len(fake.calls) == expected
    assert summary.total_tokens == expected * 120
    assert summary.cost_usd == pytest.approx(expected * 0.001)
    assert summary.median_latency_ms is not None

    with session_scope(ingested) as s:
        extracted_ids = set(s.scalars(select(Extraction.job_id)))
        non_target = s.scalars(
            select(Job.id).where((Job.is_remote.is_(False)) | (Job.is_duplicate_of.is_not(None)))
        ).all()
        assert not extracted_ids & set(non_target)
        row = s.scalars(select(Extraction)).first()
        assert "python" in row.data["skills"]
        assert row.ok and row.backend == "ollama" and row.model == "fake-current"
        assert row.prompt_version == config.PROMPT_VERSION
        assert (row.input_tokens, row.output_tokens, row.cost_usd) == (100, 20, 0.001)

    again = extract(ingested, fake)
    assert again.targets == 0
    assert len(fake.calls) == expected
    assert count(ingested, select(func.count()).select_from(Extraction)) == expected


def test_extract_force_limit_and_since_days(ingested):
    fake = FakeExtractor()
    first = extract(ingested, fake, limit=3)
    assert first.targets == 3
    with session_scope(ingested) as s:
        done = set(s.scalars(select(Extraction.job_id)))
        newest_left = s.scalars(
            select(Job.id)
            .where(Job.is_duplicate_of.is_(None), Job.is_remote.is_(True), Job.id.not_in(done))
            .order_by(func.coalesce(Job.posted_at, Job.created_at).desc())
        ).first()
        newest_done = min(s.get(Job, i).posted_at for i in done)
        assert newest_done >= s.get(Job, newest_left).posted_at  # newest first
    forced = extract(ingested, fake, limit=3, force=True)
    assert forced.targets == 3
    assert count(ingested, select(func.count()).select_from(Extraction)) == 6

    with session_scope(ingested) as s:
        cutoff = NOW - timedelta(days=10)
        recent = s.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.is_duplicate_of.is_(None),
                Job.is_remote.is_(True),
                func.coalesce(Job.posted_at, Job.created_at) >= cutoff,
            )
        )
    got = extract(ingested, FakeExtractor(model="other"), since_days=10, now=NOW)
    assert got.targets == recent > 0


def test_extraction_rerun_for_another_model_only_adds_that_model(ingested):
    extract(ingested, FakeExtractor())
    n = canonical_remote_count(ingested)
    other = extract(ingested, FakeExtractor(backend="claude", model="fake-claude"), workers=3)
    assert other.targets == n
    assert count(ingested, select(func.count()).select_from(Extraction)) == 2 * n


def test_skills_rebuilt_only_for_the_current_model(ingested):
    extract(ingested, FakeExtractor(backend="claude", model="fake-claude"), workers=2)
    assert count(ingested, select(func.count()).select_from(JobSkill)) == 0

    extract(ingested, FakeExtractor(backend="ollama", model="some-other-model"))
    assert count(ingested, select(func.count()).select_from(JobSkill)) == 0

    extract(ingested, FakeExtractor())  # the configured current one
    n = canonical_remote_count(ingested)
    expected = normalize_skills(["Python", "PostgreSQL", "k8s"])
    with session_scope(ingested) as s:
        rows = s.scalars(select(JobSkill)).all()
        assert rows
        assert len({r.job_id for r in rows}) == n
        plain = [
            r
            for r in rows
            if r.job_id in set(s.scalars(select(Job.id).where(~Job.title.like("%data%"))))
        ]
        assert {r.skill for r in plain} >= set(expected)
        ext = {e.id: e for e in s.scalars(select(Extraction))}
        assert all(ext[r.extraction_id].model == "fake-current" for r in rows)

    # rerunning with --force replaces rows instead of duplicating them
    before = count(ingested, select(func.count()).select_from(JobSkill))
    extract(ingested, FakeExtractor(), force=True)
    assert count(ingested, select(func.count()).select_from(JobSkill)) == before


def test_set_current_rebuilds_skills_for_a_non_default_model(ingested):
    extract(ingested, FakeExtractor(backend="claude", model="fake-claude"), set_current=True)
    assert count(ingested, select(func.count()).select_from(JobSkill)) > 0


def test_per_job_errors_are_stored_and_the_run_continues(ingested):
    fake = FakeExtractor(
        raises={"Rails Engineer": ValueError("boom")}, returns_failure=("Data Scientist",)
    )
    summary = extract(ingested, fake)
    n = canonical_remote_count(ingested)
    assert summary.ok + summary.failed == n and summary.failed >= 2
    with session_scope(ingested) as s:
        failed = s.scalars(select(Extraction).where(Extraction.ok.is_(False))).all()
        assert len(failed) == summary.failed
        by_error = {e.error for e in failed}
        assert any(e.startswith("ValueError: boom") for e in by_error)
        assert "bad json" in by_error
        assert all(e.data is None for e in failed)
        run = s.scalars(select(Run).where(Run.stage == "extract")).one()
        assert run.status == "partial" and run.stats["failed"] == summary.failed
    # failed attempts do not block a retry
    retry = extract(ingested, FakeExtractor())
    assert retry.targets == summary.failed


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (MissingApiKeyError("ANTHROPIC_API_KEY is not set."), "ANTHROPIC_API_KEY"),
        (auth_error(), "rejected the API key"),
        (permission_error(), "rejected the API key"),
        (RuntimeError("Cannot reach the Ollama server. Start it."), "Cannot reach the Ollama"),
        (
            RuntimeError("Ollama model 'x' not found. Run: ollama pull x"),
            "ollama pull x",
        ),
    ],
)
@pytest.mark.parametrize("workers", [1, 3])
def test_configuration_errors_abort_the_stage(ingested, exc, message, workers):
    backend = "claude" if workers > 1 else "ollama"
    fake = FakeExtractor(backend=backend, model="fake-claude", raises={"Engineer": exc})
    with pytest.raises(StageError, match=message):
        extract(ingested, fake, workers=workers)
    with session_scope(ingested) as s:
        stored = s.scalars(select(Extraction)).all()
        # nothing is stored for the job that hit the configuration error
        assert all("Engineer" not in s.get(Job, e.job_id).title for e in stored)
        run = s.scalars(select(Run).where(Run.stage == "extract")).one()
        assert run.status == "failed" and message.split()[0] in run.error


def test_factory_failure_is_a_clear_fatal_error_with_a_run_row(ingested):
    def factory():
        raise MissingApiKeyError("ANTHROPIC_API_KEY is not set. Export it.")

    with pytest.raises(StageError, match="ANTHROPIC_API_KEY"):
        run_extract(factory, ingested, show_progress=False)
    with session_scope(ingested) as s:
        assert s.scalars(select(Run).where(Run.stage == "extract")).one().status == "failed"


def test_results_before_a_fatal_error_stay_committed(ingested):
    fake = FakeExtractor(raises={"Scientist": MissingApiKeyError("no key")})
    with pytest.raises(StageError):
        extract(ingested, fake)
    stored = count(ingested, select(func.count()).select_from(Extraction))
    assert stored == len(fake.calls) - 1 > 0


def test_parallel_workers_store_everything_once(ingested):
    fake = FakeExtractor(backend="claude", model="fake-claude")
    summary = extract(ingested, fake, workers=4)
    n = canonical_remote_count(ingested)
    assert summary.ok == n and len(fake.calls) == n
    assert count(ingested, select(func.count(func.distinct(Extraction.job_id)))) == n


# --------------------------------------------------------------------------- FX and salary


def test_fx_table():
    assert usd_rate("usd") == 1.0
    for code in ["EUR", "GBP", "CAD", "AUD", "CHF", "SEK", "NOK", "DKK", "PLN", "INR", "BRL"]:
        assert usd_rate(code) and usd_rate(code) > 0
    assert usd_rate("XXX") is None and usd_rate(None) is None
    assert to_usd(100, "EUR") == pytest.approx(100 * usd_rate("EUR"))
    assert to_usd(None, "EUR") is None and to_usd(10, "XXX") is None


def test_annualisation_and_conversion():
    eur = usd_rate("EUR")
    monthly = annual_usd(RawSalary(5000, 6000, "EUR", "month"))
    assert monthly.annual_usd_min == pytest.approx(60000 * eur)
    assert monthly.annual_usd_max == pytest.approx(72000 * eur)
    assert monthly.annual_usd_mid == pytest.approx(66000 * eur)
    assert annual_usd(RawSalary(50, 50, "USD", "hour")).annual_usd_mid == pytest.approx(104000)
    assert annual_usd(RawSalary(90000, None, "USD", "year")).annual_usd_mid == 90000
    assert annual_usd(RawSalary(None, 90000, "usd", None)).annual_usd_mid == 90000
    cad = annual_usd(RawSalary(69000, 115000, "CAD", "year"))
    assert cad.annual_usd_mid == pytest.approx(92000 * usd_rate("CAD"))


@pytest.mark.parametrize(
    "salary",
    [
        RawSalary(None, None, "USD", "year"),
        RawSalary(100000, 120000, "XXX", "year"),  # unknown currency
        RawSalary(100000, 120000, None, "year"),  # no currency
        RawSalary(100, 200, "USD", "year"),  # below 5,000
        RawSalary(2_000_000, 3_000_000, "USD", "year"),  # above 1,000,000
        RawSalary(4000, 6000, "USD", "year"),  # lower bound implausible
        RawSalary(100, 200, "USD", "week"),  # unknown period
        RawSalary(1, 2, "USD", "hour"),  # 2,080 - 4,160 a year
    ],
)
def test_implausible_or_unconvertible_salaries_are_excluded(salary):
    assert annual_usd(salary) is None


def test_structured_salary_is_preferred_then_extraction():
    structured = RawSalary(100000, 120000, "USD", "year")
    extracted = RawSalary(50000, 60000, "EUR", "year")
    assert resolve_salary([structured, extracted]).annual_usd_mid == 110000
    unusable = RawSalary(100000, 120000, None, "year")
    assert resolve_salary([unusable, extracted]).raw is extracted
    assert resolve_salary([unusable, RawSalary(None, None, None, None)]) is None


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 25) == 2
    assert percentile([10, 20], 50) == 15
    assert percentile([7], 90) == 7
    assert percentile([1, 2, 3, 4, 5], 90) == pytest.approx(4.6)


# --------------------------------------------------------------------------- aggregate (pure)


def make_record(
    i: int,
    posted: datetime,
    skills=("python",),
    salary: RawSalary | None = None,
    role="data",
    seniority="senior",
    source="remotive",
    company: str | None = None,
) -> JobRecord:
    return JobRecord(
        id=f"{source}-{i}",
        source=source,
        title=f"Job {i}",
        company=company or f"Company {i}",
        url=f"https://example.com/{i}",
        location="Worldwide",
        posted_at=posted,
        role=role,
        seniority=seniority,
        employment_type="full_time",
        remote_regions=["worldwide"],
        skills=list(skills),
        salaries=[salary] if salary else [],
    )


def snapshot_of(records, **kw):
    return compute_snapshot(records, now=NOW, backend="ollama", model="m", **kw)


def skill_of(snapshot, slug):
    return next(s for s in snapshot["skills"] if s["slug"] == slug)


def half_records(prev_jobs: int, prev_python: int, recent_jobs: int, recent_python: int):
    """Records spread over the previous 4 weeks (Sep 14 - Oct 11) and the last 4 weeks."""
    out = []
    prev_day = datetime(2026, 9, 21, 10)  # W39
    recent_day = datetime(2026, 10, 28, 10)  # W44
    for i in range(prev_jobs):
        out.append(make_record(i, prev_day, ("python",) if i < prev_python else ("sql",)))
    for i in range(recent_jobs):
        out.append(
            make_record(1000 + i, recent_day, ("python",) if i < recent_python else ("sql",))
        )
    return out


def test_week_helpers():
    starts = week_starts(NOW, 8)
    assert len(starts) == 8
    assert starts[-1] == datetime(2026, 11, 2) and starts[0] == datetime(2026, 9, 14)
    assert iso_week(NOW) == "2026-W45"
    assert iso_week(datetime(2026, 1, 1)) == "2026-W01"
    assert iso_week(datetime(2027, 1, 1)) == "2026-W53"  # ISO year differs from calendar year


def test_change_4w_in_percentage_points():
    snap = snapshot_of(half_records(20, 10, 20, 15))
    assert skill_of(snap, "python")["change_4w"] == 25.0  # (0.75 - 0.5) * 100
    assert skill_of(snap, "sql")["change_4w"] == -25.0
    assert skill_of(snap, "python")["share"] == pytest.approx(0.625)  # a fraction, not a percent


@pytest.mark.parametrize(("prev", "recent"), [(19, 20), (20, 19), (5, 5), (0, 40), (40, 0)])
def test_change_4w_is_null_when_a_half_has_fewer_than_20_jobs(prev, recent):
    snap = snapshot_of(half_records(prev, prev // 2, recent, recent // 2))
    assert snap["skills"], "fixture must publish skills"
    assert all(s["change_4w"] is None for s in snap["skills"])


def test_weekly_trend_is_zero_filled_and_shares_are_fractions():
    snap = snapshot_of(half_records(20, 10, 20, 15))
    weeks = [w["week"] for w in snap["meta"]["weekly"]]
    assert weeks[0] == "2026-W38" and weeks[-1] == "2026-W45" and len(weeks) == 8
    trend = skill_of(snap, "python")["trend"]
    assert [t["week"] for t in trend] == weeks
    by_week = {t["week"]: t for t in trend}
    assert by_week["2026-W39"] == {"week": "2026-W39", "count": 10, "share": 0.5}
    assert by_week["2026-W44"]["share"] == 0.75
    assert by_week["2026-W40"] == {"week": "2026-W40", "count": 0, "share": 0.0}
    assert sum(w["jobs"] for w in snap["meta"]["weekly"]) == snap["meta"]["totals"]["jobs"] == 40


def test_window_excludes_old_jobs_but_jobs_list_reaches_60_days():
    recent = make_record(1, NOW - timedelta(days=3))
    in_list_only = make_record(2, NOW - timedelta(days=58), source="remoteok")  # before window
    too_old = make_record(3, NOW - timedelta(days=61))
    snap = snapshot_of([recent, in_list_only, too_old])
    assert snap["meta"]["totals"]["jobs"] == 1
    assert [j["id"] for j in snap["jobs"]] == ["remotive-1", "remoteok-2"]  # newest first


def test_skill_salary_median_needs_five_salaried_jobs():
    def jobs(n_salaried):
        out = []
        for i in range(6):
            salary = RawSalary(90000 + i * 1000, None, "USD", "year") if i < n_salaried else None
            out.append(make_record(i, NOW - timedelta(days=2), ("python",), salary))
        return out

    assert skill_of(snapshot_of(jobs(4)), "python")["median_salary_usd"] is None
    snap = snapshot_of(jobs(5))
    assert skill_of(snap, "python")["median_salary_usd"] == 92000
    assert snap["meta"]["totals"]["with_salary"] == 5
    assert snapshot_of(jobs(4))["salary"] == {"by_seniority": [], "by_role": []}
    assert snap["salary"]["by_seniority"][0] == {
        "key": "senior", "n": 5, "p10": 90400, "p25": 91000, "median": 92000,
        "p75": 93000, "p90": 93600,
    }  # fmt: skip
    assert snap["roles"] == [{"role": "data", "count": 6, "median_salary_usd": 92000}]


def test_jobs_list_salary_midpoint_and_exclusions():
    records = [
        make_record(1, NOW - timedelta(days=1), salary=RawSalary(4000, 6000, "EUR", "month")),
        make_record(2, NOW - timedelta(days=2), salary=RawSalary(80000, None, "USD", "year")),
        make_record(3, NOW - timedelta(days=3), salary=RawSalary(80000, 90000, "XXX", "year")),
        make_record(4, NOW - timedelta(days=4), salary=RawSalary(10, 20, "USD", "year")),
    ]
    jobs = {j["id"]: j for j in snapshot_of(records)["jobs"]}
    eur = usd_rate("EUR")
    assert jobs["remotive-1"]["salary"] == {
        "min": 4000, "max": 6000, "currency": "EUR", "period": "month",
        "annual_usd_mid": round(60000 * eur),
    }  # fmt: skip
    assert jobs["remotive-2"]["salary"]["annual_usd_mid"] == 80000
    assert jobs["remotive-2"]["salary"]["max"] is None
    assert jobs["remotive-3"]["salary"] is None and jobs["remotive-4"]["salary"] is None


def test_skills_cooccurrence_roles_and_totals():
    records = []
    for i in range(6):
        records.append(
            make_record(i, NOW - timedelta(days=1), ("python", "sql", "dbt"), company="A")
        )
    for i in range(6, 9):
        records.append(make_record(i, NOW - timedelta(days=1), ("python", "rare-skill")))
    records.append(make_record(9, NOW - timedelta(days=1), ("only-once",), role="design"))
    snap = snapshot_of(records)
    slugs = [s["slug"] for s in snap["skills"]]
    assert slugs[0] == "python" and "only-once" not in slugs  # below the publish threshold
    python = skill_of(snap, "python")
    assert python["count"] == 9 and python["share"] == 0.9
    assert python["cooccurring"][0] == {"slug": "dbt", "count": 6}  # tie with sql, slug order
    assert {"slug": "rare-skill", "count": 3} in python["cooccurring"]
    assert [r["role"] for r in snap["roles"]] == ["data", "design"]
    assert snap["meta"]["totals"]["companies"] == 1 + 3 + 1  # six jobs share company "A"
    assert snap["meta"]["totals"]["skills"] == len(snap["skills"])
    assert [s["name"] for s in snap["meta"]["sources"]] == [s.name for s in ALL_SOURCES]


def test_enum_strings_are_used_verbatim():
    records = [
        make_record(
            i, NOW - timedelta(days=1), role="software_engineering", seniority="unspecified"
        )
        for i in range(5)
    ]
    snap = snapshot_of(records)
    job = snap["jobs"][0]
    assert (job["role"], job["seniority"], job["employment_type"]) == (
        "software_engineering",
        "unspecified",
        "full_time",
    )
    assert snap["roles"][0]["role"] == "software_engineering"


# --------------------------------------------------------------------------- snapshot schema

NUM = (int, float)
OPT_NUM = (int, float, type(None))
OPT_STR = (str, type(None))
SALARY_DIST = {"key": str, "n": int, "p10": NUM, "p25": NUM, "median": NUM, "p75": NUM, "p90": NUM}
SCHEMAS = {
    "meta": {
        "generated_at": str,
        "last_run_at": str,
        "window_days": int,
        "backend": str,
        "model": str,
        "totals": {"jobs": int, "companies": int, "with_salary": int, "skills": int},
        "sources": [{"name": str, "display_name": str, "homepage": str, "jobs": int}],
        "weekly": [{"week": str, "jobs": int}],
    },
    "skills": [
        {
            "slug": str,
            "name": str,
            "category": str,
            "count": int,
            "share": NUM,
            "change_4w": OPT_NUM,
            "median_salary_usd": OPT_NUM,
            "trend": [{"week": str, "count": int, "share": NUM}],
            "cooccurring": [{"slug": str, "count": int}],
        }
    ],
    "roles": [{"role": str, "count": int, "median_salary_usd": OPT_NUM}],
    "salary": {"by_seniority": [SALARY_DIST], "by_role": [SALARY_DIST]},
    "jobs": [
        {
            "id": str,
            "title": str,
            "company": str,
            "url": str,
            "source": str,
            "posted_at": str,
            "location": OPT_STR,
            "remote_regions": [str],
            "role": str,
            "seniority": str,
            "employment_type": str,
            "skills": [str],
            "salary": (
                type(None),
                {
                    "min": OPT_NUM,
                    "max": OPT_NUM,
                    "currency": str,
                    "period": str,
                    "annual_usd_mid": NUM,
                },
            ),
        }
    ],
}


def check_schema(value, spec, path="$"):
    """Tiny structural validator: dict spec = exact keys, list spec = homogeneous list,
    tuple spec = any of the alternatives, otherwise an isinstance check."""
    if isinstance(spec, dict):
        assert isinstance(value, dict), f"{path}: expected object, got {type(value).__name__}"
        assert set(value) == set(spec), f"{path}: keys {sorted(value)} != {sorted(spec)}"
        for key, sub in spec.items():
            check_schema(value[key], sub, f"{path}.{key}")
    elif isinstance(spec, list):
        assert isinstance(value, list), f"{path}: expected array"
        for i, item in enumerate(value):
            check_schema(item, spec[0], f"{path}[{i}]")
    elif isinstance(spec, tuple):
        errors = []
        for alt in spec:
            try:
                check_schema(value, alt, path)
                return
            except AssertionError as exc:
                errors.append(str(exc))
        raise AssertionError(f"{path}: no alternative matched: {errors}")
    else:
        assert isinstance(value, spec), f"{path}: {value!r} is not {spec}"
        assert not isinstance(value, bool) or spec is bool, f"{path}: unexpected bool"


def test_schema_checker_catches_problems():
    with pytest.raises(AssertionError):
        check_schema({"a": 1, "b": 2}, {"a": int})
    with pytest.raises(AssertionError):
        check_schema("x", OPT_NUM)
    check_schema(None, OPT_NUM)


# --------------------------------------------------------------------------- publish


@pytest.fixture
def extracted(ingested) -> Path:
    extract(ingested, FakeExtractor())
    return ingested


def test_publish_writes_files_matching_the_contract(extracted, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "eval.json").write_text('{"keep":"me"}', encoding="utf-8")
    (out / "meta.json").write_text('{"sample":true}', encoding="utf-8")

    result = publish(extracted, out, now=NOW)

    assert sorted(p.name for p in out.iterdir()) == sorted([*FILES.values(), "eval.json"])
    assert (out / "eval.json").read_text(encoding="utf-8") == '{"keep":"me"}'
    docs = {
        key: json.loads((out / name).read_text(encoding="utf-8")) for key, name in FILES.items()
    }
    for key, doc in docs.items():
        check_schema(doc, SCHEMAS[key], key)
    assert "sample" not in docs["meta"]
    assert docs["meta"]["backend"] == "ollama" and docs["meta"]["model"] == "fake-current"
    assert docs["meta"]["window_days"] == 56
    assert docs["meta"]["generated_at"] == "2026-11-07T12:00:00Z"
    assert docs["meta"]["last_run_at"].endswith("Z")
    assert docs["meta"]["totals"]["jobs"] == canonical_remote_count(extracted) == result["jobs"]
    assert sum(s["jobs"] for s in docs["meta"]["sources"]) == docs["meta"]["totals"]["jobs"]
    assert [s["name"] for s in docs["meta"]["sources"]] == [s.name for s in ALL_SOURCES]

    # skills: sorted by count, canonical slugs, fractions
    counts = [s["count"] for s in docs["skills"]]
    assert counts == sorted(counts, reverse=True)
    python = skill_of(docs, "python")
    assert python["name"] == "Python" and python["category"] == "language"
    assert 0 < python["share"] <= 1
    assert all(s["change_4w"] is None for s in docs["skills"])  # fixtures are tiny
    assert all(len(s["trend"]) == 8 and len(s["cooccurring"]) <= 8 for s in docs["skills"])

    # jobs: no descriptions, only canonical remote jobs, structured salary converted
    with session_scope(extracted) as s:
        valid = {
            f"{j.source}-{j.external_id}"
            for j in s.scalars(
                select(Job).where(Job.is_duplicate_of.is_(None), Job.is_remote.is_(True))
            )
        }
    assert {j["id"] for j in docs["jobs"]} == valid
    assert all("description" not in j for j in docs["jobs"])
    posted = [j["posted_at"] for j in docs["jobs"]]
    assert posted == sorted(posted, reverse=True)
    by_title = {j["title"]: j for j in docs["jobs"]}
    cad = by_title["Database Programmer"]["salary"]
    assert (cad["min"], cad["max"], cad["currency"], cad["period"]) == (
        75000,
        125000,
        "CAD",
        "year",
    )
    assert cad["annual_usd_mid"] == round(100000 * usd_rate("CAD"))
    nurse = next(j for j in docs["jobs"] if j["title"].startswith("Licensed Practical Nurse"))
    assert nurse["salary"]["period"] == "hour" and nurse["salary"]["annual_usd_mid"] == 40 * 2080
    eur_job = by_title["CRM Marketing Intern"]["salary"]
    assert eur_job["annual_usd_mid"] == round(600 * 12 * usd_rate("EUR"))
    assert by_title["Senior Staff Infrastructure & Security Engineer"]["salary"][
        "annual_usd_mid"
    ] == round((137318 + 192960) / 2)

    # with_salary counts exactly the jobs that have a published salary in the window
    assert docs["meta"]["totals"]["with_salary"] == sum(1 for j in docs["jobs"] if j["salary"])

    with session_scope(extracted) as s:
        run = s.scalars(select(Run).where(Run.stage == "publish")).one()
        assert run.status == "ok" and run.stats["jobs"] == result["jobs"]


def test_publish_defaults_to_the_web_data_dir(extracted, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WEB_DATA_DIR", tmp_path / "web-data")
    publish(extracted, now=NOW)
    assert (tmp_path / "web-data" / "meta.json").exists()


def test_publish_refuses_to_overwrite_with_an_empty_snapshot(ingested, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "meta.json").write_text('{"previous": true}', encoding="utf-8")
    with pytest.raises(StageError, match="refusing to overwrite"):
        publish(ingested, out, now=NOW)  # nothing extracted yet
    assert json.loads((out / "meta.json").read_text(encoding="utf-8")) == {"previous": True}
    publish(ingested, out, now=NOW, allow_empty=True)
    assert json.loads((out / "meta.json").read_text(encoding="utf-8"))["totals"]["jobs"] == 0
    with session_scope(ingested) as s:
        statuses = [
            r.status for r in s.scalars(select(Run).where(Run.stage == "publish").order_by(Run.id))
        ]
    assert statuses == ["failed", "ok"]


def test_publish_for_another_backend_uses_that_models_extractions(extracted, tmp_path):
    out = tmp_path / "out"
    with pytest.raises(StageError):
        publish(extracted, out, backend="claude", model="fake-claude", now=NOW)
    extract(extracted, FakeExtractor(backend="claude", model="fake-claude"))
    publish(extracted, out, backend="claude", model="fake-claude", now=NOW)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert (meta["backend"], meta["model"]) == ("claude", "fake-claude")


def test_write_snapshot_is_atomic_and_rejects_sample_flag(extracted, tmp_path):
    out = tmp_path / "out"
    publish(extracted, out, now=NOW)
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    snapshot = {
        key: json.loads((out / name).read_text(encoding="utf-8")) for key, name in FILES.items()
    }

    broken = {**snapshot, "jobs": [object()]}  # fails to serialise after the others are staged
    with pytest.raises(TypeError):
        write_snapshot(broken, out)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before  # no temp files, no change

    flagged = {**snapshot, "meta": {**snapshot["meta"], "sample": True}}
    with pytest.raises(ValueError, match="sample"):
        write_snapshot(flagged, out)
    with pytest.raises(ValueError):
        write_snapshot({"meta": snapshot["meta"]}, out)


# --------------------------------------------------------------------------- CLI

runner = CliRunner()


def test_cli_stats_and_aggregate_and_publish(extracted, tmp_path):
    result = runner.invoke(app, ["--db", str(extracted), "stats"])
    assert result.exit_code == 0, result.output
    assert "fake-current" in result.output and "canonical remote" in result.output

    result = runner.invoke(app, ["--db", str(extracted), "aggregate"])
    assert result.exit_code == 0, result.output
    assert "python" in result.output.lower()

    out = tmp_path / "cli-out"
    result = runner.invoke(app, ["--db", str(extracted), "publish", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "jobs.json").exists()


def test_cli_aggregate_writes_nothing(extracted, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WEB_DATA_DIR", tmp_path / "web-data")
    assert runner.invoke(app, ["--db", str(extracted), "aggregate"]).exit_code == 0
    assert not (tmp_path / "web-data").exists()


def test_cli_extract_without_api_key_exits_nonzero(ingested, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(app, ["--db", str(ingested), "extract", "--backend", "claude"])
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output
    with session_scope(ingested) as s:
        assert s.scalars(select(Run).where(Run.stage == "extract")).one().status == "failed"


def test_cli_rejects_unknown_backend(ingested):
    result = runner.invoke(app, ["--db", str(ingested), "extract", "--backend", "gpt"])
    assert result.exit_code != 0


def test_cli_run_all_stops_on_a_fatal_stage_error(db, monkeypatch):
    from radar import cli

    calls = []
    monkeypatch.setattr(cli, "fetch_sources", lambda d: {"sources": {}, "new": 0, "seen": 0})
    monkeypatch.setattr(
        cli,
        "ingest_raw_jobs",
        lambda d: {"pending": 0, "canonical": 0, "duplicates": 0, "errors": 0},
    )

    def boom(*a, **k):
        calls.append("extract")
        raise StageError("Ollama is not reachable")

    monkeypatch.setattr(cli, "run_extract", boom)
    monkeypatch.setattr(cli, "publish", lambda *a, **k: calls.append("publish"))
    result = runner.invoke(app, ["--db", str(db), "run-all"])
    assert result.exit_code == 1
    assert "Ollama is not reachable" in result.output
    assert calls == ["extract"]  # publish never ran
