"""Tests for radar.dedupe."""

from __future__ import annotations

import re

import pytest

from radar.dedupe import dedupe_key, normalize_company, normalize_title

# Same job cross-posted / re-posted: every pair must collide.
COLLISIONS = [
    pytest.param(
        ("Acme GmbH", "Senior Backend Engineer (m/w/d)"),
        ("ACME", "Senior Backend Engineer"),
        id="legal-suffix-and-gender-marker",
    ),
    pytest.param(
        ("Fluence International, Inc.", "Full-Stack Developer"),
        ("Fluence International", "Fullstack Developer - Remote"),
        id="inc-and-remote-suffix-and-fullstack-spelling",
    ),
    pytest.param(
        ("Lemon.io", "Senior Back-end Developer"),
        ("lemon.io ", "Senior Backend Developer (Remote)"),
        id="backend-spelling-and-remote-paren",
    ),
    pytest.param(
        ("Teampicnic", "Senior Category Manager Non-Food (m/w/d) - Berlin"),
        ("Teampicnic", "Senior Category Manager Non-Food"),
        id="location-tail-dash",
    ),
    pytest.param(
        ("Example Ltd", "Senior Accountant | London"),
        ("Example Limited", "Senior Accountant"),
        id="pipe-location-and-ltd-vs-limited",
    ),
    pytest.param(
        ("Workato", "Sr. Forward Deployed AI Engineer (Remote Eligible in the UK)"),
        ("workato", "Senior Forward Deployed AI Engineer"),
        id="sr-expansion-and-remote-eligible-paren",
    ),
    pytest.param(
        ("Some Corp.", "Client Support &amp; Travel Booking Online"),
        ("Some", "Client Support & Travel Booking Online"),
        id="html-entities-and-corp",
    ),
    pytest.param(
        ("Concircle Österreich GmbH", "Sales & Account Manager*"),
        ("Concircle Osterreich", "Sales and Account Manager"),
        id="accents-ampersand-and-trailing-asterisk",
    ),
    pytest.param(
        ("Bar B.V.", "Developer Advocate (France)"),
        ("Bar", "Developer Advocate"),
        id="bv-and-parenthesised-country",
    ),
    pytest.param(
        ("Foo S.A.", "Data Engineer in Germany"),
        ("Foo", "Data Engineer"),
        id="sa-and-in-country",
    ),
]


@pytest.mark.parametrize(("a", "b"), COLLISIONS)
def test_same_job_collides(a, b):
    assert dedupe_key(*a) == dedupe_key(*b)


# Genuinely different jobs: every pair must differ.
DISTINCT = [
    pytest.param(
        ("Acme", "Product Manager - Security"),
        ("Acme", "Product Manager - Investing"),
        id="different-team-suffix-is-not-a-location",
    ),
    pytest.param(
        ("Acme", "Senior Backend Engineer"),
        ("Acme", "Backend Engineer"),
        id="seniority-is-kept",
    ),
    pytest.param(
        ("Acme", "Backend Engineer"),
        ("Beta", "Backend Engineer"),
        id="different-company",
    ),
    pytest.param(
        ("Acme", "C++ Developer"),
        ("Acme", "C# Developer"),
        id="plus-and-hash-are-kept",
    ),
    pytest.param(
        ("Acme", "Junior Marketing Manager B2B"),
        ("Acme", "Senior Marketing Manager B2B"),
        id="junior-vs-senior",
    ),
    pytest.param(
        ("Acme", "Data Engineer"),
        ("Acme", "Data Analyst"),
        id="different-role",
    ),
    pytest.param(
        ("Acme", "Remote Sensing Engineer"),
        ("Acme", "Sensing Engineer"),
        id="remote-sensing-is-a-discipline-not-a-marker",
    ),
    pytest.param(
        ("Rotzinger Group", "Buchhalter"),
        ("Rotzinger PharmaPack", "Buchhalter"),
        id="group-is-not-a-legal-suffix",
    ),
    pytest.param(
        ("Acme", "AI Trainer - Video Annotation"),
        ("Acme", "AI Trainer - Audio Annotation"),
        id="dash-qualifier-differs",
    ),
]


@pytest.mark.parametrize(("a", "b"), DISTINCT)
def test_different_jobs_do_not_collide(a, b):
    assert dedupe_key(*a) != dedupe_key(*b)


def test_key_format_and_stability():
    key = dedupe_key("Acme GmbH", "Senior Backend Engineer (m/w/d)")
    assert re.fullmatch(r"[0-9a-f]{40}", key)
    # stable across runs: sha1("acme|senior backend engineer")
    assert key == "2084cbbe9e8ee5853a7a305c9898e22c45665bf0"


def test_empty_inputs_do_not_crash():
    assert len(dedupe_key("", "")) == 40
    assert dedupe_key("", "") == dedupe_key("  ", " ")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fluence International, Inc.", "fluence international"),
        ("Acme GmbH & Co. KG", "acme"),
        ("The Talent Institute", "talent institute"),
        ("Foo S.A.", "foo"),
        ("Co", "co"),  # never reduces a name to nothing
    ],
)
def test_normalize_company(raw, expected):
    assert normalize_company(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Senior Backend Engineer (m/w/d)", "senior backend engineer"),
        ("Senior Python Developer - Remote", "senior python developer"),
        ("Data Engineer | London", "data engineer"),
        ("Product Manager - Security", "product manager security"),
        ("Senior/Staff Software Engineer", "senior staff software engineer"),
        ("C++ Developer", "c++ developer"),
    ],
)
def test_normalize_title(raw, expected):
    assert normalize_title(raw) == expected
