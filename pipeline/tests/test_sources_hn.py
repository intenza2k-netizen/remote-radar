"""Tests for the Hacker News "Who is hiring?" adapter. No network: fetch uses MockTransport.

``fixtures/hn_thread.json`` holds real top-level comments from the November 2026 thread
(trimmed to their first paragraphs) plus a few synthetic edge cases with ids >= 900000000
(explicit "no remote", a ``Remote.com`` company, a deleted comment, a blank comment).
``hn_thread_prev.json`` is a small synthetic October thread, ``hn_search.json`` models the
Algolia search response.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from radar.config import HTTP_TIMEOUT, USER_AGENT
from radar.sources import base as base_mod
from radar.sources import hackernews as hn
from radar.sources.base import SourceJob
from radar.sources.hackernews import (
    HackerNewsSource,
    first_line,
    looks_remote,
    parse_first_line,
    select_threads,
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

NOW_EARLY = datetime(2026, 11, 6, 12, 0)  # latest thread is 4 days old
NOW_LATE = datetime(2026, 11, 20, 12, 0)  # latest thread is 18 days old

# Remote comments in hn_thread.json (everything else is on-site, hybrid or unusable).
REMOTE_IDS = {
    "50338732",
    "50338736",
    "50338907",
    "50340101",
    "50339308",
    "50342723",
    "50341833",
    "50349615",
    "50344339",
    "50341745",
    "50349601",
    "50342365",
    "50350077",
    "50346665",
    "900000005",
}
PREV_REMOTE_IDS = {"910000001"}


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


def hn_handler(search=None, threads=None):
    search = load("hn_search") if search is None else search
    threads = threads or {
        "50338728": load("hn_thread"),
        "48999999": load("hn_thread_prev"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/search_by_date"):
            return httpx.Response(200, json=search)
        thread_id = path.rsplit("/", 1)[-1]
        if thread_id in threads:
            return httpx.Response(200, json=threads[thread_id])
        return httpx.Response(404, json={"error": "not found"})

    return handler


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(base_mod, "RETRY_WAIT_SECONDS", 0)


def fetch(now: datetime = NOW_EARLY, **handler_kwargs):
    client, seen = make_client(hn_handler(**handler_kwargs))
    jobs = HackerNewsSource(now=lambda: now).fetch(client)
    return jobs, seen


def by_id(jobs: list[SourceJob]) -> dict[str, SourceJob]:
    return {j.external_id: j for j in jobs}


def thread_comment(comment_id: int) -> dict:
    for child in load("hn_thread")["children"]:
        if child["id"] == comment_id:
            return child
    raise KeyError(comment_id)


# ---------------------------------------------------------------------------- identity


def test_source_identity():
    source = HackerNewsSource()
    assert source.name == "hackernews"
    assert source.display_name == "Hacker News: Who is hiring"
    assert source.homepage == "https://news.ycombinator.com"
    assert source.scope == "broad"


def test_module_constants():
    assert hn.PREVIOUS_THREAD_IF_YOUNGER_THAN_DAYS == 10
    assert hn.SEARCH_URL == "https://hn.algolia.com/api/v1/search_by_date"
    assert hn.ITEM_URL == "https://hn.algolia.com/api/v1/items/{id}"


# ------------------------------------------------------------------------- first_line


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Acme | Engineer | REMOTE<p>Second paragraph", "Acme | Engineer | REMOTE"),
        ("Acme | Engineer<br>REMOTE", "Acme | Engineer"),
        ("Acme | Engineer\nsecond line", "Acme | Engineer"),
        ("<p>Acme | Engineer<p>more", "Acme | Engineer"),
        ("A &amp; B | Dev &#x2F; Ops | Berlin&#x27;s", "A & B | Dev / Ops | Berlin's"),
        (
            'Acme | <a href="https:&#x2F;&#x2F;acme.test&#x2F;jobs" rel="nofollow">'
            "https:&#x2F;&#x2F;acme.test&#x2F;jobs</a> | REMOTE",
            "Acme | https://acme.test/jobs | REMOTE",
        ),
        ("  spaced   out  ", "spaced out"),
        ("", ""),
        (None, ""),
        (42, ""),
    ],
)
def test_first_line(text, expected):
    assert first_line(text) == expected


# ---------------------------------------------------------------------- looks_remote


@pytest.mark.parametrize(
    "line",
    [
        "Acme | Engineer | REMOTE",
        "Acme | Engineer | Remote (US only)",
        "Acme | Engineer | remote",
        "Acme | Engineer | REMOTE(US)",
        "Acme | Engineer | US Remote | Full-time",
        "Acme | Engineer | Fully Remote (US-only)",
        "Acme | Engineer | Fully-remote",
        "Acme | Engineer | 100% Remote (Global)",
        "Acme | Engineer | Remote-first",
        "Acme | Engineer | NYC or REMOTE (US, Europe)",
        "Acme | Engineer | REMOTE (US) or ONSITE in Reno, NV",
        "Acme | Engineer | ONSITE (SoCal preferred) or REMOTE (US)",
        "North America, South America, Europe REMOTE",
        "DuckDuckGo - all of our roles are fully-remote, except where noted",
        "*Software Engineer - Remote - US Only*",
        "UNICEF - REMOTE backend dev",
        "Acme | Engineer | Remote possible | Full-time",
        "Acme | Engineer | Chicago, IL / Remote",
        "Acme | Engineer | Remote (no visa sponsorship)",
        "Acme | Engineer | Remote, not relocation",
    ],
)
def test_looks_remote_true(line):
    assert looks_remote(line)


@pytest.mark.parametrize(
    "line",
    [
        "",
        "Acme | Engineer | ONSITE | San Francisco",
        "Acme | Engineer | Hybrid (3 days/week)",
        "Acme | Engineer | In Office",
        "Acme | Engineer | No remote",
        "Acme | Engineer | NO REMOTE, onsite only",
        "Acme | Engineer | Not remote",
        "Acme | Engineer | Non-remote",
        "Acme | Engineer | no remote work",
        "Acme | Engineer | Remote not possible",
        "Acme | Engineer | remote is not available",
        "Acme | Engineer | Remote work unavailable",
        "Acme | Engineer | ONSITE (part remote)",
        "OpenRent | London, UK | ONSITE+PART REMOTE",
        "Acme | Engineer | partially remote",
        "Acme | Engineer | Onsite only",
        "Remote.com | Senior Recruiter | Berlin | ONSITE",
        "RemoteOK | Engineer | Berlin | ONSITE",
        "Acme | https://remote-first.example.com/jobs | Berlin | ONSITE",
        "Acme | Engineer | Berlin | 2 days in the office",
    ],
)
def test_looks_remote_false(line):
    assert not looks_remote(line)


def test_looks_remote_only_inspects_the_start_of_the_line():
    line = "Acme | Engineer | " + "x" * 400 + " | REMOTE"
    assert not looks_remote(line)
    assert looks_remote(line, limit=1000)
    assert looks_remote("Acme | Engineer | " + "x" * 100 + " | REMOTE")


def test_looks_remote_negation_does_not_hide_a_separate_remote():
    assert looks_remote("Acme | Engineer | REMOTE (EU) | no remote contractors in the US")


# --------------------------------------------------------------------- parse_first_line


def parsed(line: str):
    h = parse_first_line(line)
    return (h.company, h.title, h.location, h.salary_text, h.employment_type_text)


def test_parse_conventional_pipe_line():
    assert parsed(
        "Simple Analytics | DevOps Engineer | REMOTE (worldwide, any timezone) | "
        "Full-time, 32h, 24h possible | €5,000/month (full-time)"
    ) == (
        "Simple Analytics",
        "DevOps Engineer",
        "REMOTE (worldwide, any timezone)",
        "€5,000/month (full-time)",
        "Full-time",
    )


def test_parse_order_varies():
    assert parsed("Rune Labs | Remote (US, CA) | Full Time | Senior or Lead Backend Engineer") == (
        "Rune Labs",
        "Senior or Lead Backend Engineer",
        "Remote (US, CA)",
        None,
        "Full-time",
    )
    assert parsed(
        "KSC Trading | Remote | Full-Time | Senior Backend Software Engineer | "
        "$200k to $250k USD Total Compensation + Benefits"
    ) == (
        "KSC Trading",
        "Senior Backend Software Engineer",
        None,  # a bare "Remote" says nothing beyond is_remote
        "$200k to $250k USD Total Compensation + Benefits",
        "Full-time",
    )


def test_parse_city_and_remote_both_kept_as_location():
    h = parse_first_line("Synteq | Systems Administrator | Austin, TX | REMOTE (US) | Full-time")
    assert h.title == "Systems Administrator"
    assert h.location == "Austin, TX; REMOTE (US)"


def test_parse_strips_urls_parentheses_and_bare_domains():
    h = parse_first_line(
        "Distru (https://www.distru.com) | Product Engineer | REMOTE (Americas) | "
        "https://jobs.distru.com/1 | distru.com"
    )
    assert h.company == "Distru"
    assert h.title == "Product Engineer"
    assert h.location == "REMOTE (Americas)"
    h = parse_first_line("MixRank (YC S11) | Software Engineers | 100% Remote (Global) | Full-Time")
    assert h.company == "MixRank"
    assert h.location == "100% Remote (Global)"
    # a company called after its domain keeps it
    assert parse_first_line("Fly.io | REMOTE (multiple countries) | Full time").company == "Fly.io"
    # URL as the second field
    h = parse_first_line("Better Stack | https://betterstack.com/ | Backend Engineer | Remote (EU)")
    assert (h.company, h.title) == ("Better Stack", "Backend Engineer")


def test_parse_multiple_roles_in_one_field():
    h = parse_first_line(
        "PostHog | Full-Time | Technical CSMs, SRE, Product Manager, AI Research Engineer | "
        "REMOTE (all remote)"
    )
    assert h.title == "Multiple roles: Technical CSMs, SRE, Product Manager, …"
    assert h.multiple_roles
    assert h.employment_type_text == "Full-time"
    h = parse_first_line(
        "Telescope Partners | Software Engineer & Data Scientist | Remote | Full-time"
    )
    assert h.title == "Multiple roles: Software Engineer, Data Scientist"
    h = parse_first_line("ORFF Maestra | Prototype Developer; Technical Product Lead | REMOTE (US)")
    assert h.title == "Multiple roles: Prototype Developer, Technical Product Lead"
    h = parse_first_line(
        "Stratirus | AI Developer + Linux Admin (junior to mid) | REMOTE (US only)"
    )
    assert h.title == "Multiple roles: AI Developer, Linux Admin (junior to mid)"


def test_parse_multiple_roles_in_separate_fields():
    h = parse_first_line(
        "Distru | AI Product Engineer | AI Product Manager | VP of Product | REMOTE (Americas)"
    )
    assert h.title == "Multiple roles: AI Product Engineer, AI Product Manager, VP of Product"
    assert h.multiple_roles
    assert h.location == "REMOTE (Americas)"


def test_parse_single_role_with_comma_or_ampersand_is_not_split():
    assert parse_first_line("Postscript | Senior Software Engineer, Full Stack | REMOTE").title == (
        "Senior Software Engineer, Full Stack"
    )
    assert parse_first_line("CreativeLens | Founding Growth & Sales Lead | Remote (US)").title == (
        "Founding Growth & Sales Lead"
    )
    assert parse_first_line(
        "Reddit | Senior and Staff Full-stack Engineers | REMOTE(US)"
    ).title == ("Senior and Staff Full-stack Engineers")
    assert parse_first_line(
        "Mozilla | Staff Software Engineer, Browser (New Products) | REMOTE"
    ).title == ("Staff Software Engineer, Browser (New Products)")


def test_parse_generic_multiple_roles():
    h = parse_first_line("Sumble | Multiple Roles | Remote (US)| Full-time ")
    assert h.title == "Multiple roles"
    assert h.multiple_roles
    assert h.location == "Remote (US)"
    h = parse_first_line(
        "Fusionality | Multiple Positions (Controls, SciML, Data Engineering) | Lausanne | REMOTE"
    )
    assert h.title == "Multiple roles: Controls, SciML, Data Engineering"


def test_parse_no_role_gives_generic_title():
    h = parse_first_line("Curai | Remote (US) | Full-time | https://curaihealth.com")
    assert (h.company, h.title, h.location) == ("Curai", "Multiple roles", "Remote (US)")
    assert h.multiple_roles


def test_parse_salary_forms():
    cases = {
        "A | Dev Engineer | Remote | $60-120K USD/year": "$60-120K USD/year",
        "A | Engineer | Remote | $55 - $75/hr": "$55 - $75/hr",
        "A | Engineer | Remote | 70k - 100k EUR": "70k - 100k EUR",
        "A | Engineer | Remote | £115k + equity": "£115k + equity",
        "A | Engineer | Remote | €80k–110k": "€80k–110k",
        "A | Engineer | Remote | $199K–$249K + equity": "$199K–$249K + equity",
        "A | Engineer | Remote | 200k - 325k + Equity": "200k - 325k + Equity",
        "A | Engineer | Remote | $170k to $230k Base + Equity + Health": (
            "$170k to $230k Base + Equity + Health"
        ),
        "A | Engineer | Remote | $130,000 - $150,000": "$130,000 - $150,000",
    }
    for line, expected in cases.items():
        assert parse_first_line(line).salary_text == expected, line


def test_parse_non_salary_numbers_are_ignored():
    h = parse_first_line(
        "A | Engineer | Remote | Full-time | Series B | 10 openings | 2-3 days in office | "
        "€10k signing bonus"
    )
    assert h.salary_text is None


def test_parse_employment_types():
    assert parse_first_line("A | Engineer | Remote | Full time").employment_type_text == "Full-time"
    assert (
        parse_first_line("A | Engineer | Remote | Part-time or Full-time").employment_type_text
        == "Part-time, Full-time"
    )
    assert (
        parse_first_line("A | Engineer | Remote | Contract, part-time").employment_type_text
        == "Contract, Part-time"
    )
    assert parse_first_line("A | Engineer | Remote | Summer internship").employment_type_text == (
        "Internship"
    )
    assert parse_first_line("A | Engineer | Remote").employment_type_text is None


def test_parse_dash_separated_line():
    h = parse_first_line("Acme - Data Engineer - Remote (EU) - Full-time - 70k - 90k EUR")
    assert h.company == "Acme"
    assert h.title == "Data Engineer"
    assert h.location == "Remote (EU)"
    assert h.employment_type_text == "Full-time"
    assert h.salary_text == "70k - 90k EUR"


def test_parse_bullet_separated_line():
    h = parse_first_line("Acme • Data Analyst • Remote (US) • Full-time")
    assert (h.company, h.title, h.location) == ("Acme", "Data Analyst", "Remote (US)")


def test_parse_line_without_company_field():
    h = parse_first_line("*Software Engineer — Remote — US Only* - US Work Authorization Required")
    assert h.company is None
    assert h.title == "Software Engineer"


def test_parse_prose_line():
    h = parse_first_line(
        "Duranta (https://getduranta.com/) is hiring a computer vision engineer, "
        "enterprise account representative, and sales representatives"
    )
    assert h.company == "Duranta"
    assert h.title == (
        "Multiple roles: computer vision engineer, enterprise account representative, "
        "sales representatives"
    )
    h = parse_first_line(
        "DigitalTolk is hiring for remote positions across Pakistan, India and Philippines."
    )
    assert (h.company, h.title) == ("DigitalTolk", "Multiple roles")


def test_parse_sentence_instead_of_company_falls_back_to_none():
    h = parse_first_line(
        "Backed by Sequoia Capital, Peregrine is the operational AI platform powering "
        "decision making | Remote | $175,000 - $300,000"
    )
    assert h.company is None
    assert h.salary_text == "$175,000 - $300,000"
    assert parse_first_line("Location: Dorset, UK").company is None
    assert parse_first_line("Apply here: https://example.test/apply").company is None


def test_parse_place_before_company():
    h = parse_first_line("Cologne, Germany | UMH | Product Engineer | Full-time | REMOTE (EU)")
    assert h.company == "UMH"
    assert h.title == "Product Engineer"
    assert h.location == "Cologne, Germany; REMOTE (EU)"


def test_parse_role_in_location_field_is_not_a_role():
    h = parse_first_line(
        "Meta | Security Engineer (Senior / Staff) | ONSITE Bellevue, Menlo Park, New York — "
        "Staff role also REMOTE (US) | Full-time"
    )
    assert h.title == "Security Engineer (Senior / Staff)"
    assert h.location is not None and "REMOTE (US)" in h.location


def test_parse_noise_fields_are_not_locations():
    h = parse_first_line(
        "Quantum Rise | Chicago IL or Remote (US, Brazil or EU) | Full-time | "
        "No visa sponsorship | Hiring GMT-8 to GMT+2 | German-speaking | Series A"
    )
    assert h.location == "Chicago IL or Remote (US, Brazil or EU)"


def test_parse_empty_and_junk():
    h = parse_first_line("")
    assert (h.company, h.title, h.location, h.salary_text) == (None, "Multiple roles", None, None)
    h = parse_first_line("| | |")
    assert h.company is None and h.title == "Multiple roles"


def test_parse_long_titles_are_capped():
    roles = ", ".join(f"Senior Specialist Engineer {i}" for i in range(12))
    h = parse_first_line(f"A | {roles} | Remote")
    assert len(h.title) <= 150


# ---------------------------------------------------------------------- select_threads


def test_select_threads_keeps_only_who_is_hiring_titles():
    hits = load("hn_search")["hits"]
    chosen = select_threads(hits, NOW_LATE)
    assert [h["objectID"] for h in chosen] == ["50338728"]
    chosen = select_threads(hits, NOW_EARLY)
    assert [h["objectID"] for h in chosen] == ["50338728", "48999999"]
    for h in chosen:
        assert h["title"].startswith("Ask HN: Who is hiring?")


def test_select_threads_orders_by_date_not_by_input_order():
    hits = list(reversed(load("hn_search")["hits"]))
    assert [h["objectID"] for h in select_threads(hits, NOW_EARLY)] == ["50338728", "48999999"]


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 11, 2, 16, 1, 38), 2),  # a second old
        (datetime(2026, 11, 6, 12, 0), 2),  # 4 days
        (datetime(2026, 11, 12, 16, 1, 0), 2),  # just under 10 days
        (datetime(2026, 11, 12, 16, 1, 37), 1),  # exactly 10 days: not "less than"
        (datetime(2026, 11, 20, 12, 0), 1),
    ],
)
def test_select_threads_previous_month_rule(now, expected):
    assert len(select_threads(load("hn_search")["hits"], now)) == expected


def test_select_threads_previous_month_rule_with_tz_aware_now():
    from datetime import UTC

    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    assert len(select_threads(load("hn_search")["hits"], now)) == 2


def test_select_threads_single_thread_available_when_young():
    hits = [h for h in load("hn_search")["hits"] if h["objectID"] == "50338728"]
    assert len(select_threads(hits, NOW_EARLY)) == 1


def test_select_threads_ignores_other_titles_and_junk():
    hits = [
        h
        for h in load("hn_search")["hits"]
        if "hiring" not in h["title"]  # only "wants to be hired" / "Freelancer" left
    ]
    assert select_threads(hits + ["junk", None, {"title": None}], NOW_EARLY) == []
    assert select_threads([], NOW_EARLY) == []


def test_select_threads_matches_title_case_insensitively():
    hit = {
        "objectID": "1",
        "title": "ask hn: WHO IS HIRING? (January 2027)",
        "created_at_i": 1798000000,
    }
    assert select_threads([hit], datetime(2027, 1, 5)) == [hit]


# ----------------------------------------------------------------------------- fetch


def test_fetch_requests_and_politeness():
    jobs, seen = fetch()
    assert jobs
    assert len(seen) == 3  # one search + one item request per thread, no more
    search = seen[0]
    assert str(search.url).startswith("https://hn.algolia.com/api/v1/search_by_date?")
    assert search.url.params["tags"] == "story,author_whoishiring"
    assert search.url.params["hitsPerPage"] == "10"
    assert [r.url.path for r in seen[1:]] == [
        "/api/v1/items/50338728",
        "/api/v1/items/48999999",
    ]
    assert all(r.headers["User-Agent"] == USER_AGENT for r in seen)


def test_fetch_keeps_remote_top_level_posts_from_both_threads():
    jobs, _ = fetch()
    assert {j.external_id for j in jobs} == REMOTE_IDS | PREV_REMOTE_IDS
    assert {j.source for j in jobs} == {"hackernews"}


def test_fetch_late_in_the_month_uses_only_the_latest_thread():
    jobs, seen = fetch(NOW_LATE)
    assert len(seen) == 2
    assert {j.external_id for j in jobs} == REMOTE_IDS


def test_fetch_skips_non_remote_negated_deleted_and_blank_posts():
    ids = {j.external_id for j in fetch()[0]}
    assert "50338768" not in ids  # ONSITE
    assert "50339895" not in ids  # ONSITE (part remote)
    assert "50349755" not in ids  # ONSITE+PART REMOTE
    assert "900000001" not in ids  # No remote, ONSITE only
    assert "900000002" not in ids  # Not remote
    assert "900000003" not in ids  # company called Remote.com, on-site job
    assert "900000004" not in ids  # REMOTE only mentioned in the second paragraph
    assert "900000006" not in ids  # deleted: no text, no author
    assert "900000007" not in ids  # blank text
    assert "910000002" not in ids  # previous thread, on-site


def test_fetch_payload_is_the_comment_without_replies():
    jobs = by_id(fetch()[0])
    original = thread_comment(50338732)
    assert original["children"], "fixture should contain a reply to prove it is dropped"
    payload = jobs["50338732"].payload
    assert "children" not in payload
    assert payload == {k: v for k, v in original.items() if k != "children"}
    json.dumps(payload)  # serialisable


def test_fetch_ignores_nested_replies_as_posts():
    reply_id = str(thread_comment(50338732)["children"][0]["id"])
    assert reply_id not in {j.external_id for j in fetch()[0]}


def test_fetch_dedupes_comments_seen_in_both_threads():
    thread = load("hn_thread")
    prev = copy.deepcopy(load("hn_thread_prev"))
    prev["children"].append(copy.deepcopy(thread["children"][0]))  # same comment id twice
    jobs, _ = fetch(threads={"50338728": thread, "48999999": prev})
    assert [j.external_id for j in jobs].count("50338732") == 1


def test_fetch_retries_once_on_server_error():
    thread = load("hn_thread")
    calls = {"n": 0}
    inner = hn_handler(threads={"50338728": thread, "48999999": load("hn_thread_prev")})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search_by_date"):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503)
        return inner(request)

    client, seen = make_client(handler)
    jobs = HackerNewsSource(now=lambda: NOW_EARLY).fetch(client)
    assert jobs
    assert calls["n"] == 2
    assert len(seen) == 4  # failed search, retried search, two item requests


def test_fetch_server_error_twice_raises():
    client, _ = make_client(lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        HackerNewsSource(now=lambda: NOW_EARLY).fetch(client)


def test_fetch_rejects_bad_search_shape():
    with pytest.raises(ValueError, match="search response"):
        fetch(search={"nope": []})
    with pytest.raises(ValueError, match="search response"):
        fetch(search=[1, 2])


def test_fetch_raises_when_no_hiring_thread_is_listed():
    search = load("hn_search")
    search["hits"] = [h for h in search["hits"] if "hiring" not in h["title"]]
    with pytest.raises(ValueError, match="no 'Ask HN: Who is hiring"):
        fetch(search=search)


def test_fetch_rejects_bad_item_shape():
    with pytest.raises(ValueError, match="item response"):
        fetch(threads={"50338728": {"id": 1, "children": None}, "48999999": {}})


def test_fetch_tolerates_odd_children():
    thread = load("hn_thread")
    thread["children"] = ["junk", None, {"text": "no id | REMOTE"}, *thread["children"][:1]]
    jobs, _ = fetch(threads={"50338728": thread, "48999999": load("hn_thread_prev")})
    assert {j.external_id for j in jobs} == {"50338732", "910000001"}


# --------------------------------------------------------------------------- to_fields


def test_to_fields_conventional_post():
    jobs = by_id(fetch()[0])
    f = HackerNewsSource().to_fields(jobs["50338732"].payload)
    assert set(f) == FIELD_KEYS
    assert f["title"] == "DevOps Engineer"
    assert f["company"] == "Simple Analytics"
    assert f["url"] == "https://news.ycombinator.com/item?id=50338732"
    assert f["location"] == "REMOTE (worldwide, any timezone)"
    assert f["is_remote"] is True
    assert f["posted_at"] == datetime(2026, 11, 2, 16, 1, 43)
    assert f["description_html"] == thread_comment(50338732)["text"]
    assert f["description_html"].startswith("Simple Analytics | DevOps Engineer")
    assert f["salary_text"] == "€5,000/month (full-time)"
    assert f["employment_type_text"] == "Full-time"
    assert (f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_period"]) == (
        None,
        None,
        None,
        None,
    )
    assert f["source_tags"] == []
    assert f["source_category"] is None
    assert f["seniority_hint"] is None


def test_to_fields_keeps_html_as_is():
    f = HackerNewsSource().to_fields(thread_comment(50338732))
    assert "<p>" in f["description_html"]
    assert "&#x2F;" in f["description_html"]  # entities are left for the normaliser


def test_to_fields_multiple_roles_title():
    f = HackerNewsSource().to_fields(thread_comment(50338907))
    assert f["company"] == "PostHog"
    assert f["title"].startswith("Multiple roles: Technical CSMs, SRE, Product Manager")
    assert f["employment_type_text"] == "Full-time"


def test_to_fields_company_falls_back_to_author():
    comment = thread_comment(50344339)  # "*Software Engineer — Remote — US Only* - ..."
    f = HackerNewsSource().to_fields(comment)
    assert f["company"] == f"HN user {comment['author']}"
    assert f["title"] == "Software Engineer"
    no_author = {k: v for k, v in comment.items() if k != "author"}
    assert HackerNewsSource().to_fields(no_author)["company"] == "Unknown"


def test_to_fields_uses_epoch_when_created_at_missing():
    comment = {**thread_comment(50338732), "created_at": None}
    assert HackerNewsSource().to_fields(comment)["posted_at"] == datetime(2026, 11, 2, 16, 1, 43)
    comment = {**comment, "created_at_i": None}
    assert HackerNewsSource().to_fields(comment)["posted_at"] is None


def test_to_fields_blank_text_gives_no_description():
    f = HackerNewsSource().to_fields({"id": 5, "text": "  ", "author": "x"})
    assert f["description_html"] is None
    assert f["url"].endswith("id=5")
    assert f["is_remote"] is False


def test_to_fields_for_every_fetched_job():
    source = HackerNewsSource()
    for job in fetch()[0]:
        f = source.to_fields(job.payload)
        assert set(f) == FIELD_KEYS
        assert f["is_remote"] is True
        assert f["title"] and f["company"]
        assert f["url"] == f"https://news.ycombinator.com/item?id={job.external_id}"
        assert f["description_html"]
        assert isinstance(f["posted_at"], datetime)
        assert f["source_tags"] == []


def test_real_fixture_parse_snapshot():
    """Hand-checked header parses of real posts, as (company, title, location, salary)."""
    expected = {
        50338736: (
            "Synteq",
            "Multiple roles: Growth Lead, Systems Administrator",
            "Austin, TX; REMOTE (US)",
            None,
        ),
        50340101: (
            "River",
            "Staff Engineers (Elixir)",
            "NYC or REMOTE (US, Europe, South America)",
            "$200K-$250K + equity",
        ),
        50339308: (
            "Kraus Hamdani Aerospace",
            "Software Engineer",
            "REMOTE (US) or ONSITE in Reno, NV",
            None,
        ),
        50342723: ("Fly.io", "Multiple roles", "REMOTE (multiple countries)", "$190k USD + equity"),
        50341833: ("Evaboot", "Agentic Python Engineer", "REMOTE worldwide", "$60-120K USD/year"),
        50342365: ("REVNODE", "Founding Sales (Founding AE)", "Remote (US)", None),
        50341745: ("DuckDuckGo", "Multiple roles", None, None),
    }
    source = HackerNewsSource()
    for comment_id, want in expected.items():
        f = source.to_fields(thread_comment(comment_id))
        assert (f["company"], f["title"], f["location"], f["salary_text"]) == want, comment_id
