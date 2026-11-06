"""``radar`` command line: fetch, ingest, extract, aggregate, publish, run-all, stats."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table
from sqlalchemy import func, select

from radar import config
from radar.aggregate import WINDOW_DAYS, aggregate
from radar.db import session_scope
from radar.embed import DEFAULT_DTYPE, MODEL_FILES, EmbedSummary, run_embed
from radar.extract import get_extractor
from radar.extract_stage import (
    DEFAULT_WORKERS,
    ExtractSummary,
    run_extract,
)
from radar.ingest import StageError, fetch_sources, ingest_raw_jobs
from radar.models import Extraction, Job, JobSkill, RawJob
from radar.publish import publish

app = typer.Typer(
    name="radar",
    help="Remote Radar pipeline: fetch, ingest, extract, aggregate and publish remote jobs.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

DbOption = Annotated[
    Path | None, typer.Option("--db", help="SQLite file (default: data/jobs.sqlite).")
]


@app.callback()
def main(
    ctx: typer.Context,
    db: DbOption = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=False)],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    ctx.obj = {"db": db}


def _db(ctx: typer.Context) -> Path | None:
    return ctx.obj["db"]


def _guard(func: Callable[[], Any]) -> Any:
    """Run a stage, turning a fatal ``StageError`` into a message and exit code 1."""
    try:
        return func()
    except StageError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(1) from exc


# --------------------------------------------------------------------------- fetch / ingest


def _do_fetch(db: Path | None) -> dict[str, Any]:
    stats = fetch_sources(db)
    table = Table(title="fetch")
    for col in ("source", "new", "seen", "error"):
        table.add_column(col, justify="left" if col in ("source", "error") else "right")
    for name, entry in stats["sources"].items():
        table.add_row(name, str(entry["new"]), str(entry["seen"]), entry["error"] or "")
    console.print(table)
    return stats


def _do_ingest(db: Path | None) -> dict[str, Any]:
    stats = ingest_raw_jobs(db)
    console.print(
        f"ingest: {stats['pending']} pending raw jobs -> {stats['canonical']} canonical, "
        f"{stats['duplicates']} duplicates, {stats['errors']} unmappable"
    )
    return stats


@app.command()
def fetch(ctx: typer.Context) -> None:
    """Fetch postings from every source into raw_jobs."""
    _guard(lambda: _do_fetch(_db(ctx)))


@app.command()
def ingest(ctx: typer.Context) -> None:
    """Normalise raw postings into jobs and mark duplicates."""
    _guard(lambda: _do_ingest(_db(ctx)))


# --------------------------------------------------------------------------- extract

BackendOption = Annotated[
    str | None, typer.Option("--backend", help="claude or ollama (default: RADAR_BACKEND).")
]
ModelOption = Annotated[str | None, typer.Option("--model", help="Model tag (default: config).")]


def _check_backend(backend: str | None) -> str:
    backend = backend or config.DEFAULT_BACKEND
    if backend not in ("claude", "ollama"):
        raise typer.BadParameter(f"unknown backend {backend!r}; expected claude or ollama")
    return backend


def print_extract_summary(summary: ExtractSummary) -> None:
    latency = f"{summary.median_latency_ms:.0f} ms" if summary.median_latency_ms else "n/a"
    table = Table(title="extract")
    table.add_column("targets", justify="right")
    table.add_column("ok", justify="right")
    table.add_column("failed", justify="right")
    table.add_column("median latency", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("cost (USD)", justify="right")
    table.add_row(
        str(summary.targets),
        str(summary.ok),
        str(summary.failed),
        latency,
        f"{summary.total_tokens:,}",
        f"{summary.cost_usd:.4f}",
    )
    console.print(table)


def _do_extract(
    db: Path | None,
    backend: str | None,
    model: str | None,
    *,
    limit: int | None = None,
    since_days: int | None = None,
    force: bool = False,
    workers: int = DEFAULT_WORKERS,
    set_current: bool = False,
) -> ExtractSummary:
    chosen = _check_backend(backend)
    summary = run_extract(
        lambda: get_extractor(chosen, model),  # type: ignore[arg-type]
        db,
        limit=limit,
        since_days=since_days,
        force=force,
        workers=workers,
        set_current=set_current,
        console=console,
    )
    print_extract_summary(summary)
    return summary


@app.command()
def extract(
    ctx: typer.Context,
    backend: BackendOption = None,
    model: ModelOption = None,
    limit: Annotated[
        int | None, typer.Option(help="Extract at most N jobs (newest first).")
    ] = None,
    since_days: Annotated[
        int | None, typer.Option(help="Only jobs posted in the last N days.")
    ] = None,
    force: Annotated[
        bool, typer.Option(help="Re-extract jobs that already have an ok run.")
    ] = False,
    workers: Annotated[int, typer.Option(help="Parallel calls (Claude only).")] = DEFAULT_WORKERS,
    set_current: Annotated[
        bool,
        typer.Option(
            "--set-current",
            help="Rebuild job skills from this backend/model even if it is not the default.",
        ),
    ] = False,
) -> None:
    """Extract structured fields with an LLM for canonical remote jobs."""
    _guard(
        lambda: _do_extract(
            _db(ctx),
            backend,
            model,
            limit=limit,
            since_days=since_days,
            force=force,
            workers=workers,
            set_current=set_current,
        )
    )


# --------------------------------------------------------------------------- embed


def _do_embed(
    db: Path | None,
    backend: str | None = None,
    model: str | None = None,
    *,
    force: bool = False,
    dtype: str = DEFAULT_DTYPE,
) -> EmbedSummary:
    with Progress(
        TextColumn("embedding"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as bar:
        task = bar.add_task("embed", total=None)

        def progress(done: int, total: int) -> None:
            bar.update(task, completed=done, total=total)

        summary = run_embed(
            db, backend=backend, model=model, force=force, dtype=dtype, progress=progress
        )
    console.print(
        f"embed: {summary.total} listed jobs, {summary.embedded} embedded, "
        f"{summary.cached} cached, {summary.seconds:.1f} s"
    )
    return summary


@app.command("embed")
def embed_cmd(
    ctx: typer.Context,
    backend: BackendOption = None,
    model: ModelOption = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-embed every listed job, ignoring the cache.")
    ] = False,
    dtype: Annotated[
        str, typer.Option(help=f"Model precision: {', '.join(sorted(MODEL_FILES))}.")
    ] = DEFAULT_DTYPE,
) -> None:
    """Embed the published jobs for the CV matcher (cached; only new or changed jobs run)."""
    if dtype not in MODEL_FILES:
        raise typer.BadParameter(f"expected one of {sorted(MODEL_FILES)}")
    _guard(lambda: _do_embed(_db(ctx), backend, model, force=force, dtype=dtype))


# --------------------------------------------------------------------------- aggregate / publish


def print_snapshot_summary(snapshot: dict[str, Any]) -> None:
    meta = snapshot["meta"]
    totals = meta["totals"]
    console.print(
        f"[bold]aggregate[/] {meta['backend']}:{meta['model']}, window {meta['window_days']} days: "
        f"{totals['jobs']} jobs, {totals['companies']} companies, "
        f"{totals['with_salary']} with salary, {totals['skills']} skills"
    )
    src = Table(title="sources")
    src.add_column("source")
    src.add_column("jobs", justify="right")
    for s in meta["sources"]:
        src.add_row(s["display_name"], str(s["jobs"]))
    console.print(src)

    skills = Table(title="top skills")
    for col in ("skill", "category", "count", "share", "change 4w (pp)", "median USD"):
        skills.add_column(col, justify="left" if col in ("skill", "category") else "right")
    for sk in snapshot["skills"][:15]:
        change = "n/a" if sk["change_4w"] is None else f"{sk['change_4w']:+.1f}"
        median = "n/a" if sk["median_salary_usd"] is None else f"{sk['median_salary_usd']:,}"
        skills.add_row(
            sk["name"], sk["category"], str(sk["count"]), f"{sk['share']:.1%}", change, median
        )
    console.print(skills)

    roles = Table(title="roles")
    for col in ("role", "count", "median USD"):
        roles.add_column(col, justify="left" if col == "role" else "right")
    for r in snapshot["roles"]:
        median = "n/a" if r["median_salary_usd"] is None else f"{r['median_salary_usd']:,}"
        roles.add_row(r["role"], str(r["count"]), median)
    console.print(roles)

    sal = Table(title="salary by seniority (annual USD)")
    for col in ("seniority", "n", "p25", "median", "p75"):
        sal.add_column(col, justify="left" if col == "seniority" else "right")
    for d in snapshot["salary"]["by_seniority"]:
        sal.add_row(d["key"], str(d["n"]), f"{d['p25']:,}", f"{d['median']:,}", f"{d['p75']:,}")
    console.print(sal)


@app.command("aggregate")
def aggregate_cmd(
    ctx: typer.Context,
    backend: BackendOption = None,
    model: ModelOption = None,
    window_days: Annotated[int, typer.Option(help="Window length in days.")] = WINDOW_DAYS,
) -> None:
    """Print the aggregate summary (writes nothing)."""

    def go() -> None:
        with session_scope(_db(ctx)) as session:
            snapshot = aggregate(session, backend=backend, model=model, window_days=window_days)
        print_snapshot_summary(snapshot)

    _guard(go)


def _do_publish(
    db: Path | None,
    out: Path | None,
    backend: str | None = None,
    model: str | None = None,
    allow_empty: bool = False,
    window_days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    result = publish(
        db, out, backend=backend, model=model, allow_empty=allow_empty, window_days=window_days
    )
    console.print(
        f"published {result['jobs']} jobs, {result['skills']} skills, "
        f"{result['jobs_listed']} listed postings, {result['vectors']} job vectors, "
        f"{result['companies']} companies to {result['out_dir']}"
    )
    return result


@app.command("publish")
def publish_cmd(
    ctx: typer.Context,
    out: Annotated[
        Path | None, typer.Option("--out", help="Output directory (default: web/public/data).")
    ] = None,
    backend: BackendOption = None,
    model: ModelOption = None,
    window_days: Annotated[int, typer.Option(help="Window length in days.")] = WINDOW_DAYS,
    allow_empty: Annotated[
        bool, typer.Option(help="Publish even when no jobs are in the window.")
    ] = False,
) -> None:
    """Write the snapshot JSON files for the dashboard."""
    _guard(lambda: _do_publish(_db(ctx), out, backend, model, allow_empty, window_days))


# --------------------------------------------------------------------------- run-all


@app.command("run-all")
def run_all(
    ctx: typer.Context,
    backend: BackendOption = None,
    model: ModelOption = None,
    limit: Annotated[int | None, typer.Option(help="Extract at most N jobs.")] = None,
    since_days: Annotated[int | None, typer.Option(help="Only extract jobs from N days.")] = None,
    workers: Annotated[int, typer.Option(help="Parallel calls (Claude only).")] = DEFAULT_WORKERS,
    out: Annotated[Path | None, typer.Option("--out", help="Publish directory.")] = None,
) -> None:
    """fetch -> ingest -> extract -> embed -> publish. Stops with exit code 1 on a fatal error."""
    db = _db(ctx)

    def go() -> None:
        _do_fetch(db)
        _do_ingest(db)
        _do_extract(db, backend, model, limit=limit, since_days=since_days, workers=workers)
        _do_embed(db, backend, model)
        # Publish from the backend/model that was just extracted (or the configured current
        # one when none was given).
        _do_publish(db, out, backend=backend, model=model)

    _guard(go)


# --------------------------------------------------------------------------- stats


def collect_stats(session) -> dict[str, Any]:
    def count(stmt) -> int:
        return session.scalar(stmt) or 0

    extractions = session.execute(
        select(
            Extraction.backend,
            Extraction.model,
            Extraction.prompt_version,
            func.count(func.distinct(Extraction.job_id)).filter(Extraction.ok.is_(True)),
            func.count().filter(Extraction.ok.is_(False)),
        ).group_by(Extraction.backend, Extraction.model, Extraction.prompt_version)
    ).all()
    return {
        "raw": count(select(func.count()).select_from(RawJob)),
        "jobs": count(select(func.count()).select_from(Job)),
        "canonical": count(
            select(func.count()).select_from(Job).where(Job.is_duplicate_of.is_(None))
        ),
        "remote": count(
            select(func.count())
            .select_from(Job)
            .where(Job.is_duplicate_of.is_(None), Job.is_remote.is_(True))
        ),
        "extractions": [
            {
                "backend": b,
                "model": m,
                "prompt_version": pv,
                "jobs_ok": ok,
                "failures": failed,
            }
            for b, m, pv, ok, failed in extractions
        ],
        "job_skill_rows": count(select(func.count()).select_from(JobSkill)),
        "distinct_skills": count(select(func.count(func.distinct(JobSkill.skill)))),
    }


@app.command()
def stats(ctx: typer.Context) -> None:
    """Show row counts for every stage."""
    with session_scope(_db(ctx)) as session:
        data = collect_stats(session)
    table = Table(title="pipeline")
    table.add_column("metric")
    table.add_column("value", justify="right")
    table.add_row("raw jobs", str(data["raw"]))
    table.add_row("jobs", str(data["jobs"]))
    table.add_row("canonical", str(data["canonical"]))
    table.add_row("canonical remote", str(data["remote"]))
    table.add_row("job_skill rows", str(data["job_skill_rows"]))
    table.add_row("distinct skills", str(data["distinct_skills"]))
    console.print(table)

    ext = Table(title="extractions (backend, model, prompt)")
    ext.add_column("backend")
    ext.add_column("model")
    ext.add_column("prompt")
    ext.add_column("jobs extracted ok", justify="right")
    ext.add_column("failed attempts", justify="right")
    for e in data["extractions"]:
        ext.add_row(
            e["backend"], e["model"], e["prompt_version"], str(e["jobs_ok"]), str(e["failures"])
        )
    if not data["extractions"]:
        ext.add_row("-", "-", "-", "0", "0")
    console.print(ext)


if __name__ == "__main__":  # pragma: no cover
    app()
