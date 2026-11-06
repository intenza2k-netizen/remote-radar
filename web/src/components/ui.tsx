import type { ReactNode } from "react";

export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-6xl px-4 sm:px-6 ${className}`}>{children}</div>;
}

/** A titled block. The heading states the takeaway; the paragraph says what is plotted. */
export function Section({ id, title, lede, children, className = "" }: { id: string; title: ReactNode; lede?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-labelledby={`${id}-h`} className={`pt-14 sm:pt-20 ${className}`}>
      <h2 id={`${id}-h`} className="max-w-3xl text-balance text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
        {title}
      </h2>
      {lede ? <p className="mt-2 max-w-3xl text-pretty text-base text-ink-2">{lede}</p> : null}
      <div className="mt-6">{children}</div>
    </section>
  );
}

export function PageHeader({ eyebrow, title, lede }: { eyebrow?: string; title: ReactNode; lede?: ReactNode }) {
  return (
    <header className="pb-2 pt-10 sm:pt-14">
      {eyebrow ? <p className="eyebrow mb-3">{eyebrow}</p> : null}
      <h1 className="max-w-3xl text-balance text-3xl font-semibold leading-[1.1] tracking-tight sm:text-5xl">{title}</h1>
      {lede ? <p className="mt-4 max-w-2xl text-pretty text-lg text-ink-2">{lede}</p> : null}
    </header>
  );
}

export function Kpi({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card p-4 sm:p-5">
      <p className="text-sm text-ink-3">{label}</p>
      <p className="mt-1 text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{value}</p>
      {sub ? <p className="mt-1 text-sm text-ink-3">{sub}</p> : null}
    </div>
  );
}

export function Delta({ pp }: { pp: number | null }) {
  if (pp == null) return <span className="text-ink-3">n/a</span>;
  const v = Math.round(pp * 10) / 10;
  if (v === 0) return <span className="tnum text-ink-3">0.0 pp</span>;
  const up = v > 0;
  return (
    <span className={`tnum inline-flex items-center gap-1 whitespace-nowrap font-medium ${up ? "text-[var(--up)]" : "text-ink-2"}`}>
      <svg width="0.6em" height="0.6em" viewBox="0 0 10 10" aria-hidden="true" fill="currentColor" style={{ minWidth: 9, minHeight: 9 }}>
        {up ? <path d="M5 1 9.5 9h-9z" /> : <path d="M5 9 .5 1h9z" />}
      </svg>
      <span className="sr-only">{up ? "up" : "down"} </span>
      {up ? "+" : "−"}
      {Math.abs(v).toFixed(1)} pp
    </span>
  );
}
