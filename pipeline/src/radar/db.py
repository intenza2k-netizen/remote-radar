"""Engine and session helpers, plus the raw-job upsert."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from radar.config import DB_PATH
from radar.models import Base, RawJob, utcnow
from radar.sources.base import SourceJob

_engines: dict[str, tuple] = {}


def _get(db_path: Path | None = None):
    path = Path(db_path or DB_PATH)
    key = str(path)
    if key not in _engines:
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
        Base.metadata.create_all(engine)
        _engines[key] = (engine, sessionmaker(bind=engine, expire_on_commit=False))
    return _engines[key]


@contextmanager
def session_scope(db_path: Path | None = None):
    _, factory = _get(db_path)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert_raw_jobs(session: Session, items: Iterable[SourceJob]) -> tuple[int, int]:
    """Insert unseen postings and refresh last_seen_at on known ones. Returns (new, seen)."""
    new = seen = 0
    now = utcnow()
    for item in items:
        existing = session.scalar(
            select(RawJob).where(
                RawJob.source == item.source, RawJob.external_id == item.external_id
            )
        )
        if existing:
            existing.last_seen_at = now
            seen += 1
        else:
            session.add(
                RawJob(
                    source=item.source,
                    external_id=item.external_id,
                    payload=item.payload,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            new += 1
    session.flush()
    return new, seen
