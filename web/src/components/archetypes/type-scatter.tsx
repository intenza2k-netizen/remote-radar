"use client";

import { useMemo, useState, type PointerEvent } from "react";
import { useElementWidth } from "@/components/charts/use-width";
import { fmtInt } from "@/lib/format";
import type { ArchetypePoint } from "@/lib/archetypes";
import { Marker, markerFor } from "./marker";

export type ScatterType = { id: string; name: string; n: number };

const PAD = 14;
const HIT_RADIUS = 14;

/**
 * Scatter of the clustered postings in two PCA dimensions, coloured by job type. The key is the
 * legend (numbered, with a marker shape per colour slot) and the numbered badges at each type's
 * median position, so identity never depends on colour alone. Hover, or tap on a touch screen, shows
 * the nearest posting; the legend buttons isolate one type. A table with the same information sits
 * under the chart on the page.
 */
export function TypeScatter({ types, points, labels, variance }: { types: ScatterType[]; points: ArchetypePoint[]; labels: Record<string, string>; variance?: number[] }) {
  const [wrapRef, width] = useElementWidth<HTMLDivElement>();
  const [focus, setFocus] = useState<string | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  const index = useMemo(() => new Map(types.map((t, i) => [t.id, i])), [types]);
  const byId = useMemo(() => new Map(types.map((t) => [t.id, t])), [types]);

  const extent = useMemo(() => {
    let x0 = Infinity,
      x1 = -Infinity,
      y0 = Infinity,
      y1 = -Infinity;
    for (const p of points) {
      x0 = Math.min(x0, p.x);
      x1 = Math.max(x1, p.x);
      y0 = Math.min(y0, p.y);
      y1 = Math.max(y1, p.y);
    }
    if (!points.length) return { x0: -1, x1: 1, y0: -1, y1: 1 };
    const px = (x1 - x0) * 0.03 || 0.1;
    const py = (y1 - y0) * 0.03 || 0.1;
    return { x0: x0 - px, x1: x1 + px, y0: y0 - py, y1: y1 + py };
  }, [points]);

  const w = width ?? 640;
  const plotW = Math.max(120, w - 2 * PAD);
  const spanX = extent.x1 - extent.x0;
  const spanY = extent.y1 - extent.y0;
  // Equal scale on both axes so distances are not stretched; the height follows the data.
  const scale = plotW / spanX;
  const plotH = Math.min(Math.max(spanY * scale, 220), 520);
  const unit = Math.min(scale, plotH / spanY);
  const offX = PAD + (plotW - spanX * unit) / 2;
  const offY = PAD + (plotH - spanY * unit) / 2;
  const { x0, y1 } = extent;
  const sx = (x: number) => offX + (x - x0) * unit;
  const sy = (y: number) => offY + (y1 - y) * unit; // y grows upwards
  const height = plotH + 2 * PAD;
  const r = w < 480 ? 2.6 : 3.2;

  const screen = useMemo(
    () => points.map((p) => ({ x: offX + (p.x - x0) * unit, y: offY + (y1 - p.y) * unit })),
    [points, offX, offY, unit, x0, y1],
  );

  const medians = useMemo(() => {
    const groups = new Map<string, { xs: number[]; ys: number[] }>();
    for (const p of points) {
      const g = groups.get(p.a) ?? { xs: [], ys: [] };
      g.xs.push(p.x);
      g.ys.push(p.y);
      groups.set(p.a, g);
    }
    const med = (v: number[]) => {
      const s = [...v].sort((a, b) => a - b);
      const m = s.length >> 1;
      return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
    };
    return types.map((t) => {
      const g = groups.get(t.id);
      return g ? { id: t.id, x: med(g.xs), y: med(g.ys) } : null;
    });
  }, [points, types]);

  const hoverPoint = hover != null ? points[hover] : null;
  const active = hoverPoint?.a ?? focus;

  function locate(e: PointerEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - box.left;
    const my = e.clientY - box.top;
    let best = -1;
    let bestD = HIT_RADIUS * HIT_RADIUS;
    for (let i = 0; i < screen.length; i++) {
      if (focus && points[i].a !== focus) continue;
      const dx = screen[i].x - mx;
      const dy = screen[i].y - my;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    setHover(best === -1 ? null : best);
  }

  const order = useMemo(() => {
    // Draw the active type last so it sits on top of the dimmed ones.
    const idx = points.map((_, i) => i);
    if (!active) return idx;
    return [...idx.filter((i) => points[i].a !== active), ...idx.filter((i) => points[i].a === active)];
  }, [points, active]);

  const focusType = focus ? byId.get(focus) : undefined;
  const pct = (v: number | undefined) => (v == null ? null : `${(v * 100).toFixed(0)}%`);

  return (
    <div>
      <div role="group" aria-label="Show one job type" className="flex flex-wrap gap-2">
        {types.map((t, i) => (
          <button key={t.id} type="button" className="chip" aria-pressed={focus === t.id} onClick={() => setFocus(focus === t.id ? null : t.id)}>
            <Marker index={i} />
            <span className="tnum font-semibold">{i + 1}</span>
            {t.name}
            <span className="tnum opacity-60">{fmtInt(t.n)}</span>
          </button>
        ))}
      </div>

      <div className="card relative mt-4 p-0" ref={wrapRef}>
        <svg
          width="100%"
          height={height}
          viewBox={`0 0 ${w} ${height}`}
          role="img"
          aria-label={`Scatter plot of ${fmtInt(points.length)} data postings in two dimensions, coloured and numbered by job type: ${types.map((t, i) => `${i + 1} ${t.name}`).join(", ")}. The same information is in the table below.`}
          style={{ touchAction: "pan-y", display: "block" }}
          onPointerMove={locate}
          onPointerDown={locate}
          onPointerLeave={() => setHover(null)}
        >
          <line x1={sx(0)} x2={sx(0)} y1={PAD} y2={height - PAD} stroke="var(--grid)" strokeWidth={1} />
          <line x1={PAD} x2={w - PAD} y1={sy(0)} y2={sy(0)} stroke="var(--grid)" strokeWidth={1} />
          {order.map((i) => {
            const p = points[i];
            const ti = index.get(p.a) ?? 0;
            const { color, shape } = markerFor(ti);
            const dim = active != null && p.a !== active;
            const { x, y } = screen[i];
            const common = { fill: color, fillOpacity: dim ? 0.1 : 0.72, stroke: "var(--surface)", strokeWidth: 0.6, strokeOpacity: dim ? 0.2 : 0.9 } as const;
            if (shape === "square") return <rect key={p.id} x={x - r} y={y - r} width={2 * r} height={2 * r} {...common} />;
            if (shape === "diamond") return <path key={p.id} d={`M${x} ${y - r * 1.3}L${x + r * 1.3} ${y}L${x} ${y + r * 1.3}L${x - r * 1.3} ${y}Z`} {...common} />;
            return <circle key={p.id} cx={x} cy={y} r={r} {...common} />;
          })}
          {medians.map((m, i) => {
            if (!m) return null;
            const dim = active != null && m.id !== active;
            return (
              <g key={m.id} opacity={dim ? 0.35 : 1} pointerEvents="none">
                <circle cx={sx(m.x)} cy={sy(m.y)} r={10} fill="var(--surface)" stroke={markerFor(i).color} strokeWidth={2} />
                <text x={sx(m.x)} y={sy(m.y)} textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={700} fill="var(--ink)">
                  {i + 1}
                </text>
              </g>
            );
          })}
          {hoverPoint ? <circle cx={screen[hover as number].x} cy={screen[hover as number].y} r={r + 3} fill="none" stroke="var(--ink)" strokeWidth={1.5} pointerEvents="none" /> : null}
        </svg>
        {hoverPoint ? (
          <div
            className="chart-tip"
            style={{
              left: Math.min(Math.max(screen[hover as number].x + 12, 4), Math.max(4, w - 200)),
              top: Math.min(screen[hover as number].y + 12, height - 70),
            }}
          >
            <p className="font-semibold">{labels[hoverPoint.id] ?? "Posting"}</p>
            <p className="mt-0.5 text-ink-2">
              <span className="tnum font-semibold">{(index.get(hoverPoint.a) ?? 0) + 1}</span> {byId.get(hoverPoint.a)?.name}
            </p>
          </div>
        ) : null}
      </div>

      <p className="mt-3 text-sm text-ink-3" aria-live="polite">
        {focusType ? (
          <>
            Showing only <strong className="font-semibold text-ink">{focusType.name}</strong> ({fmtInt(focusType.n)} postings).{" "}
            <a href={`#type-${focusType.id}`} className="link">
              Jump to its card
            </a>
            .
          </>
        ) : (
          <>Each dot is one open posting; the numbered badge sits at the middle of its type. Hover or tap a dot to see the posting.</>
        )}
      </p>
      <p className="mt-1 max-w-3xl text-xs text-ink-3">
        The two axes are the two largest directions of variation in the 384-dimensional embeddings
        {variance && variance.length >= 2 ? ` (together ${pct(variance[0] + variance[1])} of the variance: ${pct(variance[0])} horizontal, ${pct(variance[1])} vertical)` : ""}. Most of the structure is not visible in two dimensions, so dots that overlap here can still be far apart, and the
        types were found in all 384 dimensions, not in this picture.
      </p>
    </div>
  );
}
