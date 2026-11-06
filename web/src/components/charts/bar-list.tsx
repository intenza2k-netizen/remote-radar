import Link from "next/link";

export type BarItem = {
  key: string;
  label: string;
  /** Raw magnitude; bars scale to the largest value in the list. */
  value: number;
  /** Text printed at the bar tip. */
  valueLabel: string;
  /** Secondary text after the value (e.g. count). */
  sub?: string;
  href?: string;
  title?: string;
};

/**
 * Ranked horizontal bars: one hue, thin (12px) bars, 4px rounded data-end and a
 * square baseline, value printed at the tip, label in ink (not series color).
 */
export function BarList({ items, ariaLabel }: { items: BarItem[]; ariaLabel: string }) {
  const max = Math.max(...items.map((i) => i.value), 1e-9);
  return (
    <ol aria-label={ariaLabel} className="m-0 list-none p-0">
      {items.map((it) => {
        const pct = Math.max(1.5, (it.value / max) * 100);
        const label = it.href ? (
          <Link href={it.href} className="truncate text-ink no-underline hover:underline">
            {it.label}
          </Link>
        ) : (
          <span className="truncate text-ink">{it.label}</span>
        );
        return (
          <li
            key={it.key}
            title={it.title}
            className="grid grid-cols-[minmax(5.5rem,9.5rem)_1fr] items-center gap-x-3 rounded-sm py-[5px] text-sm hover:bg-surface-2 sm:grid-cols-[10.5rem_1fr]"
          >
            <div className="flex min-w-0 items-center">{label}</div>
            <div className="border-l border-[var(--axis)] pr-[5.25rem]">
              <div className="relative h-3">
                <div className="h-3 min-w-[2px] rounded-r-[4px]" style={{ width: `${pct}%`, background: "var(--bar)" }} aria-hidden="true" />
                <span className="absolute top-1/2 ml-2 flex -translate-y-1/2 items-baseline gap-1.5 whitespace-nowrap" style={{ left: `${pct}%` }}>
                  <span className="tnum font-semibold text-ink">{it.valueLabel}</span>
                  {it.sub ? <span className="tnum text-xs text-ink-3">{it.sub}</span> : null}
                </span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
