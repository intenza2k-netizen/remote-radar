"""Tests for radar.regions: canonical remote-region names."""

from __future__ import annotations

import pytest
import yaml

from radar import regions
from radar.regions import normalize_region, normalize_regions


def test_registry_loads_and_has_no_conflicting_aliases():
    reg = regions._registry()
    assert reg.by_key["usa"] == "United States"
    assert len(reg.state_codes) == 51  # 50 states + DC


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("US", "United States"),
        ("USA", "United States"),
        ("U.S.", "United States"),
        ("united states", "United States"),
        ("UK", "United Kingdom"),
        ("Czech Republic", "Czechia"),
        ("Czechia", "Czechia"),
        ("The Netherlands", "Netherlands"),
        ("Turkey", "Türkiye"),
        ("Turkiye", "Türkiye"),
        ("Bosnia & Herzegovina", "Bosnia and Herzegovina"),
        ("AMER", "Americas"),
        ("AMERICAS", "Americas"),
        ("Americas", "Americas"),
        ("NAMER", "North America"),
        ("North America", "North America"),
        ("LATAM", "Latin America"),
        ("APAC", "Asia-Pacific"),
        ("Asia Pacific", "Asia-Pacific"),
        ("EMEA", "EMEA"),
        ("EU", "EU"),
        ("W Asia", "Western Asia"),
        ("UAE", "United Arab Emirates"),
        ("DRC", "Democratic Republic of the Congo"),
        ("Worldwide", "worldwide"),
        ("anywhere", "worldwide"),
        ("Ohio", "United States"),  # a full state name always means the state
        ("germany", "Germany"),  # unknown all-lower-case values are title-cased
        ("new zealand", "New Zealand"),
        ("Germany", "Germany"),
        ("TMEA", "TMEA"),  # unknown codes are kept as written
        ("  Poland ", "Poland"),
    ],
)
def test_single_values(raw, expected):
    assert normalize_region(raw) == expected


def test_empty_and_non_string_values_are_dropped():
    assert normalize_region("  ") is None
    assert normalize_region(None) is None  # type: ignore[arg-type]
    assert normalize_regions(None) == []
    assert normalize_regions(["", "  ", None, "US"]) == ["United States"]  # type: ignore[list-item]


def test_a_list_of_state_codes_collapses_into_one_united_states():
    codes = ["AL", "AR", "AZ", "FL", "GA", "IL", "IN", "KS", "KY", "LA", "MI", "NC", "SC", "TX"]
    assert normalize_regions(codes) == ["United States"]
    assert normalize_regions(["US", *codes]) == ["United States"]
    assert normalize_regions(["Canada", *codes, "Ohio"]) == ["Canada", "United States"]


def test_lone_state_codes_are_read_as_countries_not_states():
    # "IL" and "IN" are Illinois and Indiana only inside a list of states
    assert normalize_regions(["IN"]) == ["India"]
    assert normalize_regions(["IL"]) == ["Israel"]
    assert normalize_regions(["US", "CA"]) == ["United States", "Canada"]
    assert normalize_regions(["US", "TX"]) == ["United States", "TX"]  # one code: not a state list
    assert normalize_regions(["DE", "FR"]) == ["Germany", "FR"]


def test_georgia_is_the_country_unless_listed_with_other_states():
    assert normalize_regions(["Georgia"]) == ["Georgia"]
    assert normalize_regions(["Georgia", "Armenia"]) == ["Georgia", "Armenia"]
    assert normalize_regions(["Georgia", "Ohio", "Texas"]) == ["United States"]


def test_duplicates_collapse_and_order_is_preserved():
    assert normalize_regions(["USA", "Canada", "US", "United States", "canada"]) == [
        "United States",
        "Canada",
    ]
    assert normalize_regions(["LATAM", "worldwide", "Czech Republic", "Czechia"]) == [
        "Latin America",
        "worldwide",
        "Czechia",
    ]


def test_there_is_no_hierarchy_between_regions():
    assert normalize_regions(["US"]) == ["United States"]  # not also "Americas"
    assert normalize_regions(["Germany"]) == ["Germany"]  # not also "EU"


def test_bad_yaml_is_rejected(tmp_path):
    bad = tmp_path / "regions.yaml"
    bad.write_text(yaml.safe_dump({"regions": {"A": ["x"], "B": ["X"]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="maps to"):
        regions._load(bad)
    bad.write_text(
        yaml.safe_dump({"regions": {"A": []}, "us_states": {"codes": ["Texas"]}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="two upper-case"):
        regions._load(bad)
