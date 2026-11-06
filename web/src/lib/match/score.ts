import {
  COVERAGE_PRIOR,
  FIT_OVERQUALIFIED,
  FIT_STRETCH,
  FIT_UNSPECIFIED,
  PRIOR_WEIGHT,
  SIM_CEIL,
  SIM_FLOOR,
  WEIGHTS,
  type ComponentKey,
} from "./constants";
import { seniorityLabel, seniorityRank } from "@/lib/format";
import type { Job } from "@/lib/types";
import { normRegion } from "./options";
import { LEVELS, type Breakdown, type Level, type Preferences, type ScoredJob } from "./types";

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** Cosine similarity stretched to 0..1 between SIM_FLOOR and SIM_CEIL. */
export function semanticScore(cosine: number): number {
  return clamp01((cosine - SIM_FLOOR) / (SIM_CEIL - SIM_FLOOR));
}

/** Shrunk share of the job's listed skills that the CV has. Null when the job lists none. */
export function skillCoverage(matched: number, listed: number): number | null {
  if (listed <= 0) return null;
  return clamp01((matched + PRIOR_WEIGHT * COVERAGE_PRIOR) / (listed + PRIOR_WEIGHT));
}

/** Fit 0..1 between your level and the job's. Null when your level is unknown. */
export function seniorityFit(you: Level | null, jobLevel: string | null | undefined): number | null {
  if (!you) return null;
  if (!jobLevel || jobLevel === "unspecified" || !LEVELS.includes(jobLevel as Level)) return FIT_UNSPECIFIED;
  const diff = seniorityRank(jobLevel) - seniorityRank(you);
  const idx = Math.min(3, Math.abs(diff));
  return diff > 0 ? FIT_STRETCH[idx] : FIT_OVERQUALIFIED[idx];
}


/** A job passes a region filter if it lists that region or is open worldwide. */
export function regionMatches(job: Job, region: string): boolean {
  if (!region) return true;
  const want = normRegion(region);
  return job.remote_regions.some((r) => {
    const k = normRegion(r);
    return k === want || k === "worldwide" || k === "anywhere";
  });
}

export function passesFilters(job: Job, prefs: Preferences): boolean {
  if (prefs.onlySalary && !job.salary) return false;
  // A minimum only hides jobs that STATE a lower salary; unstated pay is kept unless "only jobs that state salary" is on.
  if (prefs.minSalary > 0 && job.salary && job.salary.annual_usd_mid < prefs.minSalary) return false;
  if (!regionMatches(job, prefs.region)) return false;
  return true;
}

export type ScoreInput = {
  jobs: Job[];
  /** Skill slugs the CV is credited with (after the user edited the chips). */
  cvSkills: Set<string>;
  /** Your seniority (from the preference override, else inferred). */
  level: Level | null;
  prefs: Preferences;
  /** Job id -> cosine similarity, or null while the model is not available. */
  cosines: Map<string, number> | null;
};

/** Plain-English seniority note for the breakdown. */
function seniorityNote(job: Job, level: Level | null): string {
  const stated = job.seniority && job.seniority !== "unspecified" ? seniorityLabel(job.seniority) : null;
  if (!level) return stated ? `${stated} job; your level is unknown` : "Posting states no level; your level is unknown";
  return stated ? `${stated} job, you: ${seniorityLabel(level)}` : `Posting states no level, you: ${seniorityLabel(level)} (neutral fit)`;
}

export function scoreJob(job: Job, input: Omit<ScoreInput, "jobs">): ScoredJob {
  const { cvSkills, level, prefs, cosines } = input;
  const matched = job.skills.filter((s) => cvSkills.has(s));
  const missing = job.skills.filter((s) => !cvSkills.has(s));

  const cosine = cosines?.get(job.id) ?? null;
  const parts: Record<ComponentKey, number | null> = {
    semantic: cosine == null ? null : semanticScore(cosine),
    skills: cvSkills.size === 0 ? null : skillCoverage(matched.length, job.skills.length),
    seniority: seniorityFit(level, job.seniority),
    role: prefs.roles.length ? (job.role && prefs.roles.includes(job.role) ? 1 : 0) : null,
  };

  let totalWeight = 0;
  for (const k of Object.keys(WEIGHTS) as ComponentKey[]) if (parts[k] != null) totalWeight += WEIGHTS[k];
  const contributions: Breakdown["contributions"] = [];
  let score = 0;
  for (const k of Object.keys(WEIGHTS) as ComponentKey[]) {
    const v = parts[k];
    if (v == null) continue;
    const weight = WEIGHTS[k] / totalWeight;
    const points = weight * v;
    score += points;
    contributions.push({ key: k, weight, value: v, points });
  }

  return {
    job,
    score: clamp01(score),
    breakdown: {
      cosine,
      semantic: parts.semantic,
      skills: parts.skills,
      seniority: parts.seniority,
      role: parts.role,
      matchedSkills: matched,
      missingSkills: missing,
      seniorityNote: seniorityNote(job, level),
      contributions,
    },
  };
}

/** Score every job that passes the hard filters; best first. Ties broken by newer posting. */
export function scoreJobs(input: ScoreInput): ScoredJob[] {
  const { jobs, ...rest } = input;
  return jobs
    .filter((j) => passesFilters(j, input.prefs))
    .map((j) => scoreJob(j, rest))
    .sort((a, b) => b.score - a.score || b.job.posted_at.localeCompare(a.job.posted_at));
}
