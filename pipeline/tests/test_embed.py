"""Tests for radar.embed: passage text, int8 packing, the embedding cache, publishing.

No model is downloaded: embedding goes through a deterministic fake embedder.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import func, select
from test_pipeline import (  # noqa: F401  (fixtures reused for the end-to-end test)
    NOW,
    _fast_and_isolated,
    db,
    extracted,
    ingested,
)

from radar import config, embed
from radar.aggregate import JobRecord
from radar.db import session_scope
from radar.models import JobEmbedding, Run
from radar.publish import publish


class FakeEmbedder:
    """Deterministic unit vectors derived from the text; records every batch it embeds."""

    dim = config.EMBED_DIM

    def __init__(self, model_key: str = "fake:fp32") -> None:
        self.model_key = model_key
        self.calls: list[list[str]] = []

    def embed(self, texts, *, query: bool = False) -> np.ndarray:
        texts = [config.EMBED_QUERY_PREFIX + t if query else t for t in texts]
        self.calls.append(list(texts))
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")
            rows.append(np.random.default_rng(seed).normal(size=self.dim))
        return embed.normalize_rows(np.array(rows))

    @property
    def n_embedded(self) -> int:
        return sum(len(c) for c in self.calls)


def make_record(i: int, **overrides) -> JobRecord:
    fields = {
        "id": f"remotive-{i}",
        "source": "remotive",
        "title": f"Data Engineer {i}",
        "company": f"Company {i}",
        "url": f"https://example.com/{i}",
        "location": "Worldwide",
        "posted_at": datetime(2026, 11, 1),
        "role": "data",
        "seniority": "senior",
        "employment_type": "full_time",
        "remote_regions": ["worldwide"],
        "skills": ["python", "sql"],
        "db_id": 100 + i,
        "description": f"We are hiring engineer number {i}.",
    }
    fields.update(overrides)
    return JobRecord(**fields)


# --------------------------------------------------------------------------- passage text


def test_passage_text_has_title_role_seniority_skills_and_description():
    rec = make_record(
        1,
        title="Senior  Data Engineer",
        role="software_engineering",
        skills=["python", "sql", "ruby-on-rails"],
        description="  Build   pipelines.\n\nOn call.  ",
    )
    assert embed.passage_text(rec) == (
        "Senior Data Engineer. Role: software engineering. Seniority: senior. "
        "Skills: Python, SQL, Ruby on Rails.\nBuild pipelines. On call."
    )


def test_passage_text_omits_unspecified_seniority_empty_skills_and_company():
    rec = make_record(1, seniority="unspecified", skills=[], description="", company="Secret Inc")
    text = embed.passage_text(rec)
    assert text == "Data Engineer 1. Role: data."
    assert "Secret" not in text


def test_passage_text_truncates_description_and_limits_skills():
    skills = ["python", "sql", "dbt", "airflow", "spark", "kafka", "aws", "docker", "git", "rust"]
    rec = make_record(1, skills=skills, description="word " * 1000)
    text = embed.passage_text(rec)
    header, description = text.split("\n")
    assert len(description) <= config.EMBED_DESCRIPTION_CHARS
    assert description.startswith("word word")
    assert header.count(",") == config.EMBED_TOP_SKILLS - 1  # only the first 8 skills
    assert "Rust" not in header


def test_text_hash_changes_with_text_and_is_stable():
    assert embed.text_hash("a") == embed.text_hash("a")
    assert embed.text_hash("a") != embed.text_hash("b")
    assert len(embed.text_hash("a")) == 64


# --------------------------------------------------------------------------- int8 packing


def cosine_rows(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a * b).sum(axis=1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))


def test_int8_round_trip_keeps_cosine_above_0_999():
    rng = np.random.default_rng(7)
    vectors = embed.normalize_rows(rng.normal(size=(50, config.EMBED_DIM)))
    quantized, scales = embed.quantize_int8(vectors)
    assert quantized.dtype == np.int8 and quantized.shape == vectors.shape
    assert int(np.abs(quantized).max()) <= 127
    restored = embed.dequantize_int8(quantized, scales)
    assert cosine_rows(vectors, restored).min() >= 0.999


def test_int8_handles_zero_rows_and_scales_are_positive():
    vectors = np.zeros((2, 8))
    vectors[1, 3] = 0.5
    quantized, scales = embed.quantize_int8(vectors)
    assert all(s > 0 for s in scales)
    assert not quantized[0].any()
    assert quantized[1, 3] == 127 and abs(scales[1] * 127 - 0.5) < 1e-6
    empty, no_scales = embed.quantize_int8(np.zeros((0, 8)))
    assert empty.shape == (0, 8) and no_scales == []


def test_job_vectors_document_matches_the_contract_and_decodes():
    rng = np.random.default_rng(1)
    vectors = embed.normalize_rows(rng.normal(size=(3, config.EMBED_DIM)))
    doc = embed.job_vectors_from(["a-1", "b-2", "c-3"], vectors)
    assert doc["model"] == "Xenova/bge-small-en-v1.5"
    assert doc["python_model"] == "BAAI/bge-small-en-v1.5"
    assert (doc["dim"], doc["normalized"], doc["pooling"]) == (384, True, "cls")
    assert doc["query_prefix"] == "Represent this sentence for searching relevant passages: "
    assert doc["encoding"] == "int8-base64"
    assert doc["ids"] == ["a-1", "b-2", "c-3"] and len(doc["scales"]) == 3
    assert len(base64.b64decode(doc["data"])) == 3 * 384
    ids, restored = embed.decode_job_vectors(json.loads(json.dumps(doc)))
    assert ids == doc["ids"]
    assert cosine_rows(vectors, restored).min() >= 0.999


def test_empty_job_vectors_document():
    doc = embed.job_vectors_from([], np.zeros((0, config.EMBED_DIM)))
    assert doc["ids"] == [] and doc["scales"] == [] and doc["data"] == ""
    assert embed.decode_job_vectors(doc)[1].shape == (0, 384)


# --------------------------------------------------------------------------- cache


def count_rows(session) -> int:
    return session.scalar(select(func.count()).select_from(JobEmbedding))


def test_cache_embeds_only_new_and_changed_jobs(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    fake = FakeEmbedder()
    records = [make_record(i) for i in range(5)]

    with session_scope(db_path) as session:
        first = embed.embed_jobs(session, records, fake)
    assert (first.total, first.embedded, first.cached) == (5, 5, 0)
    assert fake.n_embedded == 5

    with session_scope(db_path) as session:
        again = embed.embed_jobs(session, records, fake)
        assert (again.embedded, again.cached) == (0, 5)
        assert count_rows(session) == 5
    assert fake.n_embedded == 5  # the model was not called again

    # one job's description changes, one new job appears
    records[2] = make_record(2, description="A completely different posting text.")
    records.append(make_record(9))
    with session_scope(db_path) as session:
        third = embed.embed_jobs(session, records, fake)
        assert (third.embedded, third.cached) == (2, 4)
        assert count_rows(session) == 6  # the stale row of job 2 was replaced, not kept
    assert fake.n_embedded == 7


def test_cache_is_keyed_by_model_and_force_reembeds(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    records = [make_record(i) for i in range(3)]
    with session_scope(db_path) as session:
        embed.embed_jobs(session, records, FakeEmbedder("model-a"))
        other = embed.embed_jobs(session, records, FakeEmbedder("model-b"))
        assert other.embedded == 3 and count_rows(session) == 6
        forced = FakeEmbedder("model-a")
        again = embed.embed_jobs(session, records, forced, force=True)
        assert again.embedded == 3 and forced.n_embedded == 3
        assert count_rows(session) == 6  # replaced in place


def test_cached_vectors_are_what_the_embedder_returned(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    fake = FakeEmbedder()
    records = [make_record(i) for i in range(3)]
    with session_scope(db_path) as session:
        embed.embed_jobs(session, records, fake)
        passages = embed.build_passages(records)
        loaded = embed.load_vectors(session, fake.model_key, passages)
    expected = fake.embed([p.text for p in passages])
    for passage, row in zip(passages, expected, strict=True):
        assert np.allclose(loaded[passage.record_id], row, atol=1e-7)


def test_vectors_document_skips_jobs_without_a_current_vector(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    fake = FakeEmbedder()
    records = [make_record(i) for i in range(4)]
    with session_scope(db_path) as session:
        embed.embed_jobs(session, records[:3], fake)
        doc, missing = embed.job_vectors_document(session, records, fake.model_key)
        assert doc["ids"] == ["remotive-0", "remotive-1", "remotive-2"] and missing == 1
        # job 1's text changed and was not re-embedded: its old vector must not be published
        records[1] = make_record(1, description="changed")
        doc, missing = embed.job_vectors_document(session, records, fake.model_key)
        assert doc["ids"] == ["remotive-0", "remotive-2"] and missing == 2
        # another model key sees nothing
        doc, missing = embed.job_vectors_document(session, records, "other")
        assert doc["ids"] == [] and missing == 4


def test_embedder_batches_by_the_chunk_size(tmp_path):
    fake = FakeEmbedder()
    records = [make_record(i) for i in range(10)]
    with session_scope(tmp_path / "c.sqlite") as session:
        seen = []
        embed.embed_jobs(session, records, fake, chunk_size=4, progress=lambda d, t: seen.append(d))
    assert [len(c) for c in fake.calls] == [4, 4, 2]
    assert seen == [4, 8, 10]


# --------------------------------------------------------------------------- model files


def test_model_cache_dir_reads_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RADAR_MODEL_CACHE", str(tmp_path / "models"))
    assert embed.model_cache_dir() == tmp_path / "models"
    monkeypatch.delenv("RADAR_MODEL_CACHE")
    assert embed.model_cache_dir() == config.DATA_DIR / "models"  # never ~/.cache


def test_ensure_model_files_uses_the_cache_and_rejects_unknown_dtype(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("must not download when the files are present")

    monkeypatch.setattr(embed, "_download", no_network)
    root = tmp_path / "Xenova--bge-small-en-v1.5" / embed.MODEL_REVISION[:12]
    (root / "onnx").mkdir(parents=True)
    (root / "onnx" / "model.onnx").write_bytes(b"x")
    (root / "tokenizer.json").write_bytes(b"{}")
    onnx, tokenizer = embed.ensure_model_files("fp32", tmp_path)
    assert onnx == root / "onnx" / "model.onnx" and tokenizer == root / "tokenizer.json"
    with pytest.raises(ValueError, match="unknown dtype"):
        embed.ensure_model_files("int3", tmp_path)


def test_download_verifies_the_checksum(tmp_path, monkeypatch):
    import httpx

    payload = b"model bytes"

    def handler(request):
        return httpx.Response(200, content=payload)

    def fake_stream(method, url, **kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler)).stream(method, url)

    monkeypatch.setattr(embed.httpx, "stream", fake_stream)
    dest = tmp_path / "a" / "model.onnx"
    embed._download("https://x/y", dest, hashlib.sha256(payload).hexdigest(), label="t")
    assert dest.read_bytes() == payload
    bad = tmp_path / "b" / "model.onnx"
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        embed._download("https://x/y", bad, "0" * 64, label="t")
    assert not bad.exists() and not bad.with_name("model.onnx.part").exists()


# --------------------------------------------------------------------------- end to end


def test_run_embed_then_publish_writes_aligned_vectors(extracted, tmp_path):  # noqa: F811
    fake = FakeEmbedder(embed.current_model_key())
    summary = embed.run_embed(extracted, embedder=fake, now=NOW)
    assert summary.embedded == summary.total > 0 and summary.cached == 0

    again = embed.run_embed(extracted, embedder=fake, now=NOW)
    assert again.embedded == 0 and again.cached == summary.total
    with session_scope(extracted) as s:
        runs = list(s.scalars(select(Run).where(Run.stage == "embed").order_by(Run.id)))
    assert [r.status for r in runs] == ["ok", "ok"]
    assert runs[0].stats["embedded"] == summary.total

    out = tmp_path / "out"
    result = publish(extracted, out, now=NOW)
    jobs = json.loads((out / "jobs.json").read_text(encoding="utf-8"))
    vectors = json.loads((out / "job_vectors.json").read_text(encoding="utf-8"))
    assert vectors["ids"] == [j["id"] for j in jobs]  # same ids, same order
    assert result["missing_vectors"] == 0 and result["vectors"] == len(jobs)
    ids, matrix = embed.decode_job_vectors(vectors)
    assert matrix.shape == (len(jobs), 384)
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=0.01)


def test_run_embed_loads_no_model_when_everything_is_cached(extracted, monkeypatch):  # noqa: F811
    embed.run_embed(extracted, embedder=FakeEmbedder(embed.current_model_key()), now=NOW)

    def boom(*args, **kwargs):
        raise AssertionError("the model must not be loaded")

    monkeypatch.setattr(embed, "OnnxEmbedder", boom)
    summary = embed.run_embed(extracted, now=NOW)
    assert summary.embedded == 0 and summary.cached == summary.total


def test_publish_without_embeddings_leaves_vectors_empty(extracted, tmp_path):  # noqa: F811
    out = tmp_path / "out"
    result = publish(extracted, out, now=NOW)
    vectors = json.loads((out / "job_vectors.json").read_text(encoding="utf-8"))
    assert vectors["ids"] == [] and result["missing_vectors"] == result["jobs_listed"] > 0


def test_cli_run_all_embeds_before_publishing(db, monkeypatch):  # noqa: F811
    from typer.testing import CliRunner

    from radar import cli

    calls: list[str] = []
    monkeypatch.setattr(cli, "fetch_sources", lambda d: {"sources": {}, "new": 0, "seen": 0})
    monkeypatch.setattr(
        cli,
        "ingest_raw_jobs",
        lambda d: {"pending": 0, "canonical": 0, "duplicates": 0, "errors": 0},
    )
    monkeypatch.setattr(cli, "_do_extract", lambda *a, **k: calls.append("extract"))
    monkeypatch.setattr(
        cli, "run_embed", lambda *a, **k: calls.append("embed") or embed.EmbedSummary()
    )
    monkeypatch.setattr(cli, "publish", lambda *a, **k: calls.append("publish") or _fake_publish())
    result = CliRunner().invoke(cli.app, ["--db", str(db), "run-all", "--out", str(db.parent)])
    assert result.exit_code == 0, result.output
    assert calls == ["extract", "embed", "publish"]


def _fake_publish() -> dict:
    return {
        "jobs": 0,
        "skills": 0,
        "jobs_listed": 0,
        "vectors": 0,
        "companies": 0,
        "out_dir": "x",
    }


def test_cli_embed_command_reports_counts(db, monkeypatch):  # noqa: F811
    from typer.testing import CliRunner

    from radar import cli

    monkeypatch.setattr(
        cli, "run_embed", lambda *a, **k: embed.EmbedSummary(total=7, embedded=2, cached=5)
    )
    result = CliRunner().invoke(cli.app, ["--db", str(db), "embed"])
    assert result.exit_code == 0, result.output
    assert "7 listed jobs, 2 embedded, 5 cached" in result.output
    bad = CliRunner().invoke(cli.app, ["--db", str(db), "embed", "--dtype", "int3"])
    assert bad.exit_code != 0
