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
        remote_regions=[],
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


def test_skill_premium_filters_small_groups_and_sorts_by_diff():
    population = premium_population()
    rows = insights.skill_premium(population)
    slugs = [r["slug"] for r in rows]
    assert "rare" not in slugs  # only 5 salaried jobs
    assert "git" not in slugs  # nobody without it: no comparison group
    diffs = [r["diff"] for r in rows]
    assert diffs == sorted(diffs, reverse=True)
    assert insights.skill_premium([rec(1, skills=["a"])]) == []  # no salaries at all


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
