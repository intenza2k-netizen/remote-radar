"""Analytical insight documents and the skill vocabulary (PLAN.md section 5).

``compute_insights`` and ``compute_companies`` are pure functions over the window population
(the same ``JobRecord`` list the dashboard statistics use), so they are unit tested without a
database. ``build_skill_vocab`` turns ``skills/aliases.yaml`` into the pattern list the
browser uses to read skills out of a CV.

insights.json
    ``skill_premium``  For every skill with at least ``MIN_PREMIUM_WITH`` salaried postings
        from at least ``MIN_PREMIUM_COMPANIES`` distinct companies (and ``MIN_PREMIUM_WITHOUT``
        salaried postings without it): median annual USD with and without the skill, the
        difference of medians, and a 95% interval for that difference. Postings of one company
        are not independent (a company board brings dozens of near-identical roles and pay
        bands), so the interval is a *cluster* bootstrap: each of the ``BOOTSTRAPS`` resamples
        draws companies with replacement and keeps all of a drawn company's salaried postings.
        The draws come from one RNG seeded with ``SEED`` and depend only on the set of
        companies, so results are deterministic and do not shift when other skills appear or
        disappear. Rows carry ``n_companies`` (distinct companies behind ``n_with``) and are
        sorted by the interval's lower bound (the distance of the interval from zero for a
        negative gap), so a fragile large estimate cannot lead.
        The raw difference mostly says which roles and places ask for a skill, so every row
        also carries a role-, seniority- and region-adjusted estimate: least squares of
        ``log(salary)`` on the skill indicator plus fixed-effect dummies for role (10
        categories), seniority (7 levels, ``unspecified`` included) and region group (7 groups
        built from the canonical ``remote_regions`` by ``regions.region_group``: us_canada,
        europe, latam, apac, worldwide, other_or_mixed, unknown; the rules are in that
        function's docstring). The coefficient ``b`` is reported as ``adj_pct =
        100 * (exp(b) - 1)``: postings that mention the skill advertise that much more than
        postings with the same role, seniority and region group that do not. ``adj_usd`` is
        that effect at the pay level of the postings that list the skill:
        ``median_with - median_with / (1 + adj_pct / 100)``, i.e. what those postings would
        advertise without the skill, all else equal, subtracted from what they advertise.
        Each skill is fitted on its own (not jointly with the other skills). To stay fast the fit
        uses the Frisch-Waugh-Lovell theorem: per resample, ``log(salary)`` and the whole
        skill-indicator matrix are projected onto the fixed-effect design once (weighted by
        that resample's company multiplicities, pseudo-inverse for rank safety), and each
        skill's ``b`` is ``sum(w rs ry) / sum(w rs^2)`` on the residuals. The adjusted interval
        (``adj_ci_low_pct``, ``adj_ci_high_pct``) is the 2.5/97.5 percentile of ``b`` over the
        *same* company resamples as the raw interval, transformed to percent. A skill with no
        variation left within role, seniority and region group (``sum(w rs^2)`` about zero in
        the point fit, e.g. it only occurs in one role and in all of that role's postings)
        keeps its raw fields and gets ``null`` adjusted fields. Rows are sorted by the adjusted
        interval's distance from zero (``adj_ci_low_pct`` for a positive estimate,
        ``-adj_ci_high_pct`` for a negative one), rows without an adjusted estimate last, by
        the raw rule. Still an association, not a causal effect: company, the other skills of a
        posting and the exact location (country, city, time zone) are not controlled for.
    ``seniority_lift``  Per role with at least ``MIN_ROLE_POSTINGS`` postings: how much more
        often each skill appears in senior (senior, lead, principal) than in junior (intern,
        junior, mid) postings. Postings with unspecified seniority are in neither group.
        ``lift`` = smoothed senior share / smoothed junior share, with add-0.5 smoothing
        ``(count + 0.5) / (n + 1)`` so a skill absent from one side does not give infinity.
        A skill needs at least ``MIN_LIFT_SUPPORT`` postings across both groups; the top
        ``LIFT_TOP`` by lift are kept. Roles where a group has fewer than ``MIN_GROUP``
        postings keep their counts but get ``skills: []``.
    ``skill_graph``  Top ``GRAPH_NODES`` skills by posting count; edges are pairs that
        co-occur in at least ``GRAPH_MIN_EDGE`` postings, ranked by pointwise mutual
        information ``log2(P(a,b) / (P(a) P(b)))`` and capped at ``GRAPH_MAX_EDGES``.
    ``role_skills``  Per role (``MIN_ROLE_SKILLS`` or more postings) the ``ROLE_SKILLS_TOP``
        skills with the highest share of that role's postings.

companies.json
    One row per company (grouped by ``dedupe.normalize_company`` so "Acme GmbH" and "ACME"
    are one company), sorted by postings. ``slug`` is the lowercase ASCII-folded name with
    runs of other characters turned into hyphens; collisions get ``-2``, ``-3``. ``job_ids``
    match ``jobs.json``, newest first. ``salary_n`` (additive) is the number of postings
    behind ``median_salary_usd``, which is published from one salaried posting upwards.

skill_vocab.json (``build_skill_vocab``)
    ``patterns`` are the lowercase display name, the slug with hyphens as spaces and every
    alias. Matching in the browser should be on word boundaries, with ``+``, ``#`` and ``.``
    kept inside tokens (``c++``, ``c#``, ``.net``).

    ``strict_patterns`` lists the patterns that are risky in free prose; the browser must
    only accept those with case or context rules (e.g. the CV text contains ``Go`` or ``R``
    capitalised, next to other skills, or inside a skills section). A pattern is strict when
    * it has at most two letters or digits and no ``+`` or ``#`` (``go``, ``r``, ``c``,
      ``ai``, ``ml``, ``ts``, ``js``, ``py``, ``bi``, ``qa``, ``k6``; ``c#`` and ``c++``
      are distinctive and stay loose), or
    * it is one of ``AMBIGUOUS`` (known clashes such as ``sem``, ``rest``, ``spark``,
      ``excel``, ``swift``, ``make``, ``monday``), or
    * it is a plain English word that is also a skill alias (``security``, ``growth``,
      ``documentation``, ``testing``, ``analytics``, ``writing``; see ``COMMON_WORDS``).
    ``strict`` is true when the skill's own name (display name or slug words) is strict, i.e.
    the skill cannot be recognised from its main spelling without the extra rules; skills
    like Python or Machine Learning are not strict, although they have strict aliases
    (``py``, ``ml``), which is why ``strict_patterns`` exists.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml

from radar.dedupe import normalize_company
from radar.regions import region_group
from radar.skills import normalize as _skills_module
from radar.skills import skill_info

if TYPE_CHECKING:
    from radar.aggregate import JobRecord

SEED = 20261106
BOOTSTRAPS = 1000
MIN_PREMIUM_WITH = 15
MIN_PREMIUM_WITHOUT = 10
MIN_PREMIUM_COMPANIES = 5  # distinct companies among the with-skill salaried postings
# Share of sum(w s) that sum(w rs^2) must exceed: below it nothing varies within role/seniority.
DEGENERATE_TOL = 1e-7
MIN_ROLE_POSTINGS = 30
MIN_GROUP = 5
MIN_LIFT_SUPPORT = 3
LIFT_TOP = 10
GRAPH_NODES = 80
GRAPH_MIN_NODE_COUNT = 3
GRAPH_MIN_EDGE = 3
GRAPH_MAX_EDGES = 250
MIN_ROLE_SKILLS = 5
ROLE_SKILLS_TOP = 12
COMPANY_TOP_SKILLS = 8
SENIOR = frozenset({"senior", "lead", "principal"})
JUNIOR = frozenset({"intern", "junior", "mid"})


Names = Mapping[str, str]


def _skill_name(slug: str, names: Names | None = None) -> str:
    """Display name: the publish step's derived name when given, else the registry's."""
    if names is not None and slug in names:
        return names[slug]
    return skill_info(slug).display


def _median(values: Sequence[float]) -> int:
    return round(float(np.median(values)))


# --------------------------------------------------------------------------- skill premium


def _company_key(rec: JobRecord) -> str:
    return normalize_company(rec.company) or rec.company.strip().lower()


def _cluster_medians(weights: np.ndarray, sorted_values: np.ndarray) -> np.ndarray:
    """Weighted median per row. ``weights`` is (replicates, postings) in ascending value order;
    a posting with weight w counts w times. Equals ``np.median`` of the expanded sample (the
    mean of the two middle values when the total is even). Rows with no weight give NaN."""
    cum = np.cumsum(weights, axis=1)
    total = cum[:, -1]
    lower = (total + 1) // 2  # rank of the lower middle value
    upper = total // 2 + 1  # rank of the upper middle value
    i_lower = (cum >= lower[:, None]).argmax(axis=1)
    i_upper = (cum >= upper[:, None]).argmax(axis=1)
    out = (sorted_values[i_lower] + sorted_values[i_upper]) / 2
    return np.where(total > 0, out, np.nan)


def skill_premium(
    population: Sequence[JobRecord],
    *,
    seed: int = SEED,
    n_boot: int = BOOTSTRAPS,
    min_with: int = MIN_PREMIUM_WITH,
    min_without: int = MIN_PREMIUM_WITHOUT,
    min_companies: int = MIN_PREMIUM_COMPANIES,
    names: Names | None = None,
) -> list[dict[str, Any]]:
    """Median salary with vs without each skill, with a company-cluster bootstrap 95% CI on
    the difference. Sorted by the interval's lower bound (see the module docstring)."""
    salaried = [r for r in population if r.salary is not None]
    if not salaried:
        return []
    # Ascending salary order, so weighted medians are a cumulative-sum lookup.
    salaried.sort(key=lambda r: (r.salary.annual_usd_mid, r.id))
    values = np.array([r.salary.annual_usd_mid for r in salaried], dtype=np.float64)
    companies = sorted({_company_key(r) for r in salaried})
    company_index = {c: i for i, c in enumerate(companies)}
    posting_company = np.array([company_index[_company_key(r)] for r in salaried])

    counts = Counter(slug for r in salaried for slug in set(r.skills))
    candidates = sorted(s for s, c in counts.items() if c >= min_with)
    if not candidates:
        return []
    # One set of company resamples for every skill: draws depend only on the company list.
    rng = np.random.default_rng([seed, len(companies)])
    draws = rng.multinomial(len(companies), np.full(len(companies), 1 / len(companies)), n_boot)
    weights = draws[:, posting_company].astype(np.int64)  # (replicates, postings)

    rows: list[dict[str, Any]] = []
    masks: list[np.ndarray] = []
    for slug in candidates:
        mask = np.array([slug in r.skills for r in salaried])
        with_, without = values[mask], values[~mask]
        n_companies = len({_company_key(r) for r, m in zip(salaried, mask, strict=True) if m})
        if len(without) < min_without or n_companies < min_companies:
            continue
        boot_diff = _cluster_medians(weights * mask, values) - _cluster_medians(
            weights * ~mask, values
        )
        diffs = boot_diff[np.isfinite(boot_diff)]
        if len(diffs) < n_boot // 2:  # the skill vanished from most resamples: no interval
            continue
        low, high = np.percentile(diffs, [2.5, 97.5])
        median_with, median_without = _median(with_), _median(without)
        rows.append(
            {
                "slug": slug,
                "name": _skill_name(slug, names),
                "n_with": int(len(with_)),
                "n_without": int(len(without)),
                "n_companies": n_companies,
                "median_with": median_with,
                "median_without": median_without,
                "diff": median_with - median_without,
                "ci_low": round(float(low)),
                "ci_high": round(float(high)),
            }
        )
        masks.append(mask)

    if rows:
        indicators = np.column_stack(masks).astype(np.float64)
        design = _fixed_effects_design(salaried)
        betas = _adjusted_coefficients(np.log(values), indicators, design, weights)
        for row, boot in zip(rows, betas, strict=True):
            row.update(_adjusted_fields(boot, row["median_with"]))
    rows.sort(key=_row_order)
    return rows


def _certain_gap(row: dict[str, Any]) -> float:
    """How far the interval stays from zero in the direction of the gap: ``ci_low`` for a
    positive gap, ``-ci_high`` for a negative one (negative when the interval crosses zero)."""
    return row["ci_low"] if row["diff"] >= 0 else -row["ci_high"]


def _certain_adj_gap(row: dict[str, Any]) -> float:
    """``_certain_gap`` on the adjusted percentages (the row must have an adjusted estimate)."""
    return row["adj_ci_low_pct"] if row["adj_pct"] >= 0 else -row["adj_ci_high_pct"]


def _row_order(row: dict[str, Any]) -> tuple[Any, ...]:
    """Adjusted rows first, furthest from zero first; rows without an adjusted estimate follow,
    ordered by the raw interval the same way."""
    if row["adj_pct"] is not None:
        return (0, -_certain_adj_gap(row), -row["adj_pct"], row["slug"])
    return (1, -_certain_gap(row), -row["diff"], row["slug"])


# ----------------------------------------- role-, seniority- and region-adjusted premium


def _fixed_effects_design(salaried: Sequence[JobRecord]) -> np.ndarray:
    """Intercept plus a dummy for every role, seniority and region-group level except the most
    common one of each (the reference level). Levels with a single posting are kept: the
    pseudo-inverse in ``_adjusted_coefficients`` makes a rank-deficient design harmless."""
    columns = [np.ones(len(salaried))]
    for labels in (
        [r.role for r in salaried],
        [r.seniority for r in salaried],
        [region_group(r.remote_regions) for r in salaried],
    ):
        levels = sorted(set(labels), key=lambda lv: (-labels.count(lv), lv))
        for level in levels[1:]:
            columns.append(np.array([lab == level for lab in labels], dtype=np.float64))
    return np.column_stack(columns)


def _adjusted_coefficients(
    log_y: np.ndarray,
    skills: np.ndarray,
    design: np.ndarray,
    weights: np.ndarray,
    *,
    block: int = 48,
) -> np.ndarray:
    """Skill coefficients of ``log y ~ skill + role + seniority + region group`` for the point
    sample and every resample, one skill at a time, via the Frisch-Waugh-Lovell theorem.

    ``weights`` is (replicates, postings) company multiplicity; the function prepends an
    all-ones row for the point fit. Per replicate the fixed effects are projected out of
    ``log y`` and of every skill indicator with that replicate's weights (``pinv`` keeps it
    stable when a role or seniority level is absent from a resample); the skill coefficient is
    ``sum(w rs ry) / sum(w rs^2)`` on the residuals ``rs`` and ``ry``. Because the residuals are
    weighted-orthogonal to the design, this needs only the cross-products ``X'Wz`` and
    ``z'Wz'`` and never builds a residual matrix. Returns (skills, 1 + replicates): column 0 is
    the point estimate; NaN where ``sum(w rs^2)`` is (relatively) zero, i.e. the skill has no
    variation left within role, seniority and region group."""
    n, p = design.shape
    w = np.vstack([np.ones(n), weights.astype(np.float64)])  # (1 + B, n)
    y = log_y - log_y.mean()  # centring only limits rounding error; the intercept absorbs it
    xx = (design[:, :, None] * design[:, None, :]).reshape(n, p * p)
    a = (w @ xx).reshape(-1, p, p)  # X'WX per replicate
    a_inv = np.linalg.pinv(a, rcond=1e-10, hermitian=True)
    beta_y = np.einsum("bpq,bq->bp", a_inv, w @ (design * y[:, None]))  # (1 + B, p)

    out = np.empty((skills.shape[1], w.shape[0]))
    for start in range(0, skills.shape[1], block):
        s = skills[:, start : start + block]
        k = s.shape[1]
        xs = (w @ (design[:, :, None] * s[:, None, :]).reshape(n, p * k)).reshape(-1, p, k)
        s_mass = w @ s  # sum(w s) = sum(w s^2) for 0/1 indicators
        num = w @ (s * y[:, None]) - np.einsum("bpk,bp->bk", xs, beta_y)
        den = s_mass - np.einsum("bpk,bpk->bk", xs, a_inv @ xs)
        usable = den > DEGENERATE_TOL * s_mass
        out[start : start + k] = np.where(usable, num / np.where(usable, den, 1.0), np.nan).T
    return out


def _adjusted_fields(boot: np.ndarray, median_with: float) -> dict[str, Any]:
    """Row fields from one skill's coefficients (index 0 = point fit, the rest = resamples).
    ``adj_usd`` is the effect at the pay level of the postings that list the skill: what they
    advertise (``median_with``) minus what they would advertise without it."""
    empty: dict[str, Any] = {
        "adj_pct": None,
        "adj_usd": None,
        "adj_ci_low_pct": None,
        "adj_ci_high_pct": None,
    }
    point, resampled = boot[0], boot[1:]
    resampled = resampled[np.isfinite(resampled)]
    if not np.isfinite(point) or len(resampled) < max(1, (len(boot) - 1) // 2):
        return empty
    low, high = np.percentile(resampled, [2.5, 97.5])
    pct = 100 * np.expm1(point)
    return {
        "adj_pct": round(float(pct), 1),
        "adj_usd": round(median_with - median_with / (1 + float(pct) / 100)),
        "adj_ci_low_pct": round(float(100 * np.expm1(low)), 1),
        "adj_ci_high_pct": round(float(100 * np.expm1(high)), 1),
    }


# --------------------------------------------------------------------------- seniority lift


def seniority_lift(
    population: Sequence[JobRecord], *, names: Names | None = None
) -> list[dict[str, Any]]:
    """Per role: skills that are much more common in senior than in junior postings."""
    by_role: dict[str, list[JobRecord]] = {}
    for rec in population:
        by_role.setdefault(rec.role, []).append(rec)
    out: list[dict[str, Any]] = []
    for role, recs in sorted(by_role.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(recs) < MIN_ROLE_POSTINGS:
            continue
        senior = [r for r in recs if r.seniority in SENIOR]
        junior = [r for r in recs if r.seniority in JUNIOR]
        skills: list[dict[str, Any]] = []
        if len(senior) >= MIN_GROUP and len(junior) >= MIN_GROUP:
            c_senior = Counter(s for r in senior for s in set(r.skills))
            c_junior = Counter(s for r in junior for s in set(r.skills))
            for slug in set(c_senior) | set(c_junior):
                if c_senior[slug] + c_junior[slug] < MIN_LIFT_SUPPORT:
                    continue
                share_senior = (c_senior[slug] + 0.5) / (len(senior) + 1)
                share_junior = (c_junior[slug] + 0.5) / (len(junior) + 1)
                skills.append(
                    {
                        "slug": slug,
                        "name": _skill_name(slug, names),
                        "share_senior": round(c_senior[slug] / len(senior), 4),
                        "share_junior": round(c_junior[slug] / len(junior), 4),
                        "lift": round(share_senior / share_junior, 2),
                    }
                )
            skills.sort(key=lambda s: (-s["lift"], -s["share_senior"], s["slug"]))
            skills = skills[:LIFT_TOP]
        out.append(
            {"role": role, "n_senior": len(senior), "n_junior": len(junior), "skills": skills}
        )
    return out


# --------------------------------------------------------------------------- skill graph


def skill_graph(
    population: Sequence[JobRecord], *, names: Names | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Top skills as nodes, co-occurring pairs ranked by PMI as edges."""
    n = len(population)
    counts = Counter(slug for r in population for slug in set(r.skills))
    ranked = sorted(
        ((s, c) for s, c in counts.items() if c >= GRAPH_MIN_NODE_COUNT),
        key=lambda kv: (-kv[1], kv[0]),
    )[:GRAPH_NODES]
    nodes = [
        {
            "slug": slug,
            "name": _skill_name(slug, names),
            "category": skill_info(slug).category,
            "count": count,
        }
        for slug, count in ranked
    ]
    keep = {slug for slug, _ in ranked}
    pairs: Counter[tuple[str, str]] = Counter()
    for rec in population:
        present = sorted(keep.intersection(rec.skills))
        pairs.update(combinations(present, 2))
    edges: list[dict[str, Any]] = []
    for (a, b), count in pairs.items():
        if count < GRAPH_MIN_EDGE:
            continue
        pmi = math.log2(count * n / (counts[a] * counts[b]))
        edges.append({"a": a, "b": b, "count": count, "pmi": round(pmi, 3)})
    edges.sort(key=lambda e: (-e["pmi"], -e["count"], e["a"], e["b"]))
    return {"nodes": nodes, "edges": edges[:GRAPH_MAX_EDGES]}


# --------------------------------------------------------------------------- role skills


def role_skills(
    population: Sequence[JobRecord], *, names: Names | None = None
) -> list[dict[str, Any]]:
    by_role: dict[str, list[JobRecord]] = {}
    for rec in population:
        by_role.setdefault(rec.role, []).append(rec)
    out: list[dict[str, Any]] = []
    for role, recs in sorted(by_role.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(recs) < MIN_ROLE_SKILLS:
            continue
        counts = Counter(s for r in recs for s in set(r.skills))
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:ROLE_SKILLS_TOP]
        out.append(
            {
                "role": role,
                "n": len(recs),
                "top": [
                    {"slug": s, "name": _skill_name(s, names), "share": round(c / len(recs), 4)}
                    for s, c in top
                ],
            }
        )
    return out


def compute_insights(
    population: Sequence[JobRecord], *, names: Names | None = None
) -> dict[str, Any]:
    """The ``insights.json`` document. ``names`` overrides skill display names (slug -> name)."""
    return {
        "skill_premium": skill_premium(population, names=names),
        "seniority_lift": seniority_lift(population, names=names),
        "skill_graph": skill_graph(population, names=names),
        "role_skills": role_skills(population, names=names),
    }


# --------------------------------------------------------------------------- companies


def company_slug(name: str) -> str:
    """Lowercase, ASCII-folded, runs of non-alphanumerics become one hyphen."""
    folded = unicodedata.normalize("NFKD", name)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "company"


def compute_companies(
    population: Sequence[JobRecord],
    listed: Sequence[JobRecord] | None = None,
    *,
    names: Names | None = None,
) -> list[dict[str, Any]]:
    """The ``companies.json`` document: one row per company with at least one listed job,
    most listed postings first.

    ``listed`` is the published job list (default: the active records of ``population``).
    ``jobs`` and everything derived from the job list (``job_ids``, roles, seniority, top
    skills, salary, sources) cover those jobs only; ``jobs_total`` is the company's posting
    count over the window plus the list, expired ones included.
    """
    if listed is None:
        listed = [r for r in population if r.active]
    groups: dict[str, list[JobRecord]] = {}
    seen: dict[str, set[str]] = {}
    for rec in [*population, *listed]:
        key = normalize_company(rec.company) or rec.company.strip().lower()
        seen.setdefault(key, set()).add(rec.id)
    for rec in listed:
        key = normalize_company(rec.company) or rec.company.strip().lower()
        groups.setdefault(key, []).append(rec)
    totals = {key: len(ids) for key, ids in seen.items()}

    rows: list[dict[str, Any]] = []
    for key, recs in groups.items():
        spellings = Counter(r.company.strip() for r in recs)
        name = sorted(spellings.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
        ordered = sorted(recs, key=lambda r: (r.posted_at, r.id), reverse=True)
        skill_counts = Counter(s for r in recs for s in set(r.skills))
        top_skills = sorted(skill_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        salaries = [r.salary.annual_usd_mid for r in recs if r.salary is not None]
        rows.append(
            {
                "slug": "",
                "name": name,
                "jobs": len(recs),
                "jobs_total": totals[key],
                "roles": dict(
                    sorted(Counter(r.role for r in recs).items(), key=lambda kv: (-kv[1], kv[0]))
                ),
                "seniority": dict(
                    sorted(
                        Counter(r.seniority for r in recs).items(), key=lambda kv: (-kv[1], kv[0])
                    )
                ),
                "top_skills": [
                    {"slug": s, "name": _skill_name(s, names), "count": c}
                    for s, c in top_skills[:COMPANY_TOP_SKILLS]
                ],
                "median_salary_usd": _median(salaries) if salaries else None,
                "salary_n": len(salaries),
                "sources": sorted({r.listed_source for r in recs}),
                "job_ids": [r.id for r in ordered],
            }
        )
    rows.sort(key=lambda r: (-r["jobs"], r["name"].lower(), r["name"]))
    used: set[str] = set()
    for row in rows:
        base = company_slug(row["name"])
        slug, suffix = base, 2
        while slug in used:
            slug = f"{base}-{suffix}"
            suffix += 1
        used.add(slug)
        row["slug"] = slug
    return rows


# --------------------------------------------------------------------------- skill vocabulary

# Known clashes with ordinary words, abbreviations or other products.
AMBIGUOUS = frozenset(
    {
        "go",
        "sem",
        "ps",
        "ae",
        "rest",
        "spark",
        "excel",
        "swift",
        "make",
        "monday",
        "notion",
        "unity",
        "linear",
        "express",
        "react",
        "dash",
        "liquid",
        "beam",
        "chef",
        "puppet",
        "helm",
        "flux",
        "argo",
        "bubble",
        "sentry",
        "shell",
        "elastic",
        "confluent",
        "phoenix",
        "spring",
        "lean",
        "coda",
        "gong",
        "soc",
        "sso",
        "tex",
        "apex",
        "outreach",
        "segment",
        "powercenter",
    }
)
# Plain English words that are aliases of business or engineering skills.
COMMON_WORDS = frozenset(
    {
        "ads",
        "advertising",
        "affiliates",
        "alliances",
        "analysis",
        "analytics",
        "annotation",
        "architecture",
        "automation",
        "automations",
        "cloud",
        "communications",
        "containers",
        "databases",
        "documentation",
        "docs",
        "editing",
        "embedded",
        "experimentation",
        "firewall",
        "firewalls",
        "growth",
        "helpdesk",
        "influencer",
        "labeling",
        "labelling",
        "logging",
        "math",
        "maths",
        "mobile",
        "moderation",
        "monitoring",
        "newsletter",
        "newsletters",
        "orchestration",
        "partnerships",
        "positioning",
        "prompting",
        "prompts",
        "quality assurance",
        "recommender",
        "reporting",
        "requirements",
        "routing",
        "security",
        "speech",
        "sprints",
        "stats",
        "surveys",
        "testing",
        "ticketing",
        "tracing",
        "troubleshooting",
        "writing",
    }
)


def _alnum_length(pattern: str) -> int:
    return len(re.sub(r"[^a-z0-9]", "", pattern))


def is_strict_pattern(pattern: str) -> bool:
    """True when ``pattern`` is risky in free prose (see the module docstring)."""
    p = pattern.lower().strip()
    if "+" in p or "#" in p:
        return False  # c++, c#, f#, c/c++ are distinctive
    return _alnum_length(p) <= 2 or p in AMBIGUOUS or p in COMMON_WORDS


def _raw_aliases() -> dict[str, list[str]]:
    """slug -> aliases from aliases.yaml (the registry only keeps a merged lookup)."""
    data = yaml.safe_load(_skills_module._ALIASES_PATH.read_text(encoding="utf-8")) or {}
    return {
        str(slug): [str(a) for a in ((spec or {}).get("aliases") or [])]
        for slug, spec in (data.get("skills") or {}).items()
    }


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        item = re.sub(r"\s+", " ", item.strip().lower())
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def build_skill_vocab(aliases: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """The ``skill_vocab.json`` document: every canonical skill with its patterns."""
    aliases = _raw_aliases() if aliases is None else aliases
    out: list[dict[str, Any]] = []
    for slug, alias_list in aliases.items():
        info = skill_info(slug)
        slug_words = slug.replace("-", " ")
        patterns = _unique([info.display, slug_words, *alias_list])
        strict_patterns = [p for p in patterns if is_strict_pattern(p)]
        main_names = _unique([info.display, slug_words])
        out.append(
            {
                "slug": slug,
                "name": info.display,
                "category": info.category,
                "patterns": patterns,
                "strict": any(is_strict_pattern(p) for p in main_names),
                "strict_patterns": strict_patterns,
            }
        )
    return out
