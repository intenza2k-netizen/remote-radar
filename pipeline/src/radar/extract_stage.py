"""Pipeline stage 3: run the LLM extractor over canonical remote jobs and store every attempt.

Error policy
------------
* Configuration problems abort the stage with a clear message (:class:`StageError`):
  a missing Anthropic key, Anthropic authentication / permission errors, and an Ollama
  server that is unreachable or lacks the model. Nothing is stored for the job that hit
  them, and everything stored before stays committed.
* Any other exception for one job is logged, stored as an ``ok=False`` extraction, and the
  run continues.

All database writes happen on the calling thread. With the Claude backend the model calls
run in a thread pool; Ollama runs sequentially.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import anthropic
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from sqlalchemy import delete, func, select

from radar import config
from radar.db import session_scope
from radar.extract import ExtractionResult, Extractor, JobInput
from radar.extract.llm import MissingApiKeyError
from radar.ingest import StageError, track_run
from radar.models import Extraction, Job, JobSkill, utcnow
from radar.skills import normalize_skills

log = logging.getLogger(__name__)

DEFAULT_WORKERS = 4


def current_model(backend: str) -> str:
    """The configured model for ``backend``."""
    return config.CLAUDE_MODEL if backend == "claude" else config.OLLAMA_MODEL


def current_backend_model() -> tuple[str, str]:
    """The extraction backend and model whose output the published snapshot is built from."""
    backend = config.DEFAULT_BACKEND
    return backend, current_model(backend)


def prompt_version_of(extractor: Any) -> str:
    return getattr(extractor, "prompt_version", config.PROMPT_VERSION)


def fatal_message(exc: BaseException, backend: str, model: str) -> str | None:
    """A user-facing message if ``exc`` is a configuration error that must abort the stage."""
    if isinstance(exc, MissingApiKeyError):
        return str(exc)
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return (
            f"Anthropic rejected the API key ({type(exc).__name__}). "
            "Check ANTHROPIC_API_KEY and that it may use this model."
        )
    text = str(exc)
    if isinstance(exc, RuntimeError) and (
        "Cannot reach the Ollama server" in text or "not found. Run: ollama pull" in text
    ):
        return text
    if backend == "ollama" and isinstance(exc, ConnectionError):
        return "Cannot reach the Ollama server. Start it (ollama serve) or set OLLAMA_HOST."
    return None


# --------------------------------------------------------------------------- summary


@dataclass
class ExtractSummary:
    targets: int = 0
    ok: int = 0
    failed: int = 0
    median_latency_ms: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    skills_rebuilt: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        return d


# --------------------------------------------------------------------------- targets


def select_targets(
    session,
    extractor: Extractor,
    *,
    limit: int | None = None,
    since_days: int | None = None,
    force: bool = False,
    now=None,
) -> list[Job]:
    """Canonical remote jobs still lacking an ok extraction for this backend/model/prompt,
    newest first."""
    when = func.coalesce(Job.posted_at, Job.created_at)
    stmt = select(Job).where(Job.is_duplicate_of.is_(None), Job.is_remote.is_(True))
    if not force:
        done = select(Extraction.job_id).where(
            Extraction.ok.is_(True),
            Extraction.backend == extractor.backend,
            Extraction.model == extractor.model,
            Extraction.prompt_version == prompt_version_of(extractor),
        )
        stmt = stmt.where(Job.id.not_in(done))
    if since_days is not None:
        cutoff = (now or utcnow()) - timedelta(days=since_days)
        stmt = stmt.where(when >= cutoff)
    stmt = stmt.order_by(when.desc(), Job.id.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def job_input(job: Job) -> JobInput:
    return JobInput(
        title=job.title,
        company=job.company,
        location=job.location,
        description_text=job.description_text or "",
        salary_text=job.salary_text,
        source_tags=list(job.source_tags or []),
    )


# --------------------------------------------------------------------------- storing


def _store(session, job_id: int, result: ExtractionResult) -> Extraction:
    row = Extraction(
        job_id=job_id,
        backend=result.backend,
        model=result.model,
        prompt_version=result.prompt_version,
        ok=result.ok,
        error=result.error,
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        raw_output=result.raw_output,
        data=result.data.model_dump() if result.data is not None else None,
    )
    session.add(row)
    session.flush()
    return row


def rebuild_job_skills(session, job_id: int, extraction: Extraction) -> None:
    """Replace the job's ``JobSkill`` rows with the canonical skills of ``extraction``."""
    session.execute(delete(JobSkill).where(JobSkill.job_id == job_id))
    slugs = normalize_skills((extraction.data or {}).get("skills", []))
    session.add_all(
        JobSkill(job_id=job_id, extraction_id=extraction.id, skill=slug) for slug in slugs
    )


def _failure(extractor: Extractor, exc: BaseException) -> ExtractionResult:
    return ExtractionResult(
        backend=extractor.backend,
        model=extractor.model,
        prompt_version=prompt_version_of(extractor),
        ok=False,
        data=None,
        error=f"{type(exc).__name__}: {exc}"[:500],
        raw_output=None,
        latency_ms=0,
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
    )


# --------------------------------------------------------------------------- the stage


def run_extract(
    extractor: Extractor | Callable[[], Extractor],
    db_path: Path | None = None,
    *,
    limit: int | None = None,
    since_days: int | None = None,
    force: bool = False,
    workers: int = DEFAULT_WORKERS,
    set_current: bool = False,
    console: Console | None = None,
    show_progress: bool = True,
    now=None,
    on_result: Callable[[int, ExtractionResult], None] | None = None,
) -> ExtractSummary:
    """Extract every target job with ``extractor`` (or the extractor a factory returns); see
    the module docstring for the error policy."""
    summary = ExtractSummary()
    latencies: list[int] = []

    with track_run("extract", db_path) as run, session_scope(db_path) as session:
        if not hasattr(extractor, "extract"):  # a factory: build it inside the tracked run
            try:
                extractor = extractor()
            except Exception as exc:
                raise StageError(
                    fatal_message(exc, "", "") or f"cannot start the extractor: {exc}"
                ) from exc
        backend, model = extractor.backend, extractor.model
        cur_backend, cur_model = current_backend_model()
        is_current = set_current or (backend == cur_backend and model == cur_model)
        pool_size = max(1, workers) if backend == "claude" else 1
        summary.skills_rebuilt = is_current
        run.stats = {"backend": backend, "model": model}
        jobs = select_targets(
            session, extractor, limit=limit, since_days=since_days, force=force, now=now
        )
        work = [(job.id, job_input(job)) for job in jobs]
        summary.targets = len(work)

        progress = Progress(
            TextColumn("[bold]extract[/] {task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            disable=not show_progress or not work,
        )

        def record(job_id: int, result: ExtractionResult) -> None:
            row = _store(session, job_id, result)
            if result.ok:
                summary.ok += 1
                if is_current:
                    rebuild_job_skills(session, job_id, row)
            else:
                summary.failed += 1
            if result.latency_ms:
                latencies.append(result.latency_ms)
            summary.input_tokens += result.input_tokens or 0
            summary.output_tokens += result.output_tokens or 0
            summary.cost_usd += result.cost_usd or 0.0
            session.commit()
            if on_result:
                on_result(job_id, result)

        def fail_fatal(exc: BaseException) -> StageError:
            message = fatal_message(exc, backend, model)
            assert message is not None
            summary.median_latency_ms = statistics.median(latencies) if latencies else None
            run.stats = {**run.stats, **summary.as_dict()}
            return StageError(message)

        with progress:
            task = progress.add_task(f"{backend}:{model}", total=len(work))
            try:
                if pool_size == 1:
                    for job_id, inp in work:
                        try:
                            result = extractor.extract(inp)
                        except Exception as exc:
                            if fatal_message(exc, backend, model):
                                raise fail_fatal(exc) from exc
                            log.warning("extraction failed for job %s: %s", job_id, exc)
                            result = _failure(extractor, exc)
                        record(job_id, result)
                        progress.advance(task)
                else:
                    _run_pool(extractor, work, pool_size, record, progress, task, fail_fatal)
            finally:
                summary.median_latency_ms = statistics.median(latencies) if latencies else None

        run.stats = {**run.stats, **summary.as_dict()}
        if summary.failed:
            run.status = "partial"
            run.error = f"{summary.failed} extraction(s) failed"
        return summary


def _run_pool(extractor, work, pool_size, record, progress, task, fail_fatal) -> None:
    """Bounded thread pool: at most ``pool_size`` calls in flight; results recorded here."""
    pending: dict[Future, int] = {}
    queue = iter(work)
    executor = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="extract")
    try:
        while True:
            while len(pending) < pool_size:
                nxt = next(queue, None)
                if nxt is None:
                    break
                job_id, inp = nxt
                pending[executor.submit(extractor.extract, inp)] = job_id
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                job_id = pending.pop(fut)
                try:
                    result = fut.result()
                except Exception as exc:
                    if fatal_message(exc, extractor.backend, extractor.model):
                        raise fail_fatal(exc) from exc
                    log.warning("extraction failed for job %s: %s", job_id, exc)
                    result = _failure(extractor, exc)
                record(job_id, result)
                progress.advance(task)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
