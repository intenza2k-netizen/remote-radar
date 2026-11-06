import { TOP_N } from "./constants";

/**
 * Which job type you fit: the archetype (`archetypes.json`, clusters of active data postings) of each of your
 * best data matches. Counting the archetypes of the matches is more robust than comparing a CV vector with
 * the cluster centroids: a CV is long, structured prose and a posting is a short ad, so their vectors sit in
 * different parts of the space, while a matched posting already has a published cluster.
 */

export type JobTypeRow = { id: string; name: string; jobs: number; share: number };

export type JobTypeMix = {
  /** Matches that belong to a job type, at most `limit`; the denominator of every share. */
  total: number;
  /** Types with at least one match, most matches first. */
  rows: JobTypeRow[];
};

/**
 * `scored` is the ranked list (best first). Only data postings have a job type, so the walk skips the rest and
 * stops after `limit` data matches: "your 30 best data matches", whatever else ranks between them.
 */
export function jobTypeMix(
  scored: readonly { job: { id: string } }[],
  assignment: ReadonlyMap<string, string>,
  names: Readonly<Record<string, string>>,
  limit: number = TOP_N,
): JobTypeMix {
  const counts = new Map<string, number>();
  let total = 0;
  for (const m of scored) {
    if (total >= limit) break;
    const type = assignment.get(m.job.id);
    if (type === undefined) continue;
    counts.set(type, (counts.get(type) ?? 0) + 1);
    total++;
  }
  const rows = [...counts.entries()]
    .map(([id, jobs]) => ({ id, name: names[id] ?? id, jobs, share: total ? jobs / total : 0 }))
    .sort((a, b) => b.jobs - a.jobs || a.name.localeCompare(b.name));
  return { total, rows };
}

/** "18 of your 30 best data matches are Data analyst postings". Null when no match is a data posting. */
export function jobTypeSentence(mix: JobTypeMix, limit: number = TOP_N): string | null {
  const top = mix.rows[0];
  if (!top || mix.total === 0) return null;
  const set = mix.total >= limit ? `your ${mix.total} best data matches` : `your ${mix.total} data ${mix.total === 1 ? "match" : "matches"}`;
  return `${top.jobs} of ${set} ${top.jobs === 1 ? "is a" : "are"} ${top.name} ${top.jobs === 1 ? "posting" : "postings"}`;
}
