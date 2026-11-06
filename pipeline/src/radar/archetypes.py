"""Job archetypes: clusters of data-role postings by embedding (``archetypes.json``).

What it does
------------
Takes the active postings whose extracted ``role`` is ``data`` and that have a published
embedding (``job_vectors.json``, bge-small, 384 dimensions, L2-normalised), groups them with
spherical k-means (k-means on the unit sphere, so the distance is cosine distance), and
describes every group with numbers read from its members: size, typical seniority, signature
skills, common titles, median advertised pay, and the three most representative postings.

Choosing k
----------
k is tried from ``K_MIN`` to ``K_MAX`` (limited so that a cluster averages at least
``MIN_PER_CLUSTER`` postings). For every k the best of ``RESTARTS`` seeded k-means++ runs (the
one with the highest total cosine similarity to its centroids) is scored with the mean cosine
silhouette. The silhouette of text embeddings is low and flat (clusters are fuzzy), so
picking the arg-max alone would chase noise. The rule is: **take the smallest k whose
silhouette is within ``SILHOUETTE_TOLERANCE`` of the best, and among those the one whose
clusters are named after the most different job families** (a cluster counts when at least
``NAMEABLE_SHARE`` of its titles fall in its dominant family), ties going to the smaller k. Put
plainly: an extra cluster has to add a new kind of job, not split a kind that is already there.
Every candidate's score is published (``method.candidates``) so the choice can be audited.

Names
-----
Names are rule-based (no model at publish time) so they are deterministic. A small curated list
of regular expressions maps each title to a *title family* (``FAMILIES``: data engineer,
analytics engineer, data analyst, BI analyst, data scientist, ML engineer, annotation / AI
training, ...). A cluster is named after the family that most of its titled members fall in. When
two clusters share a family, each gets the skill that best sets it apart from its same-family
siblings (``share * ln(lift)`` against the siblings pooled) in brackets, moving down the list
until the names are unique: "Data scientist (A/B Testing)" next to "Data scientist (Spark)".
Each archetype also publishes ``family`` and ``family_share`` (the share of its postings whose
title falls in that family), which is the purity check: a low share means the cluster is held
together by the description and skills rather than by what the jobs are called.

Skills and lift
---------------
``lift`` = share of the cluster's postings that list the skill / share of all clustered
postings that list it, both with add-0.5 smoothing ``(count + 0.5) / (n + 1)``. Signature
skills are the ones with share >= ``SIGNATURE_MIN_SHARE``, lift >= ``SIGNATURE_MIN_LIFT`` and at
least ``SIGNATURE_MIN_COUNT`` postings, ranked by ``share * ln(lift)`` (how much a skill sets the
cluster apart, counting both how common it is and how over-represented), top ``TOP_SKILLS``.

Plot
----
``points`` carry the first two principal components of the clustered vectors, scaled by one
common factor so the largest coordinate is 1. They are a picture, not the clustering: two
components keep only ``method.pca_variance`` of the variance, so neighbours in the plot are
similar but similar postings can sit apart.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from radar import embed
from radar.skills import skill_info

if TYPE_CHECKING:
    from radar.aggregate import JobRecord

SEED = 20261107
MIN_JOBS = 30  # fewer clustered postings: no archetypes
K_MIN = 6
K_MAX = 12
MIN_PER_CLUSTER = 5
RESTARTS = 10
MAX_ITER = 100
SILHOUETTE_TOLERANCE = 0.01
MIN_SALARY_N = 5
TOP_SKILLS = 8
TOP_TITLES = 5
EXAMPLES = 3
SIGNATURE_MIN_SHARE = 0.15
SIGNATURE_MIN_LIFT = 1.25
SIGNATURE_MIN_COUNT = 3
NAME_SKILL_MIN_SHARE = 0.10  # a skill used to tell same-family clusters apart
NAMEABLE_SHARE = 0.30  # a family names a cluster only if this share of its titles match
LEVELS = ("intern", "junior", "mid", "senior", "lead", "principal", "unspecified")
STATED = LEVELS[:-1]
OTHER = "Other"

# Title families: first match wins, so specific families come before general ones. Patterns run
# on the lowercased title.
FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern))
    for name, pattern in (
        (
            "Data annotation / AI training",
            r"\b(ai trainers?|annotat\w*|label(l)?(er|ers|ing)|raters?|content reviewer"
            r"|data collector|transcri\w+|ai tutor|subject matter expert|red team\w*"
            r"|prompt (writer|engineer))\b",
        ),
        ("Data architect", r"\barchitect"),
        (
            "Analytics engineer",
            r"\banalytics engineer|\bbi engineer|\bbusiness intelligence engineer"
            r"|\bdata and analytics engineer",
        ),
        (
            "Data scientist",
            r"\bdata scien|\bapplied scien|\bresearch scien|\bdecision scien|\bscientist\b",
        ),
        (
            "Data engineer",
            r"\bdata (platform |software |infrastructure |integration )?(engineer|developer)"
            r"|\bdata engineering|\betl\b|\bdata pipeline|\bdata platform|\bdata ops\b"
            r"|\bdataops\b|\bdatabase (engineer|administrator)|\bdba\b"
            r"|\bsoftware engineer.*\bdata\b",
        ),
        (
            "Machine learning engineer",
            r"\b(machine learning|ml|mlops|ai|computer vision|nlp|deep learning|llm|genai"
            r"|generative ai|applied ai)\b.*\b(engineer|developer|researcher|specialist)\b"
            r"|\bmachine learning\b|\bml engineer",
        ),
        (
            "Data governance & quality",
            r"\bgovernance|\bdata quality|\bsteward|\bmaster data|\bdata management"
            r"|\bdata catalog|\bcompliance",
        ),
        (
            "BI / reporting analyst",
            r"\bbusiness intelligence|\bbi\b|\breporting\b|\bpower bi|\btableau|\blooker\b"
            r"|\bdashboard",
        ),
        (
            "Business / product analyst",
            r"\b(product|marketing|growth|gtm|revenue|sales|commercial|customer|pricing|finance"
            r"|financial|operations|strategy|strategic|insights?|business|fraud|risk|supply"
            r"|clinical|healthcare)\b.*\banalyst|\bbusiness analyst|\banalyst,? "
            r"(product|growth|marketing|gtm|revenue)|\binsights\b",
        ),
        ("Data analyst", r"\bdata analy|\banalyst\b|\banalytics\b|\banalysis\b"),
    )
)

LEVEL_WORDS = re.compile(
    r"\b(senior|sr|staff|principal|lead|junior|jr|mid|entry[- ]level|distinguished)\b\.?",
    re.IGNORECASE,
)
ROMAN_SUFFIX = re.compile(r"\s+(?:i{1,3}|iv|v|vi)$", re.IGNORECASE)


def title_family(title: str) -> str:
    """The first matching title family, else ``OTHER``."""
    low = " ".join(title.lower().split())
    for name, pattern in FAMILIES:
        if pattern.search(low):
            return name
    return OTHER


def clean_title(title: str) -> str:
    """Title reduced to its role: no level words, numerals, brackets or ", team" / " - place"
    tails ("Sr. Data Scientist II, Growth" -> "Data Scientist")."""
    flat = " ".join(title.split())
    text = re.sub(r"\([^)]*\)", " ", flat)
    text = text.strip(" -,|/:;")
    head = re.split(r"\s[-–—|]\s|\s*,\s*", text, maxsplit=1)[0]
    for candidate in (head, text):
        cleaned = LEVEL_WORDS.sub(" ", candidate)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,|/:;")
        cleaned = ROMAN_SUFFIX.sub("", cleaned).strip(" -,|/:;")
        if cleaned:
            return cleaned
    return flat


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "archetype"


# --------------------------------------------------------------------------- k-means


def _kmeans_pp(x: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """k-means++ seeding on the sphere (distance = 1 - cosine). Returns centroid rows."""
    n = x.shape[0]
    chosen = [int(rng.integers(n))]
    best = np.clip(1.0 - x @ x[chosen[0]], 0.0, None)
    for _ in range(1, k):
        total = float(best.sum())
        # all points coincide with a centroid: any pick will do
        pick = int(rng.integers(n)) if total <= 1e-12 else int(rng.choice(n, p=best / total))
        chosen.append(pick)
        best = np.minimum(best, np.clip(1.0 - x @ x[pick], 0.0, None))
    return x[chosen].copy()


def _normalise(rows: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    return rows / np.maximum(norms, 1e-12)


def spherical_kmeans(
    x: np.ndarray, k: int, *, seed: int, restarts: int = RESTARTS, max_iter: int = MAX_ITER
) -> tuple[np.ndarray, np.ndarray]:
    """Best of ``restarts`` runs by total cosine similarity. ``x`` rows must be unit length.

    Returns (labels, centroids). An emptied cluster is re-seeded with the point that is
    farthest from its centroid. Deterministic for a given ``seed``.
    """
    best: tuple[float, np.ndarray, np.ndarray] | None = None
    for restart in range(restarts):
        rng = np.random.default_rng([seed, k, restart])
        centroids = _kmeans_pp(x, k, rng)
        labels = np.full(x.shape[0], -1)
        for _ in range(max_iter):
            sims = x @ centroids.T
            new_labels = sims.argmax(axis=1)
            if np.array_equal(new_labels, labels):
                break
            labels = new_labels
            for j in range(k):
                members = x[labels == j]
                if len(members) == 0:
                    own = sims[np.arange(len(x)), labels]
                    far = int(own.argmin())
                    centroids[j] = x[far]
                    labels[far] = j
                else:
                    centroids[j] = _normalise(members.sum(axis=0, keepdims=True))[0]
        total = float((x @ centroids.T).max(axis=1).sum())
        if best is None or total > best[0] + 1e-12:
            best = (total, labels.copy(), centroids.copy())
    assert best is not None
    return best[1], best[2]


def silhouette_values(x: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Per-point cosine silhouette (singleton clusters score 0)."""
    n = x.shape[0]
    ids = np.unique(labels)
    dist = np.clip(1.0 - x @ x.T, 0.0, 2.0)
    onehot = (labels[:, None] == ids[None, :]).astype(np.float64)
    sums = dist @ onehot  # (n, clusters): total distance to each cluster
    sizes = onehot.sum(axis=0)
    own = np.searchsorted(ids, labels)
    own_size = sizes[own]
    a = sums[np.arange(n), own] / np.maximum(own_size - 1, 1)
    others = sums / np.maximum(sizes, 1)[None, :]
    others[np.arange(n), own] = np.inf
    b = others.min(axis=1)
    denom = np.maximum(a, b)
    s = np.where(denom > 1e-12, (b - a) / np.maximum(denom, 1e-12), 0.0)
    return np.where(own_size > 1, s, 0.0)


def choose_k(
    scores: Sequence[tuple[int, float]],
    distinct: Mapping[int, int] | None = None,
    tolerance: float = SILHOUETTE_TOLERANCE,
) -> int:
    """The k to publish (see module docs): among the ``k`` whose silhouette is within
    ``tolerance`` of the best, the one with the most distinct cluster names (``distinct[k]``),
    then the smallest k."""
    top = max(score for _, score in scores)
    close = [k for k, score in scores if score >= top - tolerance]
    return min(close, key=lambda k: (-(distinct or {}).get(k, 0), k))


def distinct_families(labels: np.ndarray, families: Sequence[str]) -> int:
    """How many different title families name the clusters of one fit."""
    named: set[str] = set()
    for j in np.unique(labels):
        counts = Counter(families[int(i)] for i in np.flatnonzero(labels == j))
        counts.pop(OTHER, None)
        if not counts:
            continue
        family, count = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if count / int((labels == j).sum()) >= NAMEABLE_SHARE:
            named.add(family)
    return len(named)


# --------------------------------------------------------------------------- description


def _skill_name(slug: str, names: Mapping[str, str] | None) -> str:
    if names is not None and slug in names:
        return names[slug]
    return skill_info(slug).display


def _lift(count_in: int, n_in: int, count_all: int, n_all: int) -> float:
    return ((count_in + 0.5) / (n_in + 1)) / ((count_all + 0.5) / (n_all + 1))


def _skill_table(
    members: Sequence[JobRecord], overall: Counter[str], n_all: int
) -> list[dict[str, Any]]:
    """Every skill of the cluster with count, share and lift, strongest signature first."""
    counts: Counter[str] = Counter(s for r in members for s in set(r.skills))
    rows = []
    for slug, count in counts.items():
        share = count / len(members)
        lift = _lift(count, len(members), overall[slug], n_all)
        rows.append(
            {
                "slug": slug,
                "count": count,
                "share": share,
                "lift": lift,
                "score": share * math.log(lift) if lift > 1 else 0.0,
            }
        )
    rows.sort(key=lambda r: (-r["score"], -r["count"], r["slug"]))
    return rows


def _signature(table: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r
        for r in table
        if r["count"] >= SIGNATURE_MIN_COUNT
        and r["share"] >= SIGNATURE_MIN_SHARE
        and r["lift"] >= SIGNATURE_MIN_LIFT
    ]


def _distinctive_skills(
    table: Sequence[dict[str, Any]],
    n_members: int,
    pool: Sequence[JobRecord],
    names: Mapping[str, str] | None,
) -> list[str]:
    """Display names of the skills that set a cluster apart from ``pool`` (its same-family
    siblings), best first: share >= ``NAME_SKILL_MIN_SHARE``, lift above 1, ranked by
    ``share * ln(lift)``."""
    pool_counts: Counter[str] = Counter(s for r in pool for s in set(r.skills))
    ranked: list[tuple[float, int, str]] = []
    for row in table:
        if row["share"] < NAME_SKILL_MIN_SHARE or row["count"] < SIGNATURE_MIN_COUNT:
            continue
        lift = _lift(row["count"], n_members, pool_counts[row["slug"]], len(pool))
        if lift > 1:
            ranked.append((row["share"] * math.log(lift), row["count"], row["slug"]))
    ranked.sort(key=lambda t: (-t[0], -t[1], t[2]))
    return [_skill_name(slug, names) for _, _, slug in ranked]


def _dominant_family(members: Sequence[JobRecord]) -> tuple[str | None, float]:
    """Most common recognised title family and its share of *all* members (the purity)."""
    counts = Counter(title_family(r.title) for r in members)
    counts.pop(OTHER, None)
    if not counts:
        return None, 0.0
    family, count = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return family, count / len(members)


def _top_titles(members: Sequence[JobRecord]) -> list[dict[str, Any]]:
    by_key: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    for r in members:
        cleaned = clean_title(r.title)
        key = cleaned.lower()
        by_key[key] += 1
        spellings.setdefault(key, Counter())[cleaned] += 1
    ranked = sorted(by_key.items(), key=lambda kv: (-kv[1], kv[0]))
    repeated = [kv for kv in ranked if kv[1] >= 2]
    chosen = repeated[:TOP_TITLES] or ranked[:3]
    out = []
    for key, count in chosen:
        spelling = sorted(spellings[key].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if spelling.isupper() and len(spelling) > 4:  # "DATA GOVERNANCE ANALYST"
            spelling = spelling.title()
        out.append({"title": spelling, "n": count})
    return out


def _examples(members: Sequence[JobRecord], vectors: np.ndarray, centroid: np.ndarray) -> list[str]:
    """The postings closest to the centroid, at most one per company."""
    order = np.argsort(-(vectors @ centroid), kind="stable")
    seen: set[str] = set()
    out: list[str] = []
    for i in order:
        rec = members[int(i)]
        company = rec.company.strip().lower()
        if company in seen:
            continue
        seen.add(company)
        out.append(rec.id)
        if len(out) == EXAMPLES:
            break
    return out


def _seniority(members: Sequence[JobRecord]) -> dict[str, int]:
    counts = Counter(r.seniority if r.seniority in LEVELS else "unspecified" for r in members)
    return {level: counts[level] for level in LEVELS if counts[level]}


def _typical_level(seniority: Mapping[str, int], n: int) -> str | None:
    """Most common stated level when at least a third of the postings state one."""
    stated = {level: seniority.get(level, 0) for level in STATED}
    if sum(stated.values()) * 3 < n:
        return None
    return sorted(stated.items(), key=lambda kv: (-kv[1], STATED.index(kv[0])))[0][0]


def _list_phrase(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _summary(
    n: int,
    share: float,
    level: str | None,
    skills: Sequence[str],
    median: int | None,
    salary_n: int,
) -> str:
    parts = [f"{n} postings ({round(share * 100)}% of data roles)"]
    parts.append(f"typically {level} level" if level else "seniority rarely stated")
    if skills:
        parts.append(f"signature skills {_list_phrase(skills[:3])}")
    if median is not None:
        parts.append(
            f"median advertised pay ${int(median / 1000 + 0.5)}k (from {salary_n} salaries)"
        )
    else:
        parts.append(f"too few salaries to quote a median ({salary_n})")
    return "; ".join(parts) + "."


def assign_names(
    families: Sequence[str | None],
    sizes: Sequence[int],
    skill_choices: Sequence[Sequence[str]],
) -> list[str]:
    """Unique names. ``families[i]`` is cluster i's dominant family (``None`` when no title
    was recognised), ``sizes[i]`` its size, ``skill_choices[i]`` its distinctive skill names,
    best first. Clusters sharing a base name (or without a family) are told apart by the first
    of their skills not yet used by a sibling, largest cluster first; if that runs out, by a
    number. The result never contains duplicates."""
    bases = [f or "Mixed data roles" for f in families]
    groups: dict[str, list[int]] = {}
    for i, base in enumerate(bases):
        groups.setdefault(base, []).append(i)
    names = list(bases)
    for base, idx in groups.items():
        if len(idx) == 1 and families[idx[0]] is not None:
            continue
        taken: set[str] = set()
        for i in sorted(idx, key=lambda j: (-sizes[j], j)):
            pick = next((s for s in skill_choices[i] if s not in taken), None)
            if pick is not None:
                taken.add(pick)
                names[i] = f"{base} ({pick})"
    seen: set[str] = set()
    for i, name in enumerate(names):
        candidate, number = name, 1
        while candidate in seen:
            number += 1
            candidate = f"{name} {number}"
        names[i] = candidate
        seen.add(candidate)
    return names


# --------------------------------------------------------------------------- PCA


def pca_2d(x: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """First two principal components of ``x`` scaled to a maximum absolute value of 1, and
    the share of variance they explain. Signs are fixed so the result is deterministic."""
    centred = x - x.mean(axis=0, keepdims=True)
    _, s, vt = np.linalg.svd(centred, full_matrices=False)
    comps = vt[:2].copy()
    for i in range(len(comps)):
        if comps[i][int(np.abs(comps[i]).argmax())] < 0:
            comps[i] = -comps[i]
    coords = centred @ comps.T
    peak = float(np.abs(coords).max()) if coords.size else 0.0
    if peak > 1e-12:
        coords = coords / peak
    var = s**2
    total = float(var.sum())
    explained = [float(v / total) if total > 0 else 0.0 for v in var[:2]]
    while len(explained) < 2:
        explained.append(0.0)
    if coords.shape[1] < 2:
        coords = np.hstack([coords, np.zeros((coords.shape[0], 2 - coords.shape[1]))])
    return coords, explained


# --------------------------------------------------------------------------- document


def _empty(n_jobs: int) -> dict[str, Any]:
    return {
        "version": 1,
        "method": {
            "algorithm": "spherical k-means (cosine), k-means++ seeding",
            "k": 0,
            "seed": SEED,
            "silhouette": None,
            "candidates": [],
            "n_jobs": n_jobs,
        },
        "archetypes": [],
        "points": [],
    }


def compute_archetypes(
    listed: Sequence[JobRecord],
    vectors: Mapping[str, Any],
    *,
    names: Mapping[str, str] | None = None,
    k_range: tuple[int, int] = (K_MIN, K_MAX),
) -> dict[str, Any]:
    """Return the ``archetypes.json`` document (PLAN.md section 6).

    ``listed`` are the active records, ``vectors`` the ``job_vectors.json`` document. Only
    ``role == "data"`` records that have a vector are clustered. With fewer than ``MIN_JOBS``
    of them the result has no archetypes and no points. ``k_range`` is the inclusive range of
    cluster counts to try (tests use a smaller one).
    """
    ids = list(vectors.get("ids", []))
    if not ids:
        return _empty(0)
    all_ids, matrix = embed.decode_job_vectors(dict(vectors))  # type: ignore[arg-type]
    row = {job_id: i for i, job_id in enumerate(all_ids)}
    records = sorted((r for r in listed if r.role == "data" and r.id in row), key=lambda r: r.id)
    n = len(records)
    if n < MIN_JOBS:
        return _empty(n)

    x = _normalise(matrix[[row[r.id] for r in records]].astype(np.float64))
    families = [title_family(r.title) for r in records]
    k_min, k_max = k_range[0], min(k_range[1], n // MIN_PER_CLUSTER)
    if k_max < k_min:
        return _empty(n)
    fits: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    scores: list[tuple[int, float]] = []
    distinct: dict[int, int] = {}
    for k in range(k_min, k_max + 1):
        labels, centroids = spherical_kmeans(x, k, seed=SEED)
        sil = silhouette_values(x, labels)
        fits[k] = (labels, centroids, sil)
        scores.append((k, float(sil.mean())))
        distinct[k] = distinct_families(labels, families)
    k = choose_k(scores, distinct)
    labels, centroids, sil = fits[k]

    overall: Counter[str] = Counter(s for r in records for s in set(r.skills))
    drafts: list[dict[str, Any]] = []
    for j in range(k):
        idx = np.flatnonzero(labels == j)
        if len(idx) == 0:
            continue
        members = [records[int(i)] for i in idx]
        table = _skill_table(members, overall, n)
        family, family_share = _dominant_family(members)
        salaries = [r.salary.annual_usd_mid for r in members if r.salary is not None]
        drafts.append(
            {
                "cluster": j,
                "members": members,
                "idx": idx,
                "table": table,
                "signature": _signature(table),
                "family": family,
                "family_share": family_share,
                "base": family if family_share >= NAMEABLE_SHARE else None,
                "salaries": salaries,
                "seniority": _seniority(members),
                "centroid": centroids[j],
                "silhouette": float(sil[idx].mean()),
            }
        )
    drafts.sort(key=lambda d: (-len(d["members"]), d["cluster"]))

    # Skills that set a cluster apart from the other clusters with the same base name (all
    # clustered postings when it has no sibling).
    distinctive: list[list[str]] = []
    for d in drafts:
        sibs = [o for o in drafts if o is not d and o["base"] == d["base"]]
        pool = [r for o in sibs for r in o["members"]] or [
            r for o in drafts if o is not d for r in o["members"]
        ]
        distinctive.append(_distinctive_skills(d["table"], len(d["members"]), pool, names))
    arch_names = assign_names(
        [d["base"] for d in drafts], [len(d["members"]) for d in drafts], distinctive
    )

    archetypes: list[dict[str, Any]] = []
    label_to_id: dict[int, str] = {}
    for d, name in zip(drafts, arch_names, strict=True):
        members: list[JobRecord] = d["members"]
        size = len(members)
        median = (
            round(statistics.median(d["salaries"])) if len(d["salaries"]) >= MIN_SALARY_N else None
        )
        top = d["signature"][:TOP_SKILLS]
        level = _typical_level(d["seniority"], size)
        arch_id = slugify(name)
        label_to_id[d["cluster"]] = arch_id
        archetypes.append(
            {
                "id": arch_id,
                "name": name,
                "summary": _summary(
                    size,
                    size / n,
                    level,
                    [_skill_name(r["slug"], names) for r in top],
                    median,
                    len(d["salaries"]),
                ),
                "family": d["family"],
                "family_share": round(d["family_share"], 3),
                "n": size,
                "share": round(size / n, 4),
                "median_salary_usd": median,
                "salary_n": len(d["salaries"]),
                "silhouette": round(d["silhouette"], 3),
                "seniority": d["seniority"],
                "top_skills": [
                    {
                        "slug": r["slug"],
                        "name": _skill_name(r["slug"], names),
                        "share": round(r["share"], 3),
                        "lift": round(r["lift"], 2),
                    }
                    for r in top
                ],
                "top_titles": _top_titles(members),
                "example_job_ids": _examples(members, x[d["idx"]], d["centroid"]),
                "centroid": [round(float(v), 4) for v in d["centroid"]],
            }
        )

    coords, explained = pca_2d(x)
    points = [
        {
            "id": rec.id,
            "a": label_to_id[int(labels[i])],
            "x": round(float(coords[i, 0]), 3),
            "y": round(float(coords[i, 1]), 3),
        }
        for i, rec in enumerate(records)
    ]
    return {
        "version": 1,
        "method": {
            "algorithm": (
                f"spherical k-means (cosine), k-means++ seeding, best of {RESTARTS} restarts; "
                f"k = smallest value within {SILHOUETTE_TOLERANCE} of the best mean silhouette"
            ),
            "k": len(archetypes),
            "seed": SEED,
            "silhouette": round(dict(scores)[k], 4),
            "candidates": [{"k": c, "silhouette": round(s, 4)} for c, s in scores],
            "n_jobs": n,
            "pca_variance": [round(v, 3) for v in explained],
        },
        "archetypes": archetypes,
        "points": points,
    }
