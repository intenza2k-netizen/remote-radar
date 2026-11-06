import fs from "node:fs";
import path from "node:path";
import { fmtInt, fmtShare, fmtUsdShort, SENIORITY_ORDER, seniorityLabel } from "./format";

/**
 * Types, loader and small pure helpers for the "Job types" page. Contract: PLAN.md section 6
 * (`archetypes.json`): clusters of active data-role postings by embedding. The loader is
 * build-time only (it reads from disk); client components import types from here, nothing else.
 */

export type ArchetypeSkill = { slug: string; name: string; share: number; lift: number };

export type Archetype = {
  id: string;
  name: string;
  summary: string;
  /** Title family that names the cluster, and the share of its postings whose title is in that family. */
  family?: string | null;
  family_share?: number;
  n: number;
  share: number;
  median_salary_usd: number | null;
  salary_n: number;
  /** Mean silhouette of the cluster's postings, -1..1. */
  silhouette?: number;
  seniority: Record<string, number>;
  top_skills: ArchetypeSkill[];
  top_titles: { title: string; n: number }[];
  example_job_ids: string[];
  /** L2-normalised embedding centroid; the CV matcher uses it, this page does not. */
  centroid?: number[];
};

export type ArchetypePoint = { id: string; a: string; x: number; y: number };

export type ArchetypesMethod = {
  algorithm: string;
  k: number;
  seed: number;
  silhouette: number | null;
  candidates: { k: number; silhouette: number }[];
  n_jobs: number;
  /** Share of the vectors' variance kept by the two plotted components. */
  pca_variance?: number[];
};

export type ArchetypesDoc = {
  version: number;
  method: ArchetypesMethod;
  archetypes: Archetype[];
  points: ArchetypePoint[];
};

// ------------------------------------------------------------------ loading

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

/**
 * Validates a parsed `archetypes.json`. Returns null when there is nothing to show (not a document,
 * no archetypes), drops archetypes without a name or size, and drops points that name an unknown archetype.
 */
export function parseArchetypes(raw: unknown): ArchetypesDoc | null {
  if (!isObj(raw)) return null;
  const archetypes = arr<Archetype>(raw.archetypes)
    .filter((a) => isObj(a) && typeof a.id === "string" && typeof a.name === "string" && typeof a.n === "number" && a.n > 0)
    .map((a) => ({
      ...a,
      median_salary_usd: typeof a.median_salary_usd === "number" ? a.median_salary_usd : null,
      salary_n: typeof a.salary_n === "number" ? a.salary_n : 0,
      seniority: isObj(a.seniority) ? a.seniority : {},
      top_skills: arr<ArchetypeSkill>(a.top_skills),
      top_titles: arr<{ title: string; n: number }>(a.top_titles),
      example_job_ids: arr<string>(a.example_job_ids),
    }));
  if (!archetypes.length) return null;
  const known = new Set(archetypes.map((a) => a.id));
  const points = arr<ArchetypePoint>(raw.points).filter((p) => isObj(p) && known.has(p.a) && Number.isFinite(p.x) && Number.isFinite(p.y));
  const m = isObj(raw.method) ? raw.method : {};
  const method: ArchetypesMethod = {
    algorithm: typeof m.algorithm === "string" ? m.algorithm : "spherical k-means",
    k: typeof m.k === "number" ? m.k : archetypes.length,
    seed: typeof m.seed === "number" ? m.seed : 0,
    silhouette: typeof m.silhouette === "number" ? m.silhouette : null,
    candidates: arr<{ k: number; silhouette: number }>(m.candidates),
    n_jobs: typeof m.n_jobs === "number" ? m.n_jobs : archetypes.reduce((s, a) => s + a.n, 0),
    pca_variance: Array.isArray(m.pca_variance) ? (m.pca_variance as number[]) : undefined,
  };
  return { version: typeof raw.version === "number" ? raw.version : 1, method, archetypes, points };
}

/** `archetypes.json`, or null when it is absent, malformed or has no archetypes (too few data postings). */
export function getArchetypes(): ArchetypesDoc | null {
  try {
    const text = fs.readFileSync(path.join(process.cwd(), "public", "data", "archetypes.json"), "utf8");
    return parseArchetypes(JSON.parse(text));
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ derived numbers

/** A cluster whose silhouette is below this is about as close to a neighbouring cluster as to itself. */
export const LOOSE_SILHOUETTE = 0.05;
/** A cluster named after a title family where fewer than this share of its titles belong to it is held together by skills, not titles. */
export const LOOSE_TITLE_SHARE = 0.5;

/** Why a cluster should be read with care; empty when it is well defined. */
export function looseReasons(a: Pick<Archetype, "name" | "family" | "family_share" | "silhouette">): string[] {
  const out: string[] = [];
  if (a.silhouette != null && a.silhouette < LOOSE_SILHOUETTE) {
    out.push(`Fuzzy edges: its postings are about as close to a neighbouring type as to this one (silhouette ${a.silhouette.toFixed(2)}).`);
  }
  if (a.family && a.family_share != null && a.family_share < LOOSE_TITLE_SHARE) {
    out.push(`Mixed titles: only ${fmtShare(a.family_share)} of its postings are titled like "${a.family.toLowerCase()}"; the rest are grouped by what the posting asks for.`);
  }
  return out;
}

/** Levels in seniority order, then "unspecified", with counts and shares of the cluster. */
export function seniorityMix(a: Pick<Archetype, "n" | "seniority">): { level: string; n: number; share: number }[] {
  const order = [...SENIORITY_ORDER, "unspecified"];
  const extra = Object.keys(a.seniority).filter((k) => !order.includes(k));
  return [...order, ...extra]
    .filter((level) => (a.seniority[level] ?? 0) > 0)
    .map((level) => ({ level, n: a.seniority[level], share: a.seniority[level] / a.n }));
}

/**
 * Most common stated level, when at least a third of the postings state one (the same rule as the
 * pipeline's summary sentence). `share` is of the postings that state a level.
 */
export function typicalLevel(a: Pick<Archetype, "n" | "seniority">): { level: string; share: number; statedShare: number } | null {
  const stated = SENIORITY_ORDER.map((level) => ({ level, n: a.seniority[level] ?? 0 }));
  const total = stated.reduce((s, x) => s + x.n, 0);
  if (!total || total * 3 < a.n) return null;
  const top = stated.reduce((best, x) => (x.n > best.n ? x : best));
  return { level: top.level, share: top.n / total, statedShare: total / a.n };
}

/** The archetypes with a published median pay (>= 5 salaries), lowest and highest. */
export function payRange(archetypes: Archetype[]): { low: Archetype; high: Archetype } | null {
  const paid = archetypes.filter((a) => a.median_salary_usd != null);
  if (paid.length < 2) return null;
  const sorted = [...paid].sort((x, y) => (x.median_salary_usd as number) - (y.median_salary_usd as number));
  return { low: sorted[0], high: sorted[sorted.length - 1] };
}

/** The one-sentence takeaway, computed from the data. */
export function headline(doc: ArchetypesDoc): string {
  const { archetypes: list, method } = doc;
  const biggest = [...list].sort((a, b) => b.n - a.n)[0];
  const range = payRange(list);
  const head = `${fmtInt(method.n_jobs)} open data postings fall into ${list.length} job types`;
  const size = `the largest, ${biggest.name}, holds ${fmtShare(biggest.n / method.n_jobs)} of them`;
  if (!range) return `${head}; ${size}.`;
  return `${head}, and advertised pay differs between them: medians run from ${fmtUsdShort(range.low.median_salary_usd)} (${range.low.name}) to ${fmtUsdShort(range.high.median_salary_usd)} (${range.high.name}).`;
}

/** Mean plot position of each archetype's postings. */
export function archetypeCentres(doc: Pick<ArchetypesDoc, "points">): Map<string, { x: number; y: number; n: number }> {
  const sums = new Map<string, { x: number; y: number; n: number }>();
  for (const p of doc.points) {
    const s = sums.get(p.a) ?? { x: 0, y: 0, n: 0 };
    s.x += p.x;
    s.y += p.y;
    s.n += 1;
    sums.set(p.a, s);
  }
  return new Map([...sums].map(([id, s]) => [id, { x: s.x / s.n, y: s.y / s.n, n: s.n }]));
}

/** The archetypes whose plot centres are closest to `id`'s, nearest first. */
export function nearestTypes(doc: ArchetypesDoc, id: string, count = 2): Archetype[] {
  const centres = archetypeCentres(doc);
  const me = centres.get(id);
  if (!me) return [];
  return doc.archetypes
    .filter((a) => a.id !== id && centres.has(a.id))
    .map((a) => {
      const c = centres.get(a.id) as { x: number; y: number };
      return { a, d: Math.hypot(c.x - me.x, c.y - me.y) };
    })
    .sort((p, q) => p.d - q.d || p.a.name.localeCompare(q.a.name))
    .slice(0, count)
    .map((p) => p.a);
}

/** "Senior (47% of postings that state a level)" for a card; null when most postings state none. */
export function typicalLevelText(a: Pick<Archetype, "n" | "seniority">): string | null {
  const t = typicalLevel(a);
  if (!t) return null;
  return `${seniorityLabel(t.level)} (${fmtShare(t.share)} of those that state a level)`;
}
