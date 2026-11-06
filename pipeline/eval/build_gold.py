"""Build the gold set: select 40 jobs from the real DB, freeze their inputs, merge labels.

Subcommands
-----------
select   Stratified, seeded sample of canonical remote jobs -> ``gold.jsonl`` with
         ``labels: null``. Overwrites the file, so run it once (the selection is deterministic
         for a given DB, but the DB grows nightly: the frozen file is the source of truth).
show     Print postings exactly as the extractor sees them (for hand labelling).
merge    Merge the hand-written ``labels_draft/*.json`` (job_id -> raw labels + notes) into
         ``gold.jsonl``, canonicalising skills with ``normalize_skills``.

Nothing here calls a model. See ``README.md`` for the selection procedure.
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import typer
from sqlalchemy import select as sa_select

from radar.db import session_scope
from radar.extract.llm import build_user_message
from radar.extract_stage import job_input
from radar.models import Job
from radar.skills import normalize_skills

EVAL_DIR = Path(__file__).resolve().parent
GOLD_PATH = EVAL_DIR / "gold.jsonl"
DRAFT_DIR = EVAL_DIR / "labels_draft"

SEED = 20261106
N_TOTAL = 40
SOURCE_TARGET = {"remotive": 7, "arbeitnow": 8, "remoteok": 12, "jobicy": 13}
SOURCE_MIN = 6
MIN_DESC_CHARS = 200
LONG_CHARS = 8000

app = typer.Typer(add_completion=False, no_args_is_help=True)

# --------------------------------------------------------------------------- heuristics
# Rule-based flags used ONLY to stratify the sample. They are not labels and no model is used.

_BUCKET_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "management",
        re.compile(
            r"\b(head of|director|vp\b|vice president|engineering manager|chief|cto|coo)\b", re.I
        ),
    ),
    (
        "sales",
        re.compile(
            r"\b(sales|account executive|business development|bdr|sdr|partnership|revenue)\b", re.I
        ),
    ),
    (
        "support",
        re.compile(
            r"\b(support|customer success|customer service|helpdesk|help desk"
            r"|customer experience)\b",
            re.I,
        ),
    ),
    (
        "design",
        re.compile(r"\b(designer|design lead|ux|ui/ux|graphic|illustrator|brand design)\b", re.I),
    ),
    (
        "product",
        re.compile(r"\b(product manager|product owner|product lead|product management)\b", re.I),
    ),
    (
        "marketing",
        re.compile(
            r"\b(marketing|seo|content|growth|community|social media|copywrit|communications|pr\b)",
            re.I,
        ),
    ),
    (
        "data",
        re.compile(r"\b(data|analytics|analyst|machine learning|ml\b|ai\b|bi\b|scientist)\b", re.I),
    ),
    (
        "devops_sre",
        re.compile(
            r"\b(devops|sre|site reliability|infrastructure|platform engineer|cloud|security"
            r"|sysadmin|system administrator)\b",
            re.I,
        ),
    ),
    (
        "software_engineering",
        re.compile(
            r"\b(engineer|developer|programmer|software|backend|frontend|front-end|back-end"
            r"|full[- ]?stack|mobile|ios|android|qa|sdet)\b",
            re.I,
        ),
    ),
]

_CURRENCY_AMOUNT = re.compile(
    r"(?:[$€£]\s?\d[\d.,]*\s?[kK]?|\b(?:USD|EUR|GBP|CAD|AUD|CHF|PLN|BRL)\s?\d[\d.,]*\s?[kK]?"
    r"|\d[\d.,]*\s?[kK]?\s?(?:USD|EUR|GBP|CAD|AUD|CHF|PLN|BRL|€|£|\$))"
)
_BASE64_IMG = re.compile(r"data:image/[a-z+]+;base64,")
_EN_WORDS = {"the", "and", "of", "to", "in", "for", "with", "you", "we", "our", "is", "are", "will"}
_OTHER_WORDS = {
    "und",
    "der",
    "die",
    "das",
    "mit",
    "für",
    "wir",
    "sie",
    "ein",
    "eine",
    "nicht",
    "zu",
    "le",
    "la",
    "les",
    "des",
    "et",
    "pour",
    "vous",
    "nous",
    "une",
    "el",
    "los",
    "las",
    "para",
    "con",
    "una",
    "que",
    "uma",
    "não",
    "você",
}


def role_bucket(title: str) -> str:
    for name, pattern in _BUCKET_RULES:
        if pattern.search(title):
            return name
    return "other"


def is_non_english(text: str) -> bool:
    words = re.findall(r"[a-zäöüßéèàçñãõ]+", text.lower())[:400]
    if len(words) < 30:
        return False
    en = sum(w in _EN_WORDS for w in words)
    other = sum(w in _OTHER_WORDS for w in words)
    return other > en and en / len(words) < 0.06


def salary_kind(salary_text: str | None, description: str) -> str | None:
    """Coarse 'currency/period' key if a salary appears in what the model sees, else None."""
    blob = f"{salary_text or ''}\n{description}"
    m = _CURRENCY_AMOUNT.search(blob)
    if not m:
        return None
    context = blob[max(0, m.start() - 80) : m.end() + 80].lower()
    if not re.search(
        r"salary|compensation|pay\b|per (hour|month|year)|/(hr|hour|mo|month|yr|year)|annual|ote"
        r"|\bk\b|[$€£]\s?\d{2,3}[.,]?\d{3}",
        context,
    ):
        return None
    cur = "usd"
    for sym, code in (
        ("€", "eur"),
        ("eur", "eur"),
        ("£", "gbp"),
        ("gbp", "gbp"),
        ("cad", "cad"),
        ("aud", "aud"),
    ):
        if sym in context:
            cur = code
            break
    per = "year"
    if re.search(r"per hour|/hr|/hour|hourly|an hour", context):
        per = "hour"
    elif re.search(r"per month|/mo\b|/month|monthly|a month", context):
        per = "month"
    return f"{cur}/{per}"


# --------------------------------------------------------------------------- selection


def _pool() -> list[dict]:
    rows: list[dict] = []
    with session_scope() as session:
        jobs = session.scalars(
            sa_select(Job)
            .where(Job.is_duplicate_of.is_(None), Job.is_remote.is_(True))
            .order_by(Job.id)
        )
        for job in jobs:
            inp = job_input(job)
            if len(inp.description_text) < MIN_DESC_CHARS:
                continue
            if _BASE64_IMG.search(inp.description_text[:6000]):
                continue  # visible text is an inline image blob: nothing to label
            rows.append(
                {
                    "job": job,
                    "input": inp,
                    "bucket": role_bucket(job.title),
                    "non_en": is_non_english(inp.description_text),
                    "salary_kind": salary_kind(inp.salary_text, inp.description_text),
                    "long": len(inp.description_text) >= LONG_CHARS,
                }
            )
    return rows


def select_jobs(pool: list[dict], rng: random.Random) -> list[dict]:
    order = pool[:]
    rng.shuffle(order)
    chosen: list[dict] = []
    ids: set[int] = set()
    per_source: Counter[str] = Counter()

    def can_take(row: dict) -> bool:
        return row["job"].id not in ids and per_source[row["job"].source] < SOURCE_TARGET.get(
            row["job"].source, 0
        )

    def take(row: dict) -> None:
        chosen.append(row)
        ids.add(row["job"].id)
        per_source[row["job"].source] += 1

    def take_where(pred, n: int) -> None:
        got = 0
        for row in order:
            if got >= n or len(chosen) >= N_TOTAL:
                return
            if can_take(row) and pred(row):
                take(row)
                got += 1

    # A. non-English postings (at least 3)
    take_where(lambda r: r["non_en"], 3)
    # B. stated salaries, one pass per distinct currency/period kind, then any (target 9)
    kinds = sorted({r["salary_kind"] for r in order if r["salary_kind"]})
    for kind in kinds:
        take_where(lambda r, k=kind: r["salary_kind"] == k, 1)
    have = sum(1 for r in chosen if r["salary_kind"])
    take_where(lambda r: r["salary_kind"] is not None, max(0, 9 - have))
    # C. long descriptions (at least 4 overall)
    have = sum(1 for r in chosen if r["long"])
    take_where(lambda r: r["long"], max(0, 4 - have))
    # D. role spread: at least 2 per non-engineering bucket where available
    for bucket in (
        "sales",
        "marketing",
        "support",
        "design",
        "product",
        "management",
        "data",
        "devops_sre",
        "other",
    ):
        have = sum(1 for r in chosen if r["bucket"] == bucket)
        take_where(lambda r, b=bucket: r["bucket"] == b, max(0, 2 - have))
    # E. per-source minimum
    for source in SOURCE_TARGET:
        take_where(
            lambda r, s=source: r["job"].source == s, max(0, SOURCE_MIN - per_source[source])
        )
    # F. fill up to the per-source targets
    for source, target in SOURCE_TARGET.items():
        take_where(lambda r, s=source: r["job"].source == s, max(0, target - per_source[source]))
    chosen.sort(key=lambda r: r["job"].id)
    return chosen


@app.command("select")
def select_cmd(force: bool = typer.Option(False, help="Overwrite an existing gold.jsonl")) -> None:
    """Select the gold jobs and write gold.jsonl with empty labels."""
    if GOLD_PATH.exists() and not force:
        typer.echo(f"{GOLD_PATH} exists; pass --force to overwrite (labels would be lost).")
        raise typer.Exit(1)
    pool = _pool()
    chosen = select_jobs(pool, random.Random(SEED))
    with GOLD_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        for row in chosen:
            job = row["job"]
            record = {
                "job_id": job.id,
                "source": job.source,
                "url": job.url,
                "input": asdict(row["input"]),
                "meta": {
                    "stratum_role_bucket": row["bucket"],
                    "stratum_non_english": row["non_en"],
                    "stratum_salary_kind": row["salary_kind"],
                    "stratum_long": row["long"],
                    # Structured salary the source API gave us. NOT part of the extractor input
                    # (extract_stage.job_input drops it); kept so a reviewer can see it.
                    "db_structured_salary": {
                        "min": job.salary_min,
                        "max": job.salary_max,
                        "currency": job.salary_currency,
                        "period": job.salary_period,
                    },
                },
                "labels": None,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    typer.echo(f"pool={len(pool)} selected={len(chosen)}")
    typer.echo(f"by source: {dict(Counter(r['job'].source for r in chosen))}")
    typer.echo(f"by bucket: {dict(Counter(r['bucket'] for r in chosen))}")
    typer.echo(
        f"non-English: {sum(r['non_en'] for r in chosen)}  long: {sum(r['long'] for r in chosen)}"
    )
    typer.echo(
        f"salary kinds: {dict(Counter(r['salary_kind'] for r in chosen if r['salary_kind']))}"
    )


# --------------------------------------------------------------------------- show / merge


def load_gold(path: Path = GOLD_PATH) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_gold(records: list[dict], path: Path = GOLD_PATH) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


@app.command()
def show(start: int = 0, end: int = 5) -> None:
    """Print gold postings [start, end) exactly as the model would see them."""
    from radar.extract.llm import JobInput

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    for i, rec in enumerate(load_gold()[start:end], start=start):
        print(f"\n===== [{i}] job_id={rec['job_id']} source={rec['source']} =====")
        print(build_user_message(JobInput(**rec["input"])))
        print(f"(db structured salary, NOT shown to model: {rec['meta']['db_structured_salary']})")


@app.command()
def merge(draft_dir: Path = DRAFT_DIR) -> None:
    """Merge hand-written labels (job_id -> raw labels) into gold.jsonl."""
    labels: dict[str, dict] = {}
    for part in sorted(draft_dir.glob("*.json")):
        labels.update(json.loads(part.read_text(encoding="utf-8")))
    records = load_gold()
    missing = [r["job_id"] for r in records if str(r["job_id"]) not in labels]
    if missing:
        typer.echo(f"no labels for job_ids {missing}")
        raise typer.Exit(1)
    for rec in records:
        raw = labels[str(rec["job_id"])]
        rec["labels"] = {
            "role_category": raw["role_category"],
            "seniority": raw["seniority"],
            "skills": normalize_skills(raw["skills"]),
            "salary_min": raw.get("salary_min"),
            "salary_max": raw.get("salary_max"),
            "salary_currency": raw.get("salary_currency"),
            "salary_period": raw.get("salary_period"),
            "employment_type": raw["employment_type"],
            "remote_regions": raw.get("remote_regions", []),
            "status": "draft",
            "notes": raw.get("notes", ""),
        }
    write_gold(records)
    typer.echo(f"merged {len(records)} label sets into {GOLD_PATH}")


if __name__ == "__main__":
    app()
