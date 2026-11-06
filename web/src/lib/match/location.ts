import { fmtInt } from "@/lib/format";
import { isOpenTo, type Memberships } from "@/lib/geo";
import { regionGroupOf, type RegionGroup } from "@/lib/salary-model";

/**
 * "I can work from": the location preference of the matcher. The open-to rule itself is `isOpenTo`
 * (`lib/geo.ts`, shared with the /locations and /jobs pages and pinned to the Python rule by fixtures);
 * this file only applies it to a list and maps the location to the pay model's region group.
 */

/** Region group used for the pay estimate when no location is chosen, or the location is in none of the model's groups. */
export const DEFAULT_REGION_GROUP: RegionGroup = "us_canada";

export type LocationFilterResult<T> = {
  kept: T[];
  /** Jobs removed because they are not open to the location. */
  excluded: number;
  /** Of the removed jobs, those that state no region at all (the rule never counts them as open). */
  unknown: number;
};

/** Keeps the postings open to `location`; an empty location keeps everything. Order is preserved. */
export function filterByLocation<T extends { remote_regions: readonly string[] }>(
  jobs: readonly T[],
  location: string,
  memberships: Memberships | null,
  sanctioned: readonly string[] = [],
): LocationFilterResult<T> {
  if (!location || !memberships) return { kept: [...jobs], excluded: 0, unknown: 0 };
  const kept: T[] = [];
  let unknown = 0;
  for (const j of jobs) {
    if (isOpenTo(j, location, memberships, sanctioned)) kept.push(j);
    else if (!j.remote_regions || j.remote_regions.length === 0) unknown++;
  }
  return { kept, excluded: jobs.length - kept.length, unknown };
}

/**
 * The pay model's region group for a location the user can work from ("Estonia" and "EU" are Europe,
 * "Canada" is US or Canada). Null for a location that is in none of the model's groups (South Africa,
 * "Middle East", "Americas" ...): the caller falls back to the default and says so.
 */
export function regionGroupForLocation(location: string): RegionGroup | null {
  if (!location) return null;
  const group = regionGroupOf([location]);
  return group === "other_or_mixed" || group === "unknown" ? null : group;
}

/** A stored or chosen location counts only if it is one of the published options. */
export function validLocation(value: unknown, options: readonly string[]): string {
  return typeof value === "string" && options.includes(value) ? value : "";
}

/** One sentence for the preferences form: what the location filter removed. */
export function locationStatus(location: string, total: number, result: Pick<LocationFilterResult<unknown>, "excluded" | "unknown">): string {
  if (!location) return "";
  const base = `${fmtInt(total - result.excluded)} of ${fmtInt(total)} postings are open to applicants in ${location}; ${fmtInt(result.excluded)} excluded`;
  if (result.unknown === 0) return `${base}.`;
  return `${base}, ${fmtInt(result.unknown)} of them because they do not say where they hire.`;
}
