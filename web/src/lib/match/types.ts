import type { Job } from "@/lib/types";

/** `skill_vocab.json` entry (PLAN.md section 5). */
export type VocabEntry = {
  slug: string;
  name: string;
  category: string;
  /** Lowercase match strings. */
  patterns: string[];
  /** Ambiguous short patterns ("go", "r", "c"): only accepted with case and context rules. */
  strict: boolean;
  /** Patterns of this skill that need case/context rules (e.g. Python's alias "py"). When present, replaces the heuristic. */
  strict_patterns?: string[];
};

/** `job_vectors.json` (PLAN.md section 5). */
export type JobVectorsFile = {
  model: string;
  python_model?: string;
  dim: number;
  normalized: boolean;
  pooling: string;
  query_prefix: string;
  encoding: string;
  ids: string[];
  scales: number[];
  /** base64 of N*dim int8, row-major. */
  data: string;
};

export type DecodedVectors = {
  ids: string[];
  dim: number;
  /** N*dim floats, row-major. */
  vectors: Float32Array;
};

export type DetectedSkill = { slug: string; mentions: number };

/** Ordered seniority levels, matching `SENIORITY_ORDER` in `lib/format.ts`. */
export type Level = "intern" | "junior" | "mid" | "senior" | "lead" | "principal";
export const LEVELS: Level[] = ["intern", "junior", "mid", "senior", "lead", "principal"];

export type SeniorityGuess = {
  level: Level | null;
  years: number | null;
  /** Human-readable explanation, e.g. "Title 'Senior Data Analyst'" or "5 years of experience stated". */
  reason: string;
};

export type Preferences = {
  roles: string[];
  /** "" means "use the level inferred from the CV". */
  seniority: Level | "";
  /** Annual USD; 0 = no minimum. */
  minSalary: number;
  region: string;
  onlySalary: boolean;
};

export const DEFAULT_PREFS: Preferences = { roles: [], seniority: "", minSalary: 0, region: "", onlySalary: false };

export type Breakdown = {
  /** Raw cosine similarity, or null when the model is not available. */
  cosine: number | null;
  /** Stretched 0..1 similarity score, or null. */
  semantic: number | null;
  /** Shrunk skill coverage 0..1, or null (job lists no skills or CV has none). */
  skills: number | null;
  /** Seniority fit 0..1, or null when your level is unknown. */
  seniority: number | null;
  /** 1 or 0 when roles were picked, else null. */
  role: number | null;
  matchedSkills: string[];
  missingSkills: string[];
  /** Plain-English seniority note, e.g. "Mid-level job, you: Mid-level". */
  seniorityNote: string;
  /** Per-component contribution in score points (0..1 scale of the final score). */
  contributions: { key: "semantic" | "skills" | "seniority" | "role"; weight: number; value: number; points: number }[];
};

export type ScoredJob = {
  job: Job;
  /** Final score 0..1. */
  score: number;
  breakdown: Breakdown;
};
