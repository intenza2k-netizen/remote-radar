import "server-only";
import fs from "node:fs";
import path from "node:path";
import { crossesZero, fmtSignedUsd, groupIdOf, median, newcombeDiff } from "@/components/insights/stats";
import { fmtInt, fmtShare, roleLabel } from "./format";
import type { Job } from "./types";

/**
 * Types, build-time loaders and server-side computations for the analytical pages
 * (`/insights`, `/companies`). Contract: PLAN.md section 5. The files may be absent
 * (before the first pipeline run that produces them): loaders return null / [] and the
 * pages show an empty state instead of failing the build.
 */

// ------------------------------------------------------------------ contract types

export type SkillPremium = {
  slug: string;
  name: string;
  n_with: number;
  n_without: number;
  median_with: number;
  median_without: number;
  diff: number;
  ci_low: number;
  ci_high: number;
};

export type LiftSkill = { slug: string; name: string; share_senior: number; share_junior: number; lift: number };
export type RoleLift = { role: string; n_senior: number; n_junior: number; skills: LiftSkill[] };

export type GraphNode = { slug: string; name: string; category: string; count: number };
export type GraphEdge = { a: string; b: string; count: number; pmi: number };
export type SkillGraph = { nodes: GraphNode[]; edges: GraphEdge[] };

export type RoleSkills = { role: string; n: number; top: { slug: string; name: string; share: number }[] };

export type Insights = {
  skill_premium: SkillPremium[];
  seniority_lift: RoleLift[];
  skill_graph: SkillGraph;
  role_skills: RoleSkills[];
};

export type Company = {
  slug: string;
  name: string;
  jobs: number;
  roles: Record<string, number>;
  seniority: Record<string, number>;
  top_skills: { slug: string; name: string; count: number }[];
  median_salary_usd: number | null;
  sources: string[];
  job_ids: string[];
};

// ------------------------------------------------------------------ loaders

const DATA_DIR = path.join(process.cwd(), "public", "data");
const cache = new Map<string, unknown>();

/** Reads an optional JSON file; a missing or malformed file yields null (never throws). */
function readOptional<T>(file: string): T | null {
  if (cache.has(file)) return cache.get(file) as T | null;
  let value: T | null = null;
  try {
    value = JSON.parse(fs.readFileSync(path.join(DATA_DIR, file), "utf8")) as T;
  } catch {
    value = null;
  }
  cache.set(file, value);
  return value;
}

const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

/** `insights.json`, normalised so every section is at least an empty array. Null when the file is absent. */
export function getInsights(): Insights | null {
  const raw = readOptional<Partial<Insights>>("insights.json");
  if (!raw || typeof raw !== "object") return null;
  const g = raw.skill_graph;
  return {
    skill_premium: arr<SkillPremium>(raw.skill_premium),
    seniority_lift: arr<RoleLift>(raw.seniority_lift),
    skill_graph: { nodes: arr<GraphNode>(g?.nodes), edges: arr<GraphEdge>(g?.edges) },
    role_skills: arr<RoleSkills>(raw.role_skills),
  };
}

export function getCompanies(): Company[] {
  return arr<Company>(readOptional<Company[]>("companies.json"));
}

export function getCompany(slug: string): Company | undefined {
  return getCompanies().find((c) => c.slug === slug);
}

/** Company display name to page slug, for linking company names in job lists. */
export function getCompanySlugMap(): Record<string, string> {
  return Object.fromEntries(getCompanies().map((c) => [c.name, c.slug]));
}

// ------------------------------------------------------------------ company helpers

export type CompanyRow = {
  slug: string;
  name: string;
  jobs: number;
  /** Role keys by posting count, most frequent first. */
  roles: { role: string; n: number }[];
  top_skills: { slug: string; name: string }[];
  median_salary_usd: number | null;
  /** Postings with a stated salary (the n behind the median). */
  n_salary: number;
  sources: string[];
};

/** Rows for the companies table, with the salary sample size taken from jobs.json. */
export function companyRows(companies: Company[], jobs: Job[]): CompanyRow[] {
  const salaried = new Map(jobs.map((j) => [j.id, j.salary != null]));
  return companies.map((c) => ({
    slug: c.slug,
    name: c.name,
    jobs: c.jobs,
    roles: Object.entries(c.roles)
      .map(([role, n]) => ({ role, n }))
      .sort((a, b) => b.n - a.n || a.role.localeCompare(b.role)),
    top_skills: c.top_skills.slice(0, 4).map((s) => ({ slug: s.slug, name: s.name })),
    median_salary_usd: c.median_salary_usd,
    n_salary: c.job_ids.filter((id) => salaried.get(id)).length,
    sources: c.sources,
  }));
}

// ------------------------------------------------------------------ seniority lift

export type LiftRow = LiftSkill & {
  /** share_senior - share_junior. */
  diff: number;
  /** Newcombe 95% interval of that difference. */
  ci_low: number;
  ci_high: number;
  /** True when the interval excludes zero. */
  clear: boolean;
};

export type RoleLiftPrepared = { role: string; n_senior: number; n_junior: number; rows: LiftRow[] };

/**
 * Adds a 95% interval to each skill's senior-vs-junior share difference. The pipeline publishes
 * shares and group sizes, not an interval, so it is derived here: counts = share * n, then
 * Newcombe's hybrid-score interval for two independent proportions.
 */
export function prepareLift(roles: RoleLift[]): RoleLiftPrepared[] {
  return roles.map((r) => ({
    role: r.role,
    n_senior: r.n_senior,
    n_junior: r.n_junior,
    rows: r.skills
      .map((s) => {
        const d = newcombeDiff(Math.round(s.share_senior * r.n_senior), r.n_senior, Math.round(s.share_junior * r.n_junior), r.n_junior);
        return { ...s, diff: d.diff, ci_low: d.lo, ci_high: d.hi, clear: !crossesZero(d.lo, d.hi) };
      })
      .sort((a, b) => b.lift - a.lift),
  }));
}

// ------------------------------------------------------------------ headlines (one sentence each, generated from the data)

export function premiumHeadline(rows: SkillPremium[]): string | null {
  if (!rows.length) return null;
  const clear = rows.filter((r) => !crossesZero(r.ci_low, r.ci_high));
  if (!clear.length) {
    return `At this sample size no skill shows a pay difference we can tell apart from zero (${rows.length} skills tested).`;
  }
  const top = [...clear].sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff))[0];
  const gap = `${fmtSignedUsd(top.diff)} a year in median advertised salary (95% interval ${fmtSignedUsd(top.ci_low)} to ${fmtSignedUsd(top.ci_high)})`;
  // Raw comparison, not adjusted for role or seniority: say so in the headline itself.
  const caveat = "Postings that list it pay differently, mostly because of which roles ask for it, not because of the skill itself.";
  if (clear.length === 1) return `${top.name} is the only skill of ${rows.length} tested with a pay gap we can tell apart from zero: ${gap}. ${caveat}`;
  return `${clear.length} of ${rows.length} skills show a pay gap we can tell apart from zero; the largest is ${top.name} at ${gap}. ${caveat}`;
}

export function liftHeadline(roles: RoleLiftPrepared[]): string | null {
  const all = roles.flatMap((r) => r.rows.map((row) => ({ role: r.role, row })));
  if (!all.length) return null;
  const clear = all.filter((x) => x.row.clear && x.row.diff > 0);
  if (!clear.length) {
    return "No skill separates senior from junior postings by more than chance could produce at these sample sizes.";
  }
  const best = [...clear].sort((a, b) => b.row.diff - a.row.diff)[0];
  return `${best.row.name} is the clearest senior signal in ${roleLabel(best.role).toLowerCase()} postings: it appears in ${fmtShare(best.row.share_senior)} of senior postings against ${fmtShare(best.row.share_junior)} of junior ones.`;
}

export type Pair = { a: string; b: string; aName: string; bName: string; count: number; pmi: number; times: number };

/** Strongest skill pairs by PMI, ignoring pairs seen too rarely to trust (falls back to the contract floor of 3). */
export function strongestPairs(graph: SkillGraph, limit = 12): Pair[] {
  const names = new Map(graph.nodes.map((n) => [n.slug, n.name]));
  const toPair = (e: GraphEdge): Pair => ({
    a: e.a,
    b: e.b,
    aName: names.get(e.a) ?? e.a,
    bName: names.get(e.b) ?? e.b,
    count: e.count,
    pmi: e.pmi,
    times: 2 ** e.pmi,
  });
  const solid = graph.edges.filter((e) => e.count >= 5);
  const pool = solid.length >= Math.min(limit, 5) ? solid : graph.edges;
  return [...pool].sort((x, y) => y.pmi - x.pmi || y.count - x.count).slice(0, limit).map(toPair);
}

export function graphHeadline(graph: SkillGraph): string | null {
  const best = strongestPairs(graph, 1)[0];
  if (!best) return null;
  return `${best.aName} and ${best.bName} are the most tightly coupled pair: they share ${fmtInt(best.count)} postings, about ${fmtInt(best.times)} times more than independent skills would.`;
}

export function roleSkillsHeadline(rows: RoleSkills[]): string | null {
  const usable = rows.filter((r) => r.top.length);
  if (!usable.length) return null;
  const leaders = new Map<string, { name: string; roles: string[] }>();
  for (const r of usable) {
    const t = r.top[0];
    const e = leaders.get(t.slug) ?? { name: t.name, roles: [] };
    e.roles.push(r.role);
    leaders.set(t.slug, e);
  }
  const best = [...leaders.values()].sort((a, b) => b.roles.length - a.roles.length || a.name.localeCompare(b.name))[0];
  if (best.roles.length > 1) return `${best.name} is the most requested skill in ${best.roles.length} of ${usable.length} role groups; the rest have their own leaders.`;
  const [x, y] = usable;
  return y
    ? `Each role asks for something different: ${roleLabel(x.role)} postings lead with ${x.top[0].name}, ${roleLabel(y.role)} with ${y.top[0].name}.`
    : `${roleLabel(x.role)} postings lead with ${x.top[0].name}.`;
}

// ------------------------------------------------------------------ network layout (deterministic, build time)

export type PlacedNode = {
  slug: string;
  x: number;
  y: number;
  r: number;
  /** Label anchor (text-anchor "start" at x/y) or null when a label would collide. */
  label: { x: number; y: number } | null;
};

export type NetLayout = {
  width: number;
  height: number;
  fontSize: number;
  nodes: PlacedNode[];
  edges: { a: string; b: string; x1: number; y1: number; x2: number; y2: number; w: number; o: number }[];
};

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type LayoutOptions = { width: number; height: number; seed: number; iterations: number; pad: number; rMin: number; rMax: number; fontSize: number };

/**
 * Fruchterman-Reingold force layout with a fixed seed, so every build gives the same picture.
 * Repulsion between all node pairs, springs along PMI-weighted edges, weak gravity to the centre,
 * linear cooling; then the cloud is stretched to the canvas, residual overlaps are pushed apart and
 * labels are placed greedily (largest node first, skipped when they would collide).
 */
export function layoutGraph(graph: SkillGraph, o: LayoutOptions): NetLayout {
  const { width: W, height: H, pad } = o;
  const nodes = graph.nodes;
  const n = nodes.length;
  if (!n) return { width: W, height: H, fontSize: o.fontSize, nodes: [], edges: [] };

  const maxCount = Math.max(...nodes.map((d) => d.count), 1);
  const rad = nodes.map((d) => o.rMin + (o.rMax - o.rMin) * Math.sqrt(d.count / maxCount));
  const idx = new Map(nodes.map((d, i) => [d.slug, i]));
  const valid = graph.edges.flatMap((e) => {
    const i = idx.get(e.a);
    const j = idx.get(e.b);
    return i === undefined || j === undefined ? [] : [{ e, i, j }];
  });
  const pmis = valid.map((v) => v.e.pmi);
  const minP = Math.min(...pmis, 0);
  const maxP = Math.max(...pmis, 1);
  const spring = valid.map((v) => ({ i: v.i, j: v.j, w: 0.35 + 0.65 * ((v.e.pmi - minP) / (maxP - minP || 1)) }));

  const rand = mulberry32(o.seed);
  const cx = W / 2;
  const cy = H / 2;
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + rand() * 0.5;
    const rr = (0.25 + rand() * 0.25) * Math.min(W, H);
    x[i] = cx + Math.cos(a) * rr;
    y[i] = cy + Math.sin(a) * rr;
  }

  const k = Math.sqrt(((W - 2 * pad) * (H - 2 * pad)) / n) * 1.2;
  const cutoff = k * 3;
  const dx = new Float64Array(n);
  const dy = new Float64Array(n);
  for (let it = 0; it < o.iterations; it++) {
    const temp = 0.09 * Math.max(W, H) * (1 - it / o.iterations) + 0.4;
    dx.fill(0);
    dy.fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ex = x[i] - x[j];
        let ey = y[i] - y[j];
        let d = Math.hypot(ex, ey);
        if (d < 1e-6) {
          ex = rand() - 0.5;
          ey = rand() - 0.5;
          d = Math.hypot(ex, ey);
        }
        // Short-range repulsion only: with a global k^2/d force a crowded core flings weakly
        // connected skills to the canvas corners and the picture becomes a core plus dust.
        if (d > cutoff) continue;
        let f = (k * k) / d;
        const minD = rad[i] + rad[j] + 3;
        if (d < minD) f += (minD - d) * 4;
        const ux = ex / d;
        const uy = ey / d;
        dx[i] += ux * f;
        dy[i] += uy * f;
        dx[j] -= ux * f;
        dy[j] -= uy * f;
      }
    }
    for (const s of spring) {
      const ex = x[s.i] - x[s.j];
      const ey = y[s.i] - y[s.j];
      const d = Math.hypot(ex, ey) || 1e-6;
      const f = ((d * d) / k) * s.w * 0.55;
      const ux = ex / d;
      const uy = ey / d;
      dx[s.i] -= ux * f;
      dy[s.i] -= uy * f;
      dx[s.j] += ux * f;
      dy[s.j] += uy * f;
    }
    for (let i = 0; i < n; i++) {
      dx[i] -= (x[i] - cx) * 0.12;
      dy[i] -= (y[i] - cy) * 0.12;
      const len = Math.hypot(dx[i], dy[i]) || 1e-6;
      const step = Math.min(len, temp);
      x[i] += (dx[i] / len) * step;
      y[i] += (dy[i] / len) * step;
    }
  }

  // Stretch the cloud over the canvas (centres only; radii stay as drawn).
  const lo = pad + o.rMax;
  const fit = (v: Float64Array, size: number) => {
    let mn = Infinity;
    let mx = -Infinity;
    for (const t of v) {
      mn = Math.min(mn, t);
      mx = Math.max(mx, t);
    }
    const span = mx - mn || 1;
    for (let i = 0; i < n; i++) v[i] = lo + ((v[i] - mn) / span) * (size - 2 * lo);
  };
  fit(x, W);
  fit(y, H);

  // Resolve overlaps left over after stretching.
  for (let pass = 0; pass < 60; pass++) {
    let moved = false;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const ex = x[i] - x[j];
        const ey = y[i] - y[j];
        const d = Math.hypot(ex, ey) || 1e-6;
        const minD = rad[i] + rad[j] + 2;
        if (d < minD) {
          const push = (minD - d) / 2;
          x[i] += (ex / d) * push;
          y[i] += (ey / d) * push;
          x[j] -= (ex / d) * push;
          y[j] -= (ey / d) * push;
          moved = true;
        }
      }
    }
    for (let i = 0; i < n; i++) {
      x[i] = Math.min(W - pad - rad[i], Math.max(pad + rad[i], x[i]));
      y[i] = Math.min(H - pad - rad[i], Math.max(pad + rad[i], y[i]));
    }
    if (!moved) break;
  }

  // Greedy label placement, biggest nodes first.
  const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
  const labels: ({ x: number; y: number } | null)[] = new Array(n).fill(null);
  const order = [...nodes.keys()].sort((a, b) => nodes[b].count - nodes[a].count);
  const fs = o.fontSize;
  for (const i of order) {
    const w = nodes[i].name.length * fs * 0.56 + 2;
    const left = Math.min(W - 2 - w, Math.max(2, x[i] - w / 2));
    const candidates = [y[i] + rad[i] + fs * 0.95 + 1, y[i] - rad[i] - 3];
    for (const base of candidates) {
      if (base - fs < 1 || base + 3 > H) continue;
      const box = { x0: left - 2, y0: base - fs, x1: left + w + 2, y1: base + 3 };
      if (placed.some((p) => box.x0 < p.x1 && box.x1 > p.x0 && box.y0 < p.y1 && box.y1 > p.y0)) continue;
      placed.push(box);
      labels[i] = { x: Math.round(left * 10) / 10, y: Math.round(base * 10) / 10 };
      break;
    }
  }

  const r1 = (v: number) => Math.round(v * 10) / 10;
  return {
    width: W,
    height: H,
    fontSize: fs,
    nodes: nodes.map((d, i) => ({ slug: d.slug, x: r1(x[i]), y: r1(y[i]), r: r1(rad[i]), label: labels[i] })),
    edges: valid.map((v, q) => ({
      a: v.e.a,
      b: v.e.b,
      x1: r1(x[v.i]),
      y1: r1(y[v.i]),
      x2: r1(x[v.j]),
      y2: r1(y[v.j]),
      w: Math.round((0.6 + 1.4 * spring[q].w) * 10) / 10,
      o: Math.round((0.12 + 0.3 * spring[q].w) * 100) / 100,
    })),
  };
}

export type NetworkData = {
  nodes: (GraphNode & { group: string })[];
  edges: GraphEdge[];
  /** Wide canvas for tablets and desktops, tall canvas for phones. */
  wide: NetLayout;
  tall: NetLayout;
};

export function buildNetwork(graph: SkillGraph): NetworkData {
  return {
    nodes: graph.nodes.map((n) => ({ ...n, group: groupIdOf(n.category) })),
    edges: graph.edges,
    wide: layoutGraph(graph, { width: 960, height: 640, seed: 20261106, iterations: 400, pad: 14, rMin: 4, rMax: 17, fontSize: 12.5 }),
    tall: layoutGraph(graph, { width: 360, height: 620, seed: 20261107, iterations: 400, pad: 8, rMin: 3.5, rMax: 15, fontSize: 11.5 }),
  };
}

// ------------------------------------------------------------------ small formatting helpers for pages

/** Median and sample size of salaries in a list of jobs. */
export function salaryOf(jobs: Job[]): { median: number | null; n: number; min: number | null; max: number | null } {
  const v = jobs.flatMap((j) => (j.salary ? [j.salary.annual_usd_mid] : []));
  return { median: median(v), n: v.length, min: v.length ? Math.min(...v) : null, max: v.length ? Math.max(...v) : null };
}
