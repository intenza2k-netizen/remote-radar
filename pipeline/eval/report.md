# Extraction model evaluation

Generated 2026-11-06T11:46:16Z from `eval/runs/*.jsonl` against `eval/gold.jsonl` (40 labelled jobs; label status: 40 draft). Scoring never calls a model.

> **Read this first.** The gold labels were written by one annotator, a Claude model, before any model was run, and have not yet been reviewed by a human. That can favour the Claude extractor (same reading habits, same reading of the prompt). With 40 jobs most differences between models are within the noise; see the intervals below.

## Headline results

| Model | Skills F1 [95% CI] | Seniority acc [95% CI] | Role acc | Salary acc | Failures | Median latency | Cost / 1k jobs |
|---|---|---|---|---|---|---|---|
| `claude-sonnet-5-5` | 0.770 [0.70-0.82] | 0.850 [0.72-0.95] | 0.900 | 0.900 | 0 | 2.3 s | $5.46 |
| `gemma4:12b` | 0.670 [0.58-0.74] | 0.775 [0.65-0.90] | 0.900 | 0.875 | 0 | 0.8 s | $0 |
| `qwen3.8:27b` | 0.730 [0.64-0.79] | 0.825 [0.70-0.93] | 0.950 | 0.850 | 0 | 1.5 s | $0 |
| `gemma4:31b-it-q4_K_M` | 0.832 [0.76-0.89] | 0.800 [0.68-0.93] | 0.925 | 0.875 | 0 | 1.3 s | $0 |

n = 40 jobs scored for every model. Intervals: percentile bootstrap, 1000 resamples over jobs, seed 20261106 (the intervals reflect which jobs were sampled, not label errors). Skills F1 is micro-averaged over the pooled skill sets. A failed extraction counts as an empty / wrong prediction.

## Are the differences real?

Paired bootstrap on the same resampled jobs. A cell is **bold** when its 95% interval excludes 0 (distinguishable); otherwise the gap is *within the noise* at this sample size. Cells show the difference A - B with its interval.

| Pair (A - B) | Skills F1 | Seniority | Role | Employment | Salary |
|---|---|---|---|---|---|
| `claude-sonnet-5-5` - `gemma4:12b` | **+0.099 [+0.05, +0.15]** | +0.075 [-0.08, +0.23] | +0.000 [-0.10, +0.10] | **+0.275 [+0.15, +0.40]** | +0.025 [-0.05, +0.10] |
| `claude-sonnet-5-5` - `qwen3.8:27b` | +0.040 [-0.00, +0.09] | +0.025 [-0.12, +0.18] | -0.050 [-0.12, +0.00] | **+0.200 [+0.10, +0.32]** | +0.050 [-0.03, +0.15] |
| `claude-sonnet-5-5` - `gemma4:31b-it-q4_K_M` | -0.063 [-0.13, +0.01] | +0.050 [-0.08, +0.18] | -0.025 [-0.12, +0.05] | +0.075 [+0.00, +0.17] | +0.025 [-0.05, +0.12] |
| `gemma4:12b` - `qwen3.8:27b` | **-0.059 [-0.11, -0.00]** | -0.050 [-0.15, +0.03] | -0.050 [-0.12, +0.00] | -0.075 [-0.22, +0.08] | +0.025 [+0.00, +0.08] |
| `gemma4:12b` - `gemma4:31b-it-q4_K_M` | **-0.162 [-0.22, -0.11]** | -0.025 [-0.17, +0.12] | -0.025 [-0.08, +0.00] | **-0.200 [-0.35, -0.05]** | +0.000 [-0.07, +0.07] |
| `qwen3.8:27b` - `gemma4:31b-it-q4_K_M` | **-0.103 [-0.16, -0.05]** | +0.025 [-0.10, +0.15] | +0.025 [+0.00, +0.08] | -0.125 [-0.25, +0.00] | -0.025 [-0.10, +0.05] |

7 of 30 comparisons are distinguishable: claude-sonnet-5-5 > gemma4:12b on skills f1; claude-sonnet-5-5 > gemma4:12b on employment; claude-sonnet-5-5 > qwen3.8:27b on employment; qwen3.8:27b > gemma4:12b on skills f1; gemma4:31b-it-q4_K_M > gemma4:12b on skills f1; gemma4:31b-it-q4_K_M > gemma4:12b on employment; gemma4:31b-it-q4_K_M > qwen3.8:27b on skills f1. The other 23 are within the noise. With 30 comparisons at 95%, one or two 'distinguishable' cells could be chance, so treat isolated ones with care. The intervals cover job-sampling noise only, not label errors.

**Skills F1 mixes two different behaviours.** `claude-sonnet-5-5` has the highest recall (0.97) and `gemma4:31b-it-q4_K_M` the highest precision (0.78). Precision depends on how exhaustively the gold list was written: skills a model adds that are genuinely in the posting but not in the draft gold count as errors (see the 'hallucinated' lists and `review.md`). Expect the F1 ranking to move when the labels are reviewed; recall is the less label-dependent number.

Latency and cost are measured per job, not sampled, so those gaps are real for this hardware and prompt. Treat gaps of a few points in any accuracy on 40 jobs (one job = 2.5 points) as noise.

## All metrics

| Model | Skills P | Skills R | Skills F1 (micro) | Skills F1 (macro) | Skills / job | Seniority | Role | Employment | Salary | Regions Jaccard | Failures |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `claude-sonnet-5-5` | 0.640 | 0.966 | 0.770 | 0.644 | 9.9 | 0.850 | 0.900 | 0.975 | 0.900 | 0.950 | 0 |
| `gemma4:12b` | 0.531 | 0.909 | 0.670 | 0.562 | 11.2 | 0.775 | 0.900 | 0.700 | 0.875 | 0.863 | 0 |
| `qwen3.8:27b` | 0.622 | 0.882 | 0.730 | 0.609 | 9.3 | 0.825 | 0.950 | 0.775 | 0.850 | 0.900 | 0 |
| `gemma4:31b-it-q4_K_M` | 0.776 | 0.897 | 0.832 | 0.716 | 7.6 | 0.800 | 0.925 | 0.900 | 0.875 | 0.850 | 0 |

Skills / job is the mean number of canonical skills a model returned; the draft gold averages 6.6, so models that list more skills are penalised on precision. Salary = all four fields match (numbers within 2%, both-null counts as a match). Regions Jaccard is the mean per-job overlap after normalising aliases (USA/US, Europe/EU). Macro F1 averages per-job F1 (empty vs empty = 1.0).

| Model | Median latency | p90 latency | Input tokens | Output tokens | Cost / 1k jobs |
|---|---|---|---|---|---|
| `claude-sonnet-5-5` | 2.3 s | 3.2 s | 202,313 | 5,982 | $5.46 |
| `gemma4:12b` | 0.8 s | 1.1 s | 91,452 | 4,294 | $0 |
| `qwen3.8:27b` | 1.5 s | 1.8 s | 90,287 | 6,842 | $0 |
| `gemma4:31b-it-q4_K_M` | 1.3 s | 2.4 s | 91,452 | 3,936 | $0 |

## Accuracy on unambiguous vs ambiguous labels

21 of 40 gold label sets carry an AMBIGUOUS note (the labeller was unsure which of two answers is right). Scores on the other 19 are a cleaner read of model quality.

| Model | Role (clear, n=19) | Role (ambiguous, n=21) | Seniority (clear) | Seniority (ambiguous) | Salary (clear) | Salary (ambiguous) |
|---|---|---|---|---|---|---|
| `claude-sonnet-5-5` | 0.947 | 0.857 | 0.789 | 0.905 | 1.000 | 0.810 |
| `gemma4:12b` | 0.947 | 0.857 | 0.842 | 0.714 | 1.000 | 0.762 |
| `qwen3.8:27b` | 0.947 | 0.952 | 0.895 | 0.762 | 1.000 | 0.714 |
| `gemma4:31b-it-q4_K_M` | 0.947 | 0.905 | 0.842 | 0.762 | 1.000 | 0.762 |

## By source

| Model | Source | n | Skills F1 | Seniority | Role | Salary |
|---|---|---|---|---|---|---|
| `claude-sonnet-5-5` | arbeitnow | 8 | 0.740 | 0.875 | 0.875 | 1.000 |
| `claude-sonnet-5-5` | jobicy | 13 | 0.760 | 0.769 | 0.923 | 0.846 |
| `claude-sonnet-5-5` | remoteok | 12 | 0.740 | 0.917 | 0.917 | 1.000 |
| `claude-sonnet-5-5` | remotive | 7 | 0.849 | 0.857 | 0.857 | 0.714 |
| `gemma4:12b` | arbeitnow | 8 | 0.688 | 0.625 | 1.000 | 1.000 |
| `gemma4:12b` | jobicy | 13 | 0.675 | 0.846 | 0.923 | 0.846 |
| `gemma4:12b` | remoteok | 12 | 0.646 | 0.833 | 0.833 | 1.000 |
| `gemma4:12b` | remotive | 7 | 0.679 | 0.714 | 0.857 | 0.571 |
| `qwen3.8:27b` | arbeitnow | 8 | 0.735 | 0.750 | 1.000 | 1.000 |
| `qwen3.8:27b` | jobicy | 13 | 0.736 | 0.846 | 1.000 | 0.846 |
| `qwen3.8:27b` | remoteok | 12 | 0.701 | 0.917 | 0.917 | 0.917 |
| `qwen3.8:27b` | remotive | 7 | 0.754 | 0.714 | 0.857 | 0.571 |
| `gemma4:31b-it-q4_K_M` | arbeitnow | 8 | 0.887 | 0.875 | 1.000 | 1.000 |
| `gemma4:31b-it-q4_K_M` | jobicy | 13 | 0.794 | 0.692 | 1.000 | 0.923 |
| `gemma4:31b-it-q4_K_M` | remoteok | 12 | 0.800 | 0.917 | 0.833 | 1.000 |
| `gemma4:31b-it-q4_K_M` | remotive | 7 | 0.885 | 0.714 | 0.857 | 0.429 |

The per-source cells hold 7-13 jobs each: indicative only.

## Seniority confusion (rows = gold, columns = predicted)

### `claude-sonnet-5-5`

| gold \ pred | intern | junior | mid | senior | lead | principal | unspecified | total |
|---|---|---|---|---|---|---|---|---|
| junior |  | 3 |  |  |  |  | 2 | 5 |
| mid |  |  | 1 |  |  |  | 2 | 3 |
| senior |  |  |  | 8 |  |  | 1 | 9 |
| lead |  |  |  |  | 5 |  | 1 | 6 |
| principal |  |  |  |  |  | 2 |  | 2 |
| unspecified |  |  |  |  |  |  | 15 | 15 |

### `gemma4:12b`

| gold \ pred | intern | junior | mid | senior | lead | principal | unspecified | total |
|---|---|---|---|---|---|---|---|---|
| junior |  | 5 |  |  |  |  |  | 5 |
| mid |  |  |  | 2 |  |  | 1 | 3 |
| senior |  |  |  | 8 |  | 1 |  | 9 |
| lead |  |  |  |  | 6 |  |  | 6 |
| principal |  |  |  |  |  | 2 |  | 2 |
| unspecified |  | 1 |  | 3 | 1 |  | 10 | 15 |

### `qwen3.8:27b`

| gold \ pred | intern | junior | mid | senior | lead | principal | unspecified | total |
|---|---|---|---|---|---|---|---|---|
| junior |  | 5 |  |  |  |  |  | 5 |
| mid |  |  | 1 | 1 | 1 |  |  | 3 |
| senior |  |  |  | 9 |  |  |  | 9 |
| lead |  |  |  |  | 6 |  |  | 6 |
| principal |  |  |  |  |  | 2 |  | 2 |
| unspecified |  | 2 |  | 1 | 2 |  | 10 | 15 |

### `gemma4:31b-it-q4_K_M`

| gold \ pred | intern | junior | mid | senior | lead | principal | unspecified | total |
|---|---|---|---|---|---|---|---|---|
| junior |  | 2 |  |  |  |  | 3 | 5 |
| mid |  |  |  | 2 |  |  | 1 | 3 |
| senior |  |  |  | 9 |  |  |  | 9 |
| lead |  |  |  |  | 6 |  |  | 6 |
| principal |  |  |  |  |  | 2 |  | 2 |
| unspecified |  |  | 1 |  | 1 |  | 13 | 15 |

## Most-missed and most-hallucinated skills (canonical slugs)

*Missed* = in gold, not predicted. *Hallucinated* = predicted, not in gold (some are real skills the labeller left out; check `review.md`).

### `claude-sonnet-5-5`

- Missed: change-data-capture (1), cloudtrail (1), databricks (1), envoy (1), graph-database (1), llm (1), oauth (1), rds (1), stimulus (1)
- Hallucinated: api-development (4), disaster-recovery (3), accounting (2), cybersecurity (2), data-modeling (2), negotiation (2), observability (2), rdbms (2), sales (2), account-management (1)

### `gemma4:12b`

- Missed: azure (1), ceph (1), change-data-capture (1), cloudtrail (1), customer-communication-management (1), customer-support (1), cybersecurity (1), envoy (1), gcp (1), gitops (1)
- Hallucinated: ai (7), api-development (4), cybersecurity (3), observability (3), system-design (3), agile (2), data-analysis (2), data-modeling (2), disaster-recovery (2), invoicing-billing (2)

### `qwen3.8:27b`

- Missed: ecs (2), llm (2), api-gateway (1), aws-bedrock (1), bookkeeping (1), change-data-capture (1), ci-cd (1), cloudtrail (1), cognito (1), customer-communication-management (1)
- Hallucinated: api-development (4), ai (2), coaching (2), cybersecurity (2), sales (2), system-design (2), account-management (1), accounting (1), accounting-systems (1), active-travel (1)

### `gemma4:31b-it-q4_K_M`

- Missed: customer-support (2), llm (2), product-management (2), ceph (1), change-data-capture (1), ci-cd (1), claude (1), cloudtrail (1), customer-communication-management (1), databricks (1)
- Hallucinated: ai (3), rdbms (2), sales (2), system-design (2), a-plus (1), account-management (1), agile (1), aml-kyc (1), api-development (1), atak (1)

## Hardware, latency and offloading

Local models ran one at a time through Ollama on a single RTX 5090 (32 GB VRAM) shared with desktop apps, with thinking disabled and `num_ctx` 8192. Each local run starts with one unscored warm-up call so model-load time is not in the per-job latency; the load time is listed separately. Claude latency is a network round trip to the API with adaptive thinking at low effort, so it is not comparable to local compute time.

| Model | Ollama-reported size / placement | nvidia-smi VRAM in use: before -> while loaded | Load + first call | Median per job |
|---|---|---|---|---|
| `claude-sonnet-5-5` | API | n/a | n/a | 2.3 s |
| `gemma4:12b` | 1.5 GB, 100% on GPU | 2.6 -> 12.0 GB of 32 (+9.3) | 4.9 s | 0.8 s |
| `qwen3.8:27b` | 17.5 GB, 100% on GPU | 2.7 -> 21.1 GB of 32 (+18.4) | 31.6 s | 1.5 s |
| `gemma4:31b-it-q4_K_M` | 2.7 GB, 100% on GPU | 2.7 -> 25.0 GB of 32 (+22.3) | 41.4 s | 1.3 s |

Every local model was fully resident in VRAM (Ollama reports 100% GPU and the nvidia-smi figures leave headroom), so no CPU offloading affected the latency above. Ollama's reported size for the Gemma 4 models is far below the VRAM they actually occupy (compare with nvidia-smi), so trust the nvidia-smi column for memory. The desktop apps were holding only about 2.7 GB of VRAM during these runs, not the 12 GB assumed in the plan; a busier desktop could push the 27B/31B models into offloading and make them slower.

## Method and caveats

- **Gold set:** 40 canonical remote jobs from `data/jobs.sqlite`, seeded stratified sample (selection procedure in `eval/README.md`). Inputs are frozen copies of the exact `JobInput` the pipeline builds, so the eval reproduces even if the DB changes.
- **Labels:** written by one Claude model, using the definitions in `extract/prompts/extract.md`, before any model output was seen; status `draft`. Same-family bias is possible. Items the labeller found ambiguous are flagged in `gold.jsonl` notes and listed first in `review.md`.
- **Same prompt for every model** (`v1`), same JSON schema, one retry on invalid output. Temperature is 0 for Ollama; Claude Sonnet 5.5 accepts no sampling parameters, so its runs are not guaranteed repeatable and each model was run once.
- **What the model sees:** `extract_stage.job_input` passes only `salary_text` (set for Remotive only) and the description, truncated to 6,000 characters. The structured salaries that Jobicy and Remote OK provide are *not* in the input, so salary accuracy here measures extraction from the description text, not what the nightly pipeline publishes (which prefers the structured value).
- **Skills** are compared as canonical slugs after `normalize_skills`; the alias table merges some distinct tools (see Open issues in the hand-off), which affects every model equally.
- **Cost:** Claude cost is computed from reported token usage with the pipeline's price table (cache reads and writes included); local models cost 0 (electricity not counted).

