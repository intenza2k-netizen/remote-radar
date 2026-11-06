"""Pipeline stage 5: write the snapshot JSON files the dashboard reads.

Writes ``meta.json``, ``skills.json``, ``roles.json``, ``salary.json`` and ``jobs.json``.
It never writes ``eval.json`` (owned by the eval step) and never emits a ``sample`` key.
Files are written to temporary names first and then renamed over the old ones, so a crash
leaves the previous snapshot intact.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from radar import config
from radar.aggregate import WINDOW_DAYS, aggregate
from radar.db import session_scope
from radar.ingest import StageError, track_run

FILES = {
    "meta": "meta.json",
    "skills": "skills.json",
    "roles": "roles.json",
    "salary": "salary.json",
    "jobs": "jobs.json",
}


def write_snapshot(snapshot: dict[str, Any], out_dir: Path) -> list[Path]:
    """Write all documents atomically (temp files first, then renames)."""
    if set(snapshot) != set(FILES):
        raise ValueError(f"snapshot must have exactly the keys {sorted(FILES)}")
    if "sample" in snapshot["meta"]:
        raise ValueError("refusing to publish a snapshot flagged as sample data")
    out_dir.mkdir(parents=True, exist_ok=True)

    staged: list[tuple[Path, Path]] = []
    try:
        for key, filename in FILES.items():
            final = out_dir / filename
            tmp = out_dir / f".{filename}.tmp"
            tmp.write_text(
                json.dumps(snapshot[key], ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            staged.append((tmp, final))
        for tmp, final in staged:
            os.replace(tmp, final)
    except BaseException:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise
    return [final for _, final in staged]


def publish(
    db_path: Path | None = None,
    out_dir: Path | None = None,
    *,
    backend: str | None = None,
    model: str | None = None,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
    allow_empty: bool = False,
) -> dict[str, Any]:
    """Aggregate the database and write the snapshot to ``out_dir`` (default: the web app)."""
    target = Path(out_dir) if out_dir else config.WEB_DATA_DIR
    with track_run("publish", db_path) as run:
        with session_scope(db_path) as session:
            snapshot = aggregate(
                session, backend=backend, model=model, now=now, window_days=window_days
            )
        meta = snapshot["meta"]
        run.stats = {
            "out_dir": str(target),
            "backend": meta["backend"],
            "model": meta["model"],
            "jobs": meta["totals"]["jobs"],
            "skills": meta["totals"]["skills"],
            "with_salary": meta["totals"]["with_salary"],
            "jobs_listed": len(snapshot["jobs"]),
        }
        if meta["totals"]["jobs"] == 0 and not allow_empty:
            raise StageError(
                f"no extracted jobs in the window for {meta['backend']}:{meta['model']}; "
                "refusing to overwrite the published snapshot (run `radar extract` first, "
                "or pass --allow-empty)"
            )
        files = write_snapshot(snapshot, target)
        run.stats["files"] = [f.name for f in files]
        return {**run.stats, "snapshot": snapshot}
