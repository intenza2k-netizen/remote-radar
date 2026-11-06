"""Active-listing rule (PLAN.md v3): published lists hold only jobs a source still lists.

A job is active when its raw ``last_seen_at`` is within ``ACTIVE_DAYS`` of the latest
successful fetch of *its own source*; statistics keep using the whole window. Everything
runs offline against a hand-built SQLite database.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import event

from radar import config, embed
from radar.aggregate import (
    JobRecord,
    active_job_ids,
    aggregate,
    compute_snapshot,
    listed_records,
    load_snapshot_records,
    source_reference_times,
)
from radar.db import session_scope
from radar.embed import run_embed
from radar.models import Extraction, Job, RawJob, Run
from radar.publish import publish
from radar.sources import ALL_SOURCES

NOW = datetime(2026, 11, 12, 12, 0)  # a week after the last fetches: wall-clock must not matter
POSTED = datetime(2026, 11, 2, 12, 0)  # inside the 8-week window for every job below
BACKEND, MODEL = "ollama", "m"


# --------------------------------------------------------------------------- builders


def add_run(session, finished: datetime, sources: dict[str, int], status: str = "ok") -> None:
    """A fetch ``Run`` where each named source had that many errors."""
    session.add(
        Run(
            stage="fetch",
            status=status,
            started_at=finished - timedelta(minutes=2),
            finished_at=finished,
            stats={
                "sources": {
                    name: {
                        "new": 0,
                        "seen": 0,
                        "errors": errors,
                        "error": "boom" if errors else None,
                    }
                    for name, errors in sources.items()
                }
            },
        )
    )


_counter = {"n": 0}


def add_job(
    session,
    source: str,
    ext: str,
    seen: datetime,
    *,
    company: str | None = None,
    key: str | None = None,
    duplicate_of: Job | None = None,
    skills=("python",),
    salary: tuple[float, float] | None = None,
    regions=("worldwide",),
    description: str | None = None,
) -> Job:
    """Raw job + normalised job (+ ok extraction for canonical ones)."""
    _counter["n"] += 1
    raw = RawJob(source=source, external_id=ext, first_seen_at=seen, last_seen_at=seen, payload={})
    session.add(raw)
    session.flush()
    job = Job(
        raw_job_id=raw.id,
        source=source,
        external_id=ext,
        title=f"Data Engineer {source}-{ext}",
        company=company or f"Co {source} {ext}",
        url=f"https://example.com/{source}/{ext}",
        location="Worldwide",
        is_remote=True,
        posted_at=POSTED,
        description_text=description or f"Build pipelines, role {ext}.",
        salary_min=salary[0] if salary else None,
        salary_max=salary[1] if salary else None,
        salary_currency="USD" if salary else None,
        salary_period="year" if salary else None,
        dedupe_key=key or f"key-{source}-{ext}",
        is_duplicate_of=duplicate_of.id if duplicate_of else None,
    )
    session.add(job)
    session.flush()
    if duplicate_of is None:
        session.add(
            Extraction(
                job_id=job.id,
                backend=BACKEND,
                model=MODEL,
                prompt_version=config.PROMPT_VERSION,
                ok=True,
                data={
                    "role_category": "data",
                    "seniority": "senior",
                    "employment_type": "full_time",
                    "remote_regions": list(regions),
                    "skills": list(skills),
                },
            )
        )
    return job


def at(day: int, hour: int = 10, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute)


@pytest.fixture
def world(tmp_path):
    """A database with three sources fetched at different times.

    remotive: fetched 11-05 10:00. remoteok: fetched 10-30 10:00 (a later run in which it
    failed must not move its reference). arbeitnow: no run rows at all (fallback to the
    newest ``last_seen_at``). jobicy: no jobs.
    """
    path = tmp_path / "active.sqlite"
    with session_scope(path) as s:
        add_run(s, at(5), {"remotive": 0, "jobicy": 0})
        add_run(s, at(30, month=10), {"remoteok": 0})
        add_run(s, at(10), {"remoteok": 1}, status="partial")  # failed fetch: no new reference
        # runs without usable per-source stats, or that failed, are ignored
        s.add(Run(stage="fetch", status="ok", finished_at=at(11), stats={"new": 3}))
        s.add(Run(stage="fetch", status="failed", finished_at=at(11), stats={}))

        # remotive (reference 11-05 10:00)
        add_job(s, "remotive", "r1", at(5, 9, 50), company="Acme")  # active
        add_job(s, "remotive", "r2", at(3, 10), company="Acme")  # 2 days: active
        add_job(s, "remotive", "r3", at(2, 10), company="Beta")  # exactly 3 days: active
        add_job(s, "remotive", "r4", at(2, 9, 59), company="Acme")  # 3 days + 1 min: expired
        add_job(s, "remotive", "r5", at(20, month=10), company="Gone Corp")  # expired

        # remoteok (reference 10-30 10:00, not the failed run on 11-10)
        add_job(s, "remoteok", "o1", at(30, 9, 55, month=10), company="Beta")  # active
        add_job(s, "remoteok", "o2", at(25, month=10), company="Delta")  # expired

        # arbeitnow (no run: reference = newest last_seen_at = 11-01 12:00)
        add_job(s, "arbeitnow", "a1", at(1, 12))  # active (it is the reference)
        add_job(s, "arbeitnow", "a2", at(29, 12, month=10))  # exactly 3 days: active
        add_job(s, "arbeitnow", "a3", at(28, 12, month=10))  # expired

        # duplicates: the canonical copy on remotive is gone, the copy on remoteok is not
        d1 = add_job(s, "remotive", "d1", at(25, month=10), company="Dupco", key="dup1")
        add_job(s, "remoteok", "d1x", at(29, 12, month=10), company="Dupco", key="dup1",
                duplicate_of=d1)  # fmt: skip
        # both copies gone
        d2 = add_job(s, "remotive", "d2", at(25, month=10), company="Dupco2", key="dup2")
        add_job(s, "remotive", "d2x", at(24, month=10), company="Dupco2", key="dup2",
                duplicate_of=d2)  # fmt: skip
    return path


ACTIVE_IDS = {
    "remotive-r1",
    "remotive-r2",
    "remotive-r3",
    "remoteok-o1",
    "arbeitnow-a1",
    "arbeitnow-a2",
    "remotive-d1",
}
EXPIRED_IDS = {"remotive-r4", "remotive-r5", "remoteok-o2", "arbeitnow-a3", "remotive-d2"}


def snapshot_of(path, **kw):
    with session_scope(path) as s:
        return aggregate(s, backend=BACKEND, model=MODEL, now=NOW, **kw)


# --------------------------------------------------------------------------- reference time


def test_active_days_constant():
    assert config.ACTIVE_DAYS == 3


def test_reference_is_the_latest_successful_fetch_per_source(world):
    with session_scope(world) as s:
        ref = source_reference_times(s)
    assert ref["remotive"] == at(5)  # run finish time beats the newest last_seen_at
    assert ref["remoteok"] == at(30, month=10)  # the failed run on 11-10 does not count
    assert ref["arbeitnow"] == at(1, 12)  # no run: newest last_seen_at of its raw jobs
    assert ref["jobicy"] == at(5)


def test_active_and_expired_per_source_reference(world):
    with session_scope(world) as s:
        records, *_ = load_snapshot_records(s, backend=BACKEND, model=MODEL, now=NOW)
    by_id = {r.id: r.active for r in records}
    assert {i for i, a in by_id.items() if a} == ACTIVE_IDS
    assert {i for i, a in by_id.items() if not a} == EXPIRED_IDS
    assert len(by_id) == 12  # duplicates are not records


def test_a_pipeline_that_has_not_run_for_a_week_still_publishes_its_jobs(world):
    # NOW is 7+ days after every fetch; an absolute-age rule would publish nothing
    snap = snapshot_of(world)
    assert {j["id"] for j in snap["jobs"]} == ACTIVE_IDS


def test_active_days_boundary_is_inclusive(world):
    with session_scope(world) as s:
        loose = active_job_ids(s, active_days=4)
        tight = active_job_ids(s, active_days=2)
        ids = {j.id: f"{j.source}-{j.external_id}" for j in s.query(Job).all()}
    assert {ids[i] for i in loose} >= ACTIVE_IDS | {"remotive-r4"}
    assert "remotive-r3" not in {ids[i] for i in tight}
    assert "remotive-r2" in {ids[i] for i in tight}


def test_seeing_a_job_again_makes_it_active_again(world):
    with session_scope(world) as s:
        raw = s.query(RawJob).filter_by(external_id="r4").one()
        raw.last_seen_at = at(5, 9, 55)
    snap = snapshot_of(world)
    assert "remotive-r4" in {j["id"] for j in snap["jobs"]}


# --------------------------------------------------------------------------- duplicates


def test_canonical_stays_active_while_a_duplicate_on_another_board_is_listed(world):
    snap = snapshot_of(world)
    listed = {j["id"] for j in snap["jobs"]}
    assert "remotive-d1" in listed  # canonical expired, remoteok duplicate still listed
    assert "remotive-d2" not in listed  # every copy expired
    dupco = next(c for c in snap["companies"] if c["name"] == "Dupco")
    assert dupco["job_ids"] == ["remotive-d1"]


def test_duplicate_listed_only_relative_to_its_own_sources_reference(world):
    # d1x was seen 10-29 12:00, which is 22 h before remoteok's reference but 7 days before
    # remotive's: judged against the wrong source it would be expired.
    with session_scope(world) as s:
        d1 = s.query(Job).filter_by(external_id="d1").one()
        assert d1.id in active_job_ids(s)
        d1x = s.query(Job).filter_by(external_id="d1x").one()
        d1x.source = "remotive"  # now compared with remotive's reference
    with session_scope(world) as s:
        assert d1.id not in active_job_ids(s)


# --------------------------------------------------------------------------- published lists


def test_lists_are_filtered_but_statistics_are_not(world):
    snap = snapshot_of(world)
    assert {j["id"] for j in snap["jobs"]} == ACTIVE_IDS

    with session_scope(world) as s:
        records, *_ = load_snapshot_records(s, backend=BACKEND, model=MODEL, now=NOW)
    assert len(records) == 12
    everything_active = compute_snapshot(
        [dataclasses.replace(r, active=True) for r in records],
        now=NOW,
        backend=BACKEND,
        model=MODEL,
    )
    for key in ("skills", "roles", "salary", "insights", "skill_vocab"):
        assert snap[key] == everything_active[key], key
    assert snap["meta"]["weekly"] == everything_active["meta"]["weekly"]
    assert snap["meta"]["totals"]["jobs"] == 12
    python = next(s for s in snap["skills"] if s["slug"] == "python")
    assert python["count"] == 12
    assert sum(r["count"] for r in snap["roles"]) == 12
    assert {j["id"] for j in everything_active["jobs"]} == ACTIVE_IDS | EXPIRED_IDS


def test_listed_records_filters_inactive():
    base = dict(
        source="remotive", title="t", company="c", url="u", location=None,
        posted_at=NOW - timedelta(days=1), role="data", seniority="senior",
        employment_type="full_time", remote_regions=[], skills=[],
    )  # fmt: skip
    records = [JobRecord(id="a", **base), JobRecord(id="b", active=False, **base)]
    assert [r.id for r in listed_records(records, NOW)] == ["a"]


def test_company_job_lists_and_counts_cover_active_jobs_only(world):
    snap = snapshot_of(world)
    companies = {c["name"]: c for c in snap["companies"]}
    acme = companies["Acme"]
    assert acme["jobs"] == 2 and acme["jobs_total"] == 3
    assert set(acme["job_ids"]) == {"remotive-r1", "remotive-r2"}  # r4 expired
    assert sum(acme["roles"].values()) == acme["jobs"]
    beta = companies["Beta"]
    assert beta["jobs"] == beta["jobs_total"] == 2
    assert set(beta["sources"]) == {"remotive", "remoteok"}
    # companies whose every posting expired are not published
    assert "Gone Corp" not in companies and "Delta" not in companies and "Dupco2" not in companies
    listed = {j["id"] for j in snap["jobs"]}
    assert all(set(c["job_ids"]) <= listed for c in snap["companies"])
    assert sum(c["jobs"] for c in snap["companies"]) == len(ACTIVE_IDS)
    # one definition of "companies hiring": totals.companies is exactly the published
    # company list; the window-wide count (expired postings included) is kept separately
    assert snap["meta"]["totals"]["companies"] == len(snap["companies"]) == 5
    assert snap["meta"]["totals"]["companies_window"] == 9


# ------------------------------------------------------------------- regions and skill names


def test_snapshot_canonicalises_regions_and_names_every_listed_skill(tmp_path):
    path = tmp_path / "names.sqlite"
    with session_scope(path) as s:
        add_job(
            s, "remotive", "n1", at(5, 9, 50), company="Acme",
            regions=("USA", "AL", "AZ", "IL", "IN", "Czech Republic", "AMER", "Türkiye"),
            skills=("zorblax ops", "python", "quux strategy", "ai tools"),
            description="We use ZORBLAX OPS daily. Our ZORBLAX OPS rigour and some AI Tools. "
            "Quux strategy matters; zorblax ops too.",
        )  # fmt: skip
        add_job(
            s, "remotive", "n2", at(5, 9, 40), company="Beta",
            regions=("United States", "Turkey", "CA", "Worldwide"),
            skills=("zorblax ops", "mystery tool"),
            description="Ask about the ZORBLAX OPS process.",
        )  # fmt: skip
    snap = snapshot_of(path)
    by_id = {j["id"]: j for j in snap["jobs"]}
    assert by_id["remotive-n1"]["remote_regions"] == [
        "United States", "Czechia", "Americas", "Türkiye",
    ]  # fmt: skip
    assert by_id["remotive-n2"]["remote_regions"] == [
        "United States", "Türkiye", "Canada", "worldwide",
    ]  # fmt: skip

    names = snap["meta"]["skill_names"]
    listed = {s for j in snap["jobs"] for s in j["skills"]}
    assert set(names) == listed  # a name for every slug in jobs.json
    assert names["python"] == "Python"  # curated names are kept
    assert names["zorblax-ops"] == "ZORBLAX OPS"  # spelling seen in the postings
    assert names["mystery-tool"] == "Mystery Tool"  # nothing seen: title-cased slug
    assert names["quux-strategy"] == "Quux Strategy"
    assert names["ai-tools"] == "AI Tools"
    # the derived names are used by the other documents too
    top = {t["slug"]: t["name"] for c in snap["companies"] for t in c["top_skills"]}
    assert top["zorblax-ops"] == "ZORBLAX OPS"
    skill_rows = {r["slug"]: r["name"] for r in snap["skills"]}
    assert all(names[slug] == name for slug, name in skill_rows.items())


# --------------------------------------------------------------------------- meta


def test_meta_has_active_totals_and_per_source_scope(world):
    sources = [
        SimpleNamespace(name="remotive", display_name="Remotive", homepage="h", scope="targeted"),
        SimpleNamespace(name="remoteok", display_name="Remote OK", homepage="h"),  # no scope
        SimpleNamespace(name="arbeitnow", display_name="Arbeitnow", homepage="h", scope="x"),
        SimpleNamespace(name="jobicy", display_name="Jobicy", homepage="h", scope="broad"),
    ]
    meta = snapshot_of(world, sources=sources)["meta"]
    assert meta["totals"]["jobs"] == 12 and meta["totals"]["active"] == len(ACTIVE_IDS)
    rows = {s["name"]: s for s in meta["sources"]}
    assert rows["remotive"] == {
        "name": "remotive",
        "display_name": "Remotive",
        "homepage": "h",
        "scope": "targeted",
        "jobs": 7,
        "active": 3,  # r1-r3; d1 is credited to the board that still lists it
    }
    assert (rows["remoteok"]["scope"], rows["remoteok"]["jobs"], rows["remoteok"]["active"]) == (
        "broad",
        2,
        2,  # o1 and d1 (via its remoteok copy); "jobs" still counts o1, o2
    )
    assert rows["arbeitnow"]["scope"] == "broad"  # unknown value falls back
    assert (rows["arbeitnow"]["jobs"], rows["arbeitnow"]["active"]) == (3, 2)
    assert (rows["jobicy"]["jobs"], rows["jobicy"]["active"]) == (0, 0)
    assert sum(s["active"] for s in meta["sources"]) == meta["totals"]["active"]
    # existing keys are all still there
    assert {"generated_at", "last_run_at", "window_days", "backend", "model", "weekly"} <= set(meta)
    assert {"jobs", "companies", "with_salary", "skills"} <= set(meta["totals"])


def test_registered_sources_publish_a_valid_scope(world):
    meta = snapshot_of(world)["meta"]
    assert [s["name"] for s in meta["sources"]] == [s.name for s in ALL_SOURCES]
    assert all(s["scope"] in config.SOURCE_SCOPES for s in meta["sources"])
    assert sum(s["active"] for s in meta["sources"]) == meta["totals"]["active"]


# --------------------------------------------------------------------------- vectors


class FakeEmbedder:
    dim = config.EMBED_DIM

    def __init__(self) -> None:
        self.model_key = embed.current_model_key()
        self.texts: list[str] = []

    def embed(self, texts, *, query: bool = False) -> np.ndarray:
        self.texts += list(texts)
        rows = [
            np.random.default_rng(len(t) + i).normal(size=self.dim) for i, t in enumerate(texts)
        ]
        return embed.normalize_rows(np.array(rows))


def test_only_active_jobs_are_embedded_and_published_as_vectors(world, tmp_path):
    fake = FakeEmbedder()
    summary = run_embed(world, backend=BACKEND, model=MODEL, now=NOW, embedder=fake)
    assert summary.total == len(ACTIVE_IDS) and len(fake.texts) == len(ACTIVE_IDS)
    assert not any("remotive-r4" in t for t in fake.texts)  # expired: never embedded
    assert all(any(i in t for t in fake.texts) for i in ACTIVE_IDS)

    out = tmp_path / "out"
    publish(world, out, backend=BACKEND, model=MODEL, now=NOW)
    jobs = json.loads((out / "jobs.json").read_text(encoding="utf-8"))
    vectors = json.loads((out / "job_vectors.json").read_text(encoding="utf-8"))
    assert {j["id"] for j in jobs} == ACTIVE_IDS
    assert set(vectors["ids"]) == ACTIVE_IDS and len(vectors["ids"]) == len(ACTIVE_IDS)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["totals"]["active"] == len(ACTIVE_IDS)


def test_an_expired_job_with_a_cached_vector_is_not_published(world, tmp_path):
    # embed while everything is listed, then let r3 expire: its vector must disappear
    with session_scope(world) as s:
        for raw in s.query(RawJob).filter(RawJob.source == "remotive"):
            raw.last_seen_at = at(5, 9, 50)
    run_embed(world, backend=BACKEND, model=MODEL, now=NOW, embedder=FakeEmbedder())
    with session_scope(world) as s:
        raw = s.query(RawJob).filter_by(external_id="r3").one()
        raw.last_seen_at = at(1)
    out = tmp_path / "out"
    publish(world, out, backend=BACKEND, model=MODEL, now=NOW)
    vectors = json.loads((out / "job_vectors.json").read_text(encoding="utf-8"))
    assert "remotive-r3" not in vectors["ids"]
    assert "remotive-r1" in vectors["ids"]


# --------------------------------------------------------------------------- performance


def test_active_ids_use_a_constant_number_of_queries(tmp_path):
    path = tmp_path / "big.sqlite"
    n = 3000
    with session_scope(path) as s:
        add_run(s, at(5), {"remotive": 0, "remoteok": 0})
        raws = [
            RawJob(
                source="remotive" if i % 2 else "remoteok",
                external_id=str(i),
                first_seen_at=at(5, 9) - timedelta(days=i % 6),
                last_seen_at=at(5, 9) - timedelta(days=i % 6),
                payload={},
            )
            for i in range(n)
        ]
        s.add_all(raws)
        s.flush()
        s.add_all(
            Job(
                raw_job_id=raw.id,
                source=raw.source,
                external_id=raw.external_id,
                title="t",
                company="c",
                url="u",
                dedupe_key=f"k{i % 2500}",
                is_duplicate_of=None if i < 2500 else raws[i - 2500].id,
            )
            for i, raw in enumerate(raws)
        )
    statements: list[str] = []
    with session_scope(path) as s:
        engine = s.get_bind()

        def count(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        try:
            ids = active_job_ids(s)
        finally:
            event.remove(engine, "before_cursor_execute", count)
    assert len(statements) <= 3
    assert 0 < len(ids) <= n


# --------------------------------------------------------------------------- consistent counts


def test_totals_active_equals_the_published_job_list(world, tmp_path):
    # r3 stays listed by its board but was posted 61 days ago: outside the 60-day list, so it
    # is neither in jobs.json nor in totals.active, per-source active, vectors or companies.
    with session_scope(world) as s:
        s.query(Job).filter_by(external_id="r3").one().posted_at = NOW - timedelta(days=61)
    run_embed(world, backend=BACKEND, model=MODEL, now=NOW, embedder=FakeEmbedder())
    out = tmp_path / "out"
    publish(world, out, backend=BACKEND, model=MODEL, now=NOW)
    read = lambda name: json.loads((out / name).read_text(encoding="utf-8"))  # noqa: E731
    jobs, meta = read("jobs.json"), read("meta.json")
    listed = ACTIVE_IDS - {"remotive-r3"}
    assert {j["id"] for j in jobs} == listed
    assert meta["totals"]["active"] == len(jobs) == len(listed)
    assert sum(s["active"] for s in meta["sources"]) == len(jobs)
    for source in meta["sources"]:
        assert source["active"] == sum(1 for j in jobs if j["source"] == source["name"])
    assert set(read("job_vectors.json")["ids"]) == listed
    assert {i for c in read("companies.json") for i in c["job_ids"]} == listed
    assert sum(c["jobs"] for c in read("companies.json")) == len(jobs)


# --------------------------------------------------------------------------- no dead links


def test_expired_canonical_publishes_the_live_copys_url_and_source(world):
    snap = snapshot_of(world)
    d1 = next(j for j in snap["jobs"] if j["id"] == "remotive-d1")
    assert d1["source"] == "remoteok" and d1["url"] == "https://example.com/remoteok/d1x"
    assert d1["title"] == "Data Engineer remotive-d1"  # canonical's own fields are kept
    dupco = next(c for c in snap["companies"] if c["name"] == "Dupco")
    assert dupco["sources"] == ["remoteok"] and dupco["job_ids"] == ["remotive-d1"]
    # the window statistic keeps counting the posting under its canonical source
    rows = {s["name"]: s for s in snap["meta"]["sources"]}
    assert rows["remotive"]["jobs"] == 7
    # jobs whose own posting is listed keep their own url and source
    r1 = next(j for j in snap["jobs"] if j["id"] == "remotive-r1")
    assert (r1["source"], r1["url"]) == ("remotive", "https://example.com/remotive/r1")


def test_the_most_recently_seen_live_copy_wins_and_a_live_canonical_keeps_its_link(world):
    with session_scope(world) as s:
        d1 = s.query(Job).filter_by(external_id="d1").one()
        add_job(s, "arbeitnow", "d1y", at(1, 12), company="Dupco", key="dup1", duplicate_of=d1)
        r1 = s.query(Job).filter_by(external_id="r1").one()
        add_job(s, "arbeitnow", "r1y", at(1, 12), company="Acme", key="k-r1", duplicate_of=r1)
    jobs = {j["id"]: j for j in snapshot_of(world)["jobs"]}
    # arbeitnow's copy was seen at its own reference, fresher than the remoteok copy
    assert (jobs["remotive-d1"]["source"], jobs["remotive-d1"]["url"]) == (
        "arbeitnow",
        "https://example.com/arbeitnow/d1y",
    )
    assert jobs["remotive-r1"]["source"] == "remotive"


# --------------------------------------------------------------------------- removed sources


def test_jobs_of_a_removed_source_are_never_active(world):
    assert "oldboard" not in {s.name for s in ALL_SOURCES}
    with session_scope(world) as s:
        add_job(s, "oldboard", "x1", at(5, 9), company="Ghost Inc")  # seen recently
        # an expired canonical whose only live copy is on the removed board stays expired
        d2 = s.query(Job).filter_by(external_id="d2").one()
        add_job(s, "oldboard", "d2y", at(5, 9), company="Dupco2", key="dup2", duplicate_of=d2)
    snap = snapshot_of(world)
    listed = {j["id"] for j in snap["jobs"]}
    assert listed == ACTIVE_IDS
    assert "Ghost Inc" not in {c["name"] for c in snap["companies"]}
    assert snap["meta"]["totals"]["jobs"] == 13  # still part of the window statistics
    assert snap["meta"]["totals"]["active"] == len(ACTIVE_IDS)


def test_known_sources_follow_the_sources_passed_to_aggregate(world):
    only_remotive = [s for s in ALL_SOURCES if s.name == "remotive"]
    snap = snapshot_of(world, sources=only_remotive)
    assert {j["id"] for j in snap["jobs"]} == {"remotive-r1", "remotive-r2", "remotive-r3"}
