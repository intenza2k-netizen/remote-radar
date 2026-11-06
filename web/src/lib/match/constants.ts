/**
 * Every tunable number of the CV matcher lives here, so the scoring is easy to audit
 * and the methodology text on the page can be checked against the code.
 */

/** How many ranked jobs are shown, and the pool the skill-gap panel is computed from. */
export const TOP_N = 30;

/**
 * Hybrid score = weighted mean of the components that apply to a job.
 * A component that cannot be computed (no embedding yet, job lists no skills, no
 * role preference chosen) is dropped and the remaining weights are renormalised,
 * so the score is always a 0 to 100 % figure on the same scale.
 */
export const WEIGHTS = {
  /** Cosine similarity between your CV and the posting (language model). */
  semantic: 0.4,
  /** Share of the skills the job lists that you have. */
  skills: 0.35,
  /** How close your seniority is to the one the posting asks for. */
  seniority: 0.15,
  /** 1 if the job's role is one of the roles you picked, otherwise 0. */
  role: 0.1,
} as const;

export type ComponentKey = keyof typeof WEIGHTS;

/**
 * bge-small cosine similarities between a CV and a posting sit in a narrow band:
 * unrelated text is about 0.50 to 0.60, a genuinely close posting 0.75 or more.
 * The raw cosine is stretched linearly between these two values (and clamped)
 * before it is weighted. The raw cosine is still shown in the breakdown.
 */
export const SIM_FLOOR = 0.55;
export const SIM_CEIL = 0.8;

/**
 * Skill coverage = (matched + PRIOR_WEIGHT * COVERAGE_PRIOR) / (listed + PRIOR_WEIGHT).
 * A posting that lists one skill proves little, so coverage is pulled toward
 * COVERAGE_PRIOR for short skill lists. The prior fades as the list grows:
 * 1 of 1 matched scores 0.48, 8 of 10 scores 0.68, 4 of 4 scores 0.70.
 * (With a weight of 1, a one-skill posting you happen to match scored 0.65 and
 * outranked richer postings; tuned on the real snapshot, 2026-11-06.)
 */
export const COVERAGE_PRIOR = 0.3;
export const PRIOR_WEIGHT = 3;

/**
 * Seniority fit when the job's level differs from yours (diff = job level minus yours).
 * A more senior job than you is a stretch, a more junior job is over-qualification;
 * both fall off with the distance. Index = |diff|, 0 to 3+.
 */
export const FIT_STRETCH = [1, 0.6, 0.2, 0] as const;
export const FIT_OVERQUALIFIED = [1, 0.75, 0.4, 0.1] as const;
/** Fit used when the posting does not state a seniority (neutral, slightly below a good fit). */
export const FIT_UNSPECIFIED = 0.6;

/** Years of experience to seniority (used only when no title word decides it). */
export const YEARS_TO_LEVEL: { minYears: number; level: "junior" | "mid" | "senior" }[] = [
  { minYears: 0, level: "junior" },
  { minYears: 2, level: "mid" },
  { minYears: 5, level: "senior" },
];

/** Skill-detection context window: a strict pattern needs a context word or a neighbouring skill within this many characters. */
export const STRICT_CONTEXT_CHARS = 60;

/** CV embedding: chunk size and cap, plus the weight of the skills-and-roles summary vector. */
export const CHUNK_CHARS = 1400;
export const CHUNK_OVERLAP = 150;
export const MAX_CHUNKS = 6;
/** The summary vector counts like this many text chunks when the vectors are averaged. */
export const SUMMARY_WEIGHT = 2;

export const MIN_CV_CHARS = 80;
export const MAX_FILE_BYTES = 8 * 1024 * 1024;
