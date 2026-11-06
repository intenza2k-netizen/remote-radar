"""Tests for the job-board source adapters. No network: fetch uses httpx.MockTransport."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from radar import sources as sources_pkg
from radar.config import ARBEITNOW_PAGES, HTTP_TIMEOUT, JOBICY_PAGES, USER_AGENT
from radar.sources import ALL_SOURCES, get_source
from radar.sources import base as base_mod
from radar.sources import jobicy as jobicy_mod
from radar.sources.base import (
    SourceJob,
    clean_text,
    dedupe_jobs,
    get_json,
    parse_datetime,
    to_float,
)

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
    """Client configured like the real one, backed by ``handler``; records requests."""
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


# ------------------------------------------------------------------ registry / generic


def test_registry():
    # Job boards first, then company ATS boards, then Hacker News (dedupe keeps the first copy).
    assert [s.name for s in ALL_SOURCES] == [
        "remotive",
        "remoteok",
        "arbeitnow",
        "jobicy",
        "himalayas",
        "greenhouse",
        "ashby",
        "lever",
        "hackernews",
    ]
    assert all(getattr(s, "scope", "broad") in {"broad", "targeted"} for s in ALL_SOURCES)
    assert get_source("remoteok").display_name == "Remote OK"
    assert get_source("remotive") is ALL_SOURCES[0]
    with pytest.raises(KeyError, match="nope"):
        get_source("nope")
    for s in ALL_SOURCES:
        assert s.homepage.startswith("https://")
        assert s.display_name


def test_sources_do_not_import_normalize():
    pkg_dir = Path(sources_pkg.__file__).parent
    for path in pkg_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+radar\.normalize", text, re.M), path.name


def fixture_jobs(name: str) -> list[dict]:
    data = load(name)
    if name == "remoteok":
        return data[1:]
    return data["data"] if name == "arbeitnow" else data["jobs"]


@pytest.mark.parametrize("name", ["remotive", "remoteok", "arbeitnow", "jobicy"])
def test_every_fixture_job_maps_cleanly(name):
    source = get_source(name)
    rows = fixture_jobs(name)
    assert 5 <= len(rows) <= 10
    for payload in rows:
        fields = source.to_fields(payload)
        assert set(fields) == FIELD_KEYS
        assert fields["title"] and fields["title"] == fields["title"].strip()
        assert fields["company"] and fields["company"] == fields["company"].strip()
        assert fields["url"].startswith("https://")
        assert isinstance(fields["is_remote"], bool)
        assert isinstance(fields["posted_at"], datetime)
        assert fields["posted_at"].tzinfo is None
        assert fields["salary_period"] in {"year", "month", "hour", None}
        assert isinstance(fields["source_tags"], list)
        assert all(isinstance(t, str) and t == t.strip() and t for t in fields["source_tags"])
        if fields["salary_min"] is None and fields["salary_max"] is None:
            assert fields["salary_period"] is None and fields["salary_currency"] is None
        # to_fields must not mutate the payload, and payloads must stay JSON-serialisable
        before = copy.deepcopy(payload)
        source.to_fields(payload)
        assert payload == before
        json.dumps(payload)


# ------------------------------------------------------------------------- base helpers


def test_parse_datetime_variants():
    assert parse_datetime("2026-11-02T20:01:00") == datetime(2026, 11, 2, 20, 1)
    assert parse_datetime("2026-11-05T00:00:04+00:00") == datetime(2026, 11, 5, 0, 0, 4)
    assert parse_datetime("2026-11-05T02:00:04+02:00") == datetime(2026, 11, 5, 0, 0, 4)
    assert parse_datetime("2026-11-05T00:00:04Z") == datetime(2026, 11, 5, 0, 0, 4)
    assert parse_datetime(1793836804) == datetime(2026, 11, 5, 0, 0, 4)
    assert parse_datetime("1793836804") == datetime(2026, 11, 5, 0, 0, 4)
    assert parse_datetime(1793836804000) == datetime(2026, 11, 5, 0, 0, 4)
    assert parse_datetime("Tue, 03 Nov 2026 10:00:00 GMT") == datetime(2026, 11, 3, 10, 0)
    for bad in (None, "", "   ", "not a date", True):
        assert parse_datetime(bad) is None


def test_clean_text_and_to_float():
    assert clean_text("  Foo &amp;  Bar \n") == "Foo & Bar"
    assert clean_text("MÃ¼nchen") == "München"
    assert clean_text("München") == "München"
    assert clean_text(None) == ""
    assert to_float(0) is None and to_float("0") is None and to_float(None) is None
    assert to_float(-5) is None and to_float("abc") is None and to_float(True) is None
    assert to_float(137318) == 137318.0 and to_float("4.5") == 4.5


def test_dedupe_jobs_keeps_first():
    a = SourceJob("x", "1", {"n": 1})
    b = SourceJob("x", "1", {"n": 2})
    c = SourceJob("x", "2", {"n": 3})
    assert dedupe_jobs([a, b, c]) == [a, c]


def test_get_json_retries_once_on_server_error():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    client, _ = make_client(handler)
    assert get_json(client, "https://example.test/x") == {"ok": True}
    assert len(calls) == 2


def test_get_json_raises_after_second_failure():
    client, seen = make_client(lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        get_json(client, "https://example.test/x")
    assert len(seen) == 2


def test_get_json_does_not_retry_client_errors():
    client, seen = make_client(lambda request: httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        get_json(client, "https://example.test/x")
    assert len(seen) == 1


def test_get_json_retries_transport_errors():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json=[1])

    client, _ = make_client(handler)
    assert get_json(client, "https://example.test/x") == [1]


# ------------------------------------------------------------------------------ Remotive


def test_remotive_fetch():
    source = get_source("remotive")
    client, seen = make_client(json_handler(load("remotive")))
    jobs = source.fetch(client)
    assert len(seen) == 1
    assert str(seen[0].url) == "https://remotive.com/api/remote-jobs"
    assert seen[0].headers["user-agent"] == USER_AGENT
    assert len(jobs) == 10
    assert all(j.source == "remotive" and isinstance(j.external_id, str) for j in jobs)
    assert jobs[0].external_id == "1749306"
    assert jobs[0].payload == load("remotive")["jobs"][0]  # exactly as returned


def test_remotive_fetch_rejects_bad_shape_and_http_errors():
    source = get_source("remotive")
    client, _ = make_client(json_handler({"oops": []}))
    with pytest.raises(ValueError):
        source.fetch(client)
    client, _ = make_client(lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        source.fetch(client)


def test_remotive_to_fields():
    source = get_source("remotive")
    jobs = by_id(source.fetch(make_client(json_handler(load("remotive")))[0]))

    f = source.to_fields(jobs["1749306"].payload)
    assert f["title"] == "Freelance Copywriter"
    assert f["company"] == "Coalition Technologies"  # trailing space stripped
    assert f["url"] == "https://remotive.com/remote-jobs/writing/freelance-copywriter-1749306"
    assert f["location"] == "Worldwide"
    assert f["is_remote"] is True
    assert f["posted_at"] == datetime(2026, 11, 2, 20, 1)
    assert f["description_html"].startswith("<p>CT Marketing Agency")
    assert f["salary_text"] == "$20k -$35k"
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (
        None,
        None,
        None,
        None,
    )
    assert f["source_tags"][:3] == ["accounting", "excel", "research"]
    assert "G Suite" in f["source_tags"]
    assert f["source_category"] == "Writing"
    assert f["employment_type_text"] == "freelance"
    assert f["seniority_hint"] is None

    f = source.to_fields(jobs["2091165"].payload)
    assert f["title"] == "Full-Stack Developer"
    assert f["company"] == "Fluence International, Inc."
    assert f["salary_text"] == "$3.5k–$5k/month"
    assert f["employment_type_text"] == "contract"
    assert "Typescript" in f["source_tags"]  # 'Typescript ' trimmed
    assert f["source_category"] == "Software Development"
    assert f["posted_at"] == datetime(2026, 10, 29, 18, 22, 41)

    # empty salary string -> None; multi-country location kept verbatim
    empties = [j for j in jobs.values() if not j.payload["salary"]]
    assert empties
    f = source.to_fields(empties[0].payload)
    assert f["salary_text"] is None
    multi = [j for j in jobs.values() if "Saudi Arabia" in j.payload["candidate_required_location"]]
    assert source.to_fields(multi[0].payload)["location"].startswith("Europe, USA")


# ------------------------------------------------------------------------------ Remote OK


def test_remoteok_fetch_skips_metadata_row():
    source = get_source("remoteok")
    data = load("remoteok")
    assert "legal" in data[0] and "id" not in data[0]
    client, seen = make_client(json_handler(data))
    jobs = source.fetch(client)
    default = [r for r in seen if "tag" not in r.url.params]
    assert len(default) == 1 and str(default[0].url) == "https://remoteok.com/api"
    assert len(seen) > len(default)  # the filtered tag feeds were requested too
    assert seen[0].headers["user-agent"] == USER_AGENT
    assert len(jobs) == len(data) - 1 == 8
    assert all(isinstance(j.external_id, str) and j.external_id.isdigit() for j in jobs)
    assert jobs[0].payload == data[1]


def test_remoteok_fetch_rejects_non_array():
    client, _ = make_client(json_handler({"jobs": []}))
    with pytest.raises(ValueError):
        get_source("remoteok").fetch(client)


def test_remoteok_to_fields():
    source = get_source("remoteok")
    jobs = by_id(source.fetch(make_client(json_handler(load("remoteok")))[0]))

    f = source.to_fields(jobs["1137687"].payload)
    assert f["title"] == "Senior Staff Infrastructure & Security Engineer"
    assert f["company"] == "CivilGrid"
    assert f["url"] == (
        "https://remoteOK.com/remote-jobs/remote-senior-staff-infrastructure-security-"
        "engineer-civilgrid-1137687"
    )
    assert f["location"] == "Boston"
    assert f["is_remote"] is True
    assert f["posted_at"] == datetime(2026, 11, 5, 0, 0, 4)
    assert f["description_html"].startswith("<p")
    assert f["salary_text"] is None
    assert f["salary_min"] == 137318.0 and f["salary_max"] == 192960.0
    assert f["salary_currency"] == "USD" and f["salary_period"] == "year"
    assert "devops" in f["source_tags"]
    assert f["source_category"] is None

    # salary 0 means unknown; empty location -> None
    f = source.to_fields(jobs["1137624"].payload)
    assert jobs["1137624"].payload["salary_min"] == 0
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (
        None,
        None,
        None,
        None,
    )
    assert f["location"] is None
    assert f["is_remote"] is True

    # HTML entities in the title are decoded
    f = source.to_fields(jobs["1137680"].payload)
    assert f["title"] == "Entry Level Scheduling & Coordinating Reservations Online"
    assert f["location"] == "South Carolina"

    # mojibake in the upstream location is repaired; small salaries still pass through
    f = source.to_fields(jobs["1137677"].payload)
    assert jobs["1137677"].payload["location"] == "MÃ¼nchen"
    assert f["location"] == "München"
    assert f["title"] == "M&A Praktikum Intern"
    assert f["salary_min"] == 4000.0 and f["salary_max"] == 4000.0

    # trailing whitespace trimmed
    assert source.to_fields(jobs["1137675"].payload)["title"] == "Paid Media Manager US"


def test_remoteok_to_fields_falls_back_to_epoch_and_slug():
    source = get_source("remoteok")
    f = source.to_fields(
        {
            "slug": "remote-foo-1",
            "id": "1",
            "epoch": 1793836804,
            "company": "Foo",
            "position": "Bar",
            "salary_min": 0,
            "salary_max": 90000,
        }
    )
    assert f["posted_at"] == datetime(2026, 11, 5, 0, 0, 4)
    assert f["url"] == "https://remoteok.com/remote-jobs/remote-foo-1"
    assert f["salary_min"] is None and f["salary_max"] == 90000.0
    assert f["salary_period"] == "year"


# ----------------------------------------------------------------------------- Arbeitnow


def arbeitnow_pages(n_pages: int, *, last_has_next: bool = True):
    """Page handler serving the fixture, with page-specific slugs except an overlap row."""
    base = load("arbeitnow")

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        data = copy.deepcopy(base)
        if page > 1:
            for row in data["data"][1:]:
                row["slug"] = f"{row['slug']}-p{page}"
        is_last = page >= n_pages
        data["links"]["next"] = (
            None if is_last and not last_has_next else f"https://x.test/?page={page + 1}"
        )
        return httpx.Response(200, json=data)

    return handler


def test_arbeitnow_fetch_pages_per_config_and_dedupes():
    source = get_source("arbeitnow")
    client, seen = make_client(arbeitnow_pages(10))
    jobs = source.fetch(client)
    assert ARBEITNOW_PAGES == 2
    assert [r.url.params["page"] for r in seen] == ["1", "2"]
    assert all(r.headers["user-agent"] == USER_AGENT for r in seen)
    per_page = len(load("arbeitnow")["data"])
    # page 2 repeats the first row's slug -> deduped
    assert len(jobs) == per_page * 2 - 1
    assert len({j.external_id for j in jobs}) == len(jobs)
    assert jobs[0].source == "arbeitnow"
    assert jobs[0].external_id == "remote-director-of-national-accounts-300180"


def test_arbeitnow_fetch_stops_when_no_next_page(monkeypatch):
    from radar.sources import arbeitnow as arbeitnow_mod

    monkeypatch.setattr(arbeitnow_mod, "ARBEITNOW_PAGES", 5)
    client, seen = make_client(arbeitnow_pages(1, last_has_next=False))
    jobs = get_source("arbeitnow").fetch(client)
    assert len(seen) == 1
    assert len(jobs) == len(load("arbeitnow")["data"])


def test_arbeitnow_fetch_stops_on_empty_page(monkeypatch):
    from radar.sources import arbeitnow as arbeitnow_mod

    monkeypatch.setattr(arbeitnow_mod, "ARBEITNOW_PAGES", 5)
    full = load("arbeitnow")

    def handler(request):
        if request.url.params["page"] == "1":
            return httpx.Response(200, json=full)
        return httpx.Response(200, json={**full, "data": []})

    client, seen = make_client(handler)
    jobs = get_source("arbeitnow").fetch(client)
    assert len(seen) == 2
    assert len(jobs) == len(full["data"])


def test_arbeitnow_to_fields():
    source = get_source("arbeitnow")
    jobs = by_id(source.fetch(make_client(arbeitnow_pages(1, last_has_next=False))[0]))

    f = source.to_fields(jobs["remote-director-of-national-accounts-300180"].payload)
    assert f["title"] == "Director of National Accounts"
    assert f["company"] == "Access Destination Services"
    assert f["is_remote"] is True
    assert f["location"] == "Remote"
    assert f["posted_at"] == datetime(2026, 11, 6, 9, 40, 14)
    assert f["employment_type_text"] == "Full Time"
    assert f["source_category"] == "National"
    assert f["source_tags"] == ["National"]
    assert f["salary_text"] is None and f["salary_min"] is None

    # on-site German job: kept, flagged non-remote; gender marker left for normalize
    f = source.to_fields(jobs["senior-backend-engineer-berlin-129736"].payload)
    assert f["title"] == "Senior Backend Engineer (m/w/d)"
    assert f["company"] == "caronsale"
    assert f["is_remote"] is False
    assert f["location"] == "Berlin"
    assert f["employment_type_text"] is None  # empty job_types
    assert f["source_category"] == "Engineering"
    # description is entity-escaped upstream and passed through untouched
    assert f["description_html"].startswith("&lt;")
    assert f["url"].startswith("https://www.arbeitnow.com/jobs/companies/caronsale/")

    # empty location -> None; ampersand title survives
    f = source.to_fields(jobs["data-protection-quality-management-officer-434849"].payload)
    assert f["location"] is None
    assert f["title"] == "Data Protection & Quality Management Officer"
    assert f["is_remote"] is False

    # "Remote" tag is not a category; several job types joined
    f = source.to_fields(
        jobs["e-commerce-manager-marktplatze-internationalisierung-berlin-311820"].payload
    )
    assert f["is_remote"] is True
    assert f["source_tags"] == ["Remote", "Online Marketing"]
    assert f["source_category"] == "Online Marketing"
    assert f["employment_type_text"] == "Unbefristeter arbeitsvertrag, berufserfahren"
    assert f["title"] == "E-Commerce Manager (m/w/d) – Marktplätze & Internationalisierung"

    f = source.to_fields(
        jobs["talent-acquisition-specialist-dusseldorf-north-rhine-westphalia-83966"].payload
    )
    assert f["location"] == "Düsseldorf, North Rhine-Westphalia"


# -------------------------------------------------------------------------------- Jobicy


def jobicy_pages(*, always_more: bool = False, pages: int = 2):
    """Serve the fixture as page 1 (hasMore) and shifted-id copies after that."""
    base = load("jobicy")

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        n = 1 if cursor is None else int(cursor.removeprefix("cursor-"))
        data = copy.deepcopy(base)
        for row in data["jobs"]:
            row["id"] += (n - 1) * 100000
        last = n >= pages and not always_more
        data["hasMore"] = not last
        data["nextCursor"] = None if last else f"cursor-{n + 1}"
        return httpx.Response(200, json=data)

    return handler


def test_jobicy_fetch_follows_cursor_until_has_more_is_false():
    source = get_source("jobicy")
    client, seen = make_client(jobicy_pages(pages=2))
    jobs = source.fetch(client)
    default = [r for r in seen if "industry" not in r.url.params]
    assert any("industry" in r.url.params for r in seen)  # filtered feed requested too
    assert len(default) == 2  # stopped by hasMore=false, not by JOBICY_PAGES (3)
    assert "cursor" not in seen[0].url.params
    assert seen[0].url.params["count"] == str(jobicy_mod.PAGE_SIZE)
    assert seen[1].url.params["cursor"] == "cursor-2"
    assert all(str(r.url).startswith("https://jobicy.com/api/v2/remote-jobs?") for r in seen)
    assert all(r.headers["user-agent"] == USER_AGENT for r in seen)
    assert len(jobs) == 16
    assert len({j.external_id for j in jobs}) == 16
    assert jobs[0].external_id == "159265" and jobs[8].external_id == "259265"
    assert jobs[0].payload == load("jobicy")["jobs"][0]


def test_jobicy_fetch_caps_at_configured_pages():
    assert JOBICY_PAGES == 3
    client, seen = make_client(jobicy_pages(always_more=True))
    jobs = get_source("jobicy").fetch(client)
    default = [r for r in seen if "industry" not in r.url.params]
    assert len(default) == JOBICY_PAGES
    assert any("industry" in r.url.params for r in seen)  # filtered feed requested too
    assert len(jobs) == 8 * JOBICY_PAGES


def test_jobicy_fetch_single_page_when_no_more():
    client, seen = make_client(jobicy_pages(pages=1))
    jobs = get_source("jobicy").fetch(client)
    default = [r for r in seen if "industry" not in r.url.params]
    assert len(default) == 1 and len(jobs) == 8
    assert any("industry" in r.url.params for r in seen)  # filtered feed requested too


def test_jobicy_fetch_stops_without_cursor_even_if_has_more():
    data = {**load("jobicy"), "hasMore": True, "nextCursor": None}
    client, seen = make_client(json_handler(data))
    get_source("jobicy").fetch(client)
    default = [r for r in seen if "industry" not in r.url.params]
    assert len(default) == 1
    assert any("industry" in r.url.params for r in seen)  # filtered feed requested too


def test_jobicy_fetch_rejects_bad_shape():
    client, _ = make_client(json_handler({"success": False, "error": "nope"}))
    with pytest.raises(ValueError):
        get_source("jobicy").fetch(client)


def test_jobicy_to_fields():
    source = get_source("jobicy")
    jobs = by_id(source.fetch(make_client(jobicy_pages(pages=1))[0]))

    f = source.to_fields(jobs["159265"].payload)
    assert f["title"] == "Data Scientist"
    assert f["company"] == "Solace"
    assert f["url"] == "https://jobicy.com/jobs/159265-data-scientist-7"
    assert f["location"] == "USA"
    assert f["is_remote"] is True
    assert f["posted_at"] == datetime(2026, 11, 6, 6, 17, 17)
    assert f["description_html"].startswith("<h3>")
    assert f["salary_text"] is None
    assert f["salary_min"] == 160000.0 and f["salary_max"] == 200000.0
    assert f["salary_currency"] == "USD" and f["salary_period"] == "year"
    assert f["source_tags"] == ["Data Science & Analytics"]
    assert f["source_category"] == "Data Science & Analytics"
    assert f["employment_type_text"] == "Full-Time"
    assert f["seniority_hint"] == "Director"

    # hourly, level "Any" -> no hint
    f = source.to_fields(jobs["159255"].payload)
    assert (f["salary_min"], f["salary_max"], f["salary_period"]) == (40.0, 40.0, "hour")
    assert f["seniority_hint"] is None
    assert f["employment_type_text"] == "Contract"

    # monthly EUR
    f = source.to_fields(jobs["154706"].payload)
    assert (f["salary_min"], f["salary_currency"], f["salary_period"]) == (600.0, "EUR", "month")
    assert f["seniority_hint"] == "Entry-Level, Junior"
    assert f["employment_type_text"] == "Internship"

    # CAD yearly, multi-country geo whitespace collapsed
    f = source.to_fields(jobs["159260"].payload)
    assert (f["salary_min"], f["salary_max"]) == (69000.0, 115000.0)
    assert f["salary_currency"] == "CAD" and f["salary_period"] == "year"
    f = source.to_fields(jobs["159250"].payload)
    assert f["location"] == "Canada, USA"

    # no salary keys at all
    f = source.to_fields(jobs["159261"].payload)
    assert "salaryMin" not in jobs["159261"].payload
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (
        None,
        None,
        None,
        None,
    )

    assert source.to_fields(jobs["159236"].payload)["title"] == (
        "Growth Marketing Manager, AI & Paid Programs"
    )


def test_jobicy_unknown_period_and_currency_case():
    f = get_source("jobicy").to_fields(
        {
            "id": 1,
            "jobTitle": "X &amp; Y",
            "companyName": " Co ",
            "url": "https://jobicy.com/jobs/1",
            "salaryMin": 5,
            "salaryMax": 9,
            "salaryPeriod": "weekly",
            "salaryCurrency": "usd",
            "jobExcerpt": "short text",
        }
    )
    assert f["title"] == "X & Y" and f["company"] == "Co"
    assert f["salary_period"] is None
    assert f["salary_currency"] == "USD"
    assert f["description_html"] == "short text"  # falls back to the excerpt
    assert f["posted_at"] is None
