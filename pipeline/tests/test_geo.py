"""Tests for radar.geo: memberships, the open-to rule and the geo.json document."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from radar import geo, regions
from radar.aggregate import JobRecord, RawSalary
from radar.geo import Memberships, compute_geo, is_open_to, load_memberships, open_via
from radar.regions import region_key

NOW = datetime(2026, 11, 7, 12, 0)
FIXTURE = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "geo.fixtures.json"


def rec(
    i: int,
    regions_: list[str],
    *,
    role: str = "data",
    skills: tuple[str, ...] = ("sql",),
    salary: float | None = None,
) -> JobRecord:
    return JobRecord(
        id=f"src-{i}",
        source="src",
        title=f"Job {i}",
        company=f"Company {i}",
        url=f"https://example.com/{i}",
        location=None,
        posted_at=NOW - timedelta(days=2),
        role=role,
        seniority="mid",
        employment_type="full_time",
        remote_regions=list(regions_),
        skills=list(skills),
        salaries=[RawSalary(salary, salary, "USD", "year")] if salary else [],
    )


# --------------------------------------------------------------------------- memberships (real)


@pytest.fixture(scope="module")
def real() -> Memberships:
    return load_memberships()


def test_real_memberships_load_and_are_flat(real):
    assert real.countries
    for macro, members in real.macros.items():
        assert members, macro
        assert members <= real.countries, (macro, sorted(members - real.countries))
        assert macro not in real.countries


def test_eu_eea_europe_emea_definitions(real):
    m = real.macros
    assert len(m["EU"]) == 27
    assert m["EEA"] == m["EU"] | {"Iceland", "Liechtenstein", "Norway"}
    assert m["EEA"] <= m["Europe"]
    assert {"United Kingdom", "Switzerland", "Ukraine", "Estonia"} <= m["Europe"]
    assert "Türkiye" not in m["Europe"]
    assert m["Europe"] <= m["EMEA"]
    assert m["Middle East"] <= m["EMEA"]
    assert m["Africa"] <= m["EMEA"]
    assert {"Türkiye", "Israel", "Kenya", "South Africa"} <= m["EMEA"]
    assert "United States" not in m["EMEA"]


def test_americas_asia_pacific_africa_definitions(real):
    m = real.macros
    assert m["Americas"] == m["North America"] | m["Latin America"]
    assert {"United States", "Canada"} <= m["North America"]
    assert "Mexico" in m["Latin America"]
    assert "Mexico" not in m["North America"]  # UN "Northern America"
    assert m["South America"] <= m["Latin America"]
    assert {"Brazil", "Argentina"} <= m["South America"]
    assert {"India", "Japan", "Australia", "Singapore", "Philippines"} <= m["Asia-Pacific"]
    assert not (m["Asia-Pacific"] & m["Europe"])
    assert (
        len(m["North Africa"] | m["Sub-Saharan Africa"] - {"British Indian Ocean Territory"}) == 54
    )
    assert m["Africa"] == m["North Africa"] | m["Sub-Saharan Africa"]
    assert not (m["North Africa"] & m["Sub-Saharan Africa"])


def test_every_country_name_in_regions_yaml_is_known(real):
    """Canonical places of the ``regions:`` table that are countries are in the master list."""
    reg = regions._registry()
    canon = set(reg.by_key.values()) - {regions.WORLDWIDE} - set(real.macros)
    unknown = sorted(c for c in canon if c not in real.countries)
    assert unknown == []


def test_region_group_lists_agree_with_memberships(real):
    """The coarse region groups (radar.regions) only use places the memberships also know, and
    put each in the matching macro region."""
    ours = {region_key(c): c for c in real.countries} | {region_key(m): m for m in real.macros}
    aliases = regions._registry().by_key  # "European Union" -> "EU"
    group_macro = {
        regions.EUROPE: "Europe",
        regions.LATAM: "Latin America",
        regions.APAC: "Asia-Pacific",
        regions.US_CANADA: "North America",
    }
    for key, group in regions._GROUP_OF.items():
        name = ours.get(key) or ours.get(region_key(aliases.get(key, key)))
        assert name is not None, f"{key!r} (region group {group}) is not a known country or macro"
        macro = group_macro[group]
        if name in real.macros:
            continue  # a macro name itself (EU, EMEA, Latin America ...)
        assert name in real.macros[macro], f"{name} should be in {macro}"


def test_real_sanctioned_list(real):
    assert {"Cuba", "Iran", "North Korea", "Syria"} <= real.sanctioned
    assert real.sanctioned <= real.countries
    assert not real.sanctioned & real.macros["Europe"]
    assert not geo.is_open_to(["worldwide"], "North Korea", real.macros, real.sanctioned)
    assert geo.is_open_to(["worldwide"], "Estonia", real.macros, real.sanctioned)
    assert geo.is_open_to(["North Korea"], "North Korea", real.macros, real.sanctioned)


def test_published_lists_are_sorted_and_cover_the_macros(real):
    out = compute_geo([], [], members=real)
    assert out["macros"] == sorted(real.macros)
    assert set(out["memberships"]) == set(real.macros)
    for members in out["memberships"].values():
        assert members == sorted(members)


# ------------------------------------------------------------------- memberships (validation)


def write_yaml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "regions.yaml"
    path.write_text(body, encoding="utf-8")
    return path


GOOD = """
memberships:
  countries: [Estonia, Germany, Norway, "Côte d'Ivoire", Türkiye]
  macros:
    EU: [Estonia, Germany]
    EEA: [EU, Norway]
"""


def test_small_valid_block_expands_nested_macros(tmp_path):
    loaded = load_memberships(write_yaml(tmp_path, GOOD))
    assert loaded.macros["EEA"] == frozenset({"Estonia", "Germany", "Norway"})
    assert loaded.as_lists()["EEA"] == ["Estonia", "Germany", "Norway"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("regions: {}", "no memberships"),
        ("memberships:\n  countries: []\n  macros: {EU: [Estonia]}", "countries is empty"),
        ("memberships:\n  countries: [Estonia]\n  macros: {}", "macros is empty"),
        # unknown country: a typo in a macro list
        (
            "memberships:\n  countries: [Estonia, Germany]\n  macros: {EU: [Estonia, Germnay]}",
            "neither a known country nor a macro",
        ),
        # canonical spelling only: Turkey is Türkiye, Czech Republic is Czechia
        (
            "memberships:\n  countries: [Turkey]\n  macros: {EU: [Turkey]}",
            "not a canonical region name",
        ),
        (
            "memberships:\n  countries: [Estonia, Estonia]\n  macros: {EU: [Estonia]}",
            "listed twice",
        ),
        (
            "memberships:\n  countries: [Estonia]\n  macros: {EU: [Estonia, Estonia]}",
            "duplicate members",
        ),
        (
            "memberships:\n  countries: [Estonia]\n  macros: {Estonia: [Estonia]}",
            "also a country",
        ),
        ("memberships:\n  countries: [Estonia]\n  macros: {EU: []}", "non-empty list"),
        (
            "memberships:\n  countries: [Estonia]\n  sanctioned: [Cuba]\n  macros: {EU: [Estonia]}",
            "not known countries",
        ),
        (
            "memberships:\n  countries: [Estonia]\n  sanctioned: [Estonia, Estonia]\n"
            "  macros: {EU: [Estonia]}",
            "duplicate entries",
        ),
        (
            "memberships:\n  countries: [Estonia]\n  macros: {EU: [EEA], EEA: [EU, Estonia]}",
            "cycle",
        ),
        ("memberships:\n  countries: [Estonia]\n  macros: {EU: [EU]}", "cycle"),
        (
            "memberships:\n  countries: [worldwide]\n  macros: {EU: [worldwide]}",
            "(not a canonical|cannot be)",
        ),
    ],
)
def test_invalid_blocks_are_rejected(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        load_memberships(write_yaml(tmp_path, body))


# --------------------------------------------------------------------------- the rule

SYN = {
    "EU": frozenset({"Estonia", "Germany", "France"}),
    "EEA": frozenset({"Estonia", "Germany", "France", "Norway"}),
    "Europe": frozenset({"Estonia", "Germany", "France", "Norway", "United Kingdom", "Ukraine"}),
    "EMEA": frozenset(
        {"Estonia", "Germany", "France", "Norway", "United Kingdom", "Ukraine", "Kenya", "Egypt"}
    ),
    "North America": frozenset({"United States", "Canada"}),
    "Americas": frozenset({"United States", "Canada", "Brazil", "Cuba"}),
}
SYN_SANCTIONED = frozenset({"Cuba", "Iran"})


@pytest.mark.parametrize(
    ("regs", "location", "expected"),
    [
        # empty / unknown postings are never open, not even to a macro
        ([], "Estonia", None),
        ([], "Europe", None),
        (None, "Estonia", None),
        # worldwide is open to every country and every macro, whatever else is listed
        (["worldwide"], "Estonia", "worldwide"),
        (["worldwide"], "Japan", "worldwide"),
        (["worldwide"], "EMEA", "worldwide"),
        (["Worldwide"], "Estonia", "worldwide"),
        (["United States", "worldwide"], "Estonia", "worldwide"),
        # a country posting is open to that country only
        (["Estonia"], "Estonia", "explicit"),
        (["Estonia"], "Germany", None),
        (["United States"], "Estonia", None),
        (["United States"], "United States", "explicit"),
        # a macro posting is open to its member countries
        (["EU"], "Estonia", "explicit"),
        (["EU"], "Norway", None),
        (["EEA"], "Norway", "explicit"),
        (["Europe"], "Ukraine", "explicit"),
        (["EMEA"], "Kenya", "explicit"),
        (["EMEA"], "United States", None),
        (["North America"], "Canada", "explicit"),
        (["North America"], "Brazil", None),
        (["Americas"], "Brazil", "explicit"),
        # no hierarchy in the other direction: a country posting is not open to its macro
        (["Germany"], "EU", None),
        (["Germany", "France"], "Europe", None),
        # mixed lists: any element that matches is enough
        (["United States", "Estonia"], "Estonia", "explicit"),
        (["United States", "EU"], "Estonia", "explicit"),
        (["United States", "Canada"], "Brazil", None),
        (["Europe", "United States"], "Canada", None),
        # a macro location needs a posting that covers all of it
        (["Europe"], "Europe", "explicit"),
        (["EMEA"], "Europe", "explicit"),
        (["EU"], "Europe", None),
        (["EEA"], "EU", "explicit"),
        (["Europe"], "EU", "explicit"),
        (["EU"], "EEA", None),
        (["Americas"], "North America", "explicit"),
        (["North America"], "Americas", None),
        # a value that is neither a country nor a macro opens nothing
        (["TMEA"], "Estonia", None),
        (["Atlantis"], "Atlantis", "explicit"),  # equal to the location, whatever it is
        # worldwide does not open a posting to a sanctioned place; naming it still does
        (["worldwide"], "Cuba", None),
        (["worldwide", "United States"], "Iran", None),
        (["Cuba"], "Cuba", "explicit"),
        (["worldwide", "Iran"], "Iran", "explicit"),
        (["Americas"], "Cuba", "explicit"),
        (["worldwide"], "Americas", "worldwide"),  # a macro location is not sanctioned
    ],
)
def test_open_via_edge_cases(regs, location, expected):
    assert open_via(regs, location, SYN, SYN_SANCTIONED) == expected
    assert is_open_to(regs, location, SYN, SYN_SANCTIONED) is (expected is not None)


# --------------------------------------------------------------------------- counts


def synthetic_members() -> Memberships:
    return Memberships(
        countries=frozenset(
            {"Estonia", "Germany", "France", "Norway", "United States", "Japan", "Cuba", "Canada"}
        ),
        macros={
            "EU": SYN["EU"],
            "Europe": SYN["Europe"],
            "North America": SYN["North America"],
            "Asia-Pacific": frozenset({"Japan"}),
        },
        sanctioned=frozenset({"Cuba"}),
    )


def test_counts_on_a_small_population():
    listed = [
        rec(1, ["worldwide"], skills=("sql", "python")),
        rec(2, ["Estonia"], skills=("sql",)),
        rec(3, ["EU"], skills=("sql", "dbt")),
        rec(4, ["United States"], skills=("sql",)),
        rec(5, ["Europe"], role="sales", skills=("crm",)),
        rec(6, []),
        rec(7, ["TMEA"]),
        rec(8, ["Germany", "France"]),
    ]
    out = compute_geo(
        listed, listed, names={"sql": "SQL", "python": "Python"}, members=synthetic_members()
    )
    rows = {r["location"]: r for r in out["by_location"]}

    estonia = rows["Estonia"]
    assert estonia["kind"] == "country"
    assert estonia["open_jobs"] == 4  # worldwide, Estonia, EU, Europe
    assert estonia["open_share"] == 0.5
    assert estonia["data_jobs"] == 3  # the Europe posting is sales
    assert estonia["worldwide_jobs"] == 1
    assert estonia["explicit_jobs"] == 3
    assert estonia["by_role"] == {"data": 3, "sales": 1}
    assert estonia["salary_n"] == 0 and estonia["median_salary_usd"] is None
    assert estonia["top_skills"] == [{"slug": "sql", "name": "SQL", "share": 1.0}]

    germany = rows["Germany"]
    assert germany["open_jobs"] == 4  # worldwide, EU, Europe, and the Germany+France posting
    assert "Japan" not in rows  # no posting names it and it is not European: no row
    assert rows["Asia-Pacific"]["kind"] == "macro"
    assert rows["France"]["worldwide_jobs"] == 1 and rows["France"]["explicit_jobs"] == 3
    assert rows["United States"]["open_jobs"] == 2  # worldwide, United States
    assert rows["Norway"]["open_jobs"] == 2  # worldwide, Europe

    europe = rows["Europe"]
    assert europe["kind"] == "macro"
    assert europe["open_jobs"] == 2  # worldwide and Europe; the EU posting does not cover Europe
    assert rows["EU"]["open_jobs"] == 3  # worldwide, EU, Europe

    assert out["unknown_jobs"] == 1
    assert out["unmapped"] == [{"region": "TMEA", "n": 1}]
    summary = out["summary"]
    assert summary["listed_jobs"] == 8
    assert summary["worldwide_jobs"] == 1
    assert summary["us_only_jobs"] == 1 and summary["us_only_data_jobs"] == 1
    assert summary["unknown_jobs"] == 1
    assert summary["data_jobs"] == 7


def test_rows_are_macros_named_countries_and_european_countries():
    members = synthetic_members()
    listed = [
        rec(1, ["Japan"]),
        rec(2, ["Atlantis"]),
        rec(3, ["worldwide"]),
        rec(4, ["Cuba", "Asia-Pacific"]),
    ]
    out = compute_geo(listed, listed, members=members)
    locations = {r["location"]: r["kind"] for r in out["by_location"]}
    # macros, countries named by a posting, and all of Europe (Norway: named by no posting)
    assert locations["Japan"] == "country" and locations["Cuba"] == "country"
    assert locations["Norway"] == "country" and locations["Estonia"] == "country"
    assert locations["EU"] == "macro" and locations["Asia-Pacific"] == "macro"
    # Canada belongs to a macro list but nobody names it and it is not European
    assert "Canada" not in locations
    assert "Atlantis" not in locations and "worldwide" not in locations
    assert len(locations) == len(out["by_location"])  # one row each
    assert out["unmapped"] == [{"region": "Atlantis", "n": 1}]
    # the rule itself still works for a country without a row
    assert geo.is_open_to(["worldwide"], "Canada", members.macros, members.sanctioned)
    assert geo.is_open_to(["North America"], "Canada", members.macros, members.sanctioned)


def test_worldwide_postings_do_not_count_for_sanctioned_places():
    members = synthetic_members()
    listed = [rec(1, ["worldwide"]), rec(2, ["worldwide"]), rec(3, ["Cuba"]), rec(4, ["Estonia"])]
    out = compute_geo(listed, listed, members=members)
    rows = {r["location"]: r for r in out["by_location"]}
    assert rows["Cuba"]["open_jobs"] == 1  # only the posting that names it
    assert rows["Cuba"]["worldwide_jobs"] == 0 and rows["Cuba"]["explicit_jobs"] == 1
    assert rows["Estonia"]["open_jobs"] == 3  # worldwide x2 and Estonia
    assert out["sanctioned"] == ["Cuba"]


def test_median_pay_needs_five_salaried_open_postings():
    members = synthetic_members()
    four = [rec(i, ["worldwide"], salary=100_000 + 10_000 * i) for i in range(4)]
    out = compute_geo(four, four, members=members)
    row = next(r for r in out["by_location"] if r["location"] == "Estonia")
    assert row["salary_n"] == 4 and row["median_salary_usd"] is None

    five = [*four, rec(4, ["worldwide"], salary=140_000), rec(5, ["Japan"], salary=1_000_000)]
    out = compute_geo(five, five, members=members)
    estonia = next(r for r in out["by_location"] if r["location"] == "Estonia")
    assert estonia["salary_n"] == 5  # Japan-only posting is not open to Estonia
    assert estonia["median_salary_usd"] == 120_000
    japan = next(r for r in out["by_location"] if r["location"] == "Japan")
    assert japan["salary_n"] == 6


def test_skills_need_three_open_data_jobs_and_are_ranked_by_count():
    members = synthetic_members()
    listed = [
        rec(1, ["worldwide"], skills=("sql", "python")),
        rec(2, ["worldwide"], skills=("sql", "python")),
        rec(3, ["worldwide"], skills=("sql", "dbt")),
        rec(4, ["worldwide"], role="sales", skills=("crm",)),
    ]
    out = compute_geo(listed, listed, members=members)
    row = next(r for r in out["by_location"] if r["location"] == "Estonia")
    assert [(s["slug"], s["share"]) for s in row["top_skills"]] == [("sql", 1.0)]  # python: 2 < 3
    assert row["data_jobs"] == 3


def test_region_mix_uses_the_window_population_and_region_groups():
    population = [
        rec(1, ["United States"], salary=100_000),
        rec(2, ["United States"], salary=110_000),
        rec(3, ["United States"], salary=120_000),
        rec(4, ["United States"], salary=130_000),
        rec(5, ["Canada"], salary=140_000),
        rec(6, ["Germany"]),
        rec(7, ["worldwide"]),
        rec(8, []),
    ]
    listed = population[:2]
    out = compute_geo(population, listed, members=synthetic_members())
    mix = {r["group"]: r for r in out["region_mix"]}
    assert mix["us_canada"]["n"] == 5 and mix["us_canada"]["share"] == 0.625
    assert mix["us_canada"]["median_salary_usd"] == 120_000
    assert mix["europe"]["n"] == 1 and mix["europe"]["median_salary_usd"] is None
    assert mix["worldwide"]["n"] == 1 and mix["unknown"]["n"] == 1
    assert sum(r["n"] for r in out["region_mix"]) == len(population)
    assert out["region_mix"][0]["group"] == "us_canada"  # largest first
    assert out["unknown_jobs"] == 0  # unknown is counted over the listed postings


def test_empty_inputs_still_produce_a_valid_document():
    out = compute_geo([], [], members=synthetic_members())
    assert out["version"] == 1
    assert out["unknown_jobs"] == 0 and out["region_mix"] == []
    assert all(r["open_jobs"] == 0 and r["open_share"] == 0.0 for r in out["by_location"])


def test_real_memberships_on_a_tiny_population():
    listed = [rec(1, ["EU"]), rec(2, ["worldwide"]), rec(3, ["United States"])]
    out = compute_geo(listed, listed)
    estonia = next(r for r in out["by_location"] if r["location"] == "Estonia")
    assert estonia["open_jobs"] == 2
    rows = {r["location"]: r for r in out["by_location"]}
    # picker rows: named countries plus all of Europe; not Nauru or North Korea
    assert {"United States", "Estonia", "Norway", "Ukraine", "Switzerland"} <= set(rows)
    assert not {"Nauru", "North Korea", "American Samoa", "Cuba"} & set(rows)
    assert set(out["macros"]) <= set(rows)
    assert set(out["memberships"]["Europe"]) <= set(rows)
    assert out["sanctioned"] == sorted(load_memberships().sanctioned)
    assert next(r for r in out["by_location"] if r["location"] == "Europe")["open_jobs"] == 1


# --------------------------------------------------------------------------- web parity

PARITY_REGIONS = [
    [],
    ["worldwide"],
    ["United States"],
    ["Estonia"],
    ["EU"],
    ["EEA"],
    ["Europe"],
    ["EMEA"],
    ["North America"],
    ["Americas"],
    ["Germany", "France"],
    ["United States", "Canada"],
    ["United States", "EU"],
    ["worldwide", "United States"],
    ["Norway"],
    ["TMEA"],
    ["Europe", "United States"],
    ["Cuba"],
    ["Iran", "worldwide"],
]
PARITY_LOCATIONS = [
    "Estonia", "Germany", "Norway", "United Kingdom", "United States", "Canada", "Brazil",
    "Kenya", "Japan", "EU", "EEA", "Europe", "EMEA", "North America", "Americas", "Nowhere",
    "Cuba", "Iran",
]  # fmt: skip


def build_parity_fixture() -> dict:
    return {
        "note": "Computed by radar.geo.open_via. Regenerate: RADAR_WRITE_FIXTURES=1 pytest",
        "memberships": {k: sorted(v) for k, v in sorted(SYN.items())},
        "sanctioned": sorted(SYN_SANCTIONED),
        "cases": [
            {"regions": regs, "location": loc, "via": open_via(regs, loc, SYN, SYN_SANCTIONED)}
            for regs in PARITY_REGIONS
            for loc in PARITY_LOCATIONS
        ],
    }


def render_fixture(doc: dict) -> str:
    """One line per case keeps the file small and its diffs readable."""

    def dump(value) -> str:
        return json.dumps(value, ensure_ascii=False)

    cases = ",\n".join("  " + dump(case) for case in doc["cases"])
    return (
        "{\n"
        f' "note": {dump(doc["note"])},\n'
        f' "memberships": {dump(doc["memberships"])},\n'
        f' "sanctioned": {dump(doc["sanctioned"])},\n'
        f' "cases": [\n{cases}\n ]\n'
        "}\n"
    )


def test_web_parity_fixture_matches_python():
    expected = build_parity_fixture()
    if os.environ.get("RADAR_WRITE_FIXTURES"):
        FIXTURE.write_text(render_fixture(expected), encoding="utf-8")
    assert FIXTURE.exists(), (
        "run with RADAR_WRITE_FIXTURES=1 to create web/src/lib/geo.fixtures.json"
    )
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == expected, (
        "geo.fixtures.json is stale: regenerate with "
        "RADAR_WRITE_FIXTURES=1 pytest tests/test_geo.py and check the web tests still pass"
    )


def test_module_exports_the_public_api():
    assert {"compute_geo", "is_open_to", "load_memberships", "open_via"} <= set(geo.__all__)
