/**
 * The pay estimator's model: types, parsing and prediction (PLAN.md section 6, `salary_model.json`).
 *
 * This file is client-safe (no `fs`); the build-time loader is `salary-model-data.ts`. `predictPay` is
 * the only implementation of the model the site uses; `radar.salary_model.predict_pay` is its Python
 * twin for the parity fixtures in `salary-model.test.ts`.
 *
 * The model: `exp(intercept + role + seniority + region group + sum of skill coefficients)`, fitted by
 * ridge regression on the natural log of advertised annual USD pay (midpoint of the range). The range
 * is the prediction times `exp(low_log)` and `exp(high_log)`, the 10th and 90th percentile of the
 * held-out residuals, so about 80% of unseen postings fell inside it.
 */

export const REGION_GROUPS = ["us_canada", "europe", "latam", "apac", "worldwide", "other_or_mixed", "unknown"] as const;
export type RegionGroup = (typeof REGION_GROUPS)[number];

const REGION_GROUP_LABEL: Record<RegionGroup, string> = {
  us_canada: "US or Canada",
  europe: "Europe",
  latam: "Latin America",
  apac: "Asia-Pacific",
  worldwide: "Worldwide",
  other_or_mixed: "Mixed or other",
  unknown: "Not stated",
};
export const regionGroupLabel = (g: string): string => REGION_GROUP_LABEL[g as RegionGroup] ?? g;

// ------------------------------------------------------------------ contract types

export type SalarySkill = {
  slug: string;
  name: string;
  /** Salaried postings that list the skill. */
  n: number;
  n_companies: number;
  /** Pay effect of the (shrunken) coefficient in percent, `100 * (exp(b) - 1)`. */
  pct: number;
  ci_low_pct: number;
  ci_high_pct: number;
};

export type SalaryDriver = { slug: string; name: string; pct: number; ci_low_pct: number; ci_high_pct: number; n: number };

export type SalaryEval = {
  method: string;
  n: number;
  folds: number;
  mae_usd: number;
  mae_ci_usd: [number, number];
  median_ape: number;
  r2_log: number;
  /** Share of held-out postings inside the 80% range. */
  coverage: number;
  /** The same predictions when each posting only gets `profile_max_skills` of its skills. */
  capped: { mae_usd: number; median_ape: number; r2_log: number };
  baseline: { name: string; mae_usd: number; median_ape: number; r2_log: number };
  /** How much lower the model's mean absolute error is than the baseline's, percent. */
  mae_gain_pct: number;
  mae_gain_ci_pct: [number, number];
  verdict: "better" | "similar" | "worse";
  note: string;
};

export type SalaryModel = {
  version: number;
  target: string;
  alpha: number;
  /** Company resamples behind the skill intervals. */
  bootstraps?: number;
  n_train: number;
  n_companies: number;
  intercept: number;
  reference: { role: string; seniority: string; region_group: string };
  /** Effects against the reference level; the reference level itself is absent (its effect is 0). */
  coef: { role: Record<string, number>; seniority: Record<string, number>; region_group: Record<string, number>; skill: Record<string, number> };
  /** Salaried postings per level, reference included. */
  levels: { role: Record<string, number>; seniority: Record<string, number>; region_group: Record<string, number> };
  /** Modelled skills, most frequent first. */
  skills: SalarySkill[];
  profile_max_skills: number;
  interval: { low_log: number; high_log: number; level: number };
  eval: SalaryEval;
  drivers: SalaryDriver[];
};

/** Published instead of a model when the snapshot has too few salaried postings. */
export type SalaryModelUnavailable = { version: number; reason: string };

export type SalaryModelDoc = SalaryModel | SalaryModelUnavailable;

export const hasModel = (doc: SalaryModelDoc | null | undefined): doc is SalaryModel => !!doc && "coef" in doc;

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/**
 * Checks the shape of a parsed `salary_model.json`. Returns the model, the "not enough data" document, or null
 * when the value is neither (missing file, older snapshot, malformed), so callers show an empty state.
 */
export function parseSalaryModel(raw: unknown): SalaryModelDoc | null {
  if (!isRecord(raw) || typeof raw.version !== "number") return null;
  if (typeof raw.reason === "string" && !("coef" in raw)) return { version: raw.version, reason: raw.reason };
  const coef = raw.coef;
  const interval = raw.interval;
  if (!isRecord(coef) || !isRecord(coef.role) || !isRecord(coef.seniority) || !isRecord(coef.region_group) || !isRecord(coef.skill)) return null;
  if (!isRecord(interval) || typeof interval.low_log !== "number" || typeof interval.high_log !== "number") return null;
  if (typeof raw.intercept !== "number" || typeof raw.profile_max_skills !== "number" || !Array.isArray(raw.skills) || !isRecord(raw.reference) || !isRecord(raw.levels) || !isRecord(raw.eval)) return null;
  return raw as unknown as SalaryModel;
}

// ------------------------------------------------------------------ prediction

export type PayInput = { role: string; seniority: string; regionGroup: string; skills: readonly string[] };

export type PayEstimate = {
  /** Whole USD per year. */
  median: number;
  low: number;
  high: number;
  /** The skills that entered the estimate, in the order the profile rule picked them. */
  used_skills: string[];
};

/**
 * The profile rule: skills the model does not know are ignored; the rest are ordered by market frequency
 * (salaried postings that list the skill, most first, ties by slug), never by their coefficient, and only the
 * first `profile_max_skills` count. A long CV cannot inflate the estimate and a skill is not picked for paying well.
 */
export function profileSkills(model: SalaryModel, skills: readonly string[]): string[] {
  const frequency = new Map(model.skills.map((s) => [s.slug, s.n]));
  const known = [...new Set(skills)].filter((s) => frequency.has(s) && s in model.coef.skill);
  known.sort((a, b) => (frequency.get(b)! - frequency.get(a)!) || (a < b ? -1 : a > b ? 1 : 0));
  return known.slice(0, model.profile_max_skills);
}

/** Effect of a level on log pay; a level the model has not seen (or the reference level) counts as 0. */
const levelEffect = (effects: Record<string, number>, level: string): number => (Object.prototype.hasOwnProperty.call(effects, level) ? effects[level] : 0);

export function predictLog(model: SalaryModel, input: PayInput): { log: number; used_skills: string[] } {
  const used = profileSkills(model, input.skills);
  let log = model.intercept;
  log += levelEffect(model.coef.role, input.role);
  log += levelEffect(model.coef.seniority, input.seniority);
  log += levelEffect(model.coef.region_group, input.regionGroup);
  for (const s of used) log += model.coef.skill[s];
  return { log, used_skills: used };
}

export function predictPay(model: SalaryModel, input: PayInput): PayEstimate {
  const { log, used_skills } = predictLog(model, input);
  return {
    median: Math.round(Math.exp(log)),
    low: Math.round(Math.exp(log + model.interval.low_log)),
    high: Math.round(Math.exp(log + model.interval.high_log)),
    used_skills,
  };
}

export type Contribution = { kind: "role" | "seniority" | "region" | "skill"; key: string; pct: number };

/** Percent a coefficient moves pay by: 0.2 -> 22.1. */
export const pctOf = (b: number): number => 100 * (Math.exp(b) - 1);

/**
 * How each input moves the estimate compared with the reference profile (the most common role, seniority and
 * region group, and no skills): role, seniority, region group and every skill that counted. Each line is the
 * input's own percentage; because the model multiplies, the lines compound rather than add.
 */
export function contributions(model: SalaryModel, input: PayInput): Contribution[] {
  const out: Contribution[] = [
    { kind: "role", key: input.role, pct: pctOf(levelEffect(model.coef.role, input.role)) },
    { kind: "seniority", key: input.seniority, pct: pctOf(levelEffect(model.coef.seniority, input.seniority)) },
    { kind: "region", key: input.regionGroup, pct: pctOf(levelEffect(model.coef.region_group, input.regionGroup)) },
  ];
  for (const s of profileSkills(model, input.skills)) out.push({ kind: "skill", key: s, pct: pctOf(model.coef.skill[s]) });
  return out;
}

// ------------------------------------------------------------------ region groups

/**
 * Mirror of `radar.regions.region_group` for canonical region names (the `remote_regions` published in
 * `jobs.json`); keep the two in step. The Python function canonicalises raw strings through `regions.yaml`
 * first ("USA", "AL, AZ ..." and so on); the browser only gets canonical names, so only the key
 * normalisation (case, accents, dots, hyphens, "&", a leading "the") and the aliases of worldwide ("anywhere",
 * "global" ...) are repeated here. Rules, in order:
 *  1. no region: `unknown`;  2. any of United States, Canada, North America: `us_canada`;
 *  3. only "worldwide": `worldwide`;  4. every value in one list (Europe, Latin America, Asia-Pacific): that group;
 *  5. anything else, including a mix of groups or "worldwide" next to other values: `other_or_mixed`.
 */
const NORTH_AMERICA = ["United States", "Canada", "North America"];
const EUROPE =
  "EU, EEA, EMEA, Europe, European Union, United Kingdom, Ireland, Germany, France, Spain, Portugal, Italy, Netherlands, Belgium, Luxembourg, Switzerland, Austria, Liechtenstein, Monaco, Andorra, Malta, Cyprus, Iceland, Norway, Sweden, Denmark, Finland, Estonia, Latvia, Lithuania, Poland, Czechia, Slovakia, Hungary, Romania, Bulgaria, Greece, Croatia, Slovenia, Serbia, Bosnia and Herzegovina, Montenegro, North Macedonia, Albania, Kosovo, Moldova, Ukraine, Belarus, Russia";
const LATAM =
  "Latin America, Mexico, Guatemala, Belize, Honduras, El Salvador, Nicaragua, Costa Rica, Panama, Colombia, Venezuela, Guyana, Suriname, Ecuador, Peru, Bolivia, Brazil, Paraguay, Uruguay, Argentina, Chile, Cuba, Dominican Republic, Haiti, Jamaica, Puerto Rico, Trinidad and Tobago, Barbados, Bahamas, Anguilla, Antigua and Barbuda, Aruba";
const APAC =
  "Asia-Pacific, India, Pakistan, Bangladesh, Sri Lanka, Nepal, China, Hong Kong, Taiwan, Japan, South Korea, Mongolia, Philippines, Indonesia, Malaysia, Singapore, Vietnam, Thailand, Cambodia, Laos, Myanmar, Brunei, Timor-Leste, Australia, New Zealand, Papua New Guinea, Fiji";

/** `radar.regions.region_key`: accents, case, dots, hyphens/underscores, "&" and a leading "the" ignored. */
export function regionKey(text: string): string {
  const t = text
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/\./g, "")
    .replace(/[\s_\-–—]+/g, " ")
    .trim();
  return t.replace(/^the /, "");
}

const keysOf = (list: string | string[]): string[] => (typeof list === "string" ? list.split(",") : list).map((n) => regionKey(n.trim()));

const GROUP_OF = new Map<string, RegionGroup>();
for (const [group, names] of [
  ["us_canada", NORTH_AMERICA],
  ["europe", EUROPE],
  ["latam", LATAM],
  ["apac", APAC],
] as const) {
  for (const key of keysOf(names)) GROUP_OF.set(key, group);
}
// The `worldwide:` aliases of regions.yaml.
const WORLDWIDE_KEYS = new Set(["worldwide", "anywhere", "global", "world", "worldwide remote", "anywhere in the world"]);

export function regionGroupOf(regions: readonly string[] | null | undefined): RegionGroup {
  const keys: string[] = [];
  for (const r of regions ?? []) {
    if (typeof r !== "string") continue;
    const key = regionKey(r.replace(/\s+/g, " ").trim());
    if (key && !keys.includes(key)) keys.push(key);
  }
  if (keys.length === 0) return "unknown";
  if (keys.some((k) => GROUP_OF.get(k) === "us_canada")) return "us_canada";
  if (keys.every((k) => WORLDWIDE_KEYS.has(k))) return "worldwide";
  const groups = new Set(keys.map((k) => GROUP_OF.get(k)));
  if (groups.size === 1) {
    const only = [...groups][0];
    if (only) return only;
  }
  return "other_or_mixed";
}
