import type { ScoredJob } from "./types";

export type GapSkill = {
  slug: string;
  /** Number of the compared jobs that list this skill and you lack it. */
  jobs: number;
  /** jobs / number of jobs compared (0..1). */
  share: number;
};

/**
 * Missing skills across the best matches, ranked by how many of those jobs ask for them.
 * Ties break on how common the skill is across the whole snapshot (`globalCount`), then slug.
 */
export function rankGaps(matches: ScoredJob[], globalCount: (slug: string) => number = () => 0): GapSkill[] {
  const counts = new Map<string, number>();
  for (const m of matches) for (const s of new Set(m.breakdown.missingSkills)) counts.set(s, (counts.get(s) ?? 0) + 1);
  const n = matches.length || 1;
  return [...counts.entries()]
    .map(([slug, jobs]) => ({ slug, jobs, share: jobs / n }))
    .sort((a, b) => b.jobs - a.jobs || globalCount(b.slug) - globalCount(a.slug) || a.slug.localeCompare(b.slug));
}

/** "dbt appears in 11 of your 30 best matches". Null when nothing is missing. */
export function gapHeadline(gaps: GapSkill[], total: number, name: (slug: string) => string): string | null {
  const top = gaps[0];
  if (!top || total === 0) return null;
  if (total === 1) return `${name(top.slug)} appears in your only match`;
  return `${name(top.slug)} appears in ${top.jobs} of your ${total} best matches`;
}
