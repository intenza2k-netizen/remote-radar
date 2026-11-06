"""Pipeline stage: embed job postings for the in-browser CV matcher (PLAN.md section 5).

Compatibility with the browser (transformers.js), settings recorded here on purpose
----------------------------------------------------------------------------------
The website embeds a CV in the browser with ``@huggingface/transformers`` and the model
``Xenova/bge-small-en-v1.5``. Job vectors are only comparable with those CV vectors if both
sides use the same weights and conventions, so this module mirrors the browser exactly:

* Weights: the ONNX export ``Xenova/bge-small-en-v1.5`` of ``BAAI/bge-small-en-v1.5``
  (same weights), pinned to revision ``MODEL_REVISION`` with SHA-256 checked downloads.
  ``dtype="fp32"`` is ``onnx/model.onnx``; ``dtype="q8"`` is ``onnx/model_quantized.onnx``.
* Which dtype: the default is ``fp32`` (``DEFAULT_DTYPE``). Measured with
  ``@huggingface/transformers`` 4.3.2 (2026-11-06): in Node (and on WebGPU) transformers.js
  defaults to fp32, and Python fp32 matches it with cosine 1.00000 on all 5 test sentences;
  in the browser's WASM backend it defaults to ``q8``, and Python fp32 vs that q8 model gives
  cosine 0.9935 to 0.9971 (min 0.9935). The q8 model uses dynamic activation quantisation, so
  its output depends slightly on the batch (single vs batched: cosine ~0.995); fp32 does not
  (cosine 1.0), which makes cached vectors independent of how a run was batched. Hence fp32.
* Runtime: ``onnxruntime`` (CPU) + ``tokenizers``. No PyTorch.
* Tokenizer: the model's own ``tokenizer.json`` (BERT WordPiece, lowercase), truncation at
  ``EMBED_MAX_TOKENS`` (512), ``[CLS] ... [SEP]``, ``token_type_ids`` all zero.
* Pooling: CLS token (``last_hidden_state[:, 0]``), then L2 normalisation. This is what
  ``pipeline("feature-extraction", ...)(text, {pooling: "cls", normalize: true})`` does.
* Passages (jobs) are embedded WITHOUT a prefix. Queries (a CV, a search phrase) get
  ``EMBED_QUERY_PREFIX`` in front, which is the BGE convention for retrieval. The prefix is
  published in ``job_vectors.json`` so the browser uses exactly the same string.

Caching: vectors live in the ``job_embeddings`` table keyed by (job, model, SHA-256 of the
passage text). A nightly run therefore only embeds jobs that are new or whose text changed.

Publishing: ``job_vectors.json`` stores each vector as int8 with its own scale
(``value = int8 * scale``), all rows concatenated and base64 encoded. Per-vector scale is
``max|v| / 127``; the round trip keeps cosine similarity above 0.999.

Model files are cached under ``$RADAR_MODEL_CACHE`` (never the C: drive default).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import httpx
import numpy as np
from sqlalchemy import delete, select

from radar import config
from radar.db import session_scope
from radar.ingest import StageError, track_run
from radar.models import JobEmbedding, utcnow
from radar.skills import skill_info

if TYPE_CHECKING:
    from radar.aggregate import JobRecord

log = logging.getLogger(__name__)

MODEL_REPO = config.EMBED_BROWSER_MODEL
MODEL_REVISION = "ea104dacec62c0de699686887e3f920caeb4f3e3"
# dtype -> (file in the repo, SHA-256). The tokenizer is shared.
MODEL_FILES: dict[str, tuple[str, str]] = {
    "q8": (
        "onnx/model_quantized.onnx",
        "6c9c6101a956d62dfb5e7190c538226c0c5bb9cb27b651234b6df063ee7dbfe4",
    ),
    "fp32": (
        "onnx/model.onnx",
        "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35",
    ),
}
TOKENIZER_FILE = "tokenizer.json"
TOKENIZER_SHA256 = "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
DEFAULT_DTYPE = "fp32"
DEFAULT_BATCH_SIZE = 16


# --------------------------------------------------------------------------- passage text


@dataclass(frozen=True)
class Passage:
    """One job to embed: the DB job id, the published id, the text and its hash."""

    job_id: int
    record_id: str
    text: str
    text_hash: str


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def passage_text(record: JobRecord) -> str:
    """Text embedded for a job: title, role, seniority, top skills, then the description.

    Format (one header line, then the description)::

        <title>. Role: data. Seniority: senior. Skills: Python, SQL, dbt.
        <first EMBED_DESCRIPTION_CHARS characters of the description, whitespace collapsed>

    The company name is left out on purpose so it does not dominate similarity. Roles use
    spaces instead of underscores; ``unspecified`` seniority and an empty skill list are
    omitted. Descriptions are never published, only the vectors derived from them.
    """
    parts = [_squash(record.title).rstrip(".")]
    parts[0] += "."
    if record.role:
        parts.append(f"Role: {record.role.replace('_', ' ')}.")
    if record.seniority and record.seniority != "unspecified":
        parts.append(f"Seniority: {record.seniority}.")
    skills = [skill_info(s).display for s in record.skills[: config.EMBED_TOP_SKILLS]]
    if skills:
        parts.append(f"Skills: {', '.join(skills)}.")
    header = " ".join(parts)
    description = _squash(record.description)[: config.EMBED_DESCRIPTION_CHARS].rstrip()
    return f"{header}\n{description}" if description else header


def build_passages(records: Sequence[JobRecord]) -> list[Passage]:
    out: list[Passage] = []
    for rec in records:
        text = passage_text(rec)
        out.append(Passage(rec.db_id, rec.id, text, text_hash(text)))
    return out


# --------------------------------------------------------------------------- embedders


class Embedder(Protocol):
    """Anything that turns texts into L2-normalised float32 rows."""

    model_key: str  # stored in the cache table; changes when the vectors would change
    dim: int

    def embed(self, texts: Sequence[str], *, query: bool = False) -> np.ndarray: ...


def model_cache_dir() -> Path:
    """``$RADAR_MODEL_CACHE``, else a folder next to the project data (never ``~/.cache``)."""
    env = os.environ.get(config.EMBED_CACHE_ENV)
    return Path(env) if env else config.DATA_DIR / "models"


def _download(url: str, dest: Path, sha256: str, *, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    log.info("downloading %s -> %s", label, dest)
    with (
        httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response,
        part.open("wb") as handle,
    ):
        response.raise_for_status()
        for chunk in response.iter_bytes(1 << 20):
            handle.write(chunk)
            digest.update(chunk)
    if sha256 and digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch for {label}: got {digest.hexdigest()}")
    os.replace(part, dest)


def ensure_model_files(dtype: str, cache_dir: Path | None = None) -> tuple[Path, Path]:
    """Return (onnx path, tokenizer path), downloading into the cache dir when missing."""
    if dtype not in MODEL_FILES:
        raise ValueError(f"unknown dtype {dtype!r}; expected one of {sorted(MODEL_FILES)}")
    root = (cache_dir or model_cache_dir()) / MODEL_REPO.replace("/", "--") / MODEL_REVISION[:12]
    onnx_name, onnx_sha = MODEL_FILES[dtype]
    wanted = [(onnx_name, onnx_sha), (TOKENIZER_FILE, TOKENIZER_SHA256)]
    paths: list[Path] = []
    for name, sha in wanted:
        path = root / name
        if not path.exists():
            url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}"
            _download(url, path, sha, label=f"{MODEL_REPO}/{name}")
        paths.append(path)
    return paths[0], paths[1]


class OnnxEmbedder:
    """bge-small-en-v1.5 on onnxruntime (CPU): CLS pooling, L2 normalised, 384 dimensions."""

    dim = config.EMBED_DIM

    def __init__(
        self,
        dtype: str = DEFAULT_DTYPE,
        cache_dir: Path | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        threads: int | None = None,
    ) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        onnx_path, tokenizer_path = ensure_model_files(dtype, cache_dir)
        self.dtype = dtype
        self.model_key = f"{MODEL_REPO}:{dtype}"
        self.batch_size = batch_size
        options = ort.SessionOptions()
        options.log_severity_level = 3
        if threads:
            options.intra_op_num_threads = threads
        self._session = ort.InferenceSession(
            str(onnx_path), options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        tok = Tokenizer.from_file(str(tokenizer_path))
        tok.enable_truncation(max_length=config.EMBED_MAX_TOKENS)
        tok.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer = tok

    def _run(self, texts: list[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feed: dict[str, Any] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feed)[0]  # (batch, tokens, dim)
        cls = hidden[:, 0, :].astype(np.float32)
        return normalize_rows(cls)

    def embed(self, texts: Sequence[str], *, query: bool = False) -> np.ndarray:
        items = [config.EMBED_QUERY_PREFIX + t if query else t for t in texts]
        out = np.zeros((len(items), self.dim), dtype=np.float32)
        # Longest first inside each batch keeps padding small; results go back in order.
        order = sorted(range(len(items)), key=lambda i: len(items[i]))
        for start in range(0, len(order), self.batch_size):
            idx = order[start : start + self.batch_size]
            out[idx] = self._run([items[i] for i in idx])
        return out


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.maximum(norms, 1e-12)).astype(np.float32)


# --------------------------------------------------------------------------- cache + stage


@dataclass
class EmbedSummary:
    total: int = 0
    embedded: int = 0
    cached: int = 0
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "embedded": self.embedded,
            "cached": self.cached,
            "seconds": round(self.seconds, 2),
        }


def cached_hashes(session, model_key: str, job_ids: Sequence[int]) -> dict[int, set[str]]:
    """job id -> text hashes already stored for this model."""
    found: dict[int, set[str]] = {}
    ids = list(job_ids)
    for start in range(0, len(ids), 500):  # stay below SQLite's variable limit
        chunk = ids[start : start + 500]
        rows = session.execute(
            select(JobEmbedding.job_id, JobEmbedding.text_hash).where(
                JobEmbedding.model == model_key, JobEmbedding.job_id.in_(chunk)
            )
        )
        for job_id, digest in rows:
            found.setdefault(job_id, set()).add(digest)
    return found


def embed_jobs(
    session,
    records: Sequence[JobRecord],
    embedder: Embedder,
    *,
    force: bool = False,
    progress: Callable[[int, int], None] | None = None,
    chunk_size: int = 64,
) -> EmbedSummary:
    """Embed the jobs whose (job, model, text hash) is not cached yet and store the vectors.

    Rows for the same job and model with an older hash are deleted, so a changed posting
    replaces its vector instead of piling up.
    """
    started = time.perf_counter()
    passages = build_passages(records)
    have = {} if force else cached_hashes(session, embedder.model_key, [p.job_id for p in passages])
    todo = [p for p in passages if p.text_hash not in have.get(p.job_id, set())]
    summary = EmbedSummary(total=len(passages), cached=len(passages) - len(todo))

    for start in range(0, len(todo), chunk_size):
        chunk = todo[start : start + chunk_size]
        vectors = embedder.embed([p.text for p in chunk])
        for passage, vector in zip(chunk, vectors, strict=True):
            session.execute(
                delete(JobEmbedding).where(
                    JobEmbedding.job_id == passage.job_id,
                    JobEmbedding.model == embedder.model_key,
                )
            )
            session.add(
                JobEmbedding(
                    job_id=passage.job_id,
                    model=embedder.model_key,
                    text_hash=passage.text_hash,
                    dim=int(vector.shape[0]),
                    vector=np.asarray(vector, dtype="<f4").tobytes(),
                )
            )
        session.flush()
        summary.embedded += len(chunk)
        if progress:
            progress(summary.embedded, len(todo))
    summary.seconds = time.perf_counter() - started
    return summary


def load_vectors(session, model_key: str, passages: Sequence[Passage]) -> dict[str, np.ndarray]:
    """published id -> cached vector for passages whose current text hash is cached."""
    rows: dict[tuple[int, str], bytes] = {}
    ids = [p.job_id for p in passages]
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for job_id, digest, blob in session.execute(
            select(JobEmbedding.job_id, JobEmbedding.text_hash, JobEmbedding.vector).where(
                JobEmbedding.model == model_key, JobEmbedding.job_id.in_(chunk)
            )
        ):
            rows[(job_id, digest)] = blob
    out: dict[str, np.ndarray] = {}
    for p in passages:
        blob = rows.get((p.job_id, p.text_hash))
        if blob is not None:
            out[p.record_id] = np.frombuffer(blob, dtype="<f4").astype(np.float32)
    return out


# --------------------------------------------------------------------------- int8 packing


def quantize_int8(matrix: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """Per-row symmetric int8 quantisation. Returns (int8 matrix, scales) with
    ``matrix ~= int8 * scale[:, None]``. Scales are rounded to 7 significant digits, which is
    what gets published, and the quantisation uses the rounded value."""
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.size == 0:
        return np.zeros((0, matrix.shape[1] if matrix.ndim == 2 else 0), dtype=np.int8), []
    scales = [float(f"{max(float(np.abs(row).max()), 1e-12) / 127:.7g}") for row in matrix]
    scale_col = np.array(scales, dtype=np.float64)[:, None]
    quantized = np.clip(np.rint(matrix / scale_col), -127, 127).astype(np.int8)
    return quantized, scales


def dequantize_int8(quantized: np.ndarray, scales: Sequence[float]) -> np.ndarray:
    return quantized.astype(np.float32) * np.asarray(scales, dtype=np.float32)[:, None]


def job_vectors_from(
    ids: Sequence[str], vectors: np.ndarray, *, dim: int = config.EMBED_DIM
) -> dict[str, Any]:
    """The ``job_vectors.json`` document (PLAN.md section 5) for ``ids`` / ``vectors``."""
    quantized, scales = quantize_int8(vectors) if len(ids) else (np.zeros((0, dim), np.int8), [])
    return {
        "model": config.EMBED_BROWSER_MODEL,
        "python_model": config.EMBED_PYTHON_MODEL,
        "dim": dim,
        "normalized": True,
        "pooling": "cls",
        "query_prefix": config.EMBED_QUERY_PREFIX,
        "encoding": "int8-base64",
        "ids": list(ids),
        "scales": scales,
        "data": base64.b64encode(quantized.tobytes()).decode("ascii"),
    }


def decode_job_vectors(doc: dict[str, Any]) -> tuple[list[str], np.ndarray]:
    """Inverse of :func:`job_vectors_from` (what the browser does): ids and float matrix."""
    n, dim = len(doc["ids"]), doc["dim"]
    raw = np.frombuffer(base64.b64decode(doc["data"]), dtype=np.int8)
    return list(doc["ids"]), dequantize_int8(raw.reshape(n, dim), doc["scales"])


def job_vectors_document(
    session, records: Sequence[JobRecord], model_key: str
) -> tuple[dict[str, Any], int]:
    """Document for the listed records (same order as ``jobs.json``) and the number of
    listed jobs that have no cached vector yet (they are left out of ``ids``)."""
    passages = build_passages(records)
    vectors = load_vectors(session, model_key, passages)
    ids = [p.record_id for p in passages if p.record_id in vectors]
    matrix = np.stack([vectors[i] for i in ids]) if ids else np.zeros((0, config.EMBED_DIM))
    return job_vectors_from(ids, matrix), len(passages) - len(ids)


def current_model_key(dtype: str = DEFAULT_DTYPE) -> str:
    """Cache key of the default embedder, without loading the model."""
    return f"{MODEL_REPO}:{dtype}"


def run_embed(
    db_path: Path | None = None,
    *,
    backend: str | None = None,
    model: str | None = None,
    now=None,
    force: bool = False,
    embedder: Embedder | None = None,
    dtype: str = DEFAULT_DTYPE,
    progress: Callable[[int, int], None] | None = None,
) -> EmbedSummary:
    """Embed the jobs that ``publish`` lists (canonical, remote, current extraction, last 60
    days) that are new or whose passage text changed. ``embedder`` is created lazily, so a
    run with everything cached never loads the model."""
    from radar.aggregate import listed_records, load_snapshot_records

    with track_run("embed", db_path) as run:
        with session_scope(db_path) as session:
            records, backend, model, now = load_snapshot_records(
                session, backend=backend, model=model, now=now or utcnow()
            )
            listed = listed_records(records, now)
            if not listed:
                raise StageError(
                    f"no extracted jobs for {backend}:{model}; run `radar extract` first"
                )
            if embedder is None:
                key = current_model_key(dtype)
                have = cached_hashes(session, key, [r.db_id for r in listed])
                stale = [
                    p for p in build_passages(listed) if p.text_hash not in have.get(p.job_id, ())
                ]
                if force or stale:
                    embedder = OnnxEmbedder(dtype=dtype)
            if embedder is None:  # everything cached: nothing to load
                summary = EmbedSummary(total=len(listed), cached=len(listed))
            else:
                summary = embed_jobs(session, listed, embedder, force=force, progress=progress)
        run.stats = {"backend": backend, "model": model, **summary.as_dict()}
    return summary
