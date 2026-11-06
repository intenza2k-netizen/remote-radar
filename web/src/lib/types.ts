/**
 * Types for the published snapshot (PLAN.md, "Shared contracts" section 4).
 * The site reads only `public/data/*.json`; nothing here is invented beyond that
 * contract, except `meta.sample` (optional flag set by the sample-data generator).
 */

export type SourceInfo = {
  name: string;
  display_name: string;
  homepage: string;
  jobs: number;
};

export type Meta = {
  /** Present (true) only on generated sample data. */
  sample?: boolean;
  generated_at: string;
  last_run_at: string;
  window_days: number;
  backend: string;
  model: string;
  totals: { jobs: number; companies: number; with_salary: number; skills: number };
  sources: SourceInfo[];
  weekly: { week: string; jobs: number }[];
};

export type TrendPoint = { week: string; count: number; share: number };

export type Skill = {
  slug: string;
  name: string;
  category: string;
  count: number;
  /** Fraction (0..1) of jobs in the window that mention the skill. */
  share: number;
  /** Share last 4 weeks minus share previous 4 weeks, in percentage points. */
  change_4w: number | null;
  median_salary_usd: number | null;
  trend: TrendPoint[];
  cooccurring: { slug: string; count: number }[];
};

export type Role = { role: string; count: number; median_salary_usd: number | null };

export type SalaryDist = {
  key: string;
  n: number;
  p10: number;
  p25: number;
  median: number;
  p75: number;
  p90: number;
};

export type SalaryData = { by_seniority: SalaryDist[]; by_role: SalaryDist[] };

export type JobSalary = {
  min: number | null;
  max: number | null;
  currency: string;
  period: string;
  annual_usd_mid: number;
};

export type Job = {
  id: string;
  title: string;
  company: string;
  url: string;
  source: string;
  posted_at: string;
  location: string | null;
  remote_regions: string[];
  role: string | null;
  seniority: string | null;
  employment_type: string | null;
  skills: string[];
  salary: JobSalary | null;
};

export type EvalBackend = {
  backend: string;
  model: string;
  skills_precision: number;
  skills_recall: number;
  skills_f1: number;
  seniority_acc: number;
  role_acc: number;
  salary_acc: number;
  median_latency_ms: number;
  cost_per_1k_usd: number;
  failures: number;
};

export type EvalData = {
  generated_at: string;
  n_labeled: number;
  backends: EvalBackend[];
};
