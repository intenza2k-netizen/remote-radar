import { roleLabel } from "@/lib/format";
import { regionOptions } from "@/lib/regions";
import type { Job } from "@/lib/types";

export const MIN_SALARY_OPTIONS = [40000, 60000, 80000, 100000, 125000, 150000, 200000];

/**
 * Same normalisation the region filter uses, so "US" and "USA" are one option. The pipeline already publishes
 * canonical names ("United States"); this stays for older snapshots and for CV-side input.
 */
export const REGION_ALIAS: Record<string, string> = { usa: "us", "united states": "us", "united kingdom": "uk", "czech republic": "czechia" };
export const normRegion = (r: string) => {
  const k = r.trim().toLowerCase();
  return REGION_ALIAS[k] ?? k;
};

export type MatchOptions = {
  roles: { value: string; label: string; count: number }[];
  regions: { value: string; label: string; count: number }[];
};

/** Role and region choices derived from the snapshot, most common first (regions: Worldwide first, rare ones hidden). */
export function buildOptions(jobs: Job[]): MatchOptions {
  const roles = new Map<string, number>();
  for (const j of jobs) {
    if (j.role) roles.set(j.role, (roles.get(j.role) ?? 0) + 1);
  }
  return {
    roles: [...roles.entries()]
      .map(([value, count]) => ({ value, label: roleLabel(value), count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)),
    regions: regionOptions(jobs),
  };
}
