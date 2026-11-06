/**
 * Pure helpers shared by the insight pages' server and client code: small-sample
 * statistics, number formatting and the network colour grouping. No Node APIs here,
 * so client components may import it.
 */

/** True when a bootstrap interval includes zero, i.e. the difference is not distinguishable from "no effect". */
export const crossesZero = (lo: number, hi: number) => lo <= 0 && hi >= 0;

type PremiumLike = { diff: number; ci_low: number; ci_high: number };

/**
 * How far a pay-premium interval stays from zero, in the direction of its gap: `ci_low` for a positive gap,
 * `-ci_high` for a negative one (negative when the interval crosses zero). The headline skill is the one with
 * the largest value, not the largest point estimate, so a big but fragile estimate cannot lead.
 */
export const certainGap = (r: PremiumLike) => (r.diff >= 0 ? r.ci_low : -r.ci_high);

/** The row whose interval excludes zero and stays furthest from it; `null` when every interval crosses zero. */
export function headlineRow<T extends PremiumLike>(rows: T[]): { top: T; clear: number } | null {
  const clear = rows.filter((r) => !crossesZero(r.ci_low, r.ci_high));
  if (!clear.length) return null;
  const top = [...clear].sort((a, b) => certainGap(b) - certainGap(a) || Math.abs(b.diff) - Math.abs(a.diff))[0];
  return { top, clear: clear.length };
}

const Z = 1.96;

/** Wilson score interval for a proportion x/n (better behaved than the Wald interval at small n and near 0/1). */
export function wilson(x: number, n: number): [number, number] {
  if (n <= 0) return [0, 1];
  const p = x / n;
  const z2 = Z * Z;
  const denom = 1 + z2 / n;
  const centre = (p + z2 / (2 * n)) / denom;
  const half = (Z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / denom;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}

/**
 * Newcombe hybrid-score 95% interval for the difference of two independent proportions
 * p1 - p2 (method 10 in Newcombe 1998). Built from the two Wilson intervals, so it stays valid
 * for small groups and for shares near 0 or 1.
 */
export function newcombeDiff(x1: number, n1: number, x2: number, n2: number): { diff: number; lo: number; hi: number } {
  const p1 = n1 ? x1 / n1 : 0;
  const p2 = n2 ? x2 / n2 : 0;
  const [l1, u1] = wilson(x1, n1);
  const [l2, u2] = wilson(x2, n2);
  const diff = p1 - p2;
  return {
    diff,
    lo: diff - Math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2),
    hi: diff + Math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2),
  };
}

/** Median of a numeric array (null when empty). */
export function median(values: number[]): number | null {
  if (!values.length) return null;
  const v = [...values].sort((a, b) => a - b);
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/** 24000 -> "+$24k", -8250 -> "−$8k", 0 -> "$0". */
export function fmtSignedUsd(n: number): string {
  const v = Math.abs(n);
  const s = v >= 1000 ? `$${Math.round(v / 1000)}k` : `$${Math.round(v)}`;
  if (Math.round(v) === 0) return "$0";
  return `${n > 0 ? "+" : "−"}${s}`;
}

/** 2.43 -> "2.4×", 12.6 -> "13×". */
export function fmtLift(l: number): string {
  return `${l >= 10 ? Math.round(l) : l.toFixed(1)}×`;
}

/** Percentage-point difference of two shares (0..1): 0.123 -> "+12 pp". */
export function fmtShareDiffPP(d: number): string {
  const pp = Math.round(d * 100);
  if (pp === 0) return "0 pp";
  return `${pp > 0 ? "+" : "−"}${Math.abs(pp)} pp`;
}

/**
 * Network colour groups. Seven categories get a fixed palette slot (color follows the
 * entity, never its rank); the remaining categories share one neutral "Other" group, so the
 * chart never needs more hues than the validated palette offers. `s6` is skipped on purpose:
 * it is too close to `s3` for an all-pairs chart like a network.
 */
export type NetworkGroup = { id: string; label: string; color: string; categories: string[] };

export const NETWORK_GROUPS: NetworkGroup[] = [
  { id: "language", label: "Language", color: "var(--s1)", categories: ["language"] },
  { id: "framework", label: "Framework", color: "var(--s2)", categories: ["framework"] },
  { id: "cloud", label: "Cloud", color: "var(--s3)", categories: ["cloud"] },
  { id: "data", label: "Data", color: "var(--s4)", categories: ["data"] },
  { id: "ai_ml", label: "AI / ML", color: "var(--s7)", categories: ["ai_ml"] },
  { id: "devops", label: "DevOps", color: "var(--s5)", categories: ["devops"] },
  { id: "database", label: "Database", color: "var(--s8)", categories: ["database"] },
  { id: "other", label: "Tools, business & other", color: "var(--muted)", categories: ["tool", "design", "business", "other"] },
];

const GROUP_BY_CATEGORY = new Map(NETWORK_GROUPS.flatMap((g) => g.categories.map((c) => [c, g.id] as const)));

export function groupIdOf(category: string): string {
  return GROUP_BY_CATEGORY.get(category) ?? "other";
}

export const GROUP_BY_ID = new Map(NETWORK_GROUPS.map((g) => [g.id, g]));
