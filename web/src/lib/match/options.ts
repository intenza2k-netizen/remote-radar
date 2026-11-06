import { roleLabel, regionLabel } from "@/lib/format";
import type { Job } from "@/lib/types";

export const MIN_SALARY_OPTIONS = [40000, 60000, 80000, 100000, 125000, 150000, 200000];

/** Same normalisation the region filter uses, so "US" and "USA" are one option. */
export const REGION_ALIAS: Record<string, string> = { usa: "us", "united states": "us", "united kingdom": "uk", "czech republic": "czechia" };
export const normRegion = (r: string) => {
  const k = r.trim().toLowerCase();
  return REGION_ALIAS[k] ?? k;
};

export type MatchOptions = {
  roles: { value: string; label: string; count: number }[];
  regions: { value: string; label: string; count: number }[];
};

/** Role and region choices derived from the snapshot, most common first; synonyms merged. */
export function buildOptions(jobs: Job[]): MatchOptions {
  const roles = new Map<string, number>();
  const regions = new Map<string, { label: string; counts: Map<string, number>; total: number }>();
  for (const j of jobs) {
    if (j.role) roles.set(j.role, (roles.get(j.role) ?? 0) + 1);
    for (const r of j.remote_regions) {
      const key = normRegion(r);
      const e = regions.get(key) ?? { label: r, counts: new Map(), total: 0 };
      e.counts.set(r, (e.counts.get(r) ?? 0) + 1);
      e.total++;
      regions.set(key, e);
    }
  }
  return {
    roles: [...roles.entries()]
      .map(([value, count]) => ({ value, label: roleLabel(value), count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)),
    regions: [...regions.values()]
      .map((e) => {
        // Show the most common spelling of the merged group.
        const label = [...e.counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
        return { value: label, label: regionLabel(label), count: e.total };
      })
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)),
  };
}
