"""Paths and constants shared across the pipeline."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("RADAR_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = DATA_DIR / "jobs.sqlite"
WEB_DATA_DIR = REPO_ROOT / "web" / "public" / "data"
EVAL_DIR = REPO_ROOT / "pipeline" / "eval"

USER_AGENT = "RemoteRadar/0.1 (open-source portfolio project; contact via GitHub)"
HTTP_TIMEOUT = 30.0

# Pages per run for paginated sources: enough for a day of new postings
# without hammering the APIs.
ARBEITNOW_PAGES = 2
JOBICY_PAGES = 3

# Extraction defaults, chosen from the eval (pipeline/eval/report.md, 2026-11-06):
# gemma4:31b had the best skills F1 of four models, within noise of Claude Sonnet 5.5
# on every field, at zero marginal cost and ~1.3 s/job on the RTX 5090.
DEFAULT_BACKEND = os.environ.get("RADAR_BACKEND", "ollama")
OLLAMA_MODEL = os.environ.get("RADAR_OLLAMA_MODEL", "gemma4:31b-it-q4_K_M")
CLAUDE_MODEL = os.environ.get("RADAR_CLAUDE_MODEL", "claude-sonnet-5-5")
PROMPT_VERSION = "v1"

# Job embeddings for the in-browser CV matcher (PLAN.md section 5). The browser loads
# EMBED_BROWSER_MODEL with transformers.js; the pipeline runs the ONNX export of the same
# weights (EMBED_PYTHON_MODEL) so the vectors live in the same space. See radar.embed.
EMBED_PYTHON_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_BROWSER_MODEL = "Xenova/bge-small-en-v1.5"
EMBED_DIM = 384
EMBED_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
EMBED_MAX_TOKENS = 512
EMBED_DESCRIPTION_CHARS = 1500
EMBED_TOP_SKILLS = 8
# Model files go here (never the C: drive default). Read at call time by radar.embed.
EMBED_CACHE_ENV = "RADAR_MODEL_CACHE"
