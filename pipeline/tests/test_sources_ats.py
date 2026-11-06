"""Tests for the Greenhouse / Ashby / Lever board sources. No network: MockTransport only."""

from __future__ import annotations

import copy
import html
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from radar.config import HTTP_TIMEOUT, USER_AGENT
from radar.sources import ats_boards
from radar.sources import base as base_mod
from radar.sources.ashby import AshbySource
from radar.sources.ats_boards import (
    ALL_BOARDS,
    ATS_NAMES,
    Board,
    extract_salary_snippet,
    load_boards,
    mentions_remote,
    parse_boards,
    plain_text,
)
from radar.sources.greenhouse import GreenhouseSource
from radar.sources.lever import LeverSource, description_html

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


def fixture_rows(ats: str) -> list[dict]:
    data = load(ats)
    return data if isinstance(data, list) else data["jobs"]


def board(ats: str, token: str, company: str) -> Board:
    hosts = {"greenhouse": "job-boards.greenhouse.io", "ashby": "jobs.ashbyhq.com"}
    host = hosts.get(ats, "jobs.lever.co")
    return Board(ats, token, company, f"https://{host}/{token}")


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


def envelope(ats: str, rows: list[dict]):
    """Wrap rows the way each ATS's API does."""
    return rows if ats == "lever" else {"jobs": rows}


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(base_mod, "RETRY_WAIT_SECONDS", 0)


SOURCES = {"greenhouse": GreenhouseSource, "ashby": AshbySource, "lever": LeverSource}
PAGE_FIELDS = {"greenhouse": "jobs", "ashby": "jobs", "lever": None}


def fetch_fixture(ats: str, token: str = "acme", company: str = "Acme Corp"):
    source = SOURCES[ats]([board(ats, token, company)])
    client, seen = make_client(lambda request: httpx.Response(200, json=load(ats)))
    jobs = source.fetch(client)
    return source, jobs, seen


def by_id(jobs):
    return {j.external_id: j for j in jobs}


# ------------------------------------------------------------------- class attributes


@pytest.mark.parametrize(
    ("ats", "display", "homepage"),
    [
        ("greenhouse", "Greenhouse boards", "https://www.greenhouse.com"),
        ("ashby", "Ashby boards", "https://www.ashbyhq.com"),
        ("lever", "Lever boards", "https://www.lever.co"),
    ],
)
def test_source_identity(ats, display, homepage):
    source = SOURCES[ats]()
    assert source.name == ats
    assert source.display_name == display
    assert source.homepage == homepage
    assert source.scope == "broad"
    assert all(b.ats == ats for b in source.boards)
    assert source.boards  # the shipped YAML has boards for every ATS


# ------------------------------------------------------------------------- YAML list


def test_shipped_yaml_is_valid_and_complete():
    boards = load_boards()
    assert boards == ALL_BOARDS
    assert {b.ats for b in boards} == set(ATS_NAMES)
    assert len({(b.ats, b.token) for b in boards}) == len(boards)
    for b in boards:
        assert b.company == b.company.strip() and b.company
        assert b.careers_url.startswith("https://") and b.token in b.careers_url


def good_entry(**overrides):
    entry = {
        "ats": "lever",
        "token": "acme",
        "company": "Acme",
        "careers_url": "https://jobs.lever.co/acme",
    }
    return {**entry, **overrides}


def test_parse_boards_accepts_valid_entries():
    boards = parse_boards([good_entry(), good_entry(ats="ashby", company=" Acme Two ")])
    assert [(b.ats, b.token, b.company) for b in boards] == [
        ("lever", "acme", "Acme"),
        ("ashby", "acme", "Acme Two"),
    ]
    assert parse_boards([]) == []


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"ats": "lever"}, "expected a list"),
        (["nope"], "expected a mapping"),
        ([{"ats": "lever", "token": "x"}], "missing"),
        ([good_entry(ats="workday")], "ats must be one of"),
        ([good_entry(token="bad token/../x")], "invalid token"),
        ([good_entry(token="")], "non-empty"),
        ([good_entry(company="   ")], "non-empty"),
        ([good_entry(company=None)], "non-empty"),
        ([good_entry(careers_url="http://jobs.lever.co/acme")], "https"),
        ([good_entry(), good_entry(company="Dup")], "duplicate"),
        ([good_entry(extra="x")], "unknown keys"),
    ],
)
def test_parse_boards_rejects_bad_data(data, message):
    with pytest.raises(ValueError, match=message):
        parse_boards(data)


def test_load_boards_rejects_malformed_file(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- {ats: nope, token: x, company: X, careers_url: 'https://x.test'}\n")
    with pytest.raises(ValueError, match="ats must be one of"):
        load_boards(path)
    assert ats_boards.YAML_PATH.name == "ats_companies.yaml"


# ---------------------------------------------------------------------------- fetching


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_fetch_requests_one_get_per_board_with_user_agent(ats):
    boards = [board(ats, "alpha", "Alpha"), board(ats, "beta", "Beta")]
    source = SOURCES[ats](boards)
    client, seen = make_client(lambda request: httpx.Response(200, json=load(ats)))
    source.fetch(client)
    assert [r.method for r in seen] == ["GET", "GET"]
    assert all(r.headers["user-agent"] == USER_AGENT for r in seen)
    assert "alpha" in seen[0].url.path and "beta" in seen[1].url.path
    first = str(seen[0].url)
    expected = {
        "greenhouse": "https://boards-api.greenhouse.io/v1/boards/alpha/jobs?content=true",
        "ashby": "https://api.ashbyhq.com/posting-api/job-board/alpha?includeCompensation=true",
        "lever": "https://api.lever.co/v0/postings/alpha?mode=json",
    }
    assert first == expected[ats]


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_fetch_namespaces_ids_and_takes_company_from_the_list(ats):
    source, jobs, _ = fetch_fixture(ats, token="acme", company="Acme Corp")
    assert jobs and all(j.source == ats for j in jobs)
    assert all(j.external_id.startswith("acme/") for j in jobs)
    assert len({j.external_id for j in jobs}) == len(jobs)
    for job in jobs:
        assert job.payload["_radar"] == {"board": "acme", "company": "Acme Corp"}
        assert source.to_fields(job.payload)["company"] == "Acme Corp"


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_payload_is_the_api_object_plus_radar_key(ats):
    _, jobs, _ = fetch_fixture(ats)
    originals = {str(r["id"]): r for r in fixture_rows(ats)}
    for job in jobs:
        payload = dict(job.payload)
        payload.pop("_radar")
        assert payload == originals[job.external_id.split("/", 1)[1]]
        json.dumps(job.payload)


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_every_fixture_job_maps_cleanly(ats):
    rows = fixture_rows(ats)
    assert 5 <= len(rows) <= 10
    source, jobs, _ = fetch_fixture(ats)
    assert 0 < len(jobs) < len(rows)  # non-remote rows are filtered out
    for job in jobs:
        fields = source.to_fields(job.payload)
        assert set(fields) == FIELD_KEYS
        assert fields["title"] and fields["title"] == fields["title"].strip()
        assert fields["company"] == "Acme Corp"
        assert fields["url"].startswith("https://")
        assert fields["is_remote"] is True
        assert isinstance(fields["posted_at"], datetime) and fields["posted_at"].tzinfo is None
        assert fields["salary_period"] in {"year", "month", "hour", None}
        assert all(isinstance(t, str) and t for t in fields["source_tags"])
        if fields["salary_min"] is None and fields["salary_max"] is None:
            assert fields["salary_period"] is None and fields["salary_currency"] is None
        before = copy.deepcopy(job.payload)
        source.to_fields(job.payload)
        assert job.payload == before


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_non_remote_rows_still_map_with_is_remote_false(ats):
    source = SOURCES[ats]([board(ats, "acme", "Acme Corp")])
    kept = {
        j.payload["id"]
        for j in source.fetch(make_client(lambda r: httpx.Response(200, json=load(ats)))[0])
    }
    dropped = [r for r in fixture_rows(ats) if r["id"] not in kept]
    assert dropped
    for row in dropped:
        fields = source.to_fields({**row, "_radar": {"board": "acme", "company": "Acme Corp"}})
        assert fields["is_remote"] is False


def routed_handler(routes: dict[str, object]):
    """Serve ``routes[token]`` (a response, or a payload) based on the URL path."""

    def handler(request: httpx.Request) -> httpx.Response:
        for token, outcome in routes.items():
            if f"/{token}" in request.url.path:
                if isinstance(outcome, httpx.Response):
                    return outcome
                return httpx.Response(200, json=outcome)
        return httpx.Response(404)

    return handler


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_one_failing_board_does_not_stop_the_others(ats, caplog):
    boards = [
        board(ats, "good1", "Good One"),
        board(ats, "broken", "Broken"),
        board(ats, "good2", "Good Two"),
    ]
    source = SOURCES[ats](boards)
    handler = routed_handler(
        {"good1": load(ats), "broken": httpx.Response(500), "good2": load(ats)}
    )
    client, seen = make_client(handler)
    with caplog.at_level("WARNING"):
        jobs = source.fetch(client)
    companies = {j.payload["_radar"]["company"] for j in jobs}
    assert companies == {"Good One", "Good Two"}
    assert len(seen) == 4  # the 500 was retried once, then the next board was still fetched
    assert [(r.token, r.ok) for r in source.last_report] == [
        ("good1", True),
        ("broken", False),
        ("good2", True),
    ]
    assert source.last_report[0].remote_jobs == len(jobs) // 2
    assert source.last_report[0].open_jobs == len(fixture_rows(ats))
    assert "broken" in caplog.text


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_a_404_or_malformed_body_counts_as_a_failed_board(ats):
    boards = [board(ats, "gone", "Gone"), board(ats, "weird", "Weird"), board(ats, "good", "Good")]
    source = SOURCES[ats](boards)
    weird = httpx.Response(200, json="not what the API normally returns")
    client, _ = make_client(routed_handler({"weird": weird, "good": load(ats)}))
    jobs = source.fetch(client)
    assert {j.payload["_radar"]["board"] for j in jobs} == {"good"}
    assert [r.ok for r in source.last_report] == [False, False, True]
    assert source.last_report[0].error and "404" in source.last_report[0].error


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_non_json_body_counts_as_a_failed_board(ats):
    boards = [board(ats, "html", "Html"), board(ats, "good", "Good")]
    source = SOURCES[ats](boards)
    html_page = httpx.Response(200, text="<html>maintenance</html>")
    client, _ = make_client(routed_handler({"html": html_page, "good": load(ats)}))
    assert source.fetch(client)
    assert source.last_report[0].ok is False


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_all_boards_failing_raises(ats):
    boards = [board(ats, "a", "A"), board(ats, "b", "B")]
    source = SOURCES[ats](boards)
    client, _ = make_client(lambda request: httpx.Response(503))
    with pytest.raises(RuntimeError, match="all 2 boards failed"):
        source.fetch(client)
    assert [r.ok for r in source.last_report] == [False, False]


@pytest.mark.parametrize("ats", ["greenhouse", "ashby", "lever"])
def test_empty_board_is_not_a_failure(ats):
    source = SOURCES[ats]([board(ats, "quiet", "Quiet")])
    client, _ = make_client(lambda request: httpx.Response(200, json=envelope(ats, [])))
    assert source.fetch(client) == []
    assert source.last_report[0].ok is True and source.last_report[0].open_jobs == 0


def test_no_boards_means_no_requests():
    client, seen = make_client(lambda request: httpx.Response(200, json={"jobs": []}))
    assert GreenhouseSource([]).fetch(client) == []
    assert seen == []


# ------------------------------------------------------------------------ text helpers


def test_mentions_remote():
    for yes in (
        "Remote - US",
        "US-Remote",
        "San Francisco or Remote",
        "Anywhere in EMEA",
        "remote",
    ):
        assert mentions_remote(yes), yes
    for no in (
        "San Francisco, CA",
        "Hybrid - London",
        "On-site (not remote)",
        "Remotely hosted",
        "",
        None,
    ):
        assert not mentions_remote(no), no


def test_plain_text_unescapes_twice_and_strips_tags():
    escaped = (
        "&lt;div&gt;Pay &amp;amp; benefits&lt;/div&gt;&lt;p&gt;&amp;mdash;&amp;nbsp;ok&lt;/p&gt;"
    )
    assert plain_text(escaped) == "Pay & benefits — ok"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The base salary range is $164,200 — $229,990 USD. In select", "$164,200 — $229,990 USD"),
        ("Salary: $95.4K–$190K annually, plus equity", "$95.4K–$190K annually"),
        ("Pay is $38 - $52.50 per hour", "$38 - $52.50 per hour"),
        ("compensation: £113,000 - £161,000", "£113,000 - £161,000"),
        ("Salary range €53.000 — €71.000 EUR", "€53.000 — €71.000 EUR"),
        ("The salary is CAD $90,000 to $120,000 a year", "CAD $90,000 to $120,000 a year"),
        ("US$ 56.07 to US$ 87.13 base pay", None),  # no pay word *before* the range
        ("base pay: US$ 56.07 to US$ 87.13", "US$ 56.07 to US$ 87.13"),
        ("Our compensation philosophy: we raised $100 - $200 million", None),
        ("Compensation info: revenue of $5M-$10M", None),
        ("We offer a $500 stipend and a salary that is competitive", None),
        ("We hire in 2024 - 2026 and the base is great", None),
        ("London or Remote (UK) | 💰£85,000 - £115,000 + Incentive", "£85,000 - £115,000"),
        ("", None),
        (None, None),
    ],
)
def test_extract_salary_snippet(text, expected):
    assert extract_salary_snippet(text) == expected


def test_extract_salary_snippet_without_context_requirement():
    assert extract_salary_snippet("$70,000 - $90,000 USD per year", require_context=False) == (
        "$70,000 - $90,000 USD per year"
    )
    assert extract_salary_snippet("$70,000 - $90,000") is None


# ---------------------------------------------------------------------------- Greenhouse


def gh_fields():
    source, jobs, _ = fetch_fixture("greenhouse", token="reddit", company="Reddit")
    return source, {j.external_id: source.to_fields(j.payload) for j in jobs}, by_id(jobs)


def test_greenhouse_remote_detection():
    source, fields, _ = gh_fields()
    assert sorted(fields) == sorted(
        f"reddit/{i}" for i in (8282760, 7131932, 7131934, 8023563, 9000001, 9000002, 9000003)
    )
    # "Remote - US" and "Anywhere in EMEA" in the location, "Remote" only in an office name,
    # and "Remote (UK)" only in a location-type metadata field all count
    assert fields["reddit/8282760"]["location"] == "Remote - United States"
    assert fields["reddit/9000001"]["location"] == "Anywhere in EMEA"
    assert fields["reddit/9000002"]["location"] == "New York, NY"
    assert fields["reddit/9000003"]["location"] == "London, UK"
    # "San Francisco, CA" and "Hybrid - London" (metadata says remote eligible: No) do not
    rows = {r["id"]: r for r in fixture_rows("greenhouse")}
    assert rows[8349916]["location"]["name"] == "San Francisco, CA"
    assert source.is_remote(rows[8349916]) is False
    assert source.is_remote(rows[9000004]) is False
    assert source.is_remote({"id": 1, "location": {"name": "Berlin"}}) is False
    assert source.is_remote({"id": 1, "location": {"name": "Remote, Germany"}}) is True
    assert source.is_remote({"id": 1}) is False


def test_greenhouse_to_fields():
    _, fields, jobs = gh_fields()
    f = fields["reddit/8282760"]
    assert f["title"] == "Analytics Engineer"
    assert f["company"] == "Reddit"
    assert f["url"] == "https://job-boards.greenhouse.io/reddit/jobs/8282760"
    assert f["is_remote"] is True
    assert f["posted_at"] == datetime(2026, 10, 14, 22, 3, 16)  # first_published, converted to UTC
    assert f["salary_text"] == "$164,200 — $229,990 USD"
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (
        None,
        None,
        None,
        None,
    )
    assert f["source_tags"] == ["Data Science"] and f["source_category"] == "Data Science"
    assert f["employment_type_text"] is None and f["seniority_hint"] is None
    # content stays entity-escaped HTML for the normaliser
    assert f["description_html"] == jobs["reddit/8282760"].payload["content"]
    assert f["description_html"].startswith("&lt;div")

    assert fields["reddit/7131932"]["salary_text"] == "$185,800 — $260,100 USD"
    assert fields["reddit/7131934"]["salary_text"] is None  # no pay block in the content
    assert fields["reddit/7131934"]["location"] == "Remote - Ontario, Canada"
    assert fields["reddit/8023563"]["source_category"] == "Sales"


def test_greenhouse_posted_at_falls_back_to_updated_at_and_company_to_api():
    source, fields, jobs = gh_fields()
    assert fields["reddit/9000001"]["posted_at"] == datetime(2026, 11, 6, 12, 22, 5)
    # a magnitude like "$100 - $200 million" is not a salary
    assert fields["reddit/9000001"]["salary_text"] is None
    # without the YAML company the API's company_name is used
    payload = {k: v for k, v in jobs["reddit/8282760"].payload.items() if k != "_radar"}
    assert source.to_fields(payload)["company"] == "Reddit"


def test_greenhouse_metadata_employment_type():
    source = GreenhouseSource([])
    job = {
        "id": 1,
        "title": "X",
        "location": {"name": "Remote"},
        "absolute_url": "https://job-boards.greenhouse.io/x/jobs/1",
        "metadata": [{"name": "Employment Type", "value": "Full-time"}],
        "departments": [{"name": "Data"}, {"name": "Data"}, {"name": ""}],
    }
    f = source.to_fields(job)
    assert f["employment_type_text"] == "Full-time"
    assert f["source_tags"] == ["Data"]
    assert f["posted_at"] is None and f["description_html"] is None and f["salary_text"] is None


# ---------------------------------------------------------------------------------- Ashby


def ashby_fields():
    source, jobs, _ = fetch_fixture("ashby", token="plaid", company="Plaid")
    return source, {j.external_id.rsplit("-", 1)[-1]: source.to_fields(j.payload) for j in jobs}


def test_ashby_remote_means_workplace_type_remote_only():
    source, fields = ashby_fields()
    # the hybrid Plaid job has isRemote=true but must be excluded
    hybrid = next(r for r in fixture_rows("ashby") if r["workplaceType"] == "Hybrid")
    assert hybrid["isRemote"] is True
    assert source.is_remote(hybrid) is False
    assert set(fields) == {
        "000000000001",
        "000000000002",
        "000000000003",
        "000000000004",
        "000000000007",
    }
    # unlisted remote job and on-site job are excluded too
    rows = {r["id"][-4:]: r for r in fixture_rows("ashby")}
    assert rows["0005"]["workplaceType"] == "Remote" and rows["0005"]["isListed"] is False
    assert source.is_remote(rows["0005"]) is False
    assert source.is_remote(rows["0006"]) is False
    assert source.is_remote({"workplaceType": "remote"}) is True
    assert source.is_remote({"isRemote": True}) is False
    assert source.is_remote({}) is False


def test_ashby_salary_from_compensation():
    _, fields = ashby_fields()
    f = fields["000000000001"]
    assert f["title"] == "Senior Data Engineer"
    assert f["company"] == "Plaid"
    assert f["url"] == "https://jobs.ashbyhq.com/plaid/aaaaaaaa-0000-0000-0000-000000000001"
    assert f["location"] == "Remote - US"
    assert f["posted_at"] == datetime(2026, 9, 3, 0, 40, 25, 842000)
    assert (f["salary_min"], f["salary_max"]) == (190800.0, 238800.0)
    assert (f["salary_currency"], f["salary_period"]) == ("USD", "year")
    assert f["salary_text"] is None
    assert f["employment_type_text"] == "Full-time"
    assert f["description_html"].startswith("<p")

    # hourly EUR, contract; "All Departments" is ignored in favour of the team
    f = fields["000000000002"]
    assert (f["salary_min"], f["salary_max"]) == (40.0, 55.0)
    assert (f["salary_currency"], f["salary_period"]) == ("EUR", "hour")
    assert f["employment_type_text"] == "Contract"
    assert f["source_tags"] == ["Analytics"] and f["source_category"] == "Analytics"

    # no compensation block at all
    f = fields["000000000003"]
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (
        None,
        None,
        None,
        None,
    )
    assert f["salary_text"] is None
    assert f["employment_type_text"] == "Part-time"

    # only a lower bound; the equity component before it is skipped
    f = fields["000000000007"]
    assert (f["salary_min"], f["salary_max"]) == (90000.0, None)
    assert (f["salary_currency"], f["salary_period"]) == ("CAD", "year")
    assert f["source_category"] == "Data"


def test_ashby_unsupported_interval_keeps_text_not_numbers():
    _, fields = ashby_fields()
    f = fields["000000000004"]
    assert f["salary_min"] is None and f["salary_max"] is None
    assert f["salary_currency"] is None and f["salary_period"] is None
    assert f["salary_text"] == "$3K - $4K per week"


def test_ashby_summary_text_when_only_a_tier_summary_exists():
    source = AshbySource([])
    f = source.to_fields(
        {
            "id": "x",
            "title": "T",
            "jobUrl": "https://jobs.ashbyhq.com/x/x",
            "workplaceType": "Remote",
            "compensation": {
                "compensationTierSummary": "$100K - $120K • Offers Equity",
                "summaryComponents": [],
            },
        }
    )
    assert f["salary_text"] == "$100K - $120K • Offers Equity"
    assert f["salary_min"] is None


# ---------------------------------------------------------------------------------- Lever


def lever_fields():
    source, jobs, _ = fetch_fixture("lever", token="spotify", company="Spotify")
    return source, {j.external_id: source.to_fields(j.payload) for j in jobs}, by_id(jobs)


def test_lever_remote_means_workplace_type_remote():
    source, fields, _ = lever_fields()
    assert len(fields) == 6  # of 8: one hybrid and one onsite are dropped
    rows = fixture_rows("lever")
    kinds = {r["text"]: r["workplaceType"] for r in rows}
    assert kinds["Backend Engineer - Data Platform"] == "hybrid"
    assert kinds["Data Scientist  - Business Analytics"] == "onsite"
    assert not any(f["title"] in {"Backend Engineer - Data Platform"} for f in fields.values())
    assert source.is_remote({"workplaceType": "remote"}) is True
    assert source.is_remote({"workplaceType": "Remote"}) is True
    assert source.is_remote({"workplaceType": "hybrid"}) is False
    assert source.is_remote({"workplaceType": "unspecified"}) is False
    assert source.is_remote({}) is False


def test_lever_to_fields_structured_salary():
    _, fields, jobs = lever_fields()
    ids = {f["title"]: i for i, f in fields.items()}

    f = fields[ids["Success Engineer (Global)"]]
    assert ids["Success Engineer (Global)"].startswith("spotify/20d0af01-")
    assert f["company"] == "Spotify"
    assert f["url"].startswith("https://jobs.lever.co/metabase/20d0af01-")
    assert f["location"] == "Global Remote"
    assert f["posted_at"] == datetime(2020, 5, 19, 22, 42, 58, 39000)
    assert (f["salary_min"], f["salary_max"]) == (90000.0, 190000.0)
    assert (f["salary_currency"], f["salary_period"]) == ("USD", "year")
    assert f["salary_text"] is None
    assert f["employment_type_text"] == "Full-time (remote)"
    assert (
        f["source_tags"] == ["Success Engineering"]
        and f["source_category"] == "Success Engineering"
    )

    f = fields[ids["Data Analyst, Contract"]]
    assert (f["salary_min"], f["salary_max"]) == (38.0, 52.5)
    assert (f["salary_currency"], f["salary_period"]) == ("USD", "hour")  # "usd" upper-cased
    assert f["source_tags"] == ["Personalization", "Engineering"]
    assert f["source_category"] == "Engineering"
    assert f["location"] == "New York, NY"

    f = fields[ids["Engineering Manager - Data Platform"]]
    assert f["employment_type_text"] == "Permanent"
    assert f["posted_at"].tzinfo is None
    assert jobs[ids["Engineering Manager - Data Platform"]].payload["workplaceType"] == "remote"


def test_lever_salary_text_fallbacks():
    _, fields, _ = lever_fields()
    ids = {f["title"]: i for i, f in fields.items()}
    # no salaryRange: the sentence in salaryDescriptionPlain is cut down to the range
    f = fields[ids["Business Intelligence Analyst"]]
    assert f["salary_text"] == "$70,000 - $90,000 USD per year"
    assert f["salary_min"] is None and f["salary_period"] is None
    # no salaryRange and no salary description: nothing
    assert fields[ids["Product Manager - Data Platform"]]["salary_text"] is None

    # Metabase style: the range only lives in the "additional" text
    source = LeverSource([board("lever", "metabase", "Metabase")])
    client, _ = make_client(lambda request: httpx.Response(200, json=load("lever")))
    # (served from the spotify fixture; the first two rows are the Metabase postings)
    jobs = source.fetch(client)
    meta = next(
        source.to_fields(j.payload) for j in jobs if j.payload["text"] == "Analytics Engineer"
    )
    assert meta["salary_text"] == "$95.4K–$190K annually"
    assert meta["location"] == "Remote-North & South America"
    assert meta["posted_at"] == datetime(2020, 11, 19, 2, 41, 25, 375000)


def test_lever_unknown_interval_drops_numbers():
    source = LeverSource([])
    f = source.to_fields(
        {
            "id": "1",
            "text": "T",
            "hostedUrl": "https://jobs.lever.co/x/1",
            "workplaceType": "remote",
            "salaryRange": {
                "min": 3000,
                "max": 4000,
                "currency": "USD",
                "interval": "per-week-salary",
            },
            "categories": {"allLocations": ["Remote - EU", "Remote - UK"]},
        }
    )
    assert f["salary_min"] is None and f["salary_max"] is None
    assert f["salary_currency"] is None and f["salary_period"] is None
    assert f["location"] == "Remote - EU, Remote - UK"


def test_lever_description_combines_sections():
    _, fields, jobs = lever_fields()
    spotify_pm = next(
        j for j in jobs.values() if j.payload["text"] == "Product Manager - Data Platform"
    )
    html_text = fields[spotify_pm.external_id]["description_html"]
    assert html_text.startswith(spotify_pm.payload["description"])
    for item in spotify_pm.payload["lists"]:
        assert f"<h3>{html.escape(item['text'])}</h3>" in html_text
    assert html_text.count("<ul>") == len(spotify_pm.payload["lists"])
    assert html_text.rstrip().endswith(spotify_pm.payload["additional"].rstrip())

    # plain-text only postings are wrapped into paragraphs, and the opening+body fallback works
    assert (
        description_html({"descriptionPlain": "A & B\n\nline two"})
        == "<p>A &amp; B</p><p>line two</p>"
    )
    assert (
        description_html({"opening": "<p>o</p>", "descriptionBody": "<p>b</p>"})
        == "<p>o</p><p>b</p>"
    )
    assert description_html({}) is None
