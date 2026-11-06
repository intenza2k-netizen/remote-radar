import Link from "next/link";
import { skillLabel } from "@/lib/format";
import { COVERED_MIN_LISTED, MIN_LISTING, POOL, signedPct, skillPay, type NextSkill } from "@/lib/match/next-skill";
import type { SalaryModel } from "@/lib/salary-model";

type Props = {
  rows: NextSkill[];
  names: Record<string, string>;
  linkable: Set<string>;
  model: SalaryModel | null;
  topN: number;
  /** False when the profile has no skills, so there is nothing to add to. */
  hasSkills: boolean;
};

function PayLine({ model, slug }: { model: SalaryModel | null; slug: string }) {
  if (!model) return null;
  const p = skillPay(model, slug);
  if (!p) return <span className="text-ink-3">Pay: not modelled (too few postings state pay)</span>;
  const range = `${signedPct(p.low)} to ${signedPct(p.high)}`;
  return (
    <span className={p.distinguishable ? "text-ink-2" : "text-ink-3"}>
      Pay: <span className="tnum font-medium text-ink">{signedPct(p.pct)}</span> <span className="tnum">({range})</span>
      {p.distinguishable ? null : <span className="ml-1 italic">not distinguishable from zero</span>}
    </span>
  );
}

/**
 * The skills whose addition would change your results most, with the pay association of each next to it.
 * A list rather than a table so it fits the narrow sidebar next to the skill-gap panel.
 */
export function NextSkillPanel({ rows, names, linkable, model, topN, hasSkills }: Props) {
  return (
    <section className="card p-4 sm:p-5" aria-labelledby="next-h">
      <p className="eyebrow">Next skill to learn</p>
      <h2 id="next-h" className="mt-1 text-balance text-lg font-semibold leading-snug">
        {rows.length ? "Which missing skill would change your results most" : "No clear next skill"}
      </h2>
      {rows.length ? (
        <>
          <p className="mt-2 text-sm text-ink-2">
            Reading guide: these are associations in postings, not promises. &ldquo;Newly covered&rdquo; counts postings among your {POOL} best matches that you would reach with the skill;
            the pay figure is how postings listing it advertise, all else equal, with its 95% interval.
          </p>
          <ol className="m-0 mt-3 flex list-none flex-col p-0" aria-label="Missing skills ranked by the postings they would open up">
            {rows.map((r, i) => {
              const label = skillLabel(r.slug, names);
              return (
                <li key={r.slug} className="border-t border-line py-2.5 first:border-t-0 first:pt-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0 text-sm font-medium">
                      <span className="tnum mr-1.5 text-ink-3">{i + 1}.</span>
                      {linkable.has(r.slug) ? (
                        <Link href={`/skills/${r.slug}`} className="text-ink no-underline hover:underline">
                          {label}
                        </Link>
                      ) : (
                        label
                      )}
                    </span>
                    <span className="tnum shrink-0 text-sm font-semibold text-ink">+{r.covered} newly covered</span>
                  </div>
                  <p className="tnum mt-0.5 text-xs text-ink-2">
                    {r.entersTop} {r.entersTop === 1 ? "posting enters" : "postings enter"} your top {topN} · listed by {r.listedBy} of your {POOL} best
                  </p>
                  <p className="mt-0.5 text-xs">
                    <PayLine model={model} slug={r.slug} />
                  </p>
                </li>
              );
            })}
          </ol>
          <details className="mt-3 text-xs text-ink-3">
            <summary className="cursor-pointer text-ink-2">How this is counted</summary>
            <div className="mt-2 flex flex-col gap-1.5">
              <p>
                Candidates are the skills you lack that at least {MIN_LISTING} of your {POOL} best matches list. Each one is added to your profile and the skills part of every posting&apos;s score is
                recomputed; nothing else in the score changes.
              </p>
              <p>
                <strong className="font-semibold text-ink-2">Newly covered:</strong> a posting that lists at least {COVERED_MIN_LISTED} skills and goes from under two thirds to at least two thirds of
                them in your profile. <strong className="font-semibold text-ink-2">Enters your top {topN}:</strong> postings that are not in your top {topN} now and would be with the skill.
                Skills are ranked by newly covered, then by entries, then by how many of your best matches list them.
              </p>
              <p>
                Pay comes from the pay model (same role, seniority, region group and the other skills held fixed). An interval that crosses zero means the data cannot tell the skill from no effect.
                It is an association in advertised pay, not what learning the skill would add to your pay.
              </p>
            </div>
          </details>
        </>
      ) : (
        <p className="mt-2 text-sm text-ink-2">
          {hasSkills
            ? `Not enough of your best matches list a skill you lack (a skill needs to appear in at least ${MIN_LISTING} of ${POOL}), or no single skill moves the results. Widen your preferences to see more.`
            : "Your profile has no skills yet. Add the skills you have in the box above and this list appears."}
        </p>
      )}
    </section>
  );
}
