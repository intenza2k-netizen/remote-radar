import type { ReactNode } from "react";
import { MIN_WEEK_JOBS, collectionStartPhrase } from "@/lib/weeks";
import type { Meta } from "@/lib/types";

/**
 * Shown instead of a line chart while fewer than two weeks have enough postings.
 * Says what will appear, why it is not there yet, and lets the caller show
 * the numbers that do exist (e.g. the current share).
 */
export function TrendEmptyState({ meta, reliableCount, what, children }: { meta: Pick<Meta, "weekly" | "generated_at">; reliableCount: number; what: string; children?: ReactNode }) {
  return (
    <div className="card overflow-hidden">
      <div className="grid gap-6 p-5 sm:p-8 md:grid-cols-[minmax(0,15rem)_1fr] md:items-center">
        {/* ghost axes: decorative, hints at the chart that will live here */}
        <svg viewBox="0 0 240 120" className="w-full max-w-[15rem]" aria-hidden="true">
          {[20, 50, 80, 110].map((y) => (
            <line key={y} x1="8" x2="232" y1={y} y2={y} stroke={y === 110 ? "var(--axis)" : "var(--grid)"} strokeWidth="1" />
          ))}
          <path d="M8 92 C 50 84, 70 70, 110 66 S 180 42, 232 30" fill="none" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" opacity="0.35" />
          <circle cx="232" cy="30" r="4" fill="var(--muted)" opacity="0.35" stroke="var(--surface)" strokeWidth="2" />
        </svg>
        <div>
          <p className="text-lg font-semibold leading-snug tracking-tight">Trend lines will appear here</p>
          <p className="mt-2 max-w-xl text-pretty text-ink-2">
            This will show {what}. Trends need at least two weeks with {MIN_WEEK_JOBS}+ postings; nightly collection started {collectionStartPhrase(meta)}.
          </p>
          <p className="mt-2 text-sm text-ink-3">
            {reliableCount} of the weeks collected so far {reliableCount === 1 ? "qualifies" : "qualify"}. Shares from thinner weeks are left out because a single posting would swing them wildly.
          </p>
        </div>
      </div>
      {children ? <div className="border-t border-line bg-surface-2/40 p-5 sm:px-8">{children}</div> : null}
    </div>
  );
}
