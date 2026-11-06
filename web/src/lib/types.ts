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
  /** "targeted" when the fetch is filtered toward data roles (v3); absent in older snapshots. */
  scope?: "broad" | "targeted";
  /** Postings from this source still listed in the latest fetch (v3). */
  active?: number;
};

export type Meta = {
  /** Present (true) only on generated sample data. */
  sample?: boolean;
  generated_at: string;
  last_run_at: string;
  window_days: number;
  backend: string;
  model: string;
  totals: {
    jobs: number;
    /** Open postings listed in jobs.json (v3). */
    active?: number;
    /** Companies with at least one open posting: exactly the rows of companies.json (v3.1). */
    companies: number;
    /** Companies that posted inside the window, open or not (v3.1). */
    companies_window?: number;
    with_salary: number;
    skills: number;
  };
  sources: SourceInfo[];
  weekly: { week: string; jobs: number }[];
  /** Display name of every skill slug used in jobs.json, including the ones without a skills.json row (v3.1). */
  skill_names?: Record<string, string>;
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

/**
 * One row of `insights.json` `skill_premium` (PLAN.md section 5). Raw fields compare the median
 * advertised annual USD salary of postings with and without the skill, with a company-cluster
 * bootstrap 95% interval. The `adj_*` fields come from a regression of log salary on the skill plus
 * role, seniority and region-group dummies, over the same resamples: `adj_pct` = 100 * (exp(b) - 1)
 * is how much more postings with the skill advertise than postings of the same role, seniority and
 * region group without it, and `adj_usd` is that effect at the pay level of the postings that list the
 * skill (`median_with - median_with / (1 + adj_pct / 100)`).
 * They are `null` when nothing varies within role, seniority and region for the skill, and absent in
 * snapshots older than v3.2.
 */
export type SkillPremium = {
  slug: string;
  name: string;
  n_with: number;
  n_without: number;
  /** Distinct companies behind `n_with` (v3.1); absent in older snapshots. */
  n_companies?: number;
  median_with: number;
  median_without: number;
  diff: number;
  ci_low: number;
  ci_high: number;
  /** Role-, seniority- and region-adjusted premium in percent (v3.2). */
  adj_pct?: number | null;
  /** The adjusted effect in annual USD at the pay level of postings that list the skill (v3.2). */
  adj_usd?: number | null;
  adj_ci_low_pct?: number | null;
  adj_ci_high_pct?: number | null;
};
