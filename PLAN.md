# Remote Radar — build plan (v1)

Remote job-market intelligence: ingest remote postings daily from public job APIs, extract
structured fields with an LLM (Claude API or local Ollama, compared by a published eval),
publish a static JSON snapshot, render it as a Next.js dashboard. Target audience for the
project: data analyst / data engineer hiring managers.

Full product plan: `C:\Users\andu0\.claude\plans\i-want-to-build-eager-quill.md`.

## Already done (orchestrator)

- Repo at `remote-radar/`, git initialised (no commits yet).
- `pipeline/`: uv project, Python 3.12, deps installed (httpx, pydantic, sqlalchemy, typer,
  rich, selectolax, python-dateutil, pyyaml, tenacity, ollama, anthropic; dev: pytest, ruff).
  Run everything with `uv run ...` from `pipeline/`.
- `pipeline/src/radar/config.py`, `models.py` (tables: runs, raw_jobs, jobs, extractions,
  job_skills), `db.py` (`session_scope`, `upsert_raw_jobs`).
- `web/`: Next.js 16.4 + React 19.3 + Tailwind 4, App Router, `src/` dir.
- Real sample payloads (read-only, do not commit from here):
  `C:\Users\andu0\AppData\Local\Temp\claude\3b9d1d771b963be5\12095ed2-0924-4635-8cb6-2131d3115e8d\scratchpad\raw\{remotive,remoteok,arbeitnow,jobicy}.json`
- `ANTHROPIC_API_KEY` is stored as a Windows user env var but NOT visible to already-running
  processes. Load it per command:
  `$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY','User')`
  (PowerShell). Never print it. Live Claude call verified: ~1.4 cents/job, 3 s.

## Local model candidates (research 2026-11-06)

| Tag | Download | Notes |
|---|---|---|
| `gemma4:12b` | 8 GB | installed; baseline |
| `qwen3.8:27b` | 18 GB | dense 27B, Apache-2.0, thinking model (use think=False); downloading |
| `gemma4:31b` | 20 GB | dense 31B, isolates the effect of size within one family; awaiting user OK |

Ollama models live on F: (`OLLAMA_MODELS=F:\Ollama\models`, user env var; moved from C: 2026-11-06). Processes started before that change need `$env:OLLAMA_MODELS` set explicitly. Never download models to C:.
About 12 GB of VRAM is held by desktop apps; close GPU-heavy apps before running 27B+ models.

## Steps and ownership

| Step | Owner | Files owned | Depends on |
|---|---|---|---|
| A. Sources | worker | `pipeline/src/radar/sources/**`, `pipeline/tests/fixtures/**`, `pipeline/tests/test_sources.py` | — |
| B. Normalize, dedupe, skills | worker | `pipeline/src/radar/normalize.py`, `dedupe.py`, `skills/**`, `pipeline/tests/test_{normalize,dedupe,skills}.py` | — |
| C. Extractors | worker | `pipeline/src/radar/extract/**`, `pipeline/tests/test_extract.py` | — |
| D. Dashboard | worker | `web/**` | contract §4 only |
| E. Pipeline stages + CLI | worker | `pipeline/src/radar/{ingest,extract_stage,aggregate,publish,cli}.py`, `pipeline/tests/test_pipeline.py` | A, B, C |
| F. Eval harness + gold set draft | worker | `pipeline/eval/**` | C, E |
| G. Nightly script, CI, README | worker | `scripts/**`, `.github/**`, `README.md`, `LICENSE`, `.gitignore` | E |

A, B, C, D run in parallel. E after A–C pass review. F and G after E.
Nobody edits `pyproject.toml`, `config.py`, `models.py`, `db.py`: report needed changes instead.

## Shared contracts

### 1. Sources (`radar.sources.base`)

```python
@dataclass(frozen=True)
class SourceJob:
    source: str          # "remotive" | "remoteok" | "arbeitnow" | "jobicy"
    external_id: str     # stable id from the API, as str
    payload: dict        # the job object exactly as returned (JSON-serialisable)

class JobFields(TypedDict):
    title: str
    company: str
    url: str                       # canonical posting URL on the source site
    location: str | None
    is_remote: bool
    posted_at: datetime | None     # naive UTC
    description_html: str | None   # as provided (may be entity-escaped)
    salary_text: str | None        # free-text salary if the source only gives text
    salary_min: float | None       # only from structured source fields
    salary_max: float | None
    salary_currency: str | None    # ISO 4217
    salary_period: str | None      # "year" | "month" | "hour" | None
    source_tags: list[str]
    source_category: str | None
    employment_type_text: str | None
    seniority_hint: str | None     # e.g. Jobicy jobLevel

class Source(Protocol):
    name: str
    display_name: str              # "Remote OK"
    homepage: str                  # for attribution links
    def fetch(self, client: httpx.Client) -> list[SourceJob]: ...
    def to_fields(self, payload: dict) -> JobFields: ...

ALL_SOURCES: list[Source]          # in radar/sources/__init__.py
```

`to_fields` is pure (no network) and must not call `radar.normalize`. Free-text salary
parsing and HTML-to-text happen later in the ingest stage.

### 2. Normalize / dedupe / skills

```python
# radar.normalize
def html_to_text(html: str | None) -> str
def parse_salary_text(text: str | None) -> SalaryParse | None   # dataclass: min, max, currency, period
def clean_title(title: str) -> str      # trims, strips gender markers like (m/w/d), (f/m/x)
def clean_company(name: str) -> str     # trims, collapses whitespace
def annualize(amount: float, period: str | None) -> float | None  # hour*2080, month*12, year*1

# radar.dedupe
def dedupe_key(company: str, title: str) -> str   # 40-char sha1 hex

# radar.skills
def normalize_skill(raw: str) -> str | None        # canonical slug or None if dropped
def normalize_skills(raws: list[str]) -> list[str] # deduped, order preserved
def skill_info(slug: str) -> SkillInfo             # dataclass: slug, display, category
# data: radar/skills/aliases.yaml
```

Skill categories: `language`, `framework`, `cloud`, `data`, `devops`, `database`, `ai_ml`,
`tool`, `design`, `business`, `other`. Unknown skills keep a slugified form and category `other`.

### 3. Extraction (`radar.extract`)

```python
class ExtractedJob(BaseModel): ...   # exact fields in the product plan
@dataclass
class JobInput: title, company, location, description_text, salary_text, source_tags
@dataclass
class ExtractionResult:
    backend: str; model: str; prompt_version: str
    ok: bool; data: ExtractedJob | None; error: str | None; raw_output: str | None
    latency_ms: int; input_tokens: int | None; output_tokens: int | None; cost_usd: float | None
class Extractor(Protocol):
    backend: str; model: str
    def extract(self, job: JobInput) -> ExtractionResult: ...
def get_extractor(backend: Literal["claude", "ollama"], model: str | None = None) -> Extractor
```

### 4. Published snapshot (`web/public/data/*.json`)

All salaries in the snapshot are annualised and converted to USD (static FX table, documented).

- `meta.json`: `{generated_at, last_run_at, window_days, backend, model, totals: {jobs, companies, with_salary, skills}, sources: [{name, display_name, homepage, jobs}], weekly: [{week: "2026-W45", jobs}]}`
- `skills.json`: `[{slug, name, category, count, share, change_4w, median_salary_usd, trend: [{week, count, share}], cooccurring: [{slug, count}]}]` sorted by count desc. `share` = fraction of jobs in window mentioning the skill, 0–1 (e.g. 0.348). `change_4w` = share last 4 weeks minus share previous 4 weeks in percentage points, i.e. `(a - b) * 100` (e.g. 2.9), may be null. `role`, `seniority`, `employment_type` use the exact `ExtractedJob` enum strings (snake_case, incl. `unspecified`): role = software_engineering, data, devops_sre, product, design, marketing, sales, support, management, other; seniority = intern, junior, mid, senior, lead, principal, unspecified; employment_type = full_time, part_time, contract, unspecified. salary.json `key` uses the same strings.
- `roles.json`: `[{role, count, median_salary_usd}]`
- `salary.json`: `{by_seniority: [{key, n, p10, p25, median, p75, p90}], by_role: [same]}` (n >= 5 only)
- `jobs.json`: `[{id, title, company, url, source, posted_at, location, remote_regions, role, seniority, employment_type, skills: [slug], salary: {min, max, currency, period, annual_usd_mid} | null}]`, last 60 days, no descriptions.
- `eval.json`: `{generated_at, n_labeled, backends: [{backend, model, skills_precision, skills_recall, skills_f1, seniority_acc, role_acc, salary_acc, median_latency_ms, cost_per_1k_usd, failures}]}` (may be absent before the first eval run; the site must handle that).

## Acceptance criteria

- **A**: four sources implemented; `fetch` makes one request per page with the config User-Agent and timeout; Arbeitnow and Jobicy page per `config`; `to_fields` correct for every sample job in the trimmed fixtures (5–10 per source); `uv run pytest tests/test_sources.py` and `uv run ruff check src/radar/sources tests/test_sources.py` pass; no network in tests.
- **B**: functions match contract; salary parser handles the formats seen in the samples plus common ones; aliases.yaml covers ~250 skills; tests pass; ruff clean.
- **C**: both backends, schema-enforced output, one retry on invalid output, token and cost accounting; unit tests with mocked clients pass; live smoke run against local Ollama on 3 real jobs succeeds.
- **D**: pages Overview, Skills, Skill detail, Jobs explorer, Methodology; reads only snapshot JSON; works with sample data; `npm run lint` and `npm run build` pass; looks right at 375 px and desktop, light and dark.
- **E**: `radar fetch|ingest|extract|aggregate|publish|run-all|stats` work end to end on the real DB; publish writes files matching §4.
- **F**: `eval/run_eval.py --backend ... --model ...` runs any number of models (planned: Claude Sonnet 5.5, gemma4:12b, one Qwen model, one larger local model; exact tags from the research step, user approves downloads) and writes `eval/report.md` and `web/public/data/eval.json` with one row per model.
- **G**: nightly PowerShell script, CI workflow (ruff, pytest, web lint + build), README with architecture and attribution.

## v2: use the data (started 2026-11-06)

Goal: turn the snapshot into tools a job seeker uses. Headline feature is a private, in-browser CV matcher.

| Step | Owner | Files owned | Depends on |
|---|---|---|---|
| H. Pipeline: embeddings, skill vocab, insights | worker | `pipeline/src/radar/{embed,insights}.py`, edits to `aggregate.py`, `publish.py`, `cli.py`, `config.py` (new constants only), `pipeline/tests/test_{embed,insights}.py`, `pipeline/pyproject.toml` deps | — |
| I. Web: CV matcher `/match` | worker | `web/src/app/match/**`, `web/src/lib/match/**`, `web/src/components/match/**`, `web/package.json` deps, `web/next.config.ts`, `web/scripts/make-sample-v2.mjs` (match files only) | contract §5 |
| J. Web: `/insights`, `/companies`, `/companies/[slug]` | worker | `web/src/app/{insights,companies}/**`, `web/src/components/insights/**`, `web/src/lib/insights.ts`, `web/src/lib/site.ts` (NAV only), `web/scripts/make-sample-v2.mjs` (insights files only) | contract §5 |

I and J both need `make-sample-v2.mjs`: I writes it first section `// MATCH`, J appends section `// INSIGHTS`; whoever finds the file existing edits only their own section. Neither edits the other's directories or shared components outside their own folders; shared needs go in the report.
Model files and caches download to F: (`RADAR_MODEL_CACHE=F:\Models\remote-radar`, user env var). Never download to C:.

### 5. v2 snapshot files (`web/public/data/`)

- `job_vectors.json`: `{model: "Xenova/bge-small-en-v1.5", python_model: "BAAI/bge-small-en-v1.5", dim: 384, normalized: true, pooling: "cls", query_prefix: "Represent this sentence for searching relevant passages: ", encoding: "int8-base64", ids: [job id...], scales: [float per vector], data: "<base64 of N*dim int8, row-major>"}`. Value = int8 * scale. Ids match `jobs.json`. Passage text embedded per job = title + role + seniority + top skills + first ~1500 chars of description (descriptions are NOT published).
- `skill_vocab.json`: `[{slug, name, category, patterns: [lowercase strings], strict: bool}]` for every canonical skill in `aliases.yaml`. `patterns` = canonical slug words, display name and aliases. `strict: true` marks ambiguous short patterns (e.g. "go", "r", "c", "ai", "ml", "ps", "sem", "excel" in prose) that the browser must only accept with case/context rules.
- `insights.json`:
  - `skill_premium`: `[{slug, name, n_with, n_without, median_with, median_without, diff, ci_low, ci_high}]` annual USD, skills with n_with >= 15 salaried postings, bootstrap 95% CI on the difference of medians (1000 resamples, fixed seed), sorted by diff.
  - `seniority_lift`: per role with >= 30 postings, `{role, n_senior, n_junior, skills: [{slug, name, share_senior, share_junior, lift}]}` top 10 by lift, senior = senior|lead|principal, junior = intern|junior|mid.
  - `skill_graph`: `{nodes: [{slug, name, category, count}], edges: [{a, b, count, pmi}]}` top 80 skills by count; edges with count >= 3, ranked by PMI, max 250.
  - `role_skills`: `[{role, n, top: [{slug, name, share}]}]` top 12 per role.
- `companies.json`: `[{slug, name, jobs, roles: {role: n}, seniority: {..}, top_skills: [{slug, name, count}], median_salary_usd, sources: [..], job_ids: [..]}]` companies with >= 1 job, sorted by jobs desc.

### v2 status (2026-11-06): shipped in e7719f2, live

- H, I, J reviewed. Orchestrator fixes: pay-premium headline states it is unadjusted for role; matcher coverage prior 1 -> 3 (one-skill postings no longer outrank rich matches); single-row scrolling nav on phones; company names in job lists link to company pages; overview CTAs to /match and /insights; `web/public/ort/` gitignored (copied at build).
- Checks: pipeline 534 tests, web 47 unit tests, lint, build (461 pages), browser review of /match (sample CV, network log shows no CV data sent), /insights, /companies, 375 px dark; CI green; live pages 200.
- Follow-ups: role-adjusted pay premium; display names for unknown skill slugs ("Lqa", "Ada"); more sources for more data roles; user review of eval gold labels; nightly task (user said not yet).

## Integration (2026-11-06)

- Full extraction: 448/448 canonical remote jobs with gemma4:31b, 0 failures, median 1.36 s, 12 min.
- Real snapshot published to `web/public/data/` (415 jobs in window, 210 companies, 239 skills); sample data replaced.
- Dashboard round 2: trend views plot only weeks with >= 20 postings; null change_4w handled; limitations computed from data.
- Final checks: 477 pipeline tests, ruff clean, web lint + build (247 pages) clean; no secrets, no large or ignored files in the would-be commit.
- Open decisions for the user: review gold labels (`pipeline/eval/review.md`); whether to publish full job descriptions inside `pipeline/eval/gold.jsonl`; GitHub repo + first commit/push; Vercel deploy; registering the nightly task.

## Status

- [x] A (reviewed: 31 tests, ruff clean; Remotive API caps at 10 jobs/run; Jobicy uses count=100 + cursor)  - [x] B (reviewed: 231 tests; 325 skills; files are CRLF, add .gitattributes in G; "marketing/sales/finance" kept as skills, revisit after eval)  - [x] C (reviewed: 36 tests; live Claude + Ollama OK; no temperature on Claude, think=False on Ollama; Claude auth/400 errors raise, so stage E must catch per job)  - [x] D (reviewed after 1 fix round: enum labels; hand-rolled SVG charts, no chart deps; 151 static pages; checked light/dark, 375 px)  - [x] E (reviewed: 364 tests; live: 1009 jobs, 448 canonical remote, 40 extracted with gemma4:12b; window = 8 whole ISO weeks; skills need >= 3 mentions; FX table approximate, dated 2026-11-01)  - [x] F (reviewed: rescore reproduces; 0 failures; Claude spend $0.22; gemma4:31b best skills F1 0.826 vs Claude 0.762 (within noise), 12b weakest -> default switched to gemma4:31b in config.py; gold labels are DRAFT, user review pending via eval/review.md; alias over-merging found -> B round 2; after B fix: rerun eval/build_gold.py then `run_eval.py score`)  - [x] G (reviewed: dry run OK, ignore rules OK, README headline toned down; "Why I built this" is written in the user's voice and needs their review; CI red until eval lint fixed)
