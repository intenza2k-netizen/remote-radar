import { BarList, type BarItem } from "@/components/charts/bar-list";
import { skillLabel } from "@/lib/format";
import type { GapSkill } from "@/lib/match/gap";

type Props = {
  headline: string | null;
  gaps: GapSkill[];
  total: number;
  names: Record<string, string>;
  linkable: Set<string>;
};

const SHOWN = 8;

export function GapPanel({ headline, gaps, total, names, linkable }: Props) {
  const items: BarItem[] = gaps.slice(0, SHOWN).map((g) => ({
    key: g.slug,
    label: skillLabel(g.slug, names),
    value: g.jobs,
    valueLabel: `${g.jobs} of ${total}`,
    sub: `${Math.round(g.share * 100)}%`,
    href: linkable.has(g.slug) ? `/skills/${g.slug}` : undefined,
    title: `${skillLabel(g.slug, names)} is listed by ${g.jobs} of your ${total} best matches`,
  }));
  return (
    <section className="card p-4 sm:p-5" aria-labelledby="gap-h">
      <p className="eyebrow">Skill gap</p>
      <h2 id="gap-h" className="mt-1 text-balance text-lg font-semibold leading-snug">
        {headline ?? "You already have every skill your best matches list"}
      </h2>
      {items.length ? (
        <>
          <p className="mt-2 text-sm text-ink-2">
            Skills your {total} best matches ask for and your profile lacks, by how many of those jobs list them.
          </p>
          <div className="mt-3">
            <BarList items={items} ariaLabel="Missing skills ranked by the number of your best matches that ask for them" />
          </div>
          {gaps.length > SHOWN ? <p className="mt-2 text-xs text-ink-3">+{gaps.length - SHOWN} more missing skills, each in fewer postings.</p> : null}
          <p className="mt-3 text-xs text-ink-3">
            Already have one of these? Add it in the skills box above and the ranking updates. Skill names link to the market view of that skill.
          </p>
        </>
      ) : (
        <p className="mt-2 text-sm text-ink-2">Nothing to learn here for these postings. Widen your preferences to see more.</p>
      )}
    </section>
  );
}
