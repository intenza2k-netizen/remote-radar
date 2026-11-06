import { regionLabel } from "./format";

/**
 * Regions with fewer postings than this are left out of the region dropdowns: with a
 * long tail of one-off countries the list is unusable, and a filter that returns one or
 * two postings is not much of a filter. The postings stay visible without a region filter.
 */
export const MIN_REGION_JOBS = 3;

export type RegionOption = { value: string; label: string; count: number };

const isWorldwide = (r: string) => r.trim().toLowerCase() === "worldwide";

/**
 * Options for a region dropdown. The pipeline already publishes canonical region names
 * (`radar.regions`), so this only has to rank them: "Worldwide" first, then the rest by
 * number of postings (ties alphabetical), hiding regions with fewer than `min` postings.
 * `keep` is a currently selected value that must stay selectable even when it would be hidden
 * (for example from an old bookmarked link).
 */
export function regionOptions(
  jobs: { remote_regions: string[] }[],
  { min = MIN_REGION_JOBS, keep = "" }: { min?: number; keep?: string } = {},
): RegionOption[] {
  const counts = new Map<string, number>();
  for (const j of jobs) {
    for (const r of new Set(j.remote_regions)) counts.set(r, (counts.get(r) ?? 0) + 1);
  }
  const options = [...counts.entries()]
    .filter(([value, count]) => count >= min || isWorldwide(value) || value === keep)
    .map(([value, count]) => ({ value, label: regionLabel(value), count }));
  options.sort((a, b) => Number(isWorldwide(b.value)) - Number(isWorldwide(a.value)) || b.count - a.count || a.label.localeCompare(b.label));
  if (keep && !counts.has(keep)) options.push({ value: keep, label: regionLabel(keep), count: 0 });
  return options;
}
