"use client";

import { useId, useMemo, useState } from "react";
import { useElementWidth } from "./use-width";

export type LinePoint = { x: string; value: number; note?: string };
export type LineSeries = { id: string; label: string; color: string; points: LinePoint[] };

type Props = {
  series: LineSeries[];
  /** Ordered x categories (weeks). Every series supplies one point per x. */
  xs: string[];
  xLabel: (x: string) => string;
  /** Numeric x position per category (e.g. week number) so gaps between weeks stay visible; defaults to even spacing. */
  xPos?: (x: string) => number;
  valueLabel: (v: number) => string;
  /** Axis tick format; defaults to valueLabel. */
  tickLabel?: (v: number) => string;
  ariaLabel: string;
  /** Fill under the line (single series only). */
  area?: boolean;
  /** Skip the built-in legend (caller renders its own, e.g. removable chips). */
  hideLegend?: boolean;
  /** Name of the measure for the table view header. */
  measure?: string;
};

const MARGIN = { top: 12, right: 14, bottom: 28, left: 40 };

function niceMax(max: number) {
  const steps = [0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1];
  for (const step of steps) {
    const top = Math.ceil(max / step) * step;
    if (top / step <= 5) return { top, step };
  }
  return { top: 1, step: 0.25 };
}

/**
 * Hand-rolled SVG line chart following the dataviz spec: 2px lines, 8px end
 * markers with a 2px surface ring, hairline solid grid, crosshair + single
 * tooltip listing every series, legend for 2+ series, direct end labels only
 * when they do not collide, keyboard-operable, table view twin.
 */
export function LineChart({ series, xs, xLabel, xPos, valueLabel, tickLabel, ariaLabel, area = false, hideLegend = false, measure = "Value" }: Props) {
  const [ref, measured] = useElementWidth<HTMLDivElement>();
  const width = measured ?? 640;
  const height = width < 480 ? 230 : 290;
  const uid = useId();
  const [active, setActive] = useState<number | null>(null);

  const plot = {
    left: MARGIN.left,
    top: MARGIN.top,
    bottom: height - MARGIN.bottom,
  };

  const maxVal = Math.max(0.0001, ...series.flatMap((s) => s.points.map((p) => p.value)));
  const { top: yTop, step } = niceMax(maxVal);

  const labelRoom = series.length <= 4 && series.length > 0 && width >= 560;
  const endLabels = useMemo(() => {
    if (!labelRoom) return null;
    const ys = series.map((s) => plot.bottom - (s.points[s.points.length - 1].value / yTop) * (plot.bottom - plot.top));
    const sorted = [...ys].sort((a, b) => a - b);
    for (let i = 1; i < sorted.length; i += 1) if (sorted[i] - sorted[i - 1] < 15) return null;
    return ys;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [labelRoom, series, yTop, height]);

  const rightPad = endLabels ? 116 : MARGIN.right;
  const x0 = plot.left;
  const x1 = width - rightPad;
  const n = xs.length;
  const pos = xs.map((x, i) => (xPos ? xPos(x) : i));
  const span = pos[n - 1] - pos[0] || 1;
  const xAt = (i: number) => (n === 1 ? (x0 + x1) / 2 : x0 + ((pos[i] - pos[0]) / span) * (x1 - x0));
  const yAt = (v: number) => plot.bottom - (v / yTop) * (plot.bottom - plot.top);

  const ticks: number[] = [];
  for (let v = 0; v <= yTop + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);

  // show an x label only when it clears the previous one (labels sit on real, possibly uneven, positions)
  const labelAt = new Set<number>();
  let lastLabelX = -Infinity;
  for (let i = 0; i < n; i += 1) {
    if (xAt(i) - lastLabelX >= 52) {
      labelAt.add(i);
      lastLabelX = xAt(i);
    }
  }
  if (n > 1 && !labelAt.has(n - 1)) {
    // keep the final label; drop the previous one if it would collide
    const prev = [...labelAt].pop();
    if (prev !== undefined && xAt(n - 1) - xAt(prev) < 52) labelAt.delete(prev);
    labelAt.add(n - 1);
  }

  function indexFromPointer(clientX: number, rect: DOMRect) {
    const scale = width / rect.width;
    const px = (clientX - rect.left) * scale;
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < n; i += 1) {
      const d = Math.abs(xAt(i) - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return best;
  }

  const tipLeft = active == null ? 0 : (xAt(active) / width) * 100;
  const flip = active != null && xAt(active) > width * 0.6;

  return (
    <figure className="m-0">
      {!hideLegend && series.length >= 2 ? (
        <ul className="mb-3 flex flex-wrap gap-x-5 gap-y-1.5 text-sm text-ink-2" aria-label="Legend">
          {series.map((s) => (
            <li key={s.id} className="flex items-center gap-2">
              <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ background: s.color }} />
              {s.label}
            </li>
          ))}
        </ul>
      ) : null}

      <div
        ref={ref}
        className="relative touch-pan-y select-none outline-offset-4"
        tabIndex={0}
        role="group"
        aria-label={`${ariaLabel}. Use left and right arrow keys to inspect each week.`}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") {
            e.preventDefault();
            setActive((a) => Math.min(n - 1, (a ?? -1) + 1));
          } else if (e.key === "ArrowLeft") {
            e.preventDefault();
            setActive((a) => Math.max(0, (a ?? n) - 1));
          } else if (e.key === "Escape") setActive(null);
        }}
        onFocus={(e) => {
          if (e.target === e.currentTarget && active == null && e.currentTarget.matches(":focus-visible")) setActive(n - 1);
        }}
        onBlur={() => setActive(null)}
        onPointerMove={(e) => setActive(indexFromPointer(e.clientX, e.currentTarget.getBoundingClientRect()))}
        onPointerLeave={() => setActive(null)}
      >
        <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel} style={{ display: "block", overflow: "visible" }}>
          {/* gridlines + y ticks */}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x0} x2={x1} y1={yAt(t)} y2={yAt(t)} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1} />
              <text x={x0 - 8} y={yAt(t)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill="var(--ink-3)" className="tnum">
                {(tickLabel ?? valueLabel)(t)}
              </text>
            </g>
          ))}
          {/* x labels */}
          {xs.map((x, i) =>
            labelAt.has(i) ? (
              <text key={x} x={xAt(i)} y={plot.bottom + 18} textAnchor="middle" fontSize={11} fill="var(--ink-3)">
                {xLabel(x)}
              </text>
            ) : null,
          )}

          {/* crosshair */}
          {active != null ? <line x1={xAt(active)} x2={xAt(active)} y1={plot.top} y2={plot.bottom} stroke="var(--ink-3)" strokeWidth={1} /> : null}

          {series.map((s) => {
            const pts = s.points.map((p, i) => [xAt(i), yAt(p.value)] as const);
            const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
            const last = pts[pts.length - 1];
            return (
              <g key={s.id}>
                {area && series.length === 1 ? (
                  <path d={`${d} L${last[0].toFixed(1)},${plot.bottom} L${pts[0][0].toFixed(1)},${plot.bottom} Z`} fill={s.color} opacity={0.1} />
                ) : null}
                <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {/* end marker: 8px dot with 2px surface ring */}
                <circle cx={last[0]} cy={last[1]} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                {active != null ? <circle cx={pts[active][0]} cy={pts[active][1]} r={4.5} fill={s.color} stroke="var(--surface)" strokeWidth={2} /> : null}
              </g>
            );
          })}

          {/* direct end labels (text wears the ink token, never the series color) */}
          {endLabels
            ? series.map((s, i) => (
                <text key={s.id} x={x1 + 12} y={endLabels[i]} dominantBaseline="middle" fontSize={12} fontWeight={500} fill="var(--ink-2)">
                  {s.label.length > 14 ? `${s.label.slice(0, 13)}…` : s.label}
                </text>
              ))
            : null}
        </svg>

        {active != null ? (
          <div
            className="chart-tip"
            style={{ top: 4, left: `${tipLeft}%`, transform: flip ? "translateX(calc(-100% - 12px))" : "translateX(12px)" }}
            role="status"
          >
            <div className="mb-1 text-xs text-ink-3">Week of {xLabel(xs[active])}</div>
            {[...series]
              .sort((a, b) => b.points[active].value - a.points[active].value)
              .map((s) => (
                <div key={s.id} className="flex items-center gap-2 py-0.5">
                  <span aria-hidden className="inline-block h-0.5 w-3 shrink-0 rounded" style={{ background: s.color }} />
                  <span className="tnum font-semibold text-ink">{valueLabel(s.points[active].value)}</span>
                  <span className="truncate text-ink-3">{s.label}</span>
                  {s.points[active].note ? <span className="ml-auto whitespace-nowrap text-xs text-ink-3">{s.points[active].note}</span> : null}
                </div>
              ))}
          </div>
        ) : null}
      </div>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-3 hover:text-ink">View data as table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="data-table" aria-label={`${ariaLabel} (table view)`}>
            <caption className="sr-only">{measure} by week</caption>
            <thead>
              <tr>
                <th scope="col">Week of</th>
                {series.map((s) => (
                  <th key={s.id} scope="col" className="num">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {xs.map((x, i) => (
                <tr key={`${uid}-${x}`}>
                  <th scope="row" className="!text-sm !normal-case !tracking-normal !text-ink-2 font-medium">
                    {xLabel(x)}
                  </th>
                  {series.map((s) => (
                    <td key={s.id} className="num">
                      {valueLabel(s.points[i].value)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
