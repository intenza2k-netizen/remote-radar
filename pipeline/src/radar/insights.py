"""Analytical insight documents and the skill vocabulary (PLAN.md section 5).

``compute_insights`` and ``compute_companies`` are pure functions over the window population
(the same ``JobRecord`` list the dashboard statistics use), so they are unit tested without a
database. ``build_skill_vocab`` turns ``skills/aliases.yaml`` into the pattern list the
browser uses to read skills out of a CV.

insights.json
    ``skill_premium``  For every skill with at least ``MIN_PREMIUM_WITH`` salaried postings
        (and ``MIN_PREMIUM_WITHOUT`` salaried postings without it): median annual USD with and
        without the skill, the difference of medians, and a 95% bootstrap interval for that
        difference (``BOOTSTRAPS`` resamples of each group, fixed seed ``SEED``, one RNG
        stream per skill so results do not shift when other skills appear or disappear).
        This is an association, not a causal effect: skills travel with seniority and role.
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
import zlib
from collections import Counter
from collections.abc import Iterable, Sequence
from itertools import combinations
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml

from radar.dedupe import normalize_company
from radar.skills import normalize as _skills_module
from radar.skills import skill_info

if TYPE_CHECKING:
    from radar.aggregate import JobRecord

SEED = 20261106
BOOTSTRAPS = 1000
MIN_PREMIUM_WITH = 15
MIN_PREMIUM_WITHOUT = 10
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


def _skill_name(slug: str) -> str:
    return skill_info(slug).display


def _median(values: Sequence[float]) -> int:
    return round(float(np.median(values)))


# --------------------------------------------------------------------------- skill premium


def skill_premium(
    population: Sequence[JobRecord],
    *,
    seed: int = SEED,
    n_boot: int = BOOTSTRAPS,
    min_with: int = MIN_PREMIUM_WITH,
    min_without: int = MIN_PREMIUM_WITHOUT,
) -> list[dict[str, Any]]:
    """Median salary with vs without each skill, with a bootstrap 95% CI on the difference."""
    salaried = [r for r in population if r.salary is not None]
    if not salaried:
        return []
    values = np.array([r.salary.annual_usd_mid for r in salaried], dtype=np.float64)
    counts = Counter(slug for r in salaried for slug in set(r.skills))
    rows: list[dict[str, Any]] = []
    for slug in sorted(s for s, c in counts.items() if c >= min_with):
        mask = np.array([slug in r.skills for r in salaried])
        with_, without = values[mask], values[~mask]
        if len(without) < min_without:
            continue
        rng = np.random.default_rng([seed, zlib.crc32(slug.encode("utf-8"))])
        boot_with = np.median(with_[rng.integers(0, len(with_), (n_boot, len(with_)))], axis=1)
        boot_without = np.median(
            without[rng.integers(0, len(without), (n_boot, len(without)))], axis=1
        )
        low, high = np.percentile(boot_with - boot_without, [2.5, 97.5])
        median_with, median_without = _median(with_), _median(without)
        rows.append(
            {
                "slug": slug,
                "name": _skill_name(slug),
                "n_with": int(len(with_)),
                "n_without": int(len(without)),
                "median_with": median_with,
                "median_without": median_without,
                "diff": median_with - median_without,
                "ci_low": round(float(low)),
                "ci_high": round(float(high)),
            }
        )
    rows.sort(key=lambda r: (-r["diff"], r["slug"]))
    return rows


# --------------------------------------------------------------------------- seniority lift


def seniority_lift(population: Sequence[JobRecord]) -> list[dict[str, Any]]:
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
                        "name": _skill_name(slug),
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


def skill_graph(population: Sequence[JobRecord]) -> dict[str, list[dict[str, Any]]]:
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
            "name": _skill_name(slug),
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


def role_skills(population: Sequence[JobRecord]) -> list[dict[str, Any]]:
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
                    {"slug": s, "name": _skill_name(s), "share": round(c / len(recs), 4)}
                    for s, c in top
                ],
            }
        )
    return out


def compute_insights(population: Sequence[JobRecord]) -> dict[str, Any]:
    """The ``insights.json`` document."""
    return {
        "skill_premium": skill_premium(population),
        "seniority_lift": seniority_lift(population),
        "skill_graph": skill_graph(population),
        "role_skills": role_skills(population),
    }


# --------------------------------------------------------------------------- companies


def company_slug(name: str) -> str:
    """Lowercase, ASCII-folded, runs of non-alphanumerics become one hyphen."""
    folded = unicodedata.normalize("NFKD", name)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "company"


def compute_companies(population: Sequence[JobRecord]) -> list[dict[str, Any]]:
    """The ``companies.json`` document: one row per company, most postings first."""
    groups: dict[str, list[JobRecord]] = {}
    for rec in population:
        key = normalize_company(rec.company) or rec.company.strip().lower()
        groups.setdefault(key, []).append(rec)

    rows: list[dict[str, Any]] = []
    for recs in groups.values():
        names = Counter(r.company.strip() for r in recs)
        name = sorted(names.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
        ordered = sorted(recs, key=lambda r: (r.posted_at, r.id), reverse=True)
        skill_counts = Counter(s for r in recs for s in set(r.skills))
        top_skills = sorted(skill_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        salaries = [r.salary.annual_usd_mid for r in recs if r.salary is not None]
        rows.append(
            {
                "slug": "",
                "name": name,
                "jobs": len(recs),
                "roles": dict(
                    sorted(Counter(r.role for r in recs).items(), key=lambda kv: (-kv[1], kv[0]))
                ),
                "seniority": dict(
                    sorted(
                        Counter(r.seniority for r in recs).items(), key=lambda kv: (-kv[1], kv[0])
                    )
                ),
                "top_skills": [
                    {"slug": s, "name": _skill_name(s), "count": c}
                    for s, c in top_skills[:COMPANY_TOP_SKILLS]
                ],
                "median_salary_usd": _median(salaries) if salaries else None,
                "salary_n": len(salaries),
                "sources": sorted({r.source for r in recs}),
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
