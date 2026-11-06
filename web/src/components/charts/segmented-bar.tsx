export type Segment = { key: string; label: string; value: number; color: string };

/**
 * Thin segmented bar (one whole split into parts, no text on the bar): 8px tall,
 * fully rounded ends, 2px surface gaps. The figures live in the list beside it.
 */
export function SegmentedBar({ segments, ariaLabel }: { segments: Segment[]; ariaLabel: string }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const summary = segments.map((s) => `${s.label} ${Math.round((s.value / total) * 100)}%`).join(", ");
  return (
    <div role="img" aria-label={`${ariaLabel}: ${summary}`} className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full">
      {segments
        .filter((s) => s.value > 0)
        .map((s) => (
          <span key={s.key} title={`${s.label}: ${Math.round((s.value / total) * 100)}%`} style={{ flex: `${s.value} 1 0`, background: s.color }} />
        ))}
    </div>
  );
}
