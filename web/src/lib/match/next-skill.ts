import { TOP_N } from "./constants";
import { skillCoverage } from "./score";
import type { ScoredJob } from "./types";
import type { SalaryModel } from "@/lib/salary-model";

/**
 * Next skill to learn. For each skill the CV lacks that your best matches list, the skills part of the score is
 * recomputed with the skill added (everything else in a posting's score is unchanged by a skill, so only that one
 * term moves) and two things are counted:
 *
 *  - `entersTop`: postings that move into your top TOP_N matches;
 *  - `covered`: postings among your best POOL matches that go from "not well covered" to "well covered".
 *
 * "Well covered" = you have at least COVERED_SHARE of the skills the posting lists, and it lists at least
 * COVERED_MIN_LISTED. The minimum keeps one- and two-skill ads (where one skill is 50 or 100%) from counting.
 * Skills are ranked by `covered`, then `entersTop`, then how many of the pool list the skill, then slug.
 * The ranking does not look at pay; the pay effect of the skill is shown next to it (`skillPay`).
 */

/** The postings the candidates and the "covered" count come from: your best matches. */
export const POOL = 100;
/** A skill must be listed by at least this many of the pool to be a candidate. */
export const MIN_LISTING = 3;
/** Well covered: you have at least this share of the skills the posting lists (two thirds) ... */
export const COVERED_SHARE = 2 / 3;
/** ... and it lists at least this many skills. */
export const COVERED_MIN_LISTED = 3;

export type NextSkill = {
  slug: string;
  /** How many of the pool list the skill (and you lack it). */
  listedBy: number;
  /** Postings that enter your top TOP_N when you add the skill (any posting, not only the pool). */
  entersTop: number;
  /** Postings of the pool that become well covered when you add the skill. */
  covered: number;
};

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** True when `matched` of `listed` skills reaches the "well covered" bar. Exact arithmetic, no rounding. */
export function isWellCovered(matched: number, listed: number): boolean {
  return listed >= COVERED_MIN_LISTED && matched >= COVERED_SHARE * listed - 1e-9;
}

/** Score of a posting after the skill is added: only the skills term moves. Null if the posting does not list the skill. */
export function scoreWith(m: ScoredJob, slug: string): number | null {
  if (!m.job.skills.includes(slug) || m.breakdown.missingSkills.indexOf(slug) < 0) return null;
  const part = m.breakdown.contributions.find((c) => c.key === "skills");
  if (!part) return null;
  const listed = m.job.skills.length;
  const after = skillCoverage(m.breakdown.matchedSkills.length + 1, listed);
  if (after == null) return null;
  return clamp01(m.score + part.weight * (after - part.value));
}

const byRank = (a: { score: number; posted_at: string }, b: { score: number; posted_at: string }) => b.score - a.score || b.posted_at.localeCompare(a.posted_at);

/**
 * `scored` is the ranked list of postings open to you (best first), `cvSkills` the skills in your profile.
 * Returns at most `limit` skills. With no skills in the profile there is nothing to add to (the skills part of
 * the score is off for every posting, and turning it on would reweight them all), so the list is empty.
 */
export function rankNextSkills(scored: readonly ScoredJob[], cvSkills: ReadonlySet<string>, limit = 8, topN = TOP_N, pool = POOL): NextSkill[] {
  if (cvSkills.size === 0 || scored.length === 0) return [];
  const poolJobs = scored.slice(0, pool);
  const listedBy = new Map<string, number>();
  for (const m of poolJobs) for (const s of new Set(m.breakdown.missingSkills)) listedBy.set(s, (listedBy.get(s) ?? 0) + 1);
  const candidates = [...listedBy].filter(([, n]) => n >= MIN_LISTING).map(([slug]) => slug);
  if (candidates.length === 0) return [];

  // Which postings list each candidate (and the user lacks it): one pass over every posting, not one per candidate.
  const wanted = new Set(candidates);
  const listing = new Map<string, ScoredJob[]>();
  for (const m of scored) {
    for (const s of new Set(m.breakdown.missingSkills)) {
      if (!wanted.has(s)) continue;
      const list = listing.get(s);
      if (list) list.push(m);
      else listing.set(s, [m]);
    }
  }

  const top = scored.slice(0, topN);
  const inTop = new Set(top.map((m) => m.job.id));
  const inPool = new Set(poolJobs.map((m) => m.job.id));

  const rows: NextSkill[] = candidates.map((slug) => {
    const list = listing.get(slug) ?? [];
    // Scores only go up, so a posting outside the top that does not list the skill cannot enter: the new top is
    // the best topN of (the current top) + (postings that list the skill, at their new score).
    const updated = new Map<string, number>();
    let covered = 0;
    for (const m of list) {
      const next = scoreWith(m, slug);
      if (next != null) updated.set(m.job.id, next);
      if (inPool.has(m.job.id) && !isWellCovered(m.breakdown.matchedSkills.length, m.job.skills.length) && isWellCovered(m.breakdown.matchedSkills.length + 1, m.job.skills.length)) covered++;
    }
    const contenders = new Map<string, { score: number; posted_at: string }>();
    for (const m of top) contenders.set(m.job.id, { score: updated.get(m.job.id) ?? m.score, posted_at: m.job.posted_at });
    for (const m of list) if (!contenders.has(m.job.id)) contenders.set(m.job.id, { score: updated.get(m.job.id) ?? m.score, posted_at: m.job.posted_at });
    const best = [...contenders].sort(([, a], [, b]) => byRank(a, b)).slice(0, topN);
    const entersTop = best.reduce((n, [id]) => n + (inTop.has(id) ? 0 : 1), 0);
    return { slug, listedBy: listedBy.get(slug) ?? 0, entersTop, covered };
  });

  rows.sort((a, b) => b.covered - a.covered || b.entersTop - a.entersTop || b.listedBy - a.listedBy || a.slug.localeCompare(b.slug));
  return rows.slice(0, limit);
}

// ------------------------------------------------------------------ pay effect

export type SkillPay = {
  pct: number;
  low: number;
  high: number;
  /** False when the 95% interval of the effect crosses zero: the data cannot tell this skill from no effect. */
  distinguishable: boolean;
  /** Salaried postings behind the figure, and the number of different companies. */
  n: number;
  companies: number;
};

/** The skill's pay association from `salary_model.json` (`skills[]`), or null when the model does not cover the skill. */
export function skillPay(model: SalaryModel | null, slug: string): SkillPay | null {
  const s = model?.skills.find((x) => x.slug === slug);
  if (!s || !Number.isFinite(s.pct) || !Number.isFinite(s.ci_low_pct) || !Number.isFinite(s.ci_high_pct)) return null;
  return { pct: s.pct, low: s.ci_low_pct, high: s.ci_high_pct, distinguishable: s.ci_low_pct > 0 || s.ci_high_pct < 0, n: s.n, companies: s.n_companies };
}

/** "+6%" / "−3%" (true minus sign), whole percent; "0%" for anything that rounds to zero. */
export function signedPct(pct: number): string {
  const r = Math.round(pct);
  if (r === 0) return "0%";
  return `${r > 0 ? "+" : "−"}${Math.abs(r)}%`;
}
