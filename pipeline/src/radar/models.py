"""SQLAlchemy models. SQLite is the local source of truth."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC timestamp. SQLite has no timezone type, so everything is stored as UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawJob(Base):
    """Exactly what the source API returned for one posting, kept for replay."""

    __tablename__ = "raw_jobs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_raw_source_ext"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON)

    job: Mapped[Job | None] = relationship(back_populates="raw", uselist=False)


class Job(Base):
    """Normalized posting: one row per raw job, with source-agnostic fields."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_job_id: Mapped[int] = mapped_column(ForeignKey("raw_jobs.id"), unique=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(128))

    title: Mapped[str] = mapped_column(String(512))
    company: Mapped[str] = mapped_column(String(256), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    description_text: Mapped[str] = mapped_column(Text, default="")

    salary_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String(8), nullable=True)

    source_tags: Mapped[list] = mapped_column(JSON, default=list)
    source_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    employment_type_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seniority_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    dedupe_key: Mapped[str] = mapped_column(String(40), index=True)
    is_duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    raw: Mapped[RawJob] = relationship(back_populates="job")
    extractions: Mapped[list[Extraction]] = relationship(back_populates="job")
    skills: Mapped[list[JobSkill]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Extraction(Base):
    """One LLM extraction attempt for a job, tagged with the backend and model used."""

    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    backend: Mapped[str] = mapped_column(String(16), index=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    job: Mapped[Job] = relationship(back_populates="extractions")


class JobSkill(Base):
    """Canonical skills per job, derived from the job's current extraction."""

    __tablename__ = "job_skills"
    __table_args__ = (UniqueConstraint("job_id", "skill", name="uq_job_skill"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    extraction_id: Mapped[int] = mapped_column(ForeignKey("extractions.id"))
    skill: Mapped[str] = mapped_column(String(64), index=True)

    job: Mapped[Job] = relationship(back_populates="skills")
