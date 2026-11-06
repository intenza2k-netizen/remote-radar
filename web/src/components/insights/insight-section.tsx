import type { ReactNode } from "react";

/**
 * One analysis block: a small name above, the generated one-sentence takeaway as the heading,
 * then a "how to read this" note and the figure.
 */
export function InsightSection({
  id,
  name,
  headline,
  howTo,
  children,
}: {
  id: string;
  name: string;
  headline: ReactNode;
  howTo: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-h`} id={id} className="scroll-mt-20 border-t border-line pt-10 sm:pt-14 [&:first-of-type]:border-t-0">
      <p className="eyebrow mb-2">{name}</p>
      <h2 id={`${id}-h`} className="max-w-3xl text-balance text-xl font-semibold leading-snug tracking-tight sm:text-2xl">
        {headline}
      </h2>
      <p className="mt-3 max-w-3xl text-pretty text-sm leading-relaxed text-ink-2">
        <strong className="font-semibold text-ink">How to read this.</strong> {howTo}
      </p>
      <div className="mt-6">{children}</div>
    </section>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="card p-5 text-sm text-ink-2">{children}</p>;
}
