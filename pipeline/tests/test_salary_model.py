"""Tests for radar.salary_model: ridge maths, grouped CV, evaluation, document and prediction."""

from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from radar import salary_model as sm
from radar.aggregate import JobRecord, RawSalary, compute_snapshot
from radar.regions import region_group

NOW = datetime(2026, 11, 7, 12, 0)

ROLE_EFFECT = {"data": 0.0, "software_engineering": 0.10, "sales": -0.20}
SENIORITY_EFFECT = {"senior": 0.0, "mid": -0.25, "lead": 0.15}
REGION_EFFECT = {"us_canada": 0.0, "europe": -0.35}
REGION_OF = {"us_canada": ["United States"], "europe": ["Germany"]}
SKILL_EFFECT = {"dbt": 0.30, "excel": -0.20, "git": 0.0, "rare": 0.5}


def rec(
    i: int,
    *,
    salary: float | None,
    role: str = "data",
    seniority: str = "senior",
    company: str | None = None,
    regions: list[str] | None = None,
    skills=("git",),
) -> JobRecord:
    return JobRecord(
        id=f"remotive-{i}",
        source="remotive",
        title=f"Job {i}",
        company=company or f"Company {i}",
        url=f"https://example.com/{i}",
        location=None,
        posted_at=NOW - timedelta(days=3),
        role=role,
        seniority=seniority,
        employment_type="full_time",
        remote_regions=list(regions or []),
        skills=list(skills),
        salaries=[RawSalary(salary, salary, "USD", "year")] if salary else [],
    )


def synthetic(n: int = 600, noise: float = 0.05, seed: int = 7, companies: int = 150):
    """Pay follows the effect tables above exactly, plus gaussian noise on the log scale.
    Each company posts several jobs, but its jobs are otherwise independent draws."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        role = rnd.choices(list(ROLE_EFFECT), weights=[5, 3, 2])[0]
        seniority = rnd.choices(list(SENIORITY_EFFECT), weights=[4, 2, 1])[0]
        region = rnd.choices(list(REGION_EFFECT), weights=[3, 1])[0]
        skills = ["git"]
        for slug, p in (("dbt", 0.4), ("excel", 0.4), ("rare", 0.008)):
            if rnd.random() < p:
                skills.append(slug)
        log_pay = (
            math.log(100_000)
            + ROLE_EFFECT[role]
            + SENIORITY_EFFECT[seniority]
            + REGION_EFFECT[region]
            + sum(SKILL_EFFECT[s] for s in skills)
            + rnd.gauss(0, noise)
        )
        out.append(
            rec(
                i,
                salary=round(math.exp(log_pay)),
                role=role,
                seniority=seniority,
                company=f"Company {rnd.randrange(companies)}",
                regions=REGION_OF[region],
                skills=skills,
            )
        )
    return out


# --------------------------------------------------------------------------- ridge maths


def test_ridge_recovers_known_coefficients_without_noise():
    rng = np.random.default_rng(1)
    x = (rng.random((300, 4)) < 0.4).astype(float)
    true = np.array([0.5, -0.3, 0.0, 0.8])
    y = 11.0 + x @ true
    b0, beta = sm.fit_ridge(x, y, 1e-9)
    assert b0 == pytest.approx(11.0, abs=1e-6)
    assert beta == pytest.approx(true, abs=1e-6)


def test_ridge_shrinks_coefficients_but_never_the_intercept():
    rng = np.random.default_rng(2)
    x = (rng.random((200, 3)) < 0.5).astype(float)
    y = 1000.0 + x @ np.array([1.0, -2.0, 0.5]) + rng.normal(0, 0.1, 200)
    _, light = sm.fit_ridge(x, y, 0.1)
    b0, heavy = sm.fit_ridge(x, y, 1e7)
    assert np.all(np.abs(heavy) < np.abs(light))
    assert np.abs(heavy).max() < 1e-3
    assert b0 == pytest.approx(y.mean(), rel=1e-6)  # all pay is explained by the intercept
    # Shifting y moves only the intercept: it is not penalised.
    b0_shift, shifted = sm.fit_ridge(x, y + 5000.0, 3.0)
    b0_plain, plain = sm.fit_ridge(x, y, 3.0)
    assert shifted == pytest.approx(plain)
    assert b0_shift == pytest.approx(b0_plain + 5000.0)


def test_weighted_ridge_equals_repeated_rows():
    rng = np.random.default_rng(3)
    x = (rng.random((40, 3)) < 0.5).astype(float)
    y = rng.normal(0, 1, 40)
    w = rng.integers(0, 4, 40).astype(float)
    b0, beta = sm.fit_ridge(x, y, 2.0, weights=w)
    idx = np.repeat(np.arange(40), w.astype(int))
    b0_rep, beta_rep = sm.fit_ridge(x[idx], y[idx], 2.0)
    assert b0 == pytest.approx(b0_rep)
    assert beta == pytest.approx(beta_rep)


# --------------------------------------------------------------------------- grouped CV


def test_grouped_folds_keep_every_company_in_one_fold_and_balance_the_load():
    rng = np.random.default_rng(4)
    sizes = [130, 90, 70] + [int(s) for s in rng.integers(1, 6, 200)]
    groups = np.repeat(np.arange(len(sizes)), sizes)
    folds = sm.grouped_folds(groups, 5, seed=11)
    for g in range(len(sizes)):
        assert len(set(folds[groups == g])) == 1
    loads = np.bincount(folds)
    assert len(loads) == 5
    assert loads.max() - loads.min() <= 130  # never worse than the biggest single company
    assert loads.max() - loads.min() <= 5  # in practice the greedy placement is far tighter


def test_grouped_folds_shrink_to_the_number_of_companies():
    folds = sm.grouped_folds(np.array([0, 0, 1, 2, 2]), 5, seed=1)
    assert sorted(set(folds)) == [0, 1, 2]


def test_grouped_cv_cannot_use_company_identity():
    """Company dummies explain pay perfectly *within* a company. Under company-grouped CV an
    unseen company's dummy is all zeros, so held-out predictions carry no signal; a leaky split
    (rows of one company on both sides) would score near-perfectly."""
    rng = np.random.default_rng(5)
    n_companies, per = 60, 5
    groups = np.repeat(np.arange(n_companies), per)
    offsets = rng.normal(0, 1, n_companies)
    y = offsets[groups] + rng.normal(0, 0.01, len(groups))
    x = np.eye(n_companies)[groups]
    pred, folds, _ = sm.nested_predictions(x, y, groups, alphas=(0.1, 1.0))
    in_sample = sm.fit_ridge(x, y, 0.1)
    fitted = in_sample[0] + x @ in_sample[1]
    assert np.corrcoef(fitted, y)[0, 1] > 0.99  # the model can memorise companies ...
    r2 = 1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
    assert r2 < 0.05  # ... but cannot use that on a held-out company
    for g in range(n_companies):
        assert len(set(folds[groups == g])) == 1


def test_select_alpha_prefers_strong_shrinkage_on_pure_noise():
    rng = np.random.default_rng(6)
    x = (rng.random((400, 30)) < 0.3).astype(float)
    y = rng.normal(0, 1, 400)
    groups = np.arange(400)
    alpha, curve = sm.select_alpha(x, y, groups, alphas=(0.01, 1.0, 100.0, 10_000.0))
    assert alpha >= 100.0
    assert len(curve) == 4


# --------------------------------------------------------------------------- the document


def test_recovers_known_effects_on_synthetic_data():
    doc = sm.compute_salary_model(synthetic())
    assert doc["version"] == 1
    assert doc["reference"] == {"role": "data", "seniority": "senior", "region_group": "us_canada"}
    coef = doc["coef"]
    assert "data" not in coef["role"] and "senior" not in coef["seniority"]
    assert coef["role"]["software_engineering"] == pytest.approx(0.10, abs=0.03)
    assert coef["role"]["sales"] == pytest.approx(-0.20, abs=0.03)
    assert coef["seniority"]["mid"] == pytest.approx(-0.25, abs=0.04)
    assert coef["seniority"]["lead"] == pytest.approx(0.15, abs=0.04)
    assert coef["region_group"]["europe"] == pytest.approx(-0.35, abs=0.04)
    assert coef["skill"]["dbt"] == pytest.approx(0.30, abs=0.03)
    assert coef["skill"]["excel"] == pytest.approx(-0.20, abs=0.03)
    assert abs(coef["skill"]["git"]) < 0.03  # in every posting, so it is part of the intercept
    assert "rare" not in coef["skill"]  # fewer than MIN_SKILL_POSTINGS salaried postings


def test_document_is_json_and_internally_consistent():
    doc = sm.compute_salary_model(synthetic(), names={"dbt": "dbt"})
    json.dumps(doc)  # plain python types only
    assert doc["n_train"] == 600
    assert doc["target"] == "log(annual_usd_mid)"
    assert doc["alpha"] in sm.ALPHAS
    assert [c["alpha"] for c in doc["alpha_curve"]] == list(sm.ALPHAS)
    skills = {s["slug"]: s for s in doc["skills"]}
    assert set(skills) == set(doc["coef"]["skill"])
    assert [s["n"] for s in doc["skills"]] == sorted((s["n"] for s in doc["skills"]), reverse=True)
    assert skills["dbt"]["name"] == "dbt"
    assert skills["dbt"]["pct"] == pytest.approx(
        100 * math.expm1(doc["coef"]["skill"]["dbt"]), abs=0.2
    )
    assert skills["dbt"]["ci_low_pct"] < skills["dbt"]["pct"] < skills["dbt"]["ci_high_pct"]
    assert (
        doc["levels"]["role"]["data"]
        + doc["levels"]["role"]["sales"]
        + doc["levels"]["role"]["software_engineering"]
        == 600
    )
    # median modelled skills per salaried posting, rounded half up
    counts = sorted(len(set(r.skills) & set(doc["coef"]["skill"])) for r in synthetic())
    assert doc["profile_max_skills"] == max(1, int(np.median(counts) + 0.5))
    interval = doc["interval"]
    assert interval["level"] == 0.8 and interval["low_log"] < 0 < interval["high_log"]
    drivers = doc["drivers"]
    assert [d["pct"] for d in drivers] == sorted((d["pct"] for d in drivers), reverse=True)
    assert drivers[0]["slug"] == "dbt" and drivers[-1]["slug"] == "excel"


def test_published_accuracy_is_held_out_and_reasonable():
    doc = sm.compute_salary_model(synthetic(noise=0.15))
    ev = doc["eval"]
    assert ev["folds"] == 5 and "grouped by company" in ev["method"]
    assert ev["r2_log"] > 0.7  # most of the variance is explained by the known effects
    assert 0.05 < ev["median_ape"] < 0.20  # noise sd 0.15 -> median |error| near 10%
    assert 0.74 <= ev["coverage"] <= 0.86  # an 80% range covers roughly 80% held-out
    assert ev["baseline"]["name"]
    assert ev["mae_usd"] < ev["baseline"]["mae_usd"]
    assert ev["verdict"] == "better" and ev["mae_gain_ci_pct"][0] > 0
    assert "beats" in ev["note"]
    assert ev["mae_ci_usd"][0] < ev["mae_usd"] < ev["mae_ci_usd"][1]
    assert ev["capped"]["mae_usd"] >= ev["mae_usd"] * 0.9  # the cap is a small change


def test_says_so_when_the_model_does_not_beat_the_baseline():
    """Pay depends on role and seniority only; skills and region are noise. The extra columns
    cannot improve on the role x seniority median, and the document must not claim they do."""
    rnd = random.Random(21)
    out = []
    for i in range(500):
        role = rnd.choice(["data", "software_engineering", "sales"])
        seniority = rnd.choice(["senior", "mid", "lead"])
        log_pay = (
            math.log(100_000) + ROLE_EFFECT[role] + SENIORITY_EFFECT[seniority] + rnd.gauss(0, 0.3)
        )
        skills = [s for s in ("dbt", "excel", "git", "sql", "python") if rnd.random() < 0.4]
        out.append(
            rec(
                i,
                salary=round(math.exp(log_pay)),
                role=role,
                seniority=seniority,
                company=f"Company {i}",
                skills=skills,
            )
        )
    ev = sm.compute_salary_model(out)["eval"]
    assert ev["verdict"] != "better"
    assert "beat" in ev["note"] or "worse" in ev["note"]
    assert "does not clearly beat" in ev["note"] or "worse than" in ev["note"]


def test_baseline_falls_back_from_role_and_seniority_to_role_to_everything():
    train = [  # (role, seniority, pay, count)
        ("a", "x", 100.0, 3),  # cells with fewer than MIN_BASELINE_CELL postings ...
        ("a", "y", 400.0, 4),
        ("a", "z", 600.0, 3),  # ... so role a (10 postings) falls back to its own median, 400
        ("b", "x", 800.0, 5),  # a full cell
        ("c", "x", 1000.0, 2),  # role c is too small too: falls back to everything
    ]
    roles, sen, usd, folds = [], [], [], []
    for role, level, pay, count in train:
        roles += [role] * count
        sen += [level] * count
        usd += [pay] * count
        folds += [0] * count
    for role in ("a", "b", "c"):  # one held-out posting per role, all seniority x
        roles.append(role)
        sen.append("x")
        usd.append(1.0)
        folds.append(1)
    pred = sm.baseline_predictions(np.array(roles), np.array(sen), np.array(usd), np.array(folds))
    assert list(pred[-3:]) == [400.0, 800.0, 600.0]  # role a, cell b/x, overall median of 17


def test_coefficient_bootstrap_equals_refitting_on_resampled_companies():
    rng = np.random.default_rng(8)
    groups = np.repeat(np.arange(25), rng.integers(1, 6, 25))
    x = (rng.random((len(groups), 6)) < 0.4).astype(float)
    y = 11.0 + x @ rng.normal(0, 0.3, 6) + rng.normal(0, 0.2, len(groups))
    draws = rng.multinomial(25, np.full(25, 1 / 25), 7)
    fast = sm._coefficient_bootstrap(x, y, groups, 3.0, draws=draws)
    for b in range(7):
        _, slow = sm.fit_ridge(x, y, 3.0, weights=draws[b][groups].astype(float))
        assert fast[b] == pytest.approx(slow, abs=1e-6)


def test_deterministic_and_independent_of_input_order():
    population = synthetic(n=300)
    first = sm.compute_salary_model(population)
    again = sm.compute_salary_model(population)
    shuffled = list(population)
    random.Random(1).shuffle(shuffled)
    assert json.dumps(first) == json.dumps(again)
    assert json.dumps(first) == json.dumps(sm.compute_salary_model(shuffled))


def test_unsalaried_postings_are_ignored():
    population = synthetic(n=300)
    extra = [rec(10_000 + i, salary=None, skills=["dbt"]) for i in range(50)]
    assert json.dumps(sm.compute_salary_model(population)) == json.dumps(
        sm.compute_salary_model(population + extra)
    )


def test_small_data_guard():
    few = sm.compute_salary_model(synthetic(n=sm.MIN_SALARIED - 1))
    assert few["version"] == 1 and "coef" not in few
    assert f"only {sm.MIN_SALARIED - 1} postings" in few["reason"]
    assert set(few) == {"version", "reason"}
    assert sm.compute_salary_model([])["version"] == 1
    one_firm = [rec(i, salary=100_000 + i, company="Acme") for i in range(150)]
    reason = sm.compute_salary_model(one_firm)["reason"]
    assert "1 companies" in reason and "unseen companies" in reason


def test_snapshot_publishes_the_document():
    snapshot = compute_snapshot(synthetic(n=300), now=NOW)
    assert snapshot["salary_model"]["version"] == 1
    assert "coef" in snapshot["salary_model"]


# --------------------------------------------------------------------------- prediction


def _model():
    return sm.compute_salary_model(synthetic())


def test_predict_pay_applies_the_profile_rule():
    doc = _model()
    cap = doc["profile_max_skills"]
    assert cap >= 1
    base = dict(role="data", seniority="senior", region_group="us_canada")
    none = sm.predict_pay(doc, **base)
    assert none["used_skills"] == []
    assert none["low"] < none["median"] < none["high"]
    assert none["median"] == round(math.exp(doc["intercept"]))
    # Unknown skills are ignored; known ones are ordered by market frequency, not coefficient.
    frequency = [s["slug"] for s in doc["skills"]]
    asked = ["unknown-skill", *reversed(frequency)]
    used = sm.predict_pay(doc, **base, skills=asked)["used_skills"]
    assert used == frequency[:cap]
    # Skills beyond the cap do not change the number.
    more = sm.predict_pay(doc, **base, skills=frequency)
    assert more == sm.predict_pay(doc, **base, skills=frequency[:cap])


def test_predict_pay_matches_the_hand_computation():
    doc = _model()
    expected = (
        doc["intercept"]
        + doc["coef"]["role"]["sales"]
        + doc["coef"]["seniority"]["lead"]
        + doc["coef"]["region_group"]["europe"]
    )
    out = sm.predict_pay(doc, role="sales", seniority="lead", region_group="europe")
    assert out["median"] == round(math.exp(expected))
    assert out["low"] == round(math.exp(expected + doc["interval"]["low_log"]))
    assert out["high"] == round(math.exp(expected + doc["interval"]["high_log"]))
    # A level the model never saw counts as the reference level.
    assert (
        sm.predict_pay(doc, role="astronaut", seniority="senior", region_group="us_canada")[
            "median"
        ]
        == sm.predict_pay(doc, role="data", seniority="senior", region_group="us_canada")["median"]
    )


# --------------------------------------------------------------------------- web parity fixture

FIXTURE = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "salary-model.fixtures.json"

# A small hand-written model, so the web tests do not depend on a snapshot.
FIXTURE_MODEL = {
    "version": 1,
    "intercept": 11.5,
    "reference": {"role": "data", "seniority": "senior", "region_group": "us_canada"},
    "coef": {
        "role": {"software_engineering": 0.1, "sales": -0.2, "support": -0.35},
        "seniority": {"junior": -0.4, "mid": -0.25, "lead": 0.15, "unspecified": -0.1},
        "region_group": {"europe": -0.35, "latam": -0.8, "worldwide": -0.4, "unknown": 0.01},
        "skill": {
            "sql": 0.0,
            "python": 0.05,
            "excel": -0.2,
            "power-bi": -0.2,
            "dbt": 0.3,
            "kubernetes": 0.12,
        },
    },
    "skills": [
        {"slug": "sql", "n": 120},
        {"slug": "python", "n": 100},
        {"slug": "excel", "n": 60},
        {"slug": "power-bi", "n": 60},
        {"slug": "dbt", "n": 40},
        {"slug": "kubernetes", "n": 30},
    ],
    "profile_max_skills": 3,
    "interval": {"low_log": -0.5, "high_log": 0.45, "level": 0.8},
}

PARITY_PROFILES = [
    ("data", "senior", "us_canada", []),
    ("data", "senior", "us_canada", ["sql"]),
    ("software_engineering", "lead", "europe", ["python", "kubernetes"]),
    ("sales", "junior", "latam", ["excel", "power-bi", "dbt", "sql", "python"]),
    ("support", "mid", "worldwide", ["kubernetes", "dbt", "python", "sql"]),
    ("data", "unspecified", "unknown", ["dbt", "not-a-skill", "dbt"]),
    ("astronaut", "senior", "mars", ["kubernetes"]),
    ("data", "senior", "us_canada", ["power-bi", "excel"]),
]

PARITY_REGIONS = [
    [],
    ["worldwide"],
    ["United States"],
    ["Canada"],
    ["North America"],
    ["Germany"],
    ["Estonia", "Latvia"],
    ["EMEA"],
    ["EU", "United Kingdom"],
    ["Brazil", "Mexico"],
    ["Latin America"],
    ["India", "Singapore"],
    ["Asia-Pacific"],
    ["Germany", "India"],
    ["worldwide", "Germany"],
    ["worldwide", "United States"],
    ["Germany", "United States"],
    ["Israel"],
    ["Americas"],
    ["Africa", "Kenya"],
    ["Türkiye"],
    ["Czechia", "Poland"],
    ["Bosnia and Herzegovina"],
    ["Timor-Leste"],
    ["germany"],
    ["  United   States "],
    ["Anywhere"],
    ["Global", "Worldwide"],
    ["Germany", "germany"],
    ["Côte d'Ivoire"],
    ["Hong Kong"],
    ["Puerto Rico"],
]


def build_parity_fixture() -> dict:
    return {
        "note": "Computed by radar.salary_model.predict_pay and radar.regions.region_group. "
        "Regenerate: RADAR_WRITE_FIXTURES=1 pytest tests/test_salary_model.py",
        "model": FIXTURE_MODEL,
        "predict": [
            {
                "input": {"role": r, "seniority": s, "regionGroup": g, "skills": sk},
                "expected": sm.predict_pay(
                    FIXTURE_MODEL, role=r, seniority=s, region_group=g, skills=sk
                ),
            }
            for r, s, g, sk in PARITY_PROFILES
        ],
        "region_groups": [
            {"regions": regs, "expected": region_group(regs)} for regs in PARITY_REGIONS
        ],
    }


def test_web_parity_fixture_matches_python():
    expected = build_parity_fixture()
    if os.environ.get("RADAR_WRITE_FIXTURES"):
        text = json.dumps(expected, indent=1, ensure_ascii=False)
        FIXTURE.write_text(text + "\n", encoding="utf-8")
    assert FIXTURE.exists(), "run with RADAR_WRITE_FIXTURES=1 to create salary-model.fixtures.json"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == expected, (
        "salary-model.fixtures.json is stale: regenerate with "
        "RADAR_WRITE_FIXTURES=1 pytest tests/test_salary_model.py and check the web tests"
    )
