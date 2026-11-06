"""Tests for radar.insights: skill premium, seniority lift, graph, companies, vocabulary."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import pytest

from radar import insights
from radar.aggregate import JobRecord, RawSalary, compute_snapshot
from radar.skills.normalize import _registry

NOW = datetime(2026, 11, 7, 12, 0)


def rec(
    i: int,
    *,
    skills=("python",),
    salary: float | None = None,
    role: str = "data",
    seniority: str = "senior",
    company: str | None = None,
    regions: list[str] | None = None,
    source: str = "remotive",
    days_ago: int = 3,
) -> JobRecord:
    return JobRecord(
        id=f"{source}-{i}",
        source=source,
        title=f"Job {i}",
        company=company or f"Company {i}",
        url=f"https://example.com/{i}",
        location=None,
        posted_at=NOW - timedelta(days=days_ago),
        role=role,
        seniority=seniority,
        employment_type="full_time",
        remote_regions=list(regions or []),
        skills=list(skills),
        salaries=[RawSalary(salary, salary, "USD", "year")] if salary else [],
    )


# --------------------------------------------------------------------------- skill premium


def premium_population() -> list[JobRecord]:
    """40 salaried jobs: 20 with 'dbt' paid ~110k, 20 without paid ~70k; 'git' is everywhere
    and unrelated to pay; 'rare' appears in only 5 jobs."""
    rng = np.random.default_rng(3)
    out = []
    for i in range(40):
        has_dbt = i < 20
        pay = (110_000 if has_dbt else 70_000) + float(rng.normal(0, 8_000))
        skills = ["git"] if i % 2 == 0 else ["git", "docker"]
        if has_dbt:
            skills.append("dbt")
        if i % 8 == 0:
            skills.append("rare")
        out.append(rec(i, skills=skills, salary=round(pay)))
    return out


def test_skill_premium_estimates_the_gap_with_a_confidence_interval():
    rows = {r["slug"]: r for r in insights.skill_premium(premium_population())}
    dbt = rows["dbt"]
    assert (dbt["n_with"], dbt["n_without"]) == (20, 20)
    assert dbt["name"] == "dbt"
    assert 30_000 < dbt["diff"] < 50_000
    assert dbt["diff"] == dbt["median_with"] - dbt["median_without"]
    assert dbt["ci_low"] < dbt["diff"] < dbt["ci_high"]
    assert dbt["ci_low"] > 0  # a 40k gap with 8k noise is clearly positive


def test_skill_premium_ci_straddles_zero_for_an_unrelated_skill():
    rows = {r["slug"]: r for r in insights.skill_premium(premium_population())}
    docker = rows["docker"]
    assert docker["ci_low"] < 0 < docker["ci_high"]


def test_skill_premium_filters_small_groups_and_sorts_by_interval_lower_bound():
    population = premium_population()
    rows = insights.skill_premium(population)
    slugs = [r["slug"] for r in rows]
    assert "rare" not in slugs  # only 5 salaried jobs
    assert "git" not in slugs  # nobody without it: no comparison group
    gaps = [insights._certain_adj_gap(r) for r in rows]
    assert gaps == sorted(gaps, reverse=True)
    assert rows[0]["slug"] == "dbt"  # the clear gap leads, the noisy docker row trails
    assert insights.skill_premium([rec(1, skills=["a"])]) == []  # no salaries at all


def clustered_population() -> list[JobRecord]:
    """104 salaried jobs. 'big' = 18 postings of one company ("Whale", paid ~300k) plus 6
    ordinary postings at 6 other companies; 'wide' = one ordinary posting at each of 20
    companies. Everything else is paid about 100k."""
    rng = np.random.default_rng(11)

    def ordinary() -> int:
        return round(100_000 + rng.normal(0, 5_000))

    out: list[JobRecord] = []
    for k in range(18):
        out.append(rec(len(out), skills=["big"], salary=300_000 + 1_000 * k, company="Whale"))
    for k in range(6):
        out.append(rec(len(out), skills=["big"], salary=ordinary(), company=f"B{k}"))
    for k in range(20):
        out.append(rec(len(out), skills=["wide"], salary=ordinary(), company=f"W{k}"))
    for k in range(60):
        out.append(rec(len(out), skills=["other"], salary=ordinary(), company=f"O{k % 30}"))
    return out


def test_skill_premium_resamples_companies_not_postings():
    pop = clustered_population()
    rows = {r["slug"]: r for r in insights.skill_premium(pop)}
    big, wide = rows["big"], rows["wide"]
    assert big["n_with"] == 24 and big["n_companies"] == 7
    assert wide["n_with"] == 20 and wide["n_companies"] == 20
    assert big["diff"] > 150_000  # the point estimate is driven by one employer

    # A posting-level bootstrap would call that gap rock solid ...
    rng = np.random.default_rng(0)
    pay = np.array([r.salary.annual_usd_mid for r in pop])
    mask = np.array(["big" in r.skills for r in pop])
    naive = np.median(pay[mask][rng.integers(0, 24, (1000, 24))], axis=1) - np.median(
        pay[~mask][rng.integers(0, 80, (1000, 80))], axis=1
    )
    assert np.percentile(naive, 2.5) > 100_000
    # ... the company bootstrap sees that the gap vanishes whenever "Whale" is not drawn.
    assert big["ci_low"] < 20_000
    assert wide["ci_low"] < 0 < wide["ci_high"]


def test_skill_premium_needs_five_distinct_companies():
    pop = [
        replace(r, company="Same Co") if "big" in r.skills else r for r in clustered_population()
    ]
    assert "big" not in {r["slug"] for r in insights.skill_premium(pop)}  # 1 company
    four = [
        replace(r, company=f"Four {i % 4}") if "big" in r.skills else r
        for i, r in enumerate(clustered_population())
    ]
    assert "big" not in {r["slug"] for r in insights.skill_premium(four)}  # 4 companies
    five = [
        replace(r, company=f"Five {i % 5}") if "big" in r.skills else r
        for i, r in enumerate(clustered_population())
    ]
    rows = {r["slug"]: r for r in insights.skill_premium(five)}
    assert rows["big"]["n_companies"] == 5
    assert "big" in {r["slug"] for r in insights.skill_premium(four, min_companies=4)}


def test_cluster_medians_match_numpy_on_expanded_samples():
    rng = np.random.default_rng(5)
    values = np.sort(rng.integers(50, 150, 30).astype(float))
    weights = rng.integers(0, 4, (40, 30))
    weights[3] = 0  # an empty replicate gives NaN
    got = insights._cluster_medians(weights, values)
    assert np.isnan(got[3])
    for i in (0, 1, 2, 4, 5, 39):
        expanded = np.repeat(values, weights[i])
        assert got[i] == pytest.approx(np.median(expanded))


def test_certain_gap_is_the_distance_of_the_interval_from_zero():
    assert insights._certain_gap({"diff": 50, "ci_low": 20, "ci_high": 90}) == 20
    assert insights._certain_gap({"diff": -50, "ci_low": -90, "ci_high": -20}) == 20
    assert insights._certain_gap({"diff": 10, "ci_low": -5, "ci_high": 30}) == -5
    assert insights._certain_gap({"diff": -10, "ci_low": -30, "ci_high": 5}) == -5


def test_skill_premium_is_reproducible_and_independent_of_other_skills():
    population = premium_population()
    first = insights.skill_premium(population)
    assert insights.skill_premium(population) == first
    # Adding another skill (new premium row) must not move dbt's resampling stream.
    with_extra = [
        replace(r, skills=[*r.skills, "zzz"] if int(r.id.split("-")[1]) % 2 else r.skills)
        for r in population
    ]
    rows = {r["slug"]: r for r in insights.skill_premium(with_extra)}
    assert "zzz" in rows
    assert rows["dbt"] == next(r for r in first if r["slug"] == "dbt")
    other = next(r for r in insights.skill_premium(population, seed=1) if r["slug"] == "dbt")
    dbt = next(r for r in first if r["slug"] == "dbt")
    assert other["diff"] == dbt["diff"] and (other["ci_low"], other["ci_high"]) != (
        dbt["ci_low"],
        dbt["ci_high"],
    )


def adjusted_population(effect: float = 0.0, *, seed: int = 21) -> list[JobRecord]:
    """160 salaried postings, each from its own company. "ml" roles pay about twice as much as
    "data" roles. "torch" appears in half of the ml postings and in none of the data ones;
    "sql" appears in a random 40% of both roles and multiplies pay by exp(effect). Seniority
    alternates senior/mid and is paid +25% for senior."""
    rng = np.random.default_rng(seed)
    out: list[JobRecord] = []
    for i in range(160):
        role = "ml" if i < 80 else "data"
        seniority = "senior" if i % 2 == 0 else "mid"
        has_sql = bool(rng.random() < 0.4)
        skills = ["git"] if i % 3 else ["git", "docker"]
        if role == "ml" and i % 2 == 1:
            skills.append("torch")
        if has_sql:
            skills.append("sql")
        log_pay = (
            math.log(120_000 if role == "ml" else 60_000)
            + (math.log(1.25) if seniority == "senior" else 0.0)
            + (effect if has_sql else 0.0)
            + float(rng.normal(0, 0.08))
        )
        out.append(
            rec(i, skills=skills, salary=round(math.exp(log_pay)), role=role, seniority=seniority)
        )
    return out


def test_role_confounded_skill_has_a_large_raw_gap_but_no_adjusted_premium():
    rows = {r["slug"]: r for r in insights.skill_premium(adjusted_population())}
    torch = rows["torch"]
    assert torch["diff"] > 30_000 and torch["ci_low"] > 0  # raw: looks like a big premium
    assert abs(torch["adj_pct"]) < 8  # within role it pays the same
    assert torch["adj_ci_low_pct"] < 0 < torch["adj_ci_high_pct"]
    # adj_usd is the effect at the with-skill pay level; it is computed from the unrounded
    # percentage, so allow for the 0.1 pp rounding of adj_pct.
    expected = torch["median_with"] * (1 - 1 / (1 + torch["adj_pct"] / 100))
    assert torch["adj_usd"] == pytest.approx(expected, abs=0.002 * torch["median_with"])


def test_adjusted_usd_is_the_effect_at_the_with_skill_pay_level():
    sql = next(
        r for r in insights.skill_premium(adjusted_population(math.log(1.2))) if r["slug"] == "sql"
    )
    without_skill = sql["median_with"] / (1 + sql["adj_pct"] / 100)  # what they'd advertise
    assert sql["adj_usd"] == pytest.approx(sql["median_with"] - without_skill, abs=0.003 * 1e5)
    assert sql["adj_usd"] > 0


def region_population(effect: float = 0.0, *, seed: int = 8) -> list[JobRecord]:
    """120 salaried postings, one company each, same role and seniority throughout. 60 are
    open in the US (about 120k) and 60 in India (about 30k). "offshore" is listed by half of
    the Indian postings and by none of the US ones; "sql" is listed by a random 40% of both
    regions and multiplies pay by exp(effect)."""
    rng = np.random.default_rng(seed)
    out: list[JobRecord] = []
    for i in range(120):
        us = i < 60
        has_sql = bool(rng.random() < 0.4)
        skills = ["git"] if i % 3 else ["git", "docker"]
        if not us and i % 2 == 0:
            skills.append("offshore")
        if has_sql:
            skills.append("sql")
        log_pay = (
            math.log(120_000 if us else 30_000)
            + (effect if has_sql else 0.0)
            + float(rng.normal(0, 0.08))
        )
        out.append(
            rec(
                i,
                skills=skills,
                salary=round(math.exp(log_pay)),
                regions=["United States"] if us else ["India"],
            )
        )
    return out


def test_skill_confined_to_a_low_pay_region_has_no_adjusted_premium():
    rows = {r["slug"]: r for r in insights.skill_premium(region_population())}
    offshore = rows["offshore"]
    assert offshore["diff"] < -60_000 and offshore["ci_high"] < 0  # raw: a huge, clear penalty
    assert abs(offshore["adj_pct"]) < 8  # same region, same pay
    assert offshore["adj_ci_low_pct"] < 0 < offshore["adj_ci_high_pct"]
    # Without the region control the same data would show a big penalty: the control matters.
    pop = region_population()
    salaried = sorted(pop, key=lambda r: (r.salary.annual_usd_mid, r.id))
    y = np.log([r.salary.annual_usd_mid for r in salaried])
    s = np.array([["offshore" in r.skills] for r in salaried], dtype=float)
    plain = np.hstack([np.ones((len(y), 1)), s])
    b = np.linalg.lstsq(plain, y, rcond=None)[0][1]
    assert 100 * math.expm1(b) < -50


def test_region_effect_is_still_recovered_within_a_region():
    rows = {r["slug"]: r for r in insights.skill_premium(region_population(math.log(1.2)))}
    assert rows["sql"]["adj_pct"] == pytest.approx(20, abs=6)
    assert rows["sql"]["adj_ci_low_pct"] > 0


def test_adjusted_estimate_recovers_a_true_within_role_effect():
    effect = math.log(1.2)
    rows = {r["slug"]: r for r in insights.skill_premium(adjusted_population(effect))}
    sql = rows["sql"]
    assert sql["adj_pct"] == pytest.approx(20, abs=5)
    assert sql["adj_ci_low_pct"] < 20 < sql["adj_ci_high_pct"]
    assert sql["adj_ci_low_pct"] > 0  # and it is clearly positive
    assert sql["adj_ci_low_pct"] < sql["adj_pct"] < sql["adj_ci_high_pct"]
    # The confounded skill stays near zero in the same data.
    assert abs(rows["torch"]["adj_pct"]) < 8


def test_adjusted_estimate_matches_a_direct_regression_and_is_deterministic():
    population = adjusted_population(math.log(1.2))
    first = insights.skill_premium(population)
    assert insights.skill_premium(population) == first  # seeded: identical across runs

    salaried = sorted(population, key=lambda r: (r.salary.annual_usd_mid, r.id))
    y = np.log([r.salary.annual_usd_mid for r in salaried])
    design = np.column_stack(
        [
            np.ones(len(salaried)),
            [r.role == "data" for r in salaried],
            [r.seniority == "mid" for r in salaried],
            ["sql" in r.skills for r in salaried],
        ]
    ).astype(float)
    b = np.linalg.lstsq(design, y, rcond=None)[0][-1]
    sql = next(r for r in first if r["slug"] == "sql")
    assert sql["adj_pct"] == pytest.approx(100 * math.expm1(b), abs=0.05)


def test_fwl_bootstrap_coefficients_equal_weighted_regressions():
    """Each resample's coefficient equals the full weighted least squares fit with that
    resample's company multiplicities."""
    population = adjusted_population(math.log(1.2))
    salaried = sorted(population, key=lambda r: (r.salary.annual_usd_mid, r.id))
    y = np.log([r.salary.annual_usd_mid for r in salaried])
    sql = np.array([["sql" in r.skills] for r in salaried], dtype=float)
    design = insights._fixed_effects_design(salaried)
    rng = np.random.default_rng(4)
    weights = rng.integers(0, 4, (5, len(salaried)))
    got = insights._adjusted_coefficients(y, sql, design, weights)[0]
    full = np.hstack([design, sql])
    for i, w in enumerate(np.vstack([np.ones(len(salaried)), weights])):
        root = np.sqrt(w)[:, None]
        coef = np.linalg.lstsq(full * root, y * root[:, 0], rcond=None)[0]
        assert got[i] == pytest.approx(coef[-1], abs=1e-9)


def test_skill_without_variation_inside_role_and_seniority_is_skipped():
    population = adjusted_population()
    # "ml-only" is in every ml posting and in no data posting: role explains it completely.
    population = [
        replace(r, skills=[*r.skills, "ml-only"]) if r.role == "ml" else r for r in population
    ]
    rows = {r["slug"]: r for r in insights.skill_premium(population)}
    flat = rows["ml-only"]
    assert flat["adj_pct"] is None and flat["adj_usd"] is None
    assert flat["adj_ci_low_pct"] is None and flat["adj_ci_high_pct"] is None
    assert flat["diff"] > 30_000 and flat["ci_low"] < flat["diff"] < flat["ci_high"]  # raw kept
    order = [r["slug"] for r in insights.skill_premium(population)]
    assert order[-1] == "ml-only"  # rows without an adjusted estimate sort last
    assert rows["sql"]["adj_pct"] is not None


def test_adjusted_rows_sort_by_distance_of_the_adjusted_interval_from_zero():
    rows = insights.skill_premium(adjusted_population(math.log(1.2)))
    adjusted = [r for r in rows if r["adj_pct"] is not None]
    gaps = [insights._certain_adj_gap(r) for r in adjusted]
    assert gaps == sorted(gaps, reverse=True)
    assert rows[0]["slug"] == "sql"


# --------------------------------------------------------------------------- seniority lift


def lift_population() -> list[JobRecord]:
    out = []
    n = 0
    for _ in range(15):  # senior data jobs: 12 mention kubernetes, all python
        out.append(
            rec(n, role="data", seniority="senior", skills=["python"] + ["kubernetes"] * (n < 12))
        )
        n += 1
    for _ in range(15):  # junior/mid data jobs: 1 mentions kubernetes, 10 mention excel
        skills = ["python"] + (["kubernetes"] if n == 15 else []) + (["excel"] if n < 25 else [])
        out.append(rec(n, role="data", seniority="junior" if n % 2 else "mid", skills=skills))
        n += 1
    for _ in range(3):  # unspecified seniority counts toward the role but neither group
        out.append(rec(n, role="data", seniority="unspecified", skills=["python"]))
        n += 1
    for _ in range(10):  # a role below the 30-posting minimum
        out.append(rec(n, role="design", seniority="senior", skills=["figma"]))
        n += 1
    return out


def test_seniority_lift_ranks_senior_skills_and_skips_small_roles():
    rows = insights.seniority_lift(lift_population())
    assert [r["role"] for r in rows] == ["data"]  # design has 10 postings
    data = rows[0]
    assert (data["n_senior"], data["n_junior"]) == (15, 15)  # unspecified is in neither
    top = data["skills"][0]
    assert top["slug"] == "kubernetes" and top["name"] == "Kubernetes"
    assert top["share_senior"] == pytest.approx(12 / 15, abs=1e-4)
    assert top["share_junior"] == pytest.approx(1 / 15, abs=1e-4)
    smoothed = ((12 + 0.5) / 16) / ((1 + 0.5) / 16)
    assert top["lift"] == pytest.approx(smoothed, abs=0.01)
    by_slug = {s["slug"]: s for s in data["skills"]}
    assert by_slug["excel"]["lift"] < 1  # a junior skill
    assert by_slug["python"]["lift"] == pytest.approx(1.0, abs=0.05)
    assert len(data["skills"]) <= 10
    lifts = [s["lift"] for s in data["skills"]]
    assert lifts == sorted(lifts, reverse=True)


def test_seniority_lift_without_enough_juniors_has_no_skills():
    population = [rec(i, seniority="senior", skills=["python"]) for i in range(32)]
    population += [rec(100 + i, seniority="junior", skills=["python"]) for i in range(2)]
    (row,) = insights.seniority_lift(population)
    assert (row["n_senior"], row["n_junior"], row["skills"]) == (32, 2, [])


# --------------------------------------------------------------------------- skill graph


def test_skill_graph_pmi_and_edge_threshold():
    # 10 jobs: a in 5, b in 4, a&b together in 4 -> PMI = log2(4*10 / (5*4)) = 1
    population = []
    for i in range(10):
        skills = []
        if i < 5:
            skills.append("a")
        if 1 <= i < 5:
            skills.append("b")
        if i in (0, 9):
            skills.append("c")  # c in 2 jobs only: below node and edge minimum
        population.append(rec(i, skills=skills or ["z"]))
    graph = insights.skill_graph(population)
    nodes = {n["slug"]: n for n in graph["nodes"]}
    assert nodes["a"]["count"] == 5 and nodes["b"]["count"] == 4
    assert "c" not in nodes  # count 2 < 3
    (edge,) = graph["edges"]
    assert (edge["a"], edge["b"], edge["count"]) == ("a", "b", 4)
    assert edge["pmi"] == pytest.approx(math.log2(4 * 10 / (5 * 4)), abs=1e-3)


def test_skill_graph_caps_nodes_and_edges_and_ranks_by_pmi():
    skills = [f"s{i:02d}" for i in range(90)]
    population = [rec(i, skills=skills[:40] + [skills[40 + i]]) for i in range(5)]
    graph = insights.skill_graph(population)
    assert len(graph["nodes"]) <= insights.GRAPH_NODES
    assert len(graph["edges"]) == insights.GRAPH_MAX_EDGES  # 40 skills together: 780 pairs
    pmis = [e["pmi"] for e in graph["edges"]]
    assert pmis == sorted(pmis, reverse=True)
    keep = {n["slug"] for n in graph["nodes"]}
    assert all(e["a"] in keep and e["b"] in keep and e["a"] < e["b"] for e in graph["edges"])


def test_skill_graph_prefers_the_distinctive_pair_over_the_common_one():
    population = []
    for i in range(20):
        skills = ["common"]
        if i < 4:
            skills += ["dbt", "airflow"]  # rare and always together: high PMI
        if i % 2 == 0:
            skills += ["sql"]
        population.append(rec(i, skills=skills))
    edges = insights.skill_graph(population)["edges"]
    assert (edges[0]["a"], edges[0]["b"]) == ("airflow", "dbt")


# --------------------------------------------------------------------------- role skills


def test_role_skills_shares_and_minimum_size():
    population = [
        rec(i, role="data", skills=["python", "sql"] if i < 6 else ["python"]) for i in range(10)
    ]
    population += [rec(50 + i, role="design", skills=["figma"]) for i in range(3)]
    rows = insights.role_skills(population)
    assert [r["role"] for r in rows] == ["data"]  # design has 3 < 5 postings
    top = {t["slug"]: t["share"] for t in rows[0]["top"]}
    assert rows[0]["n"] == 10 and top == {"python": 1.0, "sql": 0.6}
    many = [rec(i, skills=[f"s{j:02d}" for j in range(30)]) for i in range(6)]
    assert len(insights.role_skills(many)[0]["top"]) == insights.ROLE_SKILLS_TOP


def test_compute_insights_has_all_sections_and_json_serialisable():
    import json

    doc = insights.compute_insights(premium_population() + lift_population())
    assert set(doc) == {"skill_premium", "seniority_lift", "skill_graph", "role_skills"}
    assert set(doc["skill_graph"]) == {"nodes", "edges"}
    json.dumps(doc)  # plain Python numbers only, no numpy scalars


# --------------------------------------------------------------------------- companies


def test_company_slug_rules():
    assert insights.company_slug("Acme Corp") == "acme-corp"
    assert insights.company_slug("Zürich Café & Co.") == "zurich-cafe-co"
    assert insights.company_slug("  --Foo__Bar!! ") == "foo-bar"
    assert insights.company_slug("Ølen  AS") == "len-as"
    assert insights.company_slug("日本語") == "company"
    assert insights.company_slug("") == "company"


def test_companies_group_legal_variants_and_aggregate():
    population = [
        rec(
            1,
            company="Acme GmbH",
            role="data",
            seniority="senior",
            skills=["python", "sql"],
            salary=100_000,
            days_ago=5,
        ),
        rec(
            2,
            company="ACME",
            role="data",
            seniority="junior",
            skills=["python"],
            salary=60_000,
            source="remoteok",
            days_ago=1,
        ),
        rec(3, company="Acme Inc", role="design", seniority="senior", skills=["figma"], days_ago=3),
        rec(4, company="Beta Co", role="product", seniority="mid", skills=["jira"]),
    ]
    rows = insights.compute_companies(population)
    assert [r["jobs"] for r in rows] == [3, 1]
    acme = rows[0]
    assert acme["slug"] == "acme" or acme["slug"].startswith("acme")
    assert acme["name"] in {"Acme GmbH", "ACME", "Acme Inc"}
    assert acme["roles"] == {"data": 2, "design": 1}
    assert acme["seniority"] == {"senior": 2, "junior": 1}
    assert acme["top_skills"][0] == {"slug": "python", "name": "Python", "count": 2}
    assert acme["median_salary_usd"] == 80_000 and acme["salary_n"] == 2
    assert acme["sources"] == ["remoteok", "remotive"]
    assert acme["job_ids"] == ["remoteok-2", "remotive-3", "remotive-1"]  # newest first
    beta = rows[1]
    assert beta["median_salary_usd"] is None and beta["salary_n"] == 0
    assert set(acme) == {
        "slug",
        "name",
        "jobs",
        "jobs_total",
        "roles",
        "seniority",
        "top_skills",
        "median_salary_usd",
        "salary_n",
        "sources",
        "job_ids",
    }


def test_company_name_is_the_most_common_spelling_and_slugs_are_deduplicated():
    population = [
        rec(1, company="Foo"),
        rec(2, company="Foo Ltd"),
        rec(3, company="Foo Ltd"),
        rec(4, company="日本"),
        rec(5, company="中国"),
        rec(6, company="Foo Bar"),
        rec(7, company="Foo-Bar!"),
    ]
    rows = insights.compute_companies(population)
    by_name = {r["name"]: r for r in rows}
    assert by_name["Foo Ltd"]["jobs"] == 3  # grouped with "Foo", majority spelling wins
    slugs = [r["slug"] for r in rows]
    assert len(set(slugs)) == len(slugs)
    assert sorted(s for s in slugs if s.startswith("company")) == ["company", "company-2"]
    assert [r["jobs"] for r in rows] == sorted((r["jobs"] for r in rows), reverse=True)


# --------------------------------------------------------------------------- skill vocabulary


def test_skill_vocab_covers_every_canonical_skill_with_lowercase_unique_patterns():
    vocab = insights.build_skill_vocab()
    registry = _registry().infos
    assert {v["slug"] for v in vocab} == set(registry)
    for entry in vocab:
        info = registry[entry["slug"]]
        assert (entry["name"], entry["category"]) == (info.display, info.category)
        patterns = entry["patterns"]
        assert patterns == [p.lower() for p in patterns] and len(set(patterns)) == len(patterns)
        assert info.display.lower() in patterns
        assert entry["slug"].replace("-", " ") in patterns
        assert set(entry["strict_patterns"]) <= set(patterns)
        assert isinstance(entry["strict"], bool)


def test_skill_vocab_contains_aliases_and_slug_words():
    by_slug = {v["slug"]: v for v in insights.build_skill_vocab()}
    assert {"ruby on rails", "rails", "ror"} <= set(by_slug["ruby-on-rails"]["patterns"])
    assert {"postgresql", "postgres", "psql"} <= set(by_slug["postgresql"]["patterns"])
    assert {"c++", "cpp", "c plus plus"} <= set(by_slug["cpp"]["patterns"])
    assert {".net", "dotnet"} <= set(by_slug["dotnet"]["patterns"])


def test_skill_vocab_strict_rules():
    by_slug = {v["slug"]: v for v in insights.build_skill_vocab()}
    for slug in ["go", "r", "c", "ai", "excel", "spark", "swift", "react"]:
        assert by_slug[slug]["strict"], slug
    assert not by_slug["monday-com"]["strict"]  # "monday.com" is distinctive ...
    assert "monday" in by_slug["monday-com"]["strict_patterns"]  # ... plain "monday" is not
    for slug in ["python", "kubernetes", "cpp", "csharp", "machine-learning", "golang"]:
        if slug in by_slug:
            assert not by_slug[slug]["strict"], slug
    # Strict aliases of otherwise safe skills are flagged per pattern.
    assert "py" in by_slug["python"]["strict_patterns"]
    assert "ml" in by_slug["machine-learning"]["strict_patterns"]
    assert "sem" in by_slug["paid-advertising"]["strict_patterns"]
    assert "rest" in by_slug["api-development"]["strict_patterns"]
    assert "golang" not in by_slug["go"]["strict_patterns"]
    assert "ms excel" not in by_slug["excel"]["strict_patterns"]
    assert "c++" not in by_slug["cpp"]["strict_patterns"]
    assert "c#" not in by_slug["csharp"]["strict_patterns"]


@pytest.mark.parametrize(
    ("pattern", "strict"),
    [
        ("go", True),
        ("r", True),
        ("c", True),
        ("ai", True),
        ("ml", True),
        ("ts", True),
        ("k6", True),
        ("sem", True),
        ("rest", True),
        ("security", True),
        ("c++", False),
        ("c#", False),
        ("f#", False),
        ("sql", False),
        ("python", False),
        ("machine learning", False),
        (".net", False),
        ("ci/cd", False),
    ],
)
def test_is_strict_pattern(pattern, strict):
    assert insights.is_strict_pattern(pattern) is strict


# --------------------------------------------------------------------------- snapshot wiring


def test_compute_snapshot_includes_the_v2_documents():
    population = premium_population() + lift_population()
    snapshot = compute_snapshot(population, now=NOW, backend="ollama", model="m")
    assert {"insights", "companies", "skill_vocab"} <= set(snapshot)
    assert snapshot["insights"]["skill_premium"]
    assert len(snapshot["companies"]) == len({r.company for r in population})
    assert len(snapshot["skill_vocab"]) == len(_registry().infos)
    listed = {j["id"] for j in snapshot["jobs"]}
    assert all(i in listed for c in snapshot["companies"] for i in c["job_ids"])
