"""Tests for radar.skills.display: names for skills that are not in aliases.yaml."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

import pytest

from radar.aggregate import JobRecord, derive_skill_names
from radar.skills import find_spellings, is_known_skill, normalize_skill, pick_display
from radar.skills.display import is_distinctive, titleize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("business strategy", "Business Strategy"),
        ("go to market strategy", "Go to Market Strategy"),
        ("command of the message", "Command of the Message"),
        ("b2b saas", "B2B Saas"),
        ("k8s", "K8S"),
        ("s3", "S3"),
        ("web3", "Web3"),
        ("", ""),
    ],
)
def test_titleize(text, expected):
    assert titleize(text) == expected


@pytest.mark.parametrize(
    ("spelling", "distinctive"),
    [
        ("MEDDPICC", True),
        ("OSINT", True),
        ("CPaaS", True),
        ("B2B SaaS", True),
        ("iOS", True),
        ("AI tools", True),
        ("Business Strategy", False),
        ("business strategy", False),
        ("Business strategy", False),
        ("Go-to-Market Strategy", False),
        ("S3", False),  # one letter is not an acronym
    ],
)
def test_is_distinctive(spelling, distinctive):
    assert is_distinctive(spelling) is distinctive


def test_find_spellings_matches_the_slug_words_with_any_separator():
    texts = [
        "We use MEDDPICC. meddpicc is great, MEDDPICC!",
        "Go-to-Market strategy and go to market strategy and GO TO MARKET STRATEGY",
        "x-ray scans, ray tracing, Ray",
    ]
    assert find_spellings("meddpicc", texts) == Counter({"MEDDPICC": 2, "meddpicc": 1})
    gtm = find_spellings("go-to-market-strategy", texts)
    assert sum(gtm.values()) == 3 and "Go-to-Market strategy" in gtm
    ray = find_spellings("ray", texts)
    assert ray == Counter({"ray": 1, "Ray": 1})  # not the "ray" inside "x-ray"
    assert find_spellings("---", texts) == Counter()
    assert find_spellings("sales", ["salesforce"]) == Counter()  # whole words only


def test_pick_display_prefers_the_usual_spelling_when_it_has_real_casing():
    assert pick_display("meddpicc", Counter({"MEDDPICC": 5, "Meddpicc": 1})) == "MEDDPICC"
    assert pick_display("cpaas", {"CPaaS": 3}) == "CPaaS"
    assert pick_display("b2b-saas", {"B2B SaaS": 4, "b2b saas": 1}) == "B2B SaaS"
    # words around an acronym get a capital: "AI tools" -> "AI Tools"
    assert pick_display("ai-tools", {"AI tools": 2}) == "AI Tools"


def test_pick_display_falls_back_to_the_title_cased_slug():
    assert pick_display("business-strategy") == "Business Strategy"
    assert pick_display("bom-modeling", {}) == "Bom Modeling"
    # the usual spelling is plain, so a rare shouted one does not win
    assert pick_display("infrastructure", {"infrastructure": 9, "INFRASTRUCTURE": 1}) == (
        "Infrastructure"
    )
    assert pick_display("causal-inference", {"Causal Inference": 4}) == "Causal Inference"
    assert pick_display("b2b-saas") == "B2B Saas"


NOW = datetime(2026, 11, 7, 12, 0)


def record(i: int, skills: list[str], text: str, days_ago: int = 1) -> JobRecord:
    return JobRecord(
        id=f"remotive-{i}",
        source="remotive",
        title=f"Job {i}",
        company=f"Company {i}",
        url="https://example.com",
        location=None,
        posted_at=NOW - timedelta(days=days_ago),
        role="data",
        seniority="senior",
        employment_type="full_time",
        remote_regions=[],
        skills=skills,
        description=text,
    )


def test_derive_skill_names_keeps_curated_names_and_reads_spellings_from_postings():
    # "python" is a curated skill (aliases.yaml) and keeps its curated name; the other
    # slugs are not and take the spelling seen in the posting text.
    assert is_known_skill("python") and not is_known_skill("osint")
    assert not is_known_skill("zorblax-ops")
    records = [
        record(1, ["python", "zorblax-ops", "osint"], "Python, OSINT, ZorblaxOps, ZORBLAX OPS."),
        record(2, ["zorblax-ops", "quux-strategy"], "ZORBLAX OPS, ZORBLAX OPS; quux strategy"),
        record(3, ["mystery-tool"], "nothing relevant here"),
    ]
    assert derive_skill_names(records) == {
        "python": "Python",
        "osint": "OSINT",
        "zorblax-ops": "ZORBLAX OPS",
        "quux-strategy": "Quux Strategy",
        "mystery-tool": "Mystery Tool",
    }


def test_derive_skill_names_slugs_come_from_the_normaliser():
    slug = normalize_skill("Quuxify Pro")
    assert slug == "quuxify-pro"
    assert derive_skill_names([record(1, [slug], "we love QuuxifyPro")])[slug] == "QuuxifyPro"


def test_derive_skill_names_reads_only_a_bounded_sample_newest_first():
    old = [record(i, ["foo-bar"], "Foo-BAR FOO-BAR", days_ago=30 + i) for i in range(40)]
    new = [record(100 + i, ["foo-bar"], "foo-bar foo-bar", days_ago=1) for i in range(12)]
    # the 12 newest postings (all lower-case) decide; the 40 old shouting ones are not read
    assert derive_skill_names([*old, *new])["foo-bar"] == "Foo Bar"
