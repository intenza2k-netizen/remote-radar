"""Markdown rendering for ``report.md`` and ``review.md`` (pure formatting over scored data)."""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import scoring
from scoring import JobScore

Key = tuple[str, str]  # (backend, model)


@dataclass
class ReportContext:
    gold: list[dict[str, Any]]
    runs: list[Key]
    per_model: dict[Key, list[JobScore]]
    results: dict[Key, dict[int, dict[str, Any]]]
    summaries: dict[Key, dict[str, Any]]
    metas: dict[Key, dict[str, Any]]
    n_resamples: int
    seed: int
    generated_at: str


# --------------------------------------------------------------------------- formatting


def label(key: Key) -> str:
    return key[1]


def f3(x: float) -> str:
    return f"{x:.3f}"


def with_ci(value: float, ci: tuple[float, float]) -> str:
    return f"{value:.3f} [{ci[0]:.2f}-{ci[1]:.2f}]"


def secs(ms: float | None) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f} s"


def usd(x: float) -> str:
    return "$0" if x == 0 else f"${x:.2f}"


def fmt_salary(d: dict[str, Any] | None) -> str:
    if not d:
        return "none"
    lo, hi = d.get("salary_min"), d.get("salary_max")
    if lo is None and hi is None:
        return "none"
    cur, per = d.get("salary_currency") or "?", d.get("salary_period") or "?"
    rng = (
        f"{lo:g}"
        if lo == hi
        else f"{lo:g}-{hi:g}"
        if lo is not None and hi is not None
        else f"{lo or hi:g}"
    )
    return f"{rng} {cur}/{per}"


def md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _gold_by_id(ctx: ReportContext) -> dict[int, dict[str, Any]]:
    return {g["job_id"]: g for g in ctx.gold}


def _ambiguous(g: dict[str, Any]) -> bool:
    return "AMBIGUOUS" in (g["labels"].get("notes") or "")


def _common_jobs(ctx: ReportContext) -> list[int]:
    sets = [{s.job_id for s in ctx.per_model[k]} for k in ctx.runs]
    return sorted(set.intersection(*sets)) if sets else []


def _restrict(scores: Sequence[JobScore], ids: Sequence[int]) -> list[JobScore]:
    by_id = {s.job_id: s for s in scores}
    return [by_id[i] for i in ids]


# --------------------------------------------------------------------------- report.md


def render_report(ctx: ReportContext) -> str:
    gold = _gold_by_id(ctx)
    common = _common_jobs(ctx)
    draws = scoring.bootstrap_indices(len(common), ctx.n_resamples, ctx.seed)
    aligned = {k: _restrict(ctx.per_model[k], common) for k in ctx.runs}
    out: list[str] = []
    add = out.append

    statuses = Counter(g["labels"].get("status", "?") for g in ctx.gold)
    add("# Extraction model evaluation\n")
    add(
        f"Generated {ctx.generated_at} from `eval/runs/*.jsonl` against `eval/gold.jsonl` "
        f"({len(ctx.gold)} labelled jobs; label status: "
        + ", ".join(f"{n} {s}" for s, n in statuses.items())
        + "). Scoring never calls a model.\n"
    )
    add(
        "> **Read this first.** The gold labels were written by one annotator, a Claude model, "
        "before any model was run, and have not yet been reviewed by a human. That can favour "
        "the Claude extractor (same reading habits, same reading of the prompt). With 40 jobs "
        "most differences between models are within the noise; see the intervals below.\n"
    )

    # ---- headline table
    add("## Headline results\n")
    rows = []
    for k in ctx.runs:
        s = ctx.summaries[k]
        sc = aligned[k]
        f1_ci = scoring.ci95(scoring.bootstrap_metric(sc, draws, scoring.skills_f1_metric))
        sen_ci = scoring.ci95(scoring.bootstrap_metric(sc, draws, scoring.seniority_acc_metric))
        rows.append(
            [
                f"`{label(k)}`",
                with_ci(scoring.skills_f1_metric(sc), f1_ci),
                with_ci(scoring.seniority_acc_metric(sc), sen_ci),
                f3(s["role_acc"]),
                f3(s["salary_acc"]),
                s["failures"],
                secs(s["median_latency_ms"]),
                usd(s["cost_per_1k_usd"]),
            ]
        )
    add(
        md_table(
            [
                "Model",
                "Skills F1 [95% CI]",
                "Seniority acc [95% CI]",
                "Role acc",
                "Salary acc",
                "Failures",
                "Median latency",
                "Cost / 1k jobs",
            ],
            rows,
        )
    )
    add(
        f"\nn = {len(common)} jobs scored for every model. Intervals: percentile bootstrap, "
        f"{ctx.n_resamples} resamples over jobs, seed {ctx.seed} (the intervals reflect which jobs "
        "were sampled, not label errors). Skills F1 is micro-averaged over the pooled skill "
        "sets. A failed extraction counts as an empty / wrong prediction.\n"
    )
    short = [k for k in ctx.runs if len(ctx.per_model[k]) < len(ctx.gold)]
    if short:
        add(
            "**Incomplete runs:** "
            + ", ".join(
                f"`{label(k)}` ({len(ctx.per_model[k])}/{len(ctx.gold)} jobs)" for k in short
            )
            + ". Headline numbers use only the jobs every model completed.\n"
        )

    # ---- paired differences
    add("## Are the differences real?\n")
    add(
        "Paired bootstrap on the same resampled jobs. A cell is **bold** when its 95% interval "
        "excludes 0 (distinguishable); otherwise the gap is *within the noise* at this sample "
        "size. Cells show the difference A - B with its interval.\n"
    )
    metrics = [
        ("Skills F1", scoring.skills_f1_metric),
        ("Seniority", scoring.seniority_acc_metric),
        ("Role", scoring.field_acc_metric("role_ok")),
        ("Employment", scoring.field_acc_metric("employment_ok")),
        ("Salary", scoring.field_acc_metric("salary_ok")),
    ]
    pair_rows = []
    real: list[str] = []
    total = 0
    for a, b in itertools.combinations(ctx.runs, 2):
        row = [f"`{label(a)}` - `{label(b)}`"]
        for name, fn in metrics:
            diff, (lo, hi) = scoring.paired_difference(aligned[a], aligned[b], draws, fn)
            total += 1
            cell = f"{diff:+.3f} [{lo:+.2f}, {hi:+.2f}]"
            if lo > 0 or hi < 0:
                cell = f"**{cell}**"
                winner, loser = (a, b) if diff > 0 else (b, a)
                real.append(f"{label(winner)} > {label(loser)} on {name.lower()}")
            row.append(cell)
        pair_rows.append(row)
    if pair_rows:
        add(md_table(["Pair (A - B)", *[name for name, _ in metrics]], pair_rows))
        add("")
        add(
            f"{len(real)} of {total} comparisons are distinguishable"
            + (": " + "; ".join(real) + "." if real else ".")
            + f" The other {total - len(real)} are within the noise. With {total} comparisons at "
            "95%, one or two 'distinguishable' cells could be chance, so treat isolated ones "
            "with care. The intervals cover job-sampling noise only, not label errors.\n"
        )
    best_p = max(ctx.runs, key=lambda k: ctx.summaries[k]["skills_precision"])
    best_r = max(ctx.runs, key=lambda k: ctx.summaries[k]["skills_recall"])
    if best_p != best_r:
        add(
            f"**Skills F1 mixes two different behaviours.** `{label(best_r)}` has the highest "
            f"recall ({ctx.summaries[best_r]['skills_recall']:.2f}) and `{label(best_p)}` the "
            f"highest precision ({ctx.summaries[best_p]['skills_precision']:.2f}). Precision "
            "depends on how exhaustively the gold list was written: skills a model adds that are "
            "genuinely in the posting but not in the draft gold count as errors (see the "
            "'hallucinated' lists and `review.md`). Expect the F1 ranking to move when the "
            "labels are reviewed; recall is the less label-dependent number.\n"
        )
    add(
        "Latency and cost are measured per job, not sampled, so those gaps are real for this "
        "hardware and prompt. Treat gaps of a few points in any accuracy on 40 jobs (one job = "
        "2.5 points) as noise.\n"
    )

    # ---- more metrics
    add("## All metrics\n")
    gold_per_job = sum(x.n_gold for x in aligned[ctx.runs[0]]) / len(aligned[ctx.runs[0]])
    rows = []
    for k in ctx.runs:
        s = ctx.summaries[k]
        rows.append(
            [
                f"`{label(k)}`",
                f3(s["skills_precision"]),
                f3(s["skills_recall"]),
                f3(s["skills_f1"]),
                f3(s["skills_macro_f1"]),
                f"{sum(x.n_pred for x in ctx.per_model[k]) / len(ctx.per_model[k]):.1f}",
                f3(s["seniority_acc"]),
                f3(s["role_acc"]),
                f3(s["employment_acc"]),
                f3(s["salary_acc"]),
                f3(s["regions_jaccard"]),
                s["failures"],
            ]
        )
    add(
        md_table(
            [
                "Model",
                "Skills P",
                "Skills R",
                "Skills F1 (micro)",
                "Skills F1 (macro)",
                "Skills / job",
                "Seniority",
                "Role",
                "Employment",
                "Salary",
                "Regions Jaccard",
                "Failures",
            ],
            rows,
        )
    )
    add(
        "\nSkills / job is the mean number of canonical skills a model returned; the draft gold "
        f"averages {gold_per_job:.1f}, so models that list more skills are penalised on "
        "precision. Salary = all four fields match (numbers within 2%, both-null counts as a "
        "match). "
        "Regions Jaccard is the mean per-job overlap after normalising aliases "
        "(USA/US, Europe/EU). "
        "Macro F1 averages per-job F1 (empty vs empty = 1.0).\n"
    )
    rows = []
    for k in ctx.runs:
        s = ctx.summaries[k]
        rows.append(
            [
                f"`{label(k)}`",
                secs(s["median_latency_ms"]),
                secs(s["p90_latency_ms"]),
                f"{s['input_tokens']:,}",
                f"{s['output_tokens']:,}",
                usd(s["cost_per_1k_usd"]),
            ]
        )
    add(
        md_table(
            [
                "Model",
                "Median latency",
                "p90 latency",
                "Input tokens",
                "Output tokens",
                "Cost / 1k jobs",
            ],
            rows,
        )
    )
    add("")

    # ---- ambiguity
    unamb = [i for i in common if not _ambiguous(gold[i])]
    amb = [i for i in common if _ambiguous(gold[i])]
    add("## Accuracy on unambiguous vs ambiguous labels\n")
    add(
        f"{len(amb)} of {len(common)} gold label sets carry an AMBIGUOUS note (the labeller was "
        "unsure which of two answers is right). Scores on the other "
        f"{len(unamb)} are a cleaner read of model quality.\n"
    )
    rows = []
    for k in ctx.runs:
        u = _restrict(ctx.per_model[k], unamb)
        a = _restrict(ctx.per_model[k], amb)
        rows.append(
            [
                f"`{label(k)}`",
                f3(scoring.accuracy([s.role_ok for s in u])),
                f3(scoring.accuracy([s.role_ok for s in a])),
                f3(scoring.accuracy([s.seniority_ok for s in u])),
                f3(scoring.accuracy([s.seniority_ok for s in a])),
                f3(scoring.accuracy([s.salary_ok for s in u])),
                f3(scoring.accuracy([s.salary_ok for s in a])),
            ]
        )
    add(
        md_table(
            [
                "Model",
                f"Role (clear, n={len(unamb)})",
                f"Role (ambiguous, n={len(amb)})",
                "Seniority (clear)",
                "Seniority (ambiguous)",
                "Salary (clear)",
                "Salary (ambiguous)",
            ],
            rows,
        )
    )
    add("")

    # ---- per source
    add("## By source\n")
    sources = sorted({gold[i]["source"] for i in common})
    rows = []
    for k in ctx.runs:
        for src in sources:
            ids = [i for i in common if gold[i]["source"] == src]
            sc = _restrict(ctx.per_model[k], ids)
            rows.append(
                [
                    f"`{label(k)}`",
                    src,
                    len(ids),
                    f3(scoring.micro_prf(sc)[2]),
                    f3(scoring.accuracy([s.seniority_ok for s in sc])),
                    f3(scoring.accuracy([s.role_ok for s in sc])),
                    f3(scoring.accuracy([s.salary_ok for s in sc])),
                ]
            )
    add(md_table(["Model", "Source", "n", "Skills F1", "Seniority", "Role", "Salary"], rows))
    add("\nThe per-source cells hold 7-13 jobs each: indicative only.\n")

    # ---- confusion + skill errors
    add("## Seniority confusion (rows = gold, columns = predicted)\n")
    for k in ctx.runs:
        table = scoring.confusion(aligned[k])
        cols = scoring.SENIORITY_LEVELS + (
            ["FAILED"] if any("FAILED" in c for c in table.values()) else []
        )
        rows = [
            [g, *[table[g].get(c, 0) or "" for c in cols], sum(table[g].values())]
            for g in table
            if table[g]
        ]
        add(f"### `{label(k)}`\n")
        add(md_table(["gold \\ pred", *cols, "total"], rows))
        add("")

    add("## Most-missed and most-hallucinated skills (canonical slugs)\n")
    add(
        "*Missed* = in gold, not predicted. *Hallucinated* = predicted, not in gold (some are real "
        "skills the labeller left out; check `review.md`).\n"
    )
    for k in ctx.runs:
        missed, extra = scoring.top_skill_errors(aligned[k], 10)
        add(f"### `{label(k)}`\n")
        add("- Missed: " + (", ".join(f"{s} ({n})" for s, n in missed) or "none"))
        add("- Hallucinated: " + (", ".join(f"{s} ({n})" for s, n in extra) or "none") + "\n")

    # ---- hardware
    add("## Hardware, latency and offloading\n")
    add(
        "Local models ran one at a time through Ollama on a single RTX 5090 (32 GB VRAM) shared "
        "with desktop apps, with thinking disabled and `num_ctx` 8192. Each local run starts with "
        "one unscored warm-up call so model-load time is not in the per-job latency; the load "
        "time is listed separately. Claude latency is a network round trip to the API with "
        "adaptive thinking at low effort, so it is not comparable to local compute time.\n"
    )
    rows = []
    fully_on_gpu = True
    seen_local = False
    for k in ctx.runs:
        m = ctx.metas.get(k, {})
        if k[0] == "claude":
            rows.append(
                [f"`{label(k)}`", "API", "n/a", "n/a", secs(ctx.summaries[k]["median_latency_ms"])]
            )
            continue
        seen_local = True
        ps = m.get("ollama_ps") or {}
        before = m.get("gpu_before_load") or {}
        during = m.get("gpu_while_loaded") or {}
        frac = ps.get("gpu_fraction")
        if frac is None or frac < 0.995:
            fully_on_gpu = False
        share = "not recorded" if frac is None else f"{frac * 100:.0f}% on GPU"
        if frac is not None and frac < 0.995:
            share += " (rest offloaded to CPU)"
        reported = f"{ps['size_bytes'] / 1e9:.1f} GB, {share}" if ps.get("size_bytes") else share
        if before and during:
            delta = (during["vram_used_mib"] - before["vram_used_mib"]) / 1024
            vram = (
                f"{before['vram_used_mib'] / 1024:.1f} -> {during['vram_used_mib'] / 1024:.1f} GB "
                f"of {during['vram_total_mib'] / 1024:.0f} (+{delta:.1f})"
            )
        else:
            vram = "not recorded"
        warm = secs(m.get("warmup_ms")) if m.get("warmup_ms") is not None else "not recorded"
        rows.append(
            [
                f"`{label(k)}`",
                reported,
                vram,
                warm,
                secs(ctx.summaries[k]["median_latency_ms"]),
            ]
        )
    add(
        md_table(
            [
                "Model",
                "Ollama-reported size / placement",
                "nvidia-smi VRAM in use: before -> while loaded",
                "Load + first call",
                "Median per job",
            ],
            rows,
        )
    )
    if seen_local:
        add("")
        add(
            (
                "Every local model was fully resident in VRAM (Ollama reports 100% GPU and the "
                "nvidia-smi figures leave headroom), so no CPU offloading affected the latency "
                "above."
                if fully_on_gpu
                else "At least one local model was partly offloaded to CPU; its latency "
                "includes that penalty."
            )
            + " Ollama's reported size for the Gemma 4 models is far below the VRAM they actually "
            "occupy (compare with nvidia-smi), so trust the nvidia-smi column for memory. The "
            "desktop apps were holding only about 2.7 GB of VRAM during these runs, not the "
            "12 GB assumed in the plan; a busier desktop could push the 27B/31B models into "
            "offloading and make them slower."
        )
    add("")

    # ---- method
    add("## Method and caveats\n")
    add(
        "- **Gold set:** 40 canonical remote jobs from `data/jobs.sqlite`, seeded stratified "
        "sample (selection procedure in `eval/README.md`). Inputs are frozen copies of the exact "
        "`JobInput` the pipeline builds, so the eval reproduces even if the DB changes.\n"
        "- **Labels:** written by one Claude model, using the definitions in "
        "`extract/prompts/extract.md`, before any model output was seen; status `draft`. "
        "Same-family bias is possible. Items the labeller found ambiguous are flagged in "
        "`gold.jsonl` notes and "
        "listed first in `review.md`.\n"
        "- **Same prompt for every model** (`v1`), same JSON schema, one retry on invalid output. "
        "Temperature is 0 for Ollama; Claude Sonnet 5.5 accepts no sampling parameters, so its "
        "runs are not guaranteed repeatable and each model was run once.\n"
        "- **What the model sees:** `extract_stage.job_input` passes only `salary_text` (set for "
        "Remotive only) and the description, truncated to 6,000 characters. The structured "
        "salaries that Jobicy and Remote OK provide are *not* in the input, so salary accuracy "
        "here measures "
        "extraction from the description text, not what the nightly pipeline publishes (which "
        "prefers the structured value).\n"
        "- **Skills** are compared as canonical slugs after `normalize_skills`; the alias table "
        "merges some distinct tools (see Open issues in the hand-off), which affects every model "
        "equally.\n"
        "- **Cost:** Claude cost is computed from reported token usage with the pipeline's price "
        "table (cache reads and writes included); local models cost 0 (electricity not counted).\n"
    )
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- review.md


def _disagreement(ctx: ReportContext, job_id: int) -> float:
    score = 0.0
    for k in ctx.runs:
        s = next((x for x in ctx.per_model[k] if x.job_id == job_id), None)
        if s is None:
            continue
        score += (not s.role_ok) + (not s.seniority_ok) + (not s.employment_ok) + (not s.salary_ok)
        score += 1 - s.f1
    return score


def _fmt_labels(lab: dict[str, Any]) -> str:
    return (
        f"role `{lab['role_category']}` | seniority `{lab['seniority']}` | "
        f"employment `{lab['employment_type']}` | salary `{fmt_salary(lab)}` | "
        f"regions `{', '.join(lab['remote_regions']) or '-'}`"
    )


def render_review(ctx: ReportContext) -> str:
    keys = ctx.runs
    order = sorted(ctx.gold, key=lambda g: (-_disagreement(ctx, g["job_id"]), g["job_id"]))
    out: list[str] = []
    add = out.append
    add("# Gold label review checklist\n")
    add(
        "The labels in `eval/gold.jsonl` are **drafts** written by a Claude model before any "
        "extractor ran. Please check them, most-contested jobs first. To fix a label, edit its "
        '`labels` object in `gold.jsonl` and set `"status": "reviewed"`, then run '
        "`uv run python eval/run_eval.py score` (free: no model calls).\n"
    )
    add(
        "How to read each entry: **Gold** is the draft label. **Notes** is the labeller's "
        "reasoning and doubts. The table shows only the fields where at least one model "
        "differs from gold. When *every* model agrees with each other and not with gold, the "
        "gold label is the likelier error.\n"
    )

    # consensus errors
    consensus: list[tuple[int, str, str, str]] = []
    for g in ctx.gold:
        jid = g["job_id"]
        for field_name, gold_val in (
            ("role_category", g["labels"]["role_category"]),
            ("seniority", g["labels"]["seniority"]),
            ("employment_type", g["labels"]["employment_type"]),
        ):
            preds = [(ctx.results[k].get(jid) or {}).get("data") for k in keys]
            vals = [p[field_name] for p in preds if p]
            if len(vals) >= 2 and len(set(vals)) == 1 and vals[0] != gold_val:
                consensus.append((jid, field_name, str(gold_val), str(vals[0])))
    if consensus:
        titles = {g["job_id"]: g["input"]["title"] for g in ctx.gold}
        add("## Likely label errors: all models agree against the gold label\n")
        add(
            md_table(
                ["Job", "Field", "Gold", "All models say"],
                [[f"{jid} {titles[jid][:50]}", f, gv, mv] for jid, f, gv, mv in consensus],
            )
        )
        add("")

    add("## Jobs, most contested first\n")
    for n, g in enumerate(order, start=1):
        jid = g["job_id"]
        lab = g["labels"]
        inp = g["input"]
        add(f"### {n}. {inp['title']} - {inp['company']}")
        add(
            f"[open posting]({g['url']}) | job {jid} | {g['source']} | "
            f"disagreement {_disagreement(ctx, jid):.1f}\n"
        )
        add(f"- [ ] labels checked  (status: `{lab.get('status', 'draft')}`)")
        add(f"- **Gold:** {_fmt_labels(lab)}")
        add(f"- **Gold skills:** {', '.join(lab['skills']) or '-'}")
        if lab.get("notes"):
            add(f"- **Notes:** {lab['notes']}")
        db_sal = g.get("meta", {}).get("db_structured_salary") or {}
        if db_sal.get("min") is not None and lab.get("salary_min") is None:
            add(
                f"- **Heads-up:** the DB holds a structured salary "
                f"({db_sal['min']:g}-{db_sal['max']:g} {db_sal.get('currency') or '?'}/"
                f"{db_sal.get('period') or '?'}) that was not part of the extractor input."
            )
        rows = []
        per_key = {k: (ctx.results[k].get(jid) or {}) for k in keys}

        def pred(k: Key, name: str, per_key: dict = per_key) -> Any:
            d = per_key[k].get("data")
            return d[name] if d else "FAILED"

        for fld, title in (
            ("role_category", "role"),
            ("seniority", "seniority"),
            ("employment_type", "employment"),
        ):
            vals = [pred(k, fld) for k in keys]
            if any(v != lab[fld] for v in vals):
                rows.append([title, f"`{lab[fld]}`", *[f"`{v}`" for v in vals]])
        sal = [
            fmt_salary(per_key[k].get("data")) if per_key[k].get("data") else "FAILED" for k in keys
        ]
        if any(
            not scoring.salary_match(lab, per_key[k]["data"]) if per_key[k].get("data") else True
            for k in keys
        ):
            rows.append(["salary", fmt_salary(lab), *sal])
        s_by_key = {k: next((x for x in ctx.per_model[k] if x.job_id == jid), None) for k in keys}
        miss = Counter(sk for s in s_by_key.values() if s for sk in s.missed)
        extra = Counter(sk for s in s_by_key.values() if s for sk in s.extra)
        if rows:
            add("")
            add(md_table(["field", "gold", *[f"`{label(k)}`" for k in keys]], rows))
        common_miss = [sk for sk, c in miss.items() if c >= max(2, len(keys) // 2)]
        common_extra = [sk for sk, c in extra.items() if c >= max(2, len(keys) // 2)]
        if common_miss:
            add(
                "\n- **Skills most models missed (gold has them):** "
                + ", ".join(sorted(common_miss))
            )
        if common_extra:
            add(
                "- **Skills most models added (gold lacks them):** "
                + ", ".join(sorted(common_extra))
            )
        f1s = ", ".join(f"{label(k)} {s_by_key[k].f1:.2f}" for k in keys if s_by_key[k])
        add(f"- Per-job skills F1: {f1s}")
        add("")
    return "\n".join(out) + "\n"
