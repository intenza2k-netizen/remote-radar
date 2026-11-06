"""Model evaluation for Remote Radar: run extractors on the gold set, then score the caches.

    uv run python eval/run_eval.py run --backend ollama --model gemma4:12b [--limit N] [--resume]
    uv run python eval/run_eval.py score

``run`` calls a model and caches every raw ``ExtractionResult`` in ``eval/runs``.
``score`` never calls a model: it re-scores the caches against the *current* gold labels, so
relabelling is free. It writes ``eval/report.md``, ``eval/review.md`` and
``web/public/data/eval.json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reporting  # noqa: E402
import scoring  # noqa: E402

from radar.config import PROMPT_VERSION, WEB_DATA_DIR  # noqa: E402
from radar.extract import ExtractionResult, JobInput, get_extractor  # noqa: E402
from radar.extract_stage import fatal_message  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
# gold.jsonl holds the full posting text the models saw. Job ads belong to their authors,
# so it stays local (gitignored). gold.public.jsonl is the same file with the description
# text removed: enough to re-score the cached runs, not to re-run the models.
GOLD_PATH = EVAL_DIR / "gold.jsonl"
GOLD_PUBLIC_PATH = EVAL_DIR / "gold.public.jsonl"
RUNS_DIR = EVAL_DIR / "runs"
REPORT_PATH = EVAL_DIR / "report.md"
REVIEW_PATH = EVAL_DIR / "review.md"
EVAL_JSON_PATH = WEB_DATA_DIR / "eval.json"

# Display order in the report and in eval.json (unknown runs are appended alphabetically).
MODEL_ORDER = [
    ("claude", "claude-sonnet-5-5"),
    ("ollama", "gemma4:12b"),
    ("ollama", "qwen3.8:27b"),
    ("ollama", "gemma4:31b-it-q4_K_M"),
]
DEFAULT_MAX_COST_USD = 2.00
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261106

app = typer.Typer(add_completion=False, no_args_is_help=True)


# --------------------------------------------------------------------------- cache helpers


def run_stem(backend: str, model: str) -> str:
    return f"{backend}__{model}".replace(":", "-").replace("/", "_")


def run_path(backend: str, model: str) -> Path:
    return RUNS_DIR / f"{run_stem(backend, model)}.jsonl"


def meta_path(backend: str, model: str) -> Path:
    return RUNS_DIR / f"{run_stem(backend, model)}.meta.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_gold(labelled_only: bool = True, need_text: bool = False) -> list[dict[str, Any]]:
    if GOLD_PATH.exists():
        records = load_jsonl(GOLD_PATH)
    elif need_text:
        raise typer.BadParameter(
            f"{GOLD_PATH.name} (with posting text) is not distributed. Rebuild it from your "
            "own database with build_gold.py, or score the cached runs instead."
        )
    else:
        records = load_jsonl(GOLD_PUBLIC_PATH)
    if labelled_only:
        records = [r for r in records if r.get("labels")]
    return records


def write_public_gold() -> None:
    """Refresh gold.public.jsonl from the local gold.jsonl, without description text."""
    if not GOLD_PATH.exists():
        return
    with GOLD_PUBLIC_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in load_jsonl(GOLD_PATH):
            public = dict(rec)
            public["input"] = {
                k: v for k, v in (rec.get("input") or {}).items() if k != "description_text"
            }
            fh.write(json.dumps(public, ensure_ascii=False) + "\n")


def result_record(job_id: int, result: ExtractionResult) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "backend": result.backend,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "ok": result.ok,
        "error": result.error,
        "data": result.data.model_dump() if result.data is not None else None,
        "raw_output": result.raw_output,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "ran_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _write_all(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- run


WARMUP_JOB = JobInput(
    title="Backend Engineer",
    company="Example Co",
    location="Worldwide",
    description_text="We need a backend engineer with Python and PostgreSQL. 3+ years.",
    salary_text=None,
    source_tags=["python"],
)


def _ollama_ps(model: str) -> dict[str, Any] | None:
    """Memory placement of ``model`` while it is loaded (GPU vs CPU split)."""
    try:
        import ollama

        for item in ollama.Client().ps().models:
            if item.model == model or item.name == model:
                size = int(item.size or 0)
                vram = int(item.size_vram or 0)
                return {
                    "size_bytes": size,
                    "size_vram_bytes": vram,
                    "gpu_fraction": round(vram / size, 3) if size else None,
                    "context_length": getattr(item, "context_length", None),
                }
    except Exception as exc:  # reporting aid only; never fail the run for it
        return {"error": f"{type(exc).__name__}: {exc}"}
    return None


def _gpu_snapshot() -> dict[str, Any] | None:
    """VRAM in use before the model loads (desktop apps hold part of it)."""
    try:
        out = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            .stdout.strip()
            .splitlines()[0]
        )
        name, used, total = (x.strip() for x in out.split(","))
        return {"gpu": name, "vram_used_mib": int(used), "vram_total_mib": int(total)}
    except Exception:
        return None


def _ollama_stop(model: str) -> None:
    try:
        subprocess.run(["ollama", "stop", model], check=False, capture_output=True, timeout=60)
    except Exception as exc:
        typer.echo(f"warning: could not run `ollama stop {model}`: {exc}")


@app.command()
def run(
    backend: str = typer.Option(..., help="claude or ollama"),
    model: str = typer.Option(..., help="Model id, e.g. claude-sonnet-5-5 or gemma4:12b"),
    limit: int | None = typer.Option(None, help="Only the first N gold jobs"),
    resume: bool = typer.Option(False, help="Skip jobs already cached for this model"),
    retry_failed: bool = typer.Option(False, help="With --resume: re-run cached failures too"),
    overwrite: bool = typer.Option(False, help="Replace an existing cache without --resume"),
    max_cost: float = typer.Option(DEFAULT_MAX_COST_USD, help="Abort when total USD would exceed"),
    stop_model: bool = typer.Option(True, help="Ollama only: `ollama stop` when finished"),
) -> None:
    """Run one extractor over the gold jobs and cache the raw results."""
    if backend not in {"claude", "ollama"}:
        raise typer.BadParameter("backend must be claude or ollama")
    gold = load_gold(labelled_only=False, need_text=True)
    if limit is not None:
        gold = gold[:limit]
    RUNS_DIR.mkdir(exist_ok=True)
    path = run_path(backend, model)
    cached = load_jsonl(path)
    if cached and not resume and not overwrite:
        typer.echo(f"{path.name} already has {len(cached)} results. Use --resume or --overwrite.")
        raise typer.Exit(1)
    if overwrite and not resume:
        cached = []
        _write_all(path, [])
    if retry_failed:
        cached = [r for r in cached if r["ok"]]
        _write_all(path, cached)
    done = {r["job_id"] for r in cached}
    todo = [g for g in gold if g["job_id"] not in done]
    spent = sum(r.get("cost_usd") or 0.0 for r in cached)
    typer.echo(f"{backend}:{model}  gold={len(gold)} cached={len(done)} todo={len(todo)}")
    if not todo:
        typer.echo("nothing to do")
        return

    try:
        extractor = get_extractor(backend, model)  # type: ignore[arg-type]
    except Exception as exc:
        typer.echo(f"cannot start the extractor: {fatal_message(exc, backend, model) or exc}")
        raise typer.Exit(2) from exc

    meta: dict[str, Any] = {}
    if meta_path(backend, model).exists():
        meta = json.loads(meta_path(backend, model).read_text(encoding="utf-8"))
    meta.update(
        {
            "backend": backend,
            "model": model,
            "prompt_version": getattr(extractor, "prompt_version", PROMPT_VERSION),
            "last_run_started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )

    exit_code = 0
    try:
        if backend == "ollama":
            meta["gpu_before_load"] = _gpu_snapshot()
            t0 = time.perf_counter()
            warm = extractor.extract(WARMUP_JOB)
            meta["warmup_ms"] = round((time.perf_counter() - t0) * 1000)
            typer.echo(f"warm-up (model load, not scored): {meta['warmup_ms']} ms ok={warm.ok}")

        with path.open("a", encoding="utf-8", newline="\n") as out:
            for i, g in enumerate(todo, start=1):
                inp = JobInput(**g["input"])
                try:
                    result = extractor.extract(inp)
                except Exception as exc:
                    message = fatal_message(exc, backend, model)
                    if message:
                        typer.echo(f"ABORT (configuration error): {message}")
                        exit_code = 2
                        break
                    result = ExtractionResult(
                        backend=backend,
                        model=model,
                        prompt_version=PROMPT_VERSION,
                        ok=False,
                        data=None,
                        error=f"{type(exc).__name__}: {exc}"[:500],
                        raw_output=None,
                        latency_ms=0,
                        input_tokens=None,
                        output_tokens=None,
                        cost_usd=None,
                    )
                rec = result_record(g["job_id"], result)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                spent += result.cost_usd or 0.0
                typer.echo(
                    f"[{i}/{len(todo)}] job {g['job_id']:>5} ok={result.ok!s:<5} "
                    f"{result.latency_ms:>6} ms  "
                    f"tokens={result.input_tokens}/{result.output_tokens} "
                    f"cost=${result.cost_usd or 0:.4f}  total=${spent:.4f}"
                    + (f"  ERROR {result.error}" if not result.ok else "")
                )
                if backend == "claude" and spent > max_cost:
                    typer.echo(f"ABORT: spend ${spent:.2f} exceeds --max-cost ${max_cost:.2f}")
                    exit_code = 3
                    break
        if backend == "ollama":
            meta["ollama_ps"] = _ollama_ps(model)
            meta["gpu_while_loaded"] = _gpu_snapshot()
            typer.echo(f"ollama ps: {meta['ollama_ps']}")
    finally:
        meta["last_run_finished_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta["total_cost_usd"] = round(spent, 6)
        meta_path(backend, model).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if backend == "ollama" and stop_model:
            _ollama_stop(model)
    typer.echo(f"done. cache: {path}  spend: ${spent:.4f}")
    if exit_code:
        raise typer.Exit(exit_code)


# --------------------------------------------------------------------------- score


def _ordered_runs() -> list[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for p in RUNS_DIR.glob("*.jsonl"):
        recs = load_jsonl(p)
        if recs:
            found.add((recs[0]["backend"], recs[0]["model"]))
    known = [m for m in MODEL_ORDER if m in found]
    return known + sorted(found - set(known))


@app.command()
def score() -> None:
    """Score every cached run against the current gold labels (no model calls)."""
    write_public_gold()
    gold = load_gold()
    if not gold:
        typer.echo("no labelled gold jobs in gold.jsonl")
        raise typer.Exit(1)
    runs = _ordered_runs()
    if not runs:
        typer.echo("no cached runs in eval/runs")
        raise typer.Exit(1)

    per_model: dict[tuple[str, str], list[scoring.JobScore]] = {}
    results: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    metas: dict[tuple[str, str], dict[str, Any]] = {}
    for backend, model in runs:
        by_job = {r["job_id"]: r for r in load_jsonl(run_path(backend, model))}
        results[(backend, model)] = by_job
        per_model[(backend, model)] = [
            scoring.score_job(g["job_id"], g["labels"], by_job.get(g["job_id"]))
            for g in gold
            if g["job_id"] in by_job
        ]
        mp = meta_path(backend, model)
        metas[(backend, model)] = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}

    summaries = {key: scoring.summarize(scores) for key, scores in per_model.items()}

    eval_json = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_labeled": len(gold),
        "backends": [
            {
                "backend": backend,
                "model": model,
                "skills_precision": round(s["skills_precision"], 3),
                "skills_recall": round(s["skills_recall"], 3),
                "skills_f1": round(s["skills_f1"], 3),
                "seniority_acc": round(s["seniority_acc"], 3),
                "role_acc": round(s["role_acc"], 3),
                "salary_acc": round(s["salary_acc"], 3),
                "median_latency_ms": round(s["median_latency_ms"] or 0),
                "cost_per_1k_usd": round(s["cost_per_1k_usd"], 2),
                "failures": s["failures"],
            }
            for (backend, model), s in summaries.items()
        ],
    }
    EVAL_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVAL_JSON_PATH.write_text(json.dumps(eval_json, separators=(",", ":")) + "\n", encoding="utf-8")

    ctx = reporting.ReportContext(
        gold=gold,
        runs=runs,
        per_model=per_model,
        results=results,
        summaries=summaries,
        metas=metas,
        n_resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        generated_at=eval_json["generated_at"],
    )
    REPORT_PATH.write_text(reporting.render_report(ctx), encoding="utf-8", newline="\n")
    REVIEW_PATH.write_text(reporting.render_review(ctx), encoding="utf-8", newline="\n")
    typer.echo(f"wrote {REPORT_PATH}\nwrote {REVIEW_PATH}\nwrote {EVAL_JSON_PATH}")
    for (backend, model), s in summaries.items():
        typer.echo(
            f"{backend}:{model:<24} n={s['n']} skillsF1={s['skills_f1']:.3f} "
            f"sen={s['seniority_acc']:.3f} role={s['role_acc']:.3f} sal={s['salary_acc']:.3f} "
            f"fail={s['failures']}"
        )


if __name__ == "__main__":
    app()
