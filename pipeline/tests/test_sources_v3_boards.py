"""Tests for the v3 data-role board sources: Himalayas, plus the targeted extra feeds of
Jobicy (``industry=data-science``) and Remote OK (``tag=...``). No network: ``fetch`` uses
``httpx.MockTransport`` and Himalayas gets an injected sleep function."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from radar.config import HTTP_TIMEOUT, JOBICY_PAGES, USER_AGENT
from radar.sources import base as base_mod
from radar.sources import himalayas as him_mod
from radar.sources import jobicy as jobicy_mod
from radar.sources import remoteok as remoteok_mod
from radar.sources.base import SourceJob
from radar.sources.himalayas import HimalayasSource
from radar.sources.jobicy import JobicySource
from radar.sources.remoteok import RemoteOKSource

FIXTURES = Path(__file__).parent / "fixtures"
FIELD_KEYS = {
    "title",
    "company",
    "url",
    "location",
    "is_remote",
    "posted_at",
    "description_html",
    "salary_text",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "source_tags",
    "source_category",
    "employment_type_text",
    "seniority_hint",
}


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def make_client(handler) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(
        transport=httpx.MockTransport(wrapped),
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
    )
    return client, seen


def json_handler(payload):
    return lambda request: httpx.Response(200, json=payload)


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(base_mod, "RETRY_WAIT_SECONDS", 0)


def by_id(jobs: list[SourceJob]) -> dict[str, SourceJob]:
    return {j.external_id: j for j in jobs}


def utc(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC).replace(tzinfo=None)


# ======================================================================== Himalayas

GUID = "https://himalayas.app/companies/{}"
MICROSOURCING = GUID.format("microsourcing/jobs/data-analyst-reporting-analyst")
TTEC = GUID.format("ttec-digital/jobs/senior-business-data-analyst-contact-center-analyst")
BIZFIRST = GUID.format(
    "bizfirst/jobs/financial-management-fm-palantir-data-analyst-analyst-and-manager-levels-de"
)
NTT = GUID.format("nttdata/jobs/remote-cyber-risk-security-data-analyst-plano-tx-us")
MICRO1 = GUID.format("micro1/jobs/senior-data-analyst")
PHARMA = GUID.format("pharmaforceiq/jobs/data-analyst-5281474080")
FUTUREPROOF = GUID.format("futureproof/jobs/eam-validation-analyst-data-validation-analyst-pharma")
SIEGEN = GUID.format(
    "siegen-hr-solutions-inc/jobs/virtual-employment-remote-data-analyst-2376601151"
)
PONTOON = GUID.format("pontoonglobal/jobs/predictive-crm-ai-analyst")
CANONICAL = GUID.format("canonical/jobs/senior-communications-manager-analyst-relations")


def himalayas_jobs() -> list[dict]:
    return load("himalayas")["jobs"]


def himalayas_pages(*, pages: int = 2, per_page: int = 4, shared: bool = False, more: bool = False):
    """Serve ``per_page`` fixture jobs on pages 1..``pages`` (empty afterwards, or never
    empty with ``more``). Guids are unique per (query, page) unless ``shared``, in which
    case every query sees the same jobs."""
    base = himalayas_jobs()[:per_page]

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        page = int(request.url.params["page"])
        rows = []
        if more or page <= pages:
            for row in copy.deepcopy(base):
                tag = f"p{page}" if shared else f"{query}-p{page}"
                row["guid"] = f"{row['guid']}#{tag}"
                rows.append(row)
        return httpx.Response(200, json={**{"limit": 20, "offset": 0}, "jobs": rows})

    return handler


class Sleeps:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def him(sleeps: Sleeps | None = None) -> HimalayasSource:
    return HimalayasSource(sleep=sleeps or Sleeps())


def test_himalayas_identity_and_scope():
    source = HimalayasSource()
    assert source.name == "himalayas"
    assert source.display_name == "Himalayas"
    assert source.homepage == "https://himalayas.app"
    assert source.scope == "targeted"


def test_himalayas_queries_cover_data_roles():
    assert len(him_mod.SEARCH_QUERIES) == len(set(him_mod.SEARCH_QUERIES))
    for needle in ("data analyst", "data engineer", "data scientist", "business intelligence"):
        assert needle in him_mod.SEARCH_QUERIES
    assert him_mod.REQUEST_SPACING_SECONDS >= 1.0


def test_himalayas_fetch_pages_each_query_until_an_empty_page():
    sleeps = Sleeps()
    client, seen = make_client(himalayas_pages(pages=2))
    jobs = him(sleeps).fetch(client)

    queries = him_mod.SEARCH_QUERIES
    # Per query: pages 1 and 2 have jobs, page 3 is empty -> stop. 3 requests per query.
    assert len(seen) == 3 * len(queries)
    assert all(str(r.url).startswith("https://himalayas.app/jobs/api/search?") for r in seen)
    assert all(r.headers["user-agent"] == USER_AGENT for r in seen)
    got = [(r.url.params["q"], int(r.url.params["page"])) for r in seen]
    assert got[:6] == [
        (queries[0], 1),
        (queries[0], 2),
        (queries[0], 3),
        (queries[1], 1),
        (queries[1], 2),
        (queries[1], 3),
    ]
    assert len(jobs) == 2 * 4 * len(queries)
    assert all(j.source == "himalayas" for j in jobs)
    assert jobs[0].external_id == f"{himalayas_jobs()[0]['guid']}#{queries[0]}-p1"
    assert jobs[0].payload["title"] == himalayas_jobs()[0]["title"]


def test_himalayas_fetch_waits_between_every_pair_of_requests():
    sleeps = Sleeps()
    client, seen = make_client(himalayas_pages(pages=1))
    him(sleeps).fetch(client)
    assert len(seen) == 2 * len(him_mod.SEARCH_QUERIES)
    assert sleeps.calls == [1.0] * (len(seen) - 1)  # none before the first request


def test_himalayas_fetch_caps_pages_per_query():
    assert him_mod.MAX_PAGES_PER_QUERY == 10
    sleeps = Sleeps()
    client, seen = make_client(himalayas_pages(more=True))
    jobs = him(sleeps).fetch(client)
    n_queries = len(him_mod.SEARCH_QUERIES)
    assert len(seen) == 10 * n_queries
    assert max(int(r.url.params["page"]) for r in seen) == 10
    assert len(jobs) == 10 * 4 * n_queries
    assert len(sleeps.calls) == len(seen) - 1


def test_himalayas_fetch_stops_a_query_when_a_page_has_nothing_new():
    # Page 2 repeats page 1's guids -> the query stops after 2 requests, not 10.
    base = himalayas_jobs()[:4]

    def handler(request):
        query = request.url.params["q"]
        rows = copy.deepcopy(base)
        for row in rows:
            row["guid"] += f"#{query}"  # same on every page of a query
        return httpx.Response(200, json={"jobs": rows})

    client, seen = make_client(handler)
    jobs = him().fetch(client)
    assert len(seen) == 2 * len(him_mod.SEARCH_QUERIES)
    assert len(jobs) == 4 * len(him_mod.SEARCH_QUERIES)


def test_himalayas_fetch_dedupes_across_queries_and_keeps_first_seen():
    # Every query serves the same jobs (shared guids): later queries add nothing new, so
    # each of them stops after its first page.
    client, seen = make_client(himalayas_pages(pages=3, shared=True))
    jobs = him().fetch(client)
    n_queries = len(him_mod.SEARCH_QUERIES)
    # query 1 walks pages 1-3 plus the empty page 4; the others stop at page 1.
    assert len(seen) == 4 + (n_queries - 1)
    assert len(jobs) == 3 * 4
    assert len({j.external_id for j in jobs}) == len(jobs)
    assert [j.external_id for j in jobs][:4] == [f"{r['guid']}#p1" for r in himalayas_jobs()[:4]]


def test_himalayas_fetch_skips_items_without_a_guid():
    rows = copy.deepcopy(himalayas_jobs()[:3])
    del rows[1]["guid"]
    rows.append("junk")
    client, _ = make_client(lambda request: httpx.Response(200, json={"jobs": rows}))
    jobs = HimalayasSource(sleep=Sleeps()).fetch(client)
    assert [j.external_id for j in jobs] == [rows[0]["guid"], rows[2]["guid"]]


def test_himalayas_fetch_rejects_bad_shape():
    client, _ = make_client(json_handler({"oops": []}))
    with pytest.raises(ValueError, match="Himalayas"):
        him().fetch(client)
    client, _ = make_client(json_handler([1, 2]))
    with pytest.raises(ValueError):
        him().fetch(client)


def test_himalayas_fetch_raises_when_the_first_request_fails():
    client, seen = make_client(lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        him().fetch(client)
    assert len(seen) == 2  # one retry


def test_himalayas_fetch_returns_partial_jobs_when_a_later_request_fails():
    inner = himalayas_pages(pages=5)

    def handler(request):
        if request.url.params["q"] == him_mod.SEARCH_QUERIES[1]:
            return httpx.Response(429)
        return inner(request)

    client, seen = make_client(handler)
    jobs = him().fetch(client)
    # First query fully walked (5 pages + empty page), then the second fails (2 attempts)
    # and the run stops instead of hammering the remaining queries.
    assert len(jobs) == 5 * 4
    assert len(seen) == 6 + 2


def test_himalayas_to_fields_without_salary():
    source = HimalayasSource()
    f = source.to_fields(by_id_payload(MICROSOURCING))
    assert set(f) == FIELD_KEYS
    assert f["title"] == "Data Analyst / Reporting Analyst"
    assert f["company"] == "MicroSourcing"
    # applicationLink is used unchanged (with its utm_source), not the guid.
    assert f["url"] == MICROSOURCING + "?utm_source=api"
    assert f["location"] == "Philippines"
    assert f["is_remote"] is True
    assert f["posted_at"] == utc(1792551771)  # pubDate = last updated
    assert f["description_html"].startswith("<p><strong>Discover your 100% YOU")
    assert f["salary_text"] is None
    assert f["salary_min"] is None and f["salary_max"] is None
    assert f["salary_currency"] is None and f["salary_period"] is None
    assert f["source_tags"][:3] == [
        "Data Analyst",
        "Reporting Analyst",
        "Business Intelligence Analyst",
    ]
    assert f["source_category"] == "Data Science"
    assert f["employment_type_text"] == "Full Time"
    assert f["seniority_hint"] == "Mid-level"


def test_himalayas_to_fields_usd_annual_range():
    f = HimalayasSource().to_fields(by_id_payload(NTT))
    assert f["salary_min"] == 105840.0 and f["salary_max"] == 196000.0
    assert f["salary_currency"] == "USD" and f["salary_period"] == "year"
    assert f["location"] == "United States"
    assert f["seniority_hint"] == "Senior"
    assert f["source_category"] == "Developer"


def test_himalayas_to_fields_equal_bounds_and_foreign_currency():
    f = HimalayasSource().to_fields(by_id_payload(PHARMA))
    assert f["salary_min"] == 425000.0 and f["salary_max"] == 425000.0
    assert f["salary_currency"] == "INR" and f["salary_period"] == "year"
    assert f["source_category"] == "Data Science"  # first parent category

    f = HimalayasSource().to_fields(by_id_payload(PONTOON))
    assert (f["salary_min"], f["salary_max"]) == (600000.0, 1200000.0)
    assert f["salary_currency"] == "INR"
    assert f["location"] == "India, United States"


def test_himalayas_to_fields_currency_without_amounts_is_dropped():
    f = HimalayasSource().to_fields(by_id_payload(BIZFIRST))
    assert f["salary_min"] is None and f["salary_max"] is None
    assert f["salary_currency"] is None and f["salary_period"] is None
    assert f["seniority_hint"] == "Senior, Manager"


def test_himalayas_to_fields_location_variants():
    source = HimalayasSource()
    f = source.to_fields(by_id_payload(SIEGEN))
    assert f["location"] == "Australia, Canada, United Kingdom, United States"
    assert f["seniority_hint"] == "Entry-level"

    payload = by_id_payload(FUTUREPROOF)
    assert len(payload["locationRestrictions"]) == 52
    f = source.to_fields(payload)
    shown = payload["locationRestrictions"][: him_mod.LOCATION_MAX_COUNTRIES]
    assert f["location"] == ", ".join(shown) + " +47 more"
    assert f["employment_type_text"] == "Contractor"

    payload = by_id_payload(CANONICAL)
    assert len(payload["locationRestrictions"]) == 148
    assert source.to_fields(payload)["location"].endswith(" +143 more")

    payload = by_id_payload(MICROSOURCING)
    payload["locationRestrictions"] = []
    assert source.to_fields(payload)["location"] == "Worldwide"
    del payload["locationRestrictions"]
    assert source.to_fields(payload)["location"] == "Worldwide"


@pytest.mark.parametrize(
    ("period", "low", "high", "expect_period", "expect_low", "expect_high"),
    [
        ("annual", 90000, 140000, "year", 90000.0, 140000.0),
        ("hourly", 45, 60, "hour", 45.0, 60.0),
        ("monthly", 5000, 6000, "month", 5000.0, 6000.0),
        ("weekly", 1000, 1500, "year", 52000.0, 78000.0),
        ("fortnightly", 2000, None, "year", 52000.0, None),
        ("Hourly", None, 80, "hour", None, 80.0),
        (None, 70000, 80000, "year", 70000.0, 80000.0),  # annual is the documented default
    ],
)
def test_himalayas_to_fields_salary_period_mapping(
    period, low, high, expect_period, expect_low, expect_high
):
    payload = by_id_payload(NTT)
    payload.update(minSalary=low, maxSalary=high, salaryPeriod=period, currency="eur")
    f = HimalayasSource().to_fields(payload)
    assert f["salary_period"] == expect_period
    assert f["salary_min"] == expect_low and f["salary_max"] == expect_high
    assert f["salary_currency"] == "EUR"


def test_himalayas_to_fields_unknown_period_and_missing_currency():
    payload = by_id_payload(NTT)
    payload.update(salaryPeriod="per-lunar-cycle")
    f = HimalayasSource().to_fields(payload)
    assert f["salary_period"] is None  # unknown period is not guessed
    assert f["salary_min"] == 105840.0

    payload = by_id_payload(NTT)
    payload.update(currency=None)
    f = HimalayasSource().to_fields(payload)
    assert f["salary_currency"] is None and f["salary_period"] == "year"

    payload = by_id_payload(NTT)
    payload.update(minSalary=0, maxSalary=0)
    f = HimalayasSource().to_fields(payload)
    assert f["salary_min"] is None and f["salary_period"] is None and f["salary_currency"] is None


def test_himalayas_to_fields_url_falls_back_to_guid_and_description_to_excerpt():
    payload = by_id_payload(MICROSOURCING)
    payload["applicationLink"] = None
    payload["description"] = ""
    f = HimalayasSource().to_fields(payload)
    assert f["url"] == MICROSOURCING
    assert f["description_html"] == payload["excerpt"]
    payload["excerpt"] = None
    assert HimalayasSource().to_fields(payload)["description_html"] is None


def test_himalayas_every_fixture_job_maps_cleanly():
    rows = himalayas_jobs()
    assert 5 <= len(rows) <= 10
    for payload in rows:
        f = HimalayasSource().to_fields(payload)
        assert set(f) == FIELD_KEYS
        assert f["title"] and f["company"]
        assert f["url"].startswith("https://himalayas.app/")
        assert f["url"].endswith("?utm_source=api")
        assert f["is_remote"] is True
        assert f["posted_at"] is not None


def by_id_payload(guid: str) -> dict:
    for row in himalayas_jobs():
        if row["guid"] == guid:
            return copy.deepcopy(row)
    raise AssertionError(guid)


# ========================================================================== Jobicy


def jobicy_feeds(*, default_pages: int = 2, data_pages: int = 2, data_more: bool = False):
    """Default feed from the old fixture, ``industry=data-science`` feed from the new one.
    Each feed pages with ``cursor-N`` cursors; later pages carry shifted ids."""
    default = load("jobicy")
    data = load("jobicy_data")

    def handler(request: httpx.Request) -> httpx.Response:
        industry = request.url.params.get("industry")
        base, pages, always = (
            (default, default_pages, False) if industry is None else (data, data_pages, data_more)
        )
        cursor = request.url.params.get("cursor")
        n = 1 if cursor is None else int(cursor.removeprefix("cursor-"))
        body = copy.deepcopy(base)
        if n > 1:
            for row in body["jobs"]:
                row["id"] += (n - 1) * 100000
        last = n >= pages and not always
        body["hasMore"] = not last
        body["nextCursor"] = None if last else f"cursor-{n + 1}"
        return httpx.Response(200, json=body)

    return handler


def test_jobicy_is_targeted():
    assert JobicySource.scope == "targeted"
    assert JobicySource().scope == "targeted"
    assert jobicy_mod.DATA_INDUSTRIES == ("data-science",)
    assert jobicy_mod.INDUSTRY_PAGES == 2


def test_jobicy_fetch_adds_the_data_science_feed_after_the_default_feed():
    client, seen = make_client(jobicy_feeds(default_pages=1, data_pages=1))
    jobs = JobicySource().fetch(client)

    assert len(seen) == 2
    default_req, data_req = seen
    assert "industry" not in default_req.url.params
    assert default_req.url.params["count"] == "100"
    assert data_req.url.params["industry"] == "data-science"
    assert data_req.url.params["count"] == "100"
    assert "cursor" not in data_req.url.params
    assert all(str(r.url).startswith("https://jobicy.com/api/v2/remote-jobs?") for r in seen)
    assert all(r.headers["user-agent"] == USER_AGENT for r in seen)

    default_ids = [str(r["id"]) for r in load("jobicy")["jobs"]]
    data_ids = [str(r["id"]) for r in load("jobicy_data")["jobs"]]
    shared = set(default_ids) & set(data_ids)
    assert shared == {"159265"}  # the same Solace posting is in both feeds
    assert len(jobs) == len(set(default_ids) | set(data_ids)) == 8 + 7 - 1
    assert [j.external_id for j in jobs] == default_ids + [i for i in data_ids if i not in shared]
    # The default feed wins for the duplicate.
    assert by_id(jobs)["159265"].payload == load("jobicy")["jobs"][0]
    assert by_id(jobs)["154739"].payload == load("jobicy_data")["jobs"][1]


def test_jobicy_fetch_follows_cursors_in_both_feeds():
    client, seen = make_client(jobicy_feeds(default_pages=2, data_pages=2))
    jobs = JobicySource().fetch(client)
    kinds = [(r.url.params.get("industry"), r.url.params.get("cursor")) for r in seen]
    assert kinds == [
        (None, None),
        (None, "cursor-2"),
        ("data-science", None),
        ("data-science", "cursor-2"),
    ]
    # page 2 of each feed has shifted ids, so nothing but 159265 collapses
    assert len(jobs) == 2 * 8 + 2 * 7 - 1 - 1
    assert len({j.external_id for j in jobs}) == len(jobs)


def test_jobicy_default_feed_still_capped_by_jobicy_pages():
    client, seen = make_client(jobicy_feeds(default_pages=99, data_pages=1))
    jobs = JobicySource().fetch(client)
    plain = [r for r in seen if "industry" not in r.url.params]
    assert len(plain) == JOBICY_PAGES
    assert len(jobs) >= 8 * JOBICY_PAGES


def test_jobicy_industry_feed_capped_by_industry_pages():
    client, seen = make_client(jobicy_feeds(default_pages=1, data_pages=1, data_more=True))
    jobs = JobicySource().fetch(client)
    data_reqs = [r for r in seen if r.url.params.get("industry") == "data-science"]
    assert len(data_reqs) == jobicy_mod.INDUSTRY_PAGES == 2
    assert data_reqs[1].url.params["cursor"] == "cursor-2"
    assert len(jobs) == 8 + 7 * 2 - 1


def test_jobicy_industry_feed_stops_without_more_pages():
    client, seen = make_client(jobicy_feeds(default_pages=1, data_pages=1))
    JobicySource().fetch(client)
    assert len([r for r in seen if "industry" in r.url.params]) == 1


def test_jobicy_fetch_keeps_default_jobs_when_the_industry_feed_fails():
    default = jobicy_feeds(default_pages=1)

    def handler(request):
        if "industry" in request.url.params:
            return httpx.Response(503)
        return default(request)

    client, seen = make_client(handler)
    jobs = JobicySource().fetch(client)
    assert len(jobs) == 8
    assert len(seen) == 1 + 2  # default + industry attempt and its retry

    def bad_shape(request):
        if "industry" in request.url.params:
            return httpx.Response(200, json={"success": False})
        return default(request)

    client, _ = make_client(bad_shape)
    assert len(JobicySource().fetch(client)) == 8


def test_jobicy_fetch_still_raises_when_the_default_feed_fails():
    client, _ = make_client(json_handler({"success": False, "error": "nope"}))
    with pytest.raises(ValueError):
        JobicySource().fetch(client)
    client, _ = make_client(lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        JobicySource().fetch(client)


def test_jobicy_to_fields_on_data_feed_jobs():
    client, _ = make_client(jobicy_feeds(default_pages=1, data_pages=1))
    jobs = by_id(JobicySource().fetch(client))
    source = JobicySource()

    f = source.to_fields(jobs["154739"].payload)
    assert set(f) == FIELD_KEYS
    assert f["title"] == "Commercial Data Scientist"
    assert f["url"].startswith("https://jobicy.com/jobs/154739-")
    assert f["location"] == "USA"
    assert f["salary_min"] == 119333.0 and f["salary_max"] == 172800.0
    assert f["salary_currency"] == "USD" and f["salary_period"] == "year"
    assert f["source_tags"] == ["Data Science & Analytics"]
    assert f["source_category"] == "Data Science & Analytics"
    assert f["seniority_hint"] is None  # jobLevel "Any" carries no information

    f = source.to_fields(jobs["152541"].payload)
    assert f["seniority_hint"] == "Director"
    assert f["posted_at"] is not None

    f = source.to_fields(jobs["159097"].payload)  # no salary at all
    assert f["location"] == "Anywhere"
    assert f["salary_min"] is None and f["salary_max"] is None
    assert f["salary_currency"] is None and f["salary_period"] is None

    f = source.to_fields(jobs["152472"].payload)
    assert f["title"] == "Marketing Data Scientist" and f["location"] == "Mexico"
    assert f["salary_period"] is None

    f = source.to_fields(jobs["158882"].payload)  # hourly amount, no currency given
    assert f["salary_min"] == 18.0 and f["salary_max"] == 18.0
    assert f["salary_period"] == "hour" and f["salary_currency"] is None


# ======================================================================== Remote OK


def remoteok_feeds(*, tags: dict[str, object] | None = None, default=None):
    """Default feed from the old fixture; tag feeds from ``remoteok_data`` unless
    ``tags`` overrides a tag's response (a list, or an int status code)."""
    default_body = load("remoteok") if default is None else default
    data_body = load("remoteok_data")
    overrides = tags or {}

    def handler(request: httpx.Request) -> httpx.Response:
        tag = request.url.params.get("tag")
        if tag is None:
            return httpx.Response(200, json=default_body)
        if tag in overrides:
            value = overrides[tag]
            if isinstance(value, int):
                return httpx.Response(value)
            return httpx.Response(200, json=value)
        return httpx.Response(200, json=data_body)

    return handler


def test_remoteok_is_targeted():
    assert RemoteOKSource.scope == "targeted"
    assert RemoteOKSource().scope == "targeted"
    assert remoteok_mod.DATA_TAGS == ("data-science", "data", "analyst")


def test_remoteok_fetch_reads_default_feed_then_each_tag_feed():
    client, seen = make_client(remoteok_feeds())
    jobs = RemoteOKSource().fetch(client)

    assert [str(r.url) for r in seen] == [
        "https://remoteok.com/api",
        "https://remoteok.com/api?tag=data-science",
        "https://remoteok.com/api?tag=data",
        "https://remoteok.com/api?tag=analyst",
    ]
    assert all(r.headers["user-agent"] == USER_AGENT for r in seen)
    old_ids = [j["id"] for j in load("remoteok")[1:]]
    data_ids = [j["id"] for j in load("remoteok_data")[1:]]
    assert len(old_ids) == 8 and len(data_ids) == 8
    # every tag feed returns the same fixture -> merged once; metadata rows never appear
    assert [j.external_id for j in jobs] == old_ids + data_ids
    assert all(j.source == "remoteok" for j in jobs)
    assert all(isinstance(j.external_id, str) and j.external_id.isdigit() for j in jobs)
    assert jobs[0].payload == load("remoteok")[1]  # default feed first, payload untouched
    assert jobs[8].payload == load("remoteok_data")[1]


def test_remoteok_fetch_dedupes_across_feeds_and_keeps_default_payload():
    default = load("remoteok")
    clash = copy.deepcopy(load("remoteok_data"))
    clash[1]["id"] = default[1]["id"]  # same posting appears in the tag feeds
    clash[1]["position"] = "Changed in tag feed"
    client, _ = make_client(remoteok_feeds(tags={"data-science": clash}))
    jobs = by_id(RemoteOKSource().fetch(client))
    assert jobs[default[1]["id"]].payload == default[1]
    assert len(jobs) == 8 + 8


def test_remoteok_fetch_skips_the_metadata_row_of_every_feed():
    for body in (load("remoteok"), load("remoteok_data")):
        assert "legal" in body[0] and "id" not in body[0]
    client, _ = make_client(remoteok_feeds())
    assert all(j.external_id for j in RemoteOKSource().fetch(client))


def test_remoteok_default_feed_alone_still_works():
    tag_feeds_empty = {t: [load("remoteok_data")[0]] for t in remoteok_mod.DATA_TAGS}
    client, seen = make_client(remoteok_feeds(tags=tag_feeds_empty))
    jobs = RemoteOKSource().fetch(client)
    assert len(seen) == 1 + len(remoteok_mod.DATA_TAGS)
    assert len(jobs) == 8
    assert jobs[0].payload == load("remoteok")[1]
    fields = RemoteOKSource().to_fields(jobs[0].payload)
    assert fields["title"] == "Senior Staff Infrastructure & Security Engineer"
    assert fields["salary_min"] == 137318.0 and fields["salary_period"] == "year"


def test_remoteok_fetch_keeps_other_jobs_when_a_tag_feed_fails():
    client, seen = make_client(remoteok_feeds(tags={"data": 503, "analyst": {"not": "a list"}}))
    jobs = RemoteOKSource().fetch(client)
    assert len(jobs) == 8 + 8  # default + data-science feed
    assert len(seen) == 1 + 1 + 2 + 1  # data retried once; analyst bad shape not retried


def test_remoteok_fetch_still_raises_when_the_default_feed_fails():
    client, _ = make_client(json_handler({"jobs": []}))
    with pytest.raises(ValueError):
        RemoteOKSource().fetch(client)
    client, _ = make_client(lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        RemoteOKSource().fetch(client)


def test_remoteok_to_fields_on_tag_feed_jobs():
    client, _ = make_client(remoteok_feeds())
    jobs = by_id(RemoteOKSource().fetch(client))
    source = RemoteOKSource()

    f = source.to_fields(jobs["1136222"].payload)
    assert set(f) == FIELD_KEYS
    assert f["title"] == "Data Analyst"
    assert f["company"] == "SEAhub Asia"
    assert f["url"] == "https://remoteOK.com/remote-jobs/remote-data-analyst-seahub-asia-1136222"
    assert f["location"].startswith("Kuala Lumpur")
    assert f["is_remote"] is True
    assert f["posted_at"] == datetime(2026, 8, 4, 14, 20, 29)
    assert "data science" in f["source_tags"] and "python" in f["source_tags"]
    assert f["salary_min"] is None and f["salary_max"] is None  # 0 means "not given"
    assert f["salary_currency"] is None and f["salary_period"] is None
    assert f["description_html"]

    f = source.to_fields(jobs["1134357"].payload)
    assert (f["title"], f["company"]) == ("Data Scientist", "New Flyer")
    assert f["location"] == "Winnipeg, Winnipeg, Manitoba, Canada"
    assert f["posted_at"] == datetime(2026, 7, 1, 18, 47, 1)

    f = source.to_fields(jobs["1134707"].payload)
    assert f["title"] == "Graduate Data Scientist"
    assert f["source_tags"] == ["data science"]

    f = source.to_fields(jobs["1134120"].payload)
    assert f["posted_at"] == datetime(2026, 6, 17, 0, 0, 0)

    payload = copy.deepcopy(jobs["1133828"].payload)
    payload.update(salary_min=70000, salary_max=90000)
    f = source.to_fields(payload)
    assert f["salary_min"] == 70000.0 and f["salary_max"] == 90000.0
    assert f["salary_currency"] == "USD" and f["salary_period"] == "year"


def test_remoteok_every_data_fixture_job_maps_cleanly():
    rows = load("remoteok_data")[1:]
    assert 5 <= len(rows) <= 10
    for payload in rows:
        f = RemoteOKSource().to_fields(payload)
        assert set(f) == FIELD_KEYS
        assert f["title"] and f["company"] and f["url"].startswith("https://remoteOK.com/")


def test_jobicy_data_fixture_jobs_all_map_cleanly():
    rows = load("jobicy_data")["jobs"]
    assert 5 <= len(rows) <= 10
    for payload in rows:
        f = JobicySource().to_fields(payload)
        assert set(f) == FIELD_KEYS
        assert f["title"] and f["company"] and f["url"].startswith("https://jobicy.com/jobs/")
