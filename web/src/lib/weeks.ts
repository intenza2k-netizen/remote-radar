import { fmtDateLong, fmtWeek, isoWeekStart } from "./format";
import type { Meta } from "./types";

/**
 * A week with fewer postings than this is too thin to show a share for
 * (one posting can swing a skill from 0% to 100%). Every trend visual uses
 * only "reliable" weeks, defined here once.
 */
export const MIN_WEEK_JOBS = 20;

/** Weeks from meta.weekly that have enough postings, in chronological order. */
export function reliableWeeks(meta: Pick<Meta, "weekly">): string[] {
  return meta.weekly.filter((w) => w.jobs >= MIN_WEEK_JOBS).map((w) => w.week).sort();
}

/** A line needs at least two reliable weeks. */
export const trendReady = (weeks: string[]) => weeks.length >= 2;

/** Keep only the points that fall in reliable weeks. */
export function reliableTrend<T extends { week: string }>(trend: T[], weeks: string[]): T[] {
  const ok = new Set(weeks);
  return trend.filter((t) => ok.has(t.week));
}

const WEEK_MS = 7 * 86400000;
/** Position of a week on a continuous time axis (in weeks), so skipped weeks show as gaps, not as neighbours. */
export const weekPos = (week: string) => isoWeekStart(week).getTime() / WEEK_MS;

/**
 * Whether the snapshot window is (nearly) full of data: at least all-but-one
 * of the weeks the window spans have reliable counts. Derived from the data.
 */
export function windowIsFull(meta: Pick<Meta, "weekly" | "window_days">): boolean {
  const span = Math.floor(meta.window_days / 7);
  return reliableWeeks(meta).length >= Math.max(2, span - 1);
}

/** "in the last 8 weeks" when the window is filled, otherwise "collected so far". */
export function windowClause(meta: Pick<Meta, "weekly" | "window_days">): string {
  return windowIsFull(meta) ? `in the last ${Math.round(meta.window_days / 7)} weeks` : "collected so far";
}

/** Short form for captions: "last 8 weeks" / "collected so far". */
export function windowCaption(meta: Pick<Meta, "weekly" | "window_days">): string {
  return windowIsFull(meta) ? `last ${Math.round(meta.window_days / 7)} weeks` : "collected so far";
}

/**
 * First week that holds a substantial share of the data (reliable and at least a
 * quarter of the busiest week). Earlier thin weeks only contain older postings
 * that were still listed when collection began.
 */
export function seriesStartWeek(meta: Pick<Meta, "weekly">): string | null {
  const max = Math.max(0, ...meta.weekly.map((w) => w.jobs));
  const first = meta.weekly.find((w) => w.jobs >= MIN_WEEK_JOBS && w.jobs >= max * 0.25);
  return first ? first.week : null;
}

/** "in the week of Nov 2" or, without any substantial week, "on Nov 6, 2026" (snapshot date). */
export function collectionStartPhrase(meta: Pick<Meta, "weekly" | "generated_at">): string {
  const w = seriesStartWeek(meta);
  return w ? `in the week of ${fmtWeek(w)}` : `on ${fmtDateLong(meta.generated_at)}`;
}
