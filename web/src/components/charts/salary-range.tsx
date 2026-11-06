import { fmtUsd, fmtUsdShort, seniorityLabel } from "@/lib/format";
import type { SalaryDist } from "@/lib/types";

/**
 * Range plot: whisker = P10..P90, box = P25..P75, tick = median. One hue,
 * shared linear axis. Each row is keyboard-focusable and reveals its exact
 * numbers on hover/focus; a table twin sits underneath.
 */
export function SalaryRange({ rows, labelFor = seniorityLabel, ariaLabel }: { rows: SalaryDist[]; labelFor?: (key: string) => string; ariaLabel: string }) {
  if (!rows.length) return <p className="text-sm text-ink-3">Not enough salary data yet (needs at least 5 postings per group).</p>;
  const maxVal = Math.max(...rows.map((r) => r.p90));
  const step = [25000, 50000, 100000].find((st) => Math.ceil((maxVal * 1.04) / st) <= 4) ?? 100000;
  const top = Math.ceil((maxVal * 1.04) / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top; v += step) ticks.push(v);
  const pos = (v: number) => `${(v / top) * 100}%`;

  return (
    <div>
      <div className="grid grid-cols-[5.5rem_1fr] gap-x-3 sm:grid-cols-[7rem_1fr]">
        <div />
        <div className="relative h-5 pr-12 text-xs text-ink-3" aria-hidden="true">
          <div className="relative h-full">
            {ticks.map((t, i) => (
              <span
                key={t}
                className="tnum absolute top-0"
                style={{ left: pos(t), transform: i === 0 ? "none" : i === ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}
              >
                {fmtUsdShort(t)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <ul aria-label={ariaLabel} className="m-0 list-none p-0">
        {rows.map((r) => (
          <li key={r.key} className="group relative grid grid-cols-[5.5rem_1fr] items-center gap-x-3 py-1 sm:grid-cols-[7rem_1fr]">
            <div className="text-sm leading-tight text-ink">
              {labelFor(r.key)}
              <span className="tnum block text-xs text-ink-3">n = {r.n}</span>
            </div>
            <div
              tabIndex={0}
              className="relative h-9 pr-12 outline-offset-0"
              aria-label={`${labelFor(r.key)}: median ${fmtUsd(r.median)}, middle half ${fmtUsd(r.p25)} to ${fmtUsd(r.p75)}, 10th to 90th percentile ${fmtUsd(r.p10)} to ${fmtUsd(r.p90)}, ${r.n} postings`}
            >
              <div className="relative h-full">
                {ticks.map((t) => (
                  <span key={t} className="absolute inset-y-0 w-px" style={{ left: pos(t), background: t === 0 ? "var(--axis)" : "var(--grid)" }} aria-hidden="true" />
                ))}
                <span className="absolute top-1/2 h-px -translate-y-1/2" style={{ left: pos(r.p10), width: `calc(${pos(r.p90)} - ${pos(r.p10)})`, background: "var(--ink-3)" }} aria-hidden="true" />
                <span
                  className="absolute top-1/2 h-4 -translate-y-1/2 rounded-[3px]"
                  style={{ left: pos(r.p25), width: `calc(${pos(r.p75)} - ${pos(r.p25)})`, background: "var(--range)" }}
                  aria-hidden="true"
                />
                <span className="absolute top-1/2 h-6 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-sm" style={{ left: pos(r.median), background: "var(--ink)" }} aria-hidden="true" />
                <span className="tnum absolute top-1/2 -translate-y-1/2 whitespace-nowrap pl-2 text-xs font-semibold text-ink" style={{ left: pos(r.p90) }}>
                  {fmtUsdShort(r.median)}
                </span>
              </div>
            </div>
            <div className="chart-tip !pointer-events-none absolute -top-9 right-0 hidden group-focus-within:block group-hover:block" role="presentation">
              <span className="tnum">
                P10 {fmtUsdShort(r.p10)} &middot; P25 {fmtUsdShort(r.p25)} &middot; <strong>median {fmtUsdShort(r.median)}</strong> &middot; P75 {fmtUsdShort(r.p75)} &middot; P90 {fmtUsdShort(r.p90)}
              </span>
            </div>
          </li>
        ))}
      </ul>

      <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-3">
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-px w-5" style={{ background: "var(--ink-3)" }} /> 10th&ndash;90th percentile
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-3 w-5 rounded-[3px]" style={{ background: "var(--range)" }} /> middle 50%
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-4 w-[3px] rounded-sm" style={{ background: "var(--ink)" }} /> median (USD / year)
        </span>
      </p>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-3 hover:text-ink">View data as table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="data-table">
            <caption className="sr-only">{ariaLabel}</caption>
            <thead>
              <tr>
                <th scope="col">Group</th>
                <th scope="col" className="num">n</th>
                <th scope="col" className="num">P10</th>
                <th scope="col" className="num">P25</th>
                <th scope="col" className="num">Median</th>
                <th scope="col" className="num">P75</th>
                <th scope="col" className="num">P90</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <th scope="row" className="!text-sm !normal-case !tracking-normal !text-ink font-medium">{labelFor(r.key)}</th>
                  <td className="num">{r.n}</td>
                  <td className="num">{fmtUsd(r.p10)}</td>
                  <td className="num">{fmtUsd(r.p25)}</td>
                  <td className="num font-semibold">{fmtUsd(r.median)}</td>
                  <td className="num">{fmtUsd(r.p75)}</td>
                  <td className="num">{fmtUsd(r.p90)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
