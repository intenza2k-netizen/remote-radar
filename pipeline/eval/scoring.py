"""Pure scoring functions for the extraction eval (no I/O, no model calls).

Conventions (also stated in ``report.md``):

* A failed extraction (``ok=False``) is scored as an empty / wrong prediction, never dropped,
  so a model that fails on a job is penalised for it.
* Skills are compared as sets of canonical slugs (``radar.skills.normalize_skills``) on both
  sides, so alias spelling differences do not count as errors.
* ``micro`` F1 pools true/false positives over all jobs. ``macro`` F1 averages per-job F1;
  a job where gold and prediction are both empty scores 1.0.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from radar.skills import normalize_skills

SALARY_REL_TOL = 0.02
SENIORITY_LEVELS = ["intern", "junior", "mid", "senior", "lead", "principal", "unspecified"]

_REGION_ALIASES = {
    "us": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "america": "US",
    "north america": "North America",
    "eu": "EU",
    "europe": "EU",
    "european union": "EU",
    "uk": "UK",
    "u.k.": "UK",
    "united kingdom": "UK",
    "great britain": "UK",
    "england": "UK",
    "worldwide": "worldwide",
    "global": "worldwide",
    "anywhere": "worldwide",
    "world": "worldwide",
    "remote worldwide": "worldwide",
    "anywhere in the world": "worldwide",
    "latam": "LATAM",
    "latin america": "LATAM",
    "apac": "APAC",
    "asia pacific": "APAC",
    "asia-pacific": "APAC",
    "emea": "EMEA",
    "canada": "Canada",
}


# --------------------------------------------------------------------------- field helpers


def norm_skills(skills: Iterable[str] | None) -> set[str]:
    return set(normalize_skills(list(skills or [])))


def norm_regions(regions: Iterable[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in regions or []:
        key = " ".join(str(raw).strip().lower().split())
        if key:
            out.add(_REGION_ALIASES.get(key, key.title()))
    return out


def prf(tp: int, n_pred: int, n_gold: int) -> tuple[float, float, float]:
    """Precision, recall, F1 from counts; 0.0 where a denominator is empty."""
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def job_f1(pred: set[str], gold: set[str]) -> float:
    if not pred and not gold:
        return 1.0
    return prf(len(pred & gold), len(pred), len(gold))[2]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def numbers_match(a: float | None, b: float | None, rel_tol: float = SALARY_REL_TOL) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a == b:
        return True
    return abs(a - b) <= rel_tol * max(abs(a), abs(b))


def _str_match(a: str | None, b: str | None) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    return a.strip().lower() == b.strip().lower()


def salary_match(gold: dict[str, Any], pred: dict[str, Any]) -> bool:
    """All four salary fields agree (numbers within 2%; both null counts as a match)."""
    return (
        numbers_match(gold.get("salary_min"), pred.get("salary_min"))
        and numbers_match(gold.get("salary_max"), pred.get("salary_max"))
        and _str_match(gold.get("salary_currency"), pred.get("salary_currency"))
        and _str_match(gold.get("salary_period"), pred.get("salary_period"))
    )


# --------------------------------------------------------------------------- per-job record


@dataclass
class JobScore:
    """Per-job comparison of one model's output against the gold labels."""

    job_id: int
    ok: bool
    tp: int
    n_pred: int
    n_gold: int
    f1: float
    seniority_ok: bool
    role_ok: bool
    employment_ok: bool
    salary_ok: bool
    regions_jaccard: float
    gold_seniority: str
    pred_seniority: str | None
    latency_ms: int | None
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    missed: list[str] = field(default_factory=list)  # in gold, not predicted
    extra: list[str] = field(default_factory=list)  # predicted, not in gold


def score_job(
    job_id: int,
    gold: dict[str, Any],
    result: dict[str, Any] | None,
) -> JobScore:
    """Score one cached result (``result`` is the cache record, or None if never run)."""
    gold_skills = norm_skills(gold.get("skills"))
    gold_regions = norm_regions(gold.get("remote_regions"))
    data = (result or {}).get("data") if result and result.get("ok") else None
    ok = data is not None
    pred_skills = norm_skills(data.get("skills")) if ok else set()
    pred_regions = norm_regions(data.get("remote_regions")) if ok else set()
    tp = len(pred_skills & gold_skills)
    return JobScore(
        job_id=job_id,
        ok=ok,
        tp=tp,
        n_pred=len(pred_skills),
        n_gold=len(gold_skills),
        f1=job_f1(pred_skills, gold_skills) if ok else 0.0,
        seniority_ok=ok and data.get("seniority") == gold.get("seniority"),
        role_ok=ok and data.get("role_category") == gold.get("role_category"),
        employment_ok=ok and data.get("employment_type") == gold.get("employment_type"),
        salary_ok=ok and salary_match(gold, data),
        regions_jaccard=jaccard(pred_regions, gold_regions) if ok else 0.0,
        gold_seniority=gold.get("seniority", "unspecified"),
        pred_seniority=data.get("seniority") if ok else None,
        latency_ms=(result or {}).get("latency_ms"),
        cost_usd=(result or {}).get("cost_usd"),
        input_tokens=(result or {}).get("input_tokens"),
        output_tokens=(result or {}).get("output_tokens"),
        missed=sorted(gold_skills - pred_skills),
        extra=sorted(pred_skills - gold_skills),
    )


# --------------------------------------------------------------------------- aggregates


def micro_prf(scores: Sequence[JobScore]) -> tuple[float, float, float]:
    return prf(
        sum(s.tp for s in scores), sum(s.n_pred for s in scores), sum(s.n_gold for s in scores)
    )


def macro_f1(scores: Sequence[JobScore]) -> float:
    return sum(s.f1 for s in scores) / len(scores) if scores else 0.0


def accuracy(flags: Sequence[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile, ``q`` in [0, 100]."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    pos = (len(xs) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return float(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


def cost_per_1k(scores: Sequence[JobScore]) -> float:
    costs = [s.cost_usd for s in scores if s.cost_usd is not None]
    return sum(costs) / len(costs) * 1000 if costs else 0.0


def summarize(scores: Sequence[JobScore]) -> dict[str, Any]:
    p, r, f = micro_prf(scores)
    lat = [s.latency_ms for s in scores if s.latency_ms]
    return {
        "n": len(scores),
        "skills_precision": p,
        "skills_recall": r,
        "skills_f1": f,
        "skills_macro_f1": macro_f1(scores),
        "seniority_acc": accuracy([s.seniority_ok for s in scores]),
        "role_acc": accuracy([s.role_ok for s in scores]),
        "employment_acc": accuracy([s.employment_ok for s in scores]),
        "salary_acc": accuracy([s.salary_ok for s in scores]),
        "regions_jaccard": sum(s.regions_jaccard for s in scores) / len(scores) if scores else 0.0,
        "failures": sum(not s.ok for s in scores),
        "median_latency_ms": percentile(lat, 50),
        "p90_latency_ms": percentile(lat, 90),
        "cost_per_1k_usd": cost_per_1k(scores),
        "input_tokens": sum(s.input_tokens or 0 for s in scores),
        "output_tokens": sum(s.output_tokens or 0 for s in scores),
    }


# --------------------------------------------------------------------------- bootstrap


def bootstrap_indices(n: int, n_resamples: int, seed: int) -> list[list[int]]:
    """Resample job indices with replacement; the same draws are reused for every model so
    paired differences are computed on identical resamples."""
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(n_resamples)]


def ci95(values: Sequence[float]) -> tuple[float, float]:
    lo = percentile(values, 2.5)
    hi = percentile(values, 97.5)
    assert lo is not None and hi is not None
    return lo, hi


def bootstrap_metric(
    scores: Sequence[JobScore],
    draws: Sequence[Sequence[int]],
    metric: Callable[[Sequence[JobScore]], float],
) -> list[float]:
    return [metric([scores[i] for i in draw]) for draw in draws]


def skills_f1_metric(scores: Sequence[JobScore]) -> float:
    return micro_prf(scores)[2]


def seniority_acc_metric(scores: Sequence[JobScore]) -> float:
    return accuracy([s.seniority_ok for s in scores])


def field_acc_metric(attr: str) -> Callable[[Sequence[JobScore]], float]:
    """Accuracy of one boolean ``JobScore`` field (role_ok, employment_ok, salary_ok, ...)."""

    def metric(scores: Sequence[JobScore]) -> float:
        return accuracy([getattr(s, attr) for s in scores])

    return metric


def paired_difference(
    a: Sequence[JobScore],
    b: Sequence[JobScore],
    draws: Sequence[Sequence[int]],
    metric: Callable[[Sequence[JobScore]], float],
) -> tuple[float, tuple[float, float]]:
    """Observed ``metric(a) - metric(b)`` and its 95% bootstrap interval (paired resampling).
    ``a`` and ``b`` must list the same jobs in the same order."""
    observed = metric(a) - metric(b)
    diffs = [metric([a[i] for i in d]) - metric([b[i] for i in d]) for d in draws]
    return observed, ci95(diffs)


# --------------------------------------------------------------------------- error analysis


def confusion(scores: Sequence[JobScore], labels: Sequence[str] = SENIORITY_LEVELS):
    """Seniority confusion counts: ``{gold: {pred: n}}``; failures count under 'FAILED'."""
    table: dict[str, Counter[str]] = {g: Counter() for g in labels}
    for s in scores:
        table.setdefault(s.gold_seniority, Counter())[s.pred_seniority or "FAILED"] += 1
    return table


def top_skill_errors(scores: Sequence[JobScore], k: int = 10) -> tuple[list, list]:
    """(most missed, most hallucinated) skills with counts, ties broken alphabetically."""
    missed: Counter[str] = Counter()
    extra: Counter[str] = Counter()
    for s in scores:
        missed.update(s.missed)
        extra.update(s.extra)

    def top(c: Counter[str]) -> list[tuple[str, int]]:
        return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k]

    return top(missed), top(extra)
