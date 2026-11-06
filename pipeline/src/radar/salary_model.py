"""Salary model: ridge regression of log advertised pay (``salary_model.json``, PLAN.md section 6).

The model answers one question: *what annual USD pay does a posting advertise, given its role,
seniority, region group and skills?* It is deliberately small and its error is published next to
every number, because the honest answer is "roughly, within a wide band".

Model
    ``log(annual_usd_mid) ~ intercept + role + seniority + region_group + skills``, where the
    three categorical blocks are dummies against their most common level (the reference; ties
    alphabetical) and every skill with at least ``MIN_SKILL_POSTINGS`` salaried postings from at
    least ``MIN_SKILL_COMPANIES`` distinct companies is a 0/1 indicator. Fitted by ridge
    regression in closed form (numpy only): all coefficients share one penalty ``alpha`` except
    the intercept, which is unpenalised (columns and target are centred before solving). The
    columns are not standardised, so a coefficient is directly "log pay versus the reference".
    ``region_group`` is :func:`radar.regions.region_group`.

Choosing alpha and measuring error
    Salaried postings come from about 700 companies and a few contribute dozens each, so every
    split is **grouped by company**: all of a company's postings are in the same fold. Folds are
    5 and balanced by posting count (largest companies first, each to the lightest fold, ties
    broken by a seeded shuffle).

    * ``alpha`` is the value in ``ALPHAS`` with the lowest 5-fold grouped cross-validated squared
      error on the log scale (ties go to the larger alpha).
    * The reported accuracy is **nested**: for each outer fold the alpha is chosen again using
      only that fold's training companies, the model is refitted there and predicts the held-out
      fold. So no number on the site was tuned on the postings it is scored on. MAE (USD),
      median absolute percentage error and R^2 (on log pay, pooled over all held-out
      predictions) are computed from these out-of-fold predictions.
    * The 80% range is ``exp(prediction + low_log)`` to ``exp(prediction + high_log)`` where the
      two offsets are the 10th and 90th percentile of the out-of-fold residuals (log actual minus
      log predicted). ``coverage`` is its honest empirical coverage: for each fold the offsets
      come from the *other* folds' residuals, and the share of this fold's postings inside the
      range is counted.
    * Baseline: the median pay of the same role and seniority in the training folds (cells with
      fewer than ``MIN_BASELINE_CELL`` salaried postings fall back to the role, then to every
      posting), evaluated on the same folds. ``eval.verdict`` compares the two with a company
      cluster bootstrap of the MAE gain: ``better`` when its 95% interval is above zero, ``worse``
      when below, else ``similar``; ``eval.note`` says it in words either way.

Profile rule (what the site's estimator and CV matcher do)
    A reader's skills are summed with at most ``profile_max_skills`` of them: the median number of
    modelled skills per salaried posting (rounded half up, at least 1). Skills the model does not
    know are ignored; the rest are ordered by market frequency (``skills[].n`` descending, slug
    ascending), not by coefficient, and the first ``profile_max_skills`` are used. A long CV
    therefore cannot inflate the estimate, and a skill is never picked because it pays well.
    ``eval.capped`` is the held-out accuracy of the same predictions under that cap.

Coefficient intervals
    ``skills[]`` and ``drivers`` carry 95% intervals from ``BOOTSTRAPS`` company-cluster
    bootstrap refits at the chosen alpha (each resample draws companies with replacement, like
    ``insights.skill_premium``). They describe the shrunken ridge coefficient; they are not
    corrected for multiple comparisons and a skill that stands in for something the model does
    not see (company, exact location) will carry that effect.

Document keys (``version`` 1)
    ``target, alpha, bootstraps, n_train, n_companies, intercept, reference, coef {role, seniority,
    region_group, skill}`` (reference levels are absent: their effect is 0), ``levels`` (salaried
    postings per level, reference included), ``skills`` (``slug, name, n, n_companies, pct,
    ci_low_pct, ci_high_pct``, most frequent first), ``profile_max_skills``, ``interval``,
    ``eval``, ``alpha_curve`` and ``drivers``. Fewer than ``MIN_SALARIED`` salaried postings (or
    ``MIN_COMPANIES`` companies) give ``{"version": 1, "reason": "..."}`` only.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from radar.insights import _company_key, _skill_name
from radar.regions import region_group

if TYPE_CHECKING:
    from radar.aggregate import JobRecord

SEED = 20261107
N_FOLDS = 5
ALPHAS = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0)
MIN_SKILL_POSTINGS = 15
MIN_SKILL_COMPANIES = 5
MIN_SALARIED = 100
MIN_COMPANIES = 20
MIN_BASELINE_CELL = 5
INTERVAL_LEVEL = 0.8
BOOTSTRAPS = 500
DRIVERS_PER_SIDE = 8
BASELINE_NAME = "median pay of the same role and seniority"

CATEGORIES = ("role", "seniority", "region_group")


# --------------------------------------------------------------------------- ridge + folds


def ridge_path(
    x: np.ndarray,
    y: np.ndarray,
    alphas: Sequence[float],
    weights: np.ndarray | None = None,
) -> list[tuple[float, np.ndarray]]:
    """Ridge fits for every alpha: ``(intercept, coefficients)`` minimising
    ``sum w (y - b0 - x b)^2 + alpha |b|^2`` with ``b0`` unpenalised.

    Columns and target are centred (with the weights, if any), so the intercept drops out of the
    penalised problem; the cross-products are formed once and reused for every alpha."""
    w = np.ones(len(y)) if weights is None else np.asarray(weights, dtype=np.float64)
    total = w.sum()
    x_mean = (w @ x) / total
    y_mean = float(w @ y) / total
    xc = x - x_mean
    gram = xc.T @ (w[:, None] * xc)
    xty = xc.T @ (w * (y - y_mean))
    eye = np.eye(x.shape[1])
    out = []
    for alpha in alphas:
        beta = np.linalg.solve(gram + alpha * eye, xty)
        out.append((y_mean - float(x_mean @ beta), beta))
    return out


def fit_ridge(
    x: np.ndarray, y: np.ndarray, alpha: float, weights: np.ndarray | None = None
) -> tuple[float, np.ndarray]:
    """One ridge fit (see :func:`ridge_path`)."""
    return ridge_path(x, y, [alpha], weights)[0]


def grouped_folds(groups: np.ndarray, k: int = N_FOLDS, seed: int = SEED) -> np.ndarray:
    """Fold index per row such that no group (company) spans two folds.

    Groups are placed largest first, each into the fold with the fewest rows so far; groups of
    equal size are ordered by a seeded shuffle, so the result is deterministic and balanced even
    when a few companies hold many postings. ``k`` shrinks to the number of groups if needed."""
    unique, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    k = max(1, min(k, len(unique)))
    rng = np.random.default_rng([seed, len(unique)])
    order = rng.permutation(len(unique))
    order = order[np.argsort(-counts[order], kind="stable")]
    load = np.zeros(k, dtype=np.int64)
    fold_of_group = np.zeros(len(unique), dtype=np.int64)
    for g in order:
        f = int(np.argmin(load))
        fold_of_group[g] = f
        load[f] += counts[g]
    return fold_of_group[inverse]


def select_alpha(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    *,
    alphas: Sequence[float] = ALPHAS,
    k: int = N_FOLDS,
    seed: int = SEED,
) -> tuple[float, list[float]]:
    """The alpha with the lowest grouped k-fold squared error on ``y`` (ties: the larger alpha),
    and the root-mean-square error of every alpha in ``alphas`` order."""
    folds = grouped_folds(groups, k, seed)
    sse = np.zeros(len(alphas))
    for f in np.unique(folds):
        test = folds == f
        for i, (b0, beta) in enumerate(ridge_path(x[~test], y[~test], alphas)):
            sse[i] += float(np.sum((y[test] - (b0 + x[test] @ beta)) ** 2))
    best = len(alphas) - 1 - int(np.argmin(sse[::-1]))  # last minimum = largest alpha
    return float(alphas[best]), [float(math.sqrt(s / len(y))) for s in sse]


def nested_predictions(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    *,
    alphas: Sequence[float] = ALPHAS,
    k: int = N_FOLDS,
    seed: int = SEED,
) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """Out-of-fold log predictions, the fold of every row and the alpha chosen in each fold.

    The alpha of an outer fold is selected by an inner grouped CV on that fold's training rows
    only, so the held-out fold never influences any choice that scores it."""
    folds = grouped_folds(groups, k, seed)
    pred = np.empty(len(y))
    chosen: list[float] = []
    for f in range(int(folds.max()) + 1):
        test = folds == f
        train = ~test
        alpha, _ = select_alpha(
            x[train], y[train], groups[train], alphas=alphas, k=k, seed=seed + 1 + f
        )
        b0, beta = fit_ridge(x[train], y[train], alpha)
        pred[test] = b0 + x[test] @ beta
        chosen.append(alpha)
    return pred, folds, chosen


# --------------------------------------------------------------------------- design


def _levels(labels: Sequence[str]) -> list[str]:
    """Levels most common first (ties alphabetical): the first is the reference."""
    counts = Counter(labels)
    return sorted(counts, key=lambda lv: (-counts[lv], lv))


def _skill_stats(salaried: Sequence[JobRecord]) -> list[tuple[str, int, int]]:
    """``(slug, salaried postings, distinct companies)`` for every modelled skill, most
    frequent first (ties by slug)."""
    postings: Counter[str] = Counter()
    companies: dict[str, set[str]] = {}
    for rec in salaried:
        company = _company_key(rec)
        for slug in set(rec.skills):
            postings[slug] += 1
            companies.setdefault(slug, set()).add(company)
    rows = [
        (slug, n, len(companies[slug]))
        for slug, n in postings.items()
        if n >= MIN_SKILL_POSTINGS and len(companies[slug]) >= MIN_SKILL_COMPANIES
    ]
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


# --------------------------------------------------------------------------- evaluation


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """MAE (USD), median absolute percentage error and R^2 on the log scale (pooled)."""
    err = np.abs(predicted - actual)
    log_a, log_p = np.log(actual), np.log(predicted)
    sst = float(np.sum((log_a - log_a.mean()) ** 2))
    return {
        "mae_usd": float(err.mean()),
        "median_ape": float(np.median(err / actual)),
        "r2_log": 1.0 - float(np.sum((log_a - log_p) ** 2)) / sst if sst > 0 else 0.0,
    }


def baseline_predictions(
    roles: np.ndarray,
    seniorities: np.ndarray,
    usd: np.ndarray,
    folds: np.ndarray,
) -> np.ndarray:
    """Out-of-fold baseline: median pay of the same role and seniority among the training
    folds, falling back to the role and then to everything when a cell has fewer than
    ``MIN_BASELINE_CELL`` postings."""
    pred = np.empty(len(usd))
    for f in np.unique(folds):
        test = folds == f
        train = ~test
        overall = float(np.median(usd[train]))
        by_role: dict[str, float] = {}
        by_cell: dict[tuple[str, str], float] = {}
        for role in set(roles[train]):
            pick = train & (roles == role)
            if pick.sum() >= MIN_BASELINE_CELL:
                by_role[role] = float(np.median(usd[pick]))
        for cell in set(zip(roles[train], seniorities[train], strict=True)):
            pick = train & (roles == cell[0]) & (seniorities == cell[1])
            if pick.sum() >= MIN_BASELINE_CELL:
                by_cell[cell] = float(np.median(usd[pick]))
        for i in np.flatnonzero(test):
            pred[i] = by_cell.get((roles[i], seniorities[i]), by_role.get(roles[i], overall))
    return pred


def _cross_fitted_coverage(residuals: np.ndarray, folds: np.ndarray, lo: float, hi: float) -> float:
    """Share of held-out postings inside the range whose offsets come from the other folds."""
    covered = 0
    for f in np.unique(folds):
        test = folds == f
        if test.all():  # single fold: nothing to cross-fit on
            continue
        low, high = np.quantile(residuals[~test], [lo, hi])
        covered += int(np.sum((residuals[test] >= low) & (residuals[test] <= high)))
    return covered / len(residuals)


def _gain_interval(
    err_baseline: np.ndarray,
    err_model: np.ndarray,
    groups: np.ndarray,
    rng: np.random.Generator,
) -> tuple[float, float, float, tuple[float, float]]:
    """MAE of the model and its gain over the baseline (percent of the baseline MAE) with 95%
    company-cluster bootstrap intervals. Returns ``(gain_pct, gain_lo, gain_hi, mae_ci)``."""
    unique, inverse = np.unique(groups, return_inverse=True)
    n_groups = len(unique)
    sum_base = np.bincount(inverse, weights=err_baseline, minlength=n_groups)
    sum_model = np.bincount(inverse, weights=err_model, minlength=n_groups)
    size = np.bincount(inverse, minlength=n_groups).astype(np.float64)
    draws = rng.multinomial(n_groups, np.full(n_groups, 1 / n_groups), BOOTSTRAPS).astype(
        np.float64
    )
    base, model, count = draws @ sum_base, draws @ sum_model, draws @ size
    gain = 100 * (1 - model / base)
    point = 100 * (1 - err_model.sum() / err_baseline.sum())
    mae_lo, mae_hi = np.percentile(model / count, [2.5, 97.5])
    g_lo, g_hi = np.percentile(gain, [2.5, 97.5])
    return float(point), float(g_lo), float(g_hi), (float(mae_lo), float(mae_hi))


def _verdict(gain: float, g_lo: float, g_hi: float) -> str:
    if g_lo > 0:
        return "better"
    if g_hi < 0:
        return "worse"
    return "similar"


def _verdict_note(verdict: str, gain: float, g_lo: float, g_hi: float) -> str:
    lower = "lower" if gain >= 0 else "higher"
    span = (
        f"its mean absolute error is {abs(gain):.0f}% {lower} than the baseline's "
        f"(95% interval for the reduction: {g_lo:.0f}% to {g_hi:.0f}%)"
    )
    if verdict == "better":
        return f"On held-out companies the model beats the {BASELINE_NAME} baseline: {span}."
    if verdict == "worse":
        return (
            f"On held-out companies the model is worse than the {BASELINE_NAME} baseline: "
            f"{span}. Treat its output as less reliable than that simple median."
        )
    return (
        f"The model does not clearly beat the {BASELINE_NAME} baseline: {span}, and the "
        "interval includes zero. Role and seniority carry most of the signal; the extra "
        "detail is not demonstrably better."
    )


# --------------------------------------------------------------------------- bootstrap


def _coefficient_bootstrap(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    alpha: float,
    rng: np.random.Generator | None = None,
    *,
    draws: np.ndarray | None = None,
) -> np.ndarray:
    """Coefficients (replicates, columns) of the ridge refitted on company resamples.

    A resample draws companies with replacement; ``draws`` (replicates, companies) are the
    multiplicities, ``np.unique(groups)`` order. Refitting 1,000 times on 1,700 rows would be
    slow, so each company's cross-products are summed once and a replicate is the multiplicity
    weighted sum of them (centred afterwards), which is exactly ``fit_ridge(..., weights=)``.
    The company gram matrices are float32 holding integers below 2**24, so they add up exactly.
    """
    unique, inverse = np.unique(groups, return_inverse=True)
    n_groups, p = len(unique), x.shape[1]
    if draws is None:
        assert rng is not None
        draws = rng.multinomial(n_groups, np.full(n_groups, 1 / n_groups), BOOTSTRAPS)
    y = y - y.mean()  # centring the target changes only the intercept
    order = np.argsort(inverse, kind="stable")
    xs, ys = x[order], y[order]
    starts = np.flatnonzero(np.r_[True, np.diff(inverse[order]) != 0])
    sizes = np.diff(np.r_[starts, len(ys)]).astype(np.float64)
    gram = np.empty((n_groups, p * p), dtype=np.float32)
    for g, (a, b) in enumerate(zip(starts, np.r_[starts[1:], len(ys)], strict=True)):
        gram[g] = (xs[a:b].T @ xs[a:b]).ravel()
    sx = np.add.reduceat(xs, starts, axis=0)
    sy = np.add.reduceat(ys, starts)
    sxy = np.add.reduceat(xs * ys[:, None], starts, axis=0)

    out = np.empty((len(draws), p))
    eye = np.eye(p)
    for lo in range(0, len(draws), 100):
        m = draws[lo : lo + 100].astype(np.float64)
        n_b, sx_b, sy_b, sxy_b = m @ sizes, m @ sx, m @ sy, m @ sxy
        gram_b = (m.astype(np.float32) @ gram).reshape(-1, p, p).astype(np.float64)
        gram_c = gram_b - sx_b[:, :, None] * sx_b[:, None, :] / n_b[:, None, None]
        xty_c = sxy_b - sx_b * (sy_b / n_b)[:, None]
        out[lo : lo + 100] = np.linalg.solve(gram_c + alpha * eye, xty_c[..., None])[..., 0]
    return out


# --------------------------------------------------------------------------- the document


def compute_salary_model(
    population: Sequence[JobRecord], *, names: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Return the ``salary_model.json`` document (module docstring, PLAN.md section 6)."""
    salaried = sorted(
        (r for r in population if r.salary is not None), key=lambda r: (r.id, r.company)
    )
    n = len(salaried)
    n_companies = len({_company_key(r) for r in salaried})
    if n < MIN_SALARIED:
        return {
            "version": 1,
            "reason": (
                f"only {n} postings state a salary; at least {MIN_SALARIED} are needed "
                "to fit and validate a model"
            ),
        }
    if n_companies < MIN_COMPANIES:
        return {
            "version": 1,
            "reason": (
                f"the salaried postings come from only {n_companies} companies; at least "
                f"{MIN_COMPANIES} are needed to validate the model on unseen companies"
            ),
        }

    usd = np.array([r.salary.annual_usd_mid for r in salaried], dtype=np.float64)
    if not np.all(usd > 0):
        raise ValueError("salary_model needs positive annual_usd_mid values")
    y = np.log(usd)
    labels = {
        "role": [r.role for r in salaried],
        "seniority": [r.seniority for r in salaried],
        "region_group": [region_group(r.remote_regions) for r in salaried],
    }
    levels = {cat: _levels(labels[cat]) for cat in CATEGORIES}
    reference = {cat: levels[cat][0] for cat in CATEGORIES}
    skill_rows = _skill_stats(salaried)
    skill_slugs = [row[0] for row in skill_rows]

    columns: list[np.ndarray] = []
    column_key: list[tuple[str, str]] = []
    for cat in CATEGORIES:
        arr = np.array(labels[cat])
        for level in levels[cat][1:]:
            columns.append((arr == level).astype(np.float64))
            column_key.append((cat, level))
    n_categorical = len(columns)
    skill_sets = [set(r.skills) for r in salaried]
    for slug in skill_slugs:
        columns.append(np.array([slug in s for s in skill_sets], dtype=np.float64))
        column_key.append(("skill", slug))
    x = np.column_stack(columns) if columns else np.zeros((n, 0))
    skill_cols = slice(n_categorical, x.shape[1])

    company_codes = np.unique([_company_key(r) for r in salaried], return_inverse=True)[1]

    # Chosen alpha, and the nested out-of-fold predictions that all accuracy figures come from.
    alpha, cv_rmse = select_alpha(x, y, company_codes)
    pred_log, folds, fold_alphas = nested_predictions(x, y, company_codes)
    intercept, beta = fit_ridge(x, y, alpha)

    # Capped predictions: the profile rule applied to each posting's own skills.
    skill_counts = x[:, skill_cols].sum(axis=1) if skill_slugs else np.zeros(n)
    max_skills = max(1, _round_half_up(float(np.median(skill_counts))))
    capped_log = _capped_predictions(
        x, y, company_codes, folds, fold_alphas, n_categorical, max_skills
    )

    residuals = y - pred_log
    lo_q, hi_q = (1 - INTERVAL_LEVEL) / 2, 1 - (1 - INTERVAL_LEVEL) / 2
    low_log, high_log = (float(v) for v in np.quantile(residuals, [lo_q, hi_q]))
    model_usd, capped_usd = np.exp(pred_log), np.exp(capped_log)
    model_metrics = _metrics(usd, model_usd)
    roles_arr, seniority_arr = np.array(labels["role"]), np.array(labels["seniority"])
    base_usd = baseline_predictions(roles_arr, seniority_arr, usd, folds)
    base_metrics = _metrics(usd, base_usd)

    boot_rng = np.random.default_rng([SEED, n_companies])
    gain, g_lo, g_hi, mae_ci = _gain_interval(
        np.abs(base_usd - usd), np.abs(model_usd - usd), company_codes, boot_rng
    )
    verdict = _verdict(gain, g_lo, g_hi)
    boot = _coefficient_bootstrap(x, y, company_codes, alpha, boot_rng)[:, skill_cols]
    ci = (
        100 * np.expm1(np.percentile(boot, [2.5, 97.5], axis=0))
        if skill_slugs
        else np.zeros((2, 0))
    )

    coef: dict[str, Any] = {cat: {} for cat in CATEGORIES}
    coef["skill"] = {}
    for (cat, key), b in zip(column_key, beta, strict=True):
        coef[cat][key] = round(float(b), 4)

    skills = []
    for j, (slug, n_with, n_comp) in enumerate(skill_rows):
        b = float(beta[n_categorical + j])
        skills.append(
            {
                "slug": slug,
                "name": _skill_name(slug, names),
                "n": n_with,
                "n_companies": n_comp,
                "pct": round(100 * math.expm1(b), 1),
                "ci_low_pct": round(float(ci[0, j]), 1),
                "ci_high_pct": round(float(ci[1, j]), 1),
            }
        )
    ranked = sorted(skills, key=lambda s: (-s["pct"], s["slug"]))
    drivers = [
        *[s for s in ranked if s["pct"] > 0][:DRIVERS_PER_SIDE],
        *[s for s in ranked[::-1] if s["pct"] < 0][:DRIVERS_PER_SIDE][::-1],
    ]
    drivers = [
        {k: d[k] for k in ("slug", "name", "pct", "ci_low_pct", "ci_high_pct", "n")}
        for d in sorted(drivers, key=lambda s: (-s["pct"], s["slug"]))
    ]

    return {
        "version": 1,
        "target": "log(annual_usd_mid)",
        "alpha": alpha,
        "bootstraps": BOOTSTRAPS,
        "n_train": n,
        "n_companies": n_companies,
        "intercept": round(intercept, 4),
        "reference": reference,
        "coef": coef,
        "levels": {cat: {lv: labels[cat].count(lv) for lv in levels[cat]} for cat in CATEGORIES},
        "skills": skills,
        "profile_max_skills": max_skills,
        "interval": {
            "low_log": round(low_log, 4),
            "high_log": round(high_log, 4),
            "level": INTERVAL_LEVEL,
        },
        "eval": {
            "method": "5-fold grouped by company, alpha chosen inside each training fold",
            "n": n,
            "folds": int(folds.max()) + 1,
            "fold_alphas": fold_alphas,
            "mae_usd": round(model_metrics["mae_usd"]),
            "mae_ci_usd": [round(mae_ci[0]), round(mae_ci[1])],
            "median_ape": round(model_metrics["median_ape"], 4),
            "r2_log": round(model_metrics["r2_log"], 4),
            "coverage": round(_cross_fitted_coverage(residuals, folds, lo_q, hi_q), 4),
            "capped": {
                k: round(v) if k == "mae_usd" else round(v, 4)
                for k, v in _metrics(usd, capped_usd).items()
            },
            "baseline": {
                "name": BASELINE_NAME,
                "mae_usd": round(base_metrics["mae_usd"]),
                "median_ape": round(base_metrics["median_ape"], 4),
                "r2_log": round(base_metrics["r2_log"], 4),
            },
            "mae_gain_pct": round(gain, 1),
            "mae_gain_ci_pct": [round(g_lo, 1), round(g_hi, 1)],
            "verdict": verdict,
            "note": _verdict_note(verdict, gain, g_lo, g_hi),
        },
        "alpha_curve": [
            {"alpha": a, "cv_rmse_log": round(r, 4)} for a, r in zip(ALPHAS, cv_rmse, strict=True)
        ],
        "drivers": drivers,
    }


def _capped_predictions(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    folds: np.ndarray,
    fold_alphas: Sequence[float],
    n_categorical: int,
    max_skills: int,
) -> np.ndarray:
    """Out-of-fold predictions when each posting only gets its ``max_skills`` most frequent
    modelled skills (columns are already ordered most frequent first)."""
    pred = np.empty(len(y))
    skill_part = x[:, n_categorical:]
    rank = np.cumsum(skill_part, axis=1)  # 1 for a posting's first skill, 2 for its second ...
    kept = skill_part * (rank <= max_skills)
    x_capped = np.hstack([x[:, :n_categorical], kept])
    for f in range(int(folds.max()) + 1):
        test = folds == f
        b0, beta = fit_ridge(x[~test], y[~test], fold_alphas[f])
        pred[test] = b0 + x_capped[test] @ beta
    return pred


# --------------------------------------------------------------------------- prediction


def predict_pay(
    model: Mapping[str, Any],
    *,
    role: str,
    seniority: str,
    region_group: str,
    skills: Sequence[str] = (),
) -> dict[str, Any]:
    """Reference implementation of the profile rule, used for the TypeScript parity fixtures
    (the site only ever runs ``predictPay`` in ``web/src/lib/salary-model.ts``).

    Returns ``{"median", "low", "high", "used_skills"}`` in whole USD."""
    coef = model["coef"]
    log_pay = model["intercept"]
    for cat, level in (("role", role), ("seniority", seniority), ("region_group", region_group)):
        log_pay += coef[cat].get(level, 0.0)
    frequency = {s["slug"]: s["n"] for s in model["skills"]}
    known = sorted({s for s in skills if s in coef["skill"]}, key=lambda s: (-frequency[s], s))
    used = known[: model["profile_max_skills"]]
    log_pay += sum(coef["skill"][s] for s in used)
    interval = model["interval"]
    return {
        "median": round(math.exp(log_pay)),
        "low": round(math.exp(log_pay + interval["low_log"])),
        "high": round(math.exp(log_pay + interval["high_log"])),
        "used_skills": used,
    }
