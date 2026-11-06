"""Tests for radar.archetypes on synthetic vectors: blobs are recovered, results are
deterministic, names are unique, small data gives no archetypes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

from radar import archetypes, embed
from radar.aggregate import JobRecord, RawSalary

NOW = datetime(2026, 11, 7, 12, 0)
DIM = 24

BLOBS = [
    # (title, skills)
    ("Data Engineer", ["spark", "airflow", "aws"]),
    ("Data Scientist", ["statistics", "r", "pandas"]),
    ("Data Analyst", ["excel", "tableau", "sql"]),
    ("Machine Learning Engineer", ["pytorch", "mlops", "tensorflow"]),
]


def rec(
    i: int,
    *,
    title: str = "Data Engineer",
    skills=("python",),
    salary: float | None = None,
    role: str = "data",
    seniority: str = "senior",
    company: str | None = None,
) -> JobRecord:
    return JobRecord(
        id=f"job-{i}",
        source="remotive",
        title=title,
        company=company or f"Company {i}",
        url=f"https://example.com/{i}",
        location=None,
        posted_at=NOW - timedelta(days=2),
        role=role,
        seniority=seniority,
        employment_type="full_time",
        remote_regions=[],
        skills=list(skills),
        salaries=[RawSalary(salary, salary, "USD", "year")] if salary else [],
    )


def blob_population(
    per_blob: int = 20, *, blobs=BLOBS, salary_for: set[int] | None = None, seed: int = 5
) -> tuple[list[JobRecord], dict]:
    """``len(blobs)`` groups on separate axes of a DIM-dimensional space, noisy but separable."""
    rng = np.random.default_rng(seed)
    records, rows = [], []
    for b, (title, skills) in enumerate(blobs):
        for j in range(per_blob):
            i = b * per_blob + j
            vec = np.zeros(DIM)
            vec[b] = 1.0
            vec += rng.normal(0, 0.08, DIM)
            vec /= np.linalg.norm(vec)
            rows.append(vec)
            pay = 100_000 + 10_000 * b if salary_for is None or b in salary_for else None
            records.append(rec(i, title=title, skills=skills, salary=pay))
    doc = embed.job_vectors_from([r.id for r in records], np.array(rows), dim=DIM)
    return records, doc


def run(records, doc, **kw):
    return archetypes.compute_archetypes(records, doc, k_range=(2, 6), **kw)


# --------------------------------------------------------------------------- recovery


def test_well_separated_blobs_are_recovered():
    records, doc = blob_population()
    out = run(records, doc)
    assert out["version"] == 1
    assert out["method"]["k"] == 4
    assert out["method"]["n_jobs"] == 80
    assert out["method"]["silhouette"] > 0.8
    assert [c["k"] for c in out["method"]["candidates"]] == [2, 3, 4, 5, 6]
    arches = out["archetypes"]
    assert sorted(a["name"] for a in arches) == sorted(
        ["Data analyst", "Data engineer", "Data scientist", "Machine learning engineer"]
    )
    by_job = {p["id"]: p["a"] for p in out["points"]}
    assert len(by_job) == 80
    for blob in range(4):
        labels = {by_job[f"job-{blob * 20 + j}"] for j in range(20)}
        assert len(labels) == 1  # one blob, one archetype
    assert all(a["n"] == 20 and a["family_share"] == 1.0 for a in arches)
    assert sum(a["share"] for a in arches) == pytest.approx(1.0)


def test_archetype_fields_follow_the_contract():
    records, doc = blob_population()
    out = run(records, doc)
    a = next(x for x in out["archetypes"] if x["name"] == "Data engineer")
    assert set(a) == {
        "id",
        "name",
        "summary",
        "family",
        "family_share",
        "n",
        "share",
        "median_salary_usd",
        "salary_n",
        "silhouette",
        "seniority",
        "top_skills",
        "top_titles",
        "example_job_ids",
        "centroid",
    }
    assert a["id"] == "data-engineer"
    assert a["median_salary_usd"] == 100_000
    assert a["salary_n"] == 20
    assert a["seniority"] == {"senior": 20}
    assert a["top_titles"] == [{"title": "Data Engineer", "n": 20}]
    assert {s["slug"] for s in a["top_skills"]} == {"spark", "airflow", "aws"}
    top = a["top_skills"][0]
    assert set(top) == {"slug", "name", "share", "lift"}
    assert top["share"] == 1.0
    assert top["lift"] > 1.25
    assert len(a["example_job_ids"]) == 3
    assert all(j in {f"job-{i}" for i in range(20)} for j in a["example_job_ids"])
    # centroid: unit length, 4 decimal places
    centroid = np.array(a["centroid"])
    assert len(centroid) == DIM
    assert np.linalg.norm(centroid) == pytest.approx(1.0, abs=1e-3)
    assert all(round(v, 4) == v for v in a["centroid"])
    assert "20 postings" in a["summary"] and "$100k" in a["summary"]
    # points: PCA coordinates in [-1, 1] with 3 decimal places
    for p in out["points"]:
        assert set(p) == {"id", "a", "x", "y"}
        assert abs(p["x"]) <= 1 and abs(p["y"]) <= 1
        assert round(p["x"], 3) == p["x"]
    assert len(out["method"]["pca_variance"]) == 2
    json.dumps(out)  # serialisable as is


def test_examples_prefer_distinct_companies():
    records, doc = blob_population()
    for r in records[:20]:
        r.company = "Same Co"
    out = run(records, doc)
    a = next(x for x in out["archetypes"] if x["name"] == "Data engineer")
    assert len(a["example_job_ids"]) == 1  # all 20 postings share one company


def test_only_active_data_jobs_with_a_vector_are_clustered():
    records, doc = blob_population()
    extra = [rec(900 + i, role="software_engineering", title="Backend Engineer") for i in range(5)]
    no_vector = [rec(950 + i) for i in range(3)]
    out = run(records + extra + no_vector, doc)
    ids = {p["id"] for p in out["points"]}
    assert out["method"]["n_jobs"] == 80
    assert not ids & {r.id for r in extra + no_vector}


# --------------------------------------------------------------------------- determinism


def test_results_are_deterministic():
    records, doc = blob_population()
    first = json.dumps(run(records, doc), sort_keys=True)
    second = json.dumps(run(list(reversed(records)), doc), sort_keys=True)
    assert first == second


def test_kmeans_is_seeded_and_labels_every_point():
    records, doc = blob_population()
    _, matrix = embed.decode_job_vectors(doc)
    x = archetypes._normalise(matrix.astype(np.float64))
    a, ca = archetypes.spherical_kmeans(x, 4, seed=1)
    b, cb = archetypes.spherical_kmeans(x, 4, seed=1)
    assert np.array_equal(a, b) and np.allclose(ca, cb)
    assert set(a.tolist()) == {0, 1, 2, 3}
    assert np.allclose(np.linalg.norm(ca, axis=1), 1.0)


# --------------------------------------------------------------------------- guards


def test_fewer_than_thirty_data_jobs_gives_no_archetypes():
    records, doc = blob_population(per_blob=7)  # 28 data jobs
    out = archetypes.compute_archetypes(records, doc)
    assert out["archetypes"] == [] and out["points"] == []
    assert out["method"]["n_jobs"] == 28 and out["method"]["k"] == 0
    assert out["version"] == 1


def test_empty_vectors_give_no_archetypes():
    doc = embed.job_vectors_from([], np.zeros((0, DIM)), dim=DIM)
    out = archetypes.compute_archetypes([rec(1)], doc)
    assert out["archetypes"] == [] and out["method"]["n_jobs"] == 0


def test_default_range_needs_enough_jobs_for_six_clusters():
    records, doc = blob_population(per_blob=8)  # 32 jobs: k_max = 6 is allowed
    out = archetypes.compute_archetypes(records, doc)
    assert out["method"]["k"] >= 6
    records, doc = blob_population(per_blob=8, blobs=BLOBS[:3])  # 24 < MIN_JOBS
    assert archetypes.compute_archetypes(records, doc)["archetypes"] == []


def test_median_pay_needs_five_salaries():
    records, doc = blob_population()
    # only 4 salaried postings in the data scientist blob
    for r in records[20:40][4:]:
        r.salaries = []
    out = run(records, doc)
    scientist = next(x for x in out["archetypes"] if x["name"] == "Data scientist")
    assert scientist["salary_n"] == 4
    assert scientist["median_salary_usd"] is None
    assert "too few salaries" in scientist["summary"]
    engineer = next(x for x in out["archetypes"] if x["name"] == "Data engineer")
    assert engineer["median_salary_usd"] == 100_000


# --------------------------------------------------------------------------- names


def test_clusters_of_one_family_get_distinct_skill_names():
    blobs = [
        ("Data Scientist", ["statistics", "r", "pandas"]),
        ("Data Scientist", ["pytorch", "deep-learning", "nlp"]),
        ("Data Engineer", ["spark", "airflow", "aws"]),
        ("Data Analyst", ["excel", "tableau", "sql"]),
    ]
    records, doc = blob_population(blobs=blobs)
    out = run(records, doc)
    names = [a["name"] for a in out["archetypes"]]
    assert len(set(names)) == 4
    assert len({a["id"] for a in out["archetypes"]}) == 4
    scientists = [n for n in names if n.startswith("Data scientist")]
    assert len(scientists) == 2 and all("(" in n for n in scientists)
    assert "Data engineer" in names and "Data analyst" in names
    assert any("Statistics" in n or "Pandas" in n or "pandas" in n or "R" in n for n in scientists)


def test_unrecognised_titles_are_named_by_skills_and_stay_unique():
    blobs = [(f"Wizard {b}", [f"skill-{b}-a", f"skill-{b}-b"]) for b in range(3)]
    records, doc = blob_population(blobs=blobs)
    out = run(records, doc)
    names = [a["name"] for a in out["archetypes"]]
    assert len(set(names)) == len(names) == 3
    assert all(n.startswith("Mixed data roles (") for n in names)
    assert all(a["family"] is None for a in out["archetypes"])


def test_assign_names_never_returns_duplicates():
    names = archetypes.assign_names(
        ["Data engineer", "Data engineer", "Data engineer", None, None],
        [50, 40, 30, 20, 10],
        [["Spark", "AWS"], ["Spark", "Airflow"], [], [], []],
    )
    assert len(set(names)) == 5
    assert names[0] == "Data engineer (Spark)"
    assert names[1] == "Data engineer (Airflow)"
    assert names[2].startswith("Data engineer")
    assert names[3].startswith("Mixed data roles")


def test_assign_names_leaves_a_lone_family_alone():
    assert archetypes.assign_names(["Data analyst"], [10], [["Excel"]]) == ["Data analyst"]


# --------------------------------------------------------------------------- k choice


def test_choose_k_prefers_more_distinct_names_within_the_tolerance():
    scores = [(6, 0.130), (7, 0.131), (8, 0.128), (9, 0.134), (10, 0.100)]
    assert archetypes.choose_k(scores) == 6  # no name information: smallest close k
    assert archetypes.choose_k(scores, {6: 6, 7: 7, 8: 7, 9: 7, 10: 9}) == 7
    # k=10 has the most names but its silhouette is not close to the best
    assert archetypes.choose_k(scores, {6: 6, 7: 6, 8: 6, 9: 6, 10: 9}) == 6


def test_silhouette_is_high_for_separated_blobs_and_low_for_noise():
    records, doc = blob_population()
    _, matrix = embed.decode_job_vectors(doc)
    x = archetypes._normalise(matrix.astype(np.float64))
    good = np.repeat(np.arange(4), 20)
    assert archetypes.silhouette_values(x, good).mean() > 0.8
    rng = np.random.default_rng(0)
    assert archetypes.silhouette_values(x, rng.integers(0, 4, 80)).mean() < 0.1


def test_pca_is_scaled_and_sign_stable():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(60, 10)) * np.array([5, 2] + [0.1] * 8)
    coords, explained = archetypes.pca_2d(x)
    assert coords.shape == (60, 2)
    assert np.abs(coords).max() == pytest.approx(1.0)
    assert explained[0] > explained[1] > 0 and sum(explained) <= 1.0
    again, _ = archetypes.pca_2d(-x + 2 * x.mean(axis=0))  # mirrored data, same axes
    assert np.allclose(np.abs(again), np.abs(coords), atol=1e-9)


# --------------------------------------------------------------------------- titles


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Senior Data Engineer", "Data engineer"),
        ("Analytics Engineer", "Analytics engineer"),
        ("Staff Machine Learning Engineer", "Machine learning engineer"),
        ("ML Engineer (Computer Vision & MLOps)", "Machine learning engineer"),
        ("AI Engineer, Marketing", "Machine learning engineer"),
        ("Principal Data Scientist", "Data scientist"),
        ("Senior ML Data Scientist - Women's Health", "Data scientist"),
        ("Business Intelligence Analyst", "BI / reporting analyst"),
        ("Senior Data Analyst", "Data analyst"),
        ("Revenue Operations Analyst", "Business / product analyst"),
        ("Data Governance Analyst", "Data governance & quality"),
        ("AI Trainers Network - Welsh", "Data annotation / AI training"),
        ("AI Data Annotator - French (Canada)", "Data annotation / AI training"),
        ("Principal Data Architect", "Data architect"),
        ("Multiple roles: SDR, AE", "Other"),
    ],
)
def test_title_families(title, family):
    assert archetypes.title_family(title) == family


@pytest.mark.parametrize(
    ("title", "clean"),
    [
        ("Sr. Data Scientist II", "Data Scientist"),
        ("(Senior) Data Engineer", "Data Engineer"),
        ("(USA) , Data Scientist", "Data Scientist"),
        ("Staff Data Scientist, Growth", "Data Scientist"),
        ("Machine Learning Engineer (Remote Position)", "Machine Learning Engineer"),
        ("AI Trainers Network - Czech", "AI Trainers Network"),
        ("Staff, Advanced Analytics", "Advanced Analytics"),
        ("Senior", "Senior"),
    ],
)
def test_clean_title(title, clean):
    assert archetypes.clean_title(title) == clean
