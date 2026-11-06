type Props = {
  values: number[];
  /** Optional x position per value (e.g. week number) so skipped weeks leave a gap. */
  xs?: number[];
  width?: number;
  height?: number;
  /** Accessible summary; the sparkline is decorative if omitted. */
  label?: string;
  /** Emphasise the final point (current period) in the accent color. */
  highlightLast?: boolean;
};

/** Inline trend glyph: de-emphasised 1.5px line, current period in the accent. */
export function Sparkline({ values, xs, width = 84, height = 24, label, highlightLast = true }: Props) {
  if (values.length < 2) return null;
  const pad = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x0 = xs ? xs[0] : 0;
  const xSpan = xs ? xs[xs.length - 1] - xs[0] || 1 : values.length - 1;
  const pts = values.map((v, i) => [pad + (((xs ? xs[i] : i) - x0) / xSpan) * (width - pad * 2), height - pad - ((v - min) / span) * (height - pad * 2)] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} style={{ display: "block" }}>
      <path d={d} fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      {highlightLast ? <circle cx={last[0]} cy={last[1]} r={3} fill="var(--s1)" stroke="var(--surface)" strokeWidth={1.5} /> : null}
    </svg>
  );
}
