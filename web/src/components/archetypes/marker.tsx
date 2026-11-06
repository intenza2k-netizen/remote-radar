/** Series slots in use order. s6 (a second green) comes last so that with up to seven types no two greens share the plot. */
const SLOT_ORDER = [1, 2, 3, 4, 5, 8, 7, 6] as const;

/** Colour slot (s1..s8) and marker shape for the i-th type: shapes repeat after eight so types stay distinguishable. */
export function markerFor(i: number): { color: string; shape: "circle" | "square" | "diamond" } {
  const shapes = ["circle", "square", "diamond"] as const;
  return { color: `var(--s${SLOT_ORDER[i % 8]})`, shape: shapes[Math.floor(i / 8) % shapes.length] };
}

/** The marker as a small SVG, used in the legend and cards so the key matches the plot. */
export function Marker({ index, size = 10 }: { index: number; size?: number }) {
  const { color, shape } = markerFor(index);
  const h = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" className="shrink-0">
      {shape === "circle" ? <circle cx={h} cy={h} r={h} fill={color} /> : null}
      {shape === "square" ? <rect x={0.5} y={0.5} width={size - 1} height={size - 1} rx={1.5} fill={color} /> : null}
      {shape === "diamond" ? <path d={`M${h} 0 L${size} ${h} L${h} ${size} L0 ${h} Z`} fill={color} /> : null}
    </svg>
  );
}
