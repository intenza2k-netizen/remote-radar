"""Toy-data tests for the pure scoring functions (no models, no database)."""

from __future__ import annotations

import pytest
import scoring


def gold(**over):
    base = {
        "role_category": "data",
        "seniority": "senior",
        "skills": ["python", "sql"],
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "employment_type": "full_time",
        "remote_regions": ["worldwide"],
    }
    return {**base, **over}


def record(**over):
    data = {
        "role_category": "data",
        "seniority": "senior",
        "skills": ["python", "sql"],
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "employment_type": "full_time",
        "remote_regions": ["worldwide"],
    }
    data.update(over)
    return {"ok": True, "data": data, "latency_ms": 100, "cost_usd": 0.01}


def test_prf_basic_and_zero_denominators():
    assert scoring.prf(2, 4, 2) == (0.5, 1.0, pytest.approx(2 / 3))
    assert scoring.prf(0, 0, 3) == (0.0, 0.0, 0.0)
    assert scoring.prf(0, 3, 0) == (0.0, 0.0, 0.0)


def test_skills_use_canonical_slugs_so_aliases_match():
    s = scoring.score_job(
        1, gold(skills=["python", "react"]), record(skills=["Python3", "React.js"])
    )
    assert (s.tp, s.n_pred, s.n_gold, s.f1) == (2, 2, 2, 1.0)


def test_micro_vs_macro_f1():
    # job A: gold {python, sql}, pred {python}      -> tp1 pred1 gold2, F1 2/3
    # job B: gold {react},        pred {react, vue} -> tp1 pred2 gold1, F1 2/3
    a = scoring.score_job(1, gold(skills=["python", "sql"]), record(skills=["python"]))
    b = scoring.score_job(2, gold(skills=["react"]), record(skills=["react", "vue"]))
    p, r, f = scoring.micro_prf([a, b])
    assert (p, r) == (pytest.approx(2 / 3), pytest.approx(2 / 3))
    assert f == pytest.approx(2 / 3)
    assert scoring.macro_f1([a, b]) == pytest.approx(2 / 3)


def test_macro_f1_empty_vs_empty_is_perfect():
    s = scoring.score_job(1, gold(skills=[]), record(skills=[]))
    assert s.f1 == 1.0
    s2 = scoring.score_job(2, gold(skills=[]), record(skills=["python"]))
    assert s2.f1 == 0.0


def test_failed_job_is_scored_as_wrong_not_dropped():
    s = scoring.score_job(1, gold(), {"ok": False, "data": None, "error": "bad json"})
    assert not s.ok and s.tp == 0 and s.n_gold == 2 and s.n_pred == 0
    assert not (s.role_ok or s.seniority_ok or s.employment_ok or s.salary_ok)
    assert scoring.summarize([s])["failures"] == 1
    # never run at all behaves the same
    assert not scoring.score_job(2, gold(), None).ok


def test_salary_match_rules():
    g = gold(salary_min=100000, salary_max=120000, salary_currency="USD", salary_period="year")
    ok = scoring.salary_match
    assert ok(g, {**g, "salary_min": 101500, "salary_max": 118000})  # within 2%
    assert not ok(g, {**g, "salary_min": 95000})  # 5% off
    assert not ok(g, {**g, "salary_currency": "EUR"})
    assert not ok(g, {**g, "salary_period": "month"})
    assert ok(g, {**g, "salary_currency": "usd"})  # case-insensitive
    assert not ok(g, gold())  # gold has a salary, prediction none
    assert not ok(gold(), g)  # hallucinated salary
    assert ok(gold(), gold())  # both null counts as a match


def test_numbers_match_edges():
    assert scoring.numbers_match(None, None)
    assert not scoring.numbers_match(None, 1)
    assert scoring.numbers_match(0, 0)
    assert scoring.numbers_match(50, 50.9)  # 1.8% of 50.9


def test_region_normalisation_and_jaccard():
    assert scoring.norm_regions(["USA", "Europe", "latin america", "Germany"]) == {
        "US",
        "EU",
        "LATAM",
        "Germany",
    }
    assert scoring.jaccard({"US", "EU"}, {"US"}) == 0.5
    assert scoring.jaccard(set(), set()) == 1.0
    assert scoring.jaccard(set(), {"US"}) == 0.0
    s = scoring.score_job(
        1, gold(remote_regions=["US", "Canada"]), record(remote_regions=["united states"])
    )
    assert s.regions_jaccard == 0.5


def test_field_accuracies():
    s = scoring.score_job(1, gold(), record(seniority="mid", employment_type="unspecified"))
    assert s.role_ok and not s.seniority_ok and not s.employment_ok and s.salary_ok
    assert scoring.accuracy([True, False, True, True]) == 0.75
    assert scoring.accuracy([]) == 0.0


def test_percentile_and_cost():
    assert scoring.percentile([1, 2, 3, 4, 5], 50) == 3
    assert scoring.percentile([10, 20], 90) == pytest.approx(19)
    assert scoring.percentile([], 50) is None
    a = scoring.score_job(1, gold(), {**record(), "cost_usd": 0.01})
    b = scoring.score_job(2, gold(), {**record(), "cost_usd": 0.03})
    assert scoring.cost_per_1k([a, b]) == pytest.approx(20.0)
    free = scoring.score_job(3, gold(), {**record(), "cost_usd": 0.0})
    assert scoring.cost_per_1k([free]) == 0.0


def test_bootstrap_is_seeded_and_paired():
    assert scoring.bootstrap_indices(10, 5, seed=7) == scoring.bootstrap_indices(10, 5, seed=7)
    assert scoring.bootstrap_indices(10, 5, seed=7) != scoring.bootstrap_indices(10, 5, seed=8)
    good = [scoring.score_job(i, gold(), record()) for i in range(20)]
    bad = [scoring.score_job(i, gold(), record(skills=["java"])) for i in range(20)]
    draws = scoring.bootstrap_indices(20, 200, seed=1)
    diff, (lo, hi) = scoring.paired_difference(good, bad, draws, scoring.skills_f1_metric)
    assert diff == 1.0 and lo > 0.9 and hi == 1.0
    diff0, (lo0, hi0) = scoring.paired_difference(good, good, draws, scoring.skills_f1_metric)
    assert (diff0, lo0, hi0) == (0.0, 0.0, 0.0)  # identical models are never distinguishable


def test_confusion_and_top_skill_errors():
    scores = [
        scoring.score_job(
            1,
            gold(seniority="senior", skills=["python", "sql"]),
            record(seniority="mid", skills=["python", "java"]),
        ),
        scoring.score_job(
            2, gold(seniority="senior", skills=["sql"]), record(seniority="mid", skills=["java"])
        ),
        scoring.score_job(3, gold(seniority="mid"), {"ok": False, "data": None}),
    ]
    table = scoring.confusion(scores)
    assert table["senior"]["mid"] == 2
    assert table["mid"]["FAILED"] == 1
    missed, extra = scoring.top_skill_errors(scores, k=2)
    assert missed == [("sql", 3), ("python", 1)]  # the failed job misses all its gold skills
    assert extra == [("java", 2)]


def test_field_acc_metric_matches_accuracy():
    scores = [
        scoring.score_job(1, gold(), record()),
        scoring.score_job(2, gold(), record(role_category="sales")),
    ]
    assert scoring.field_acc_metric("role_ok")(scores) == 0.5
    assert scoring.field_acc_metric("employment_ok")(scores) == 1.0
