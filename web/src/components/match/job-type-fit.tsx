import Link from "next/link";
import { BarList, type BarItem } from "@/components/charts/bar-list";
import { fmtShare } from "@/lib/format";
import { jobTypeSentence, type JobTypeMix } from "@/lib/match/job-types";

type Props = {
  mix: JobTypeMix;
  /** How many data matches the mix is capped at (TOP_N). */
  limit: number;
};

const SHOWN = 6;

/** Which job type you fit: the job types (/job-types) of your best data matches. */
export function JobTypeFit({ mix, limit }: Props) {
  const sentence = jobTypeSentence(mix, limit);
  const items: BarItem[] = mix.rows.slice(0, SHOWN).map((r) => ({
    key: r.id,
    label: r.name,
    value: r.jobs,
    valueLabel: String(r.jobs),
    sub: fmtShare(r.share),
    href: `/job-types#type-${r.id}`,
    title: `${r.jobs} of your ${mix.total} data matches are ${r.name} postings`,
  }));
  const hidden = mix.rows.slice(SHOWN);
  return (
    <section className="card p-4 sm:p-5" aria-labelledby="fit-h">
      <p className="eyebrow">Which job type you fit</p>
      <h2 id="fit-h" className="mt-1 text-balance text-lg font-semibold leading-snug" aria-live="polite">
        {sentence ?? "None of your best matches is a data posting"}
      </h2>
      {items.length ? (
        <>
          <p className="mt-2 text-sm text-ink-2">
            The <Link href="/job-types" className="link">job type</Link> of each of your {mix.total < limit ? mix.total : `${mix.total} best`} data matches. Types group data postings by what they ask for; select one to read about it.
          </p>
          <div className="mt-3">
            <BarList items={items} ariaLabel="Your best data matches by job type" />
          </div>
          {hidden.length ? (
            <p className="mt-2 text-xs text-ink-3">
              + {hidden.length} other {hidden.length === 1 ? "type" : "types"}: {hidden.map((r) => `${r.name} (${r.jobs})`).join(", ")}.
            </p>
          ) : null}
          <p className="mt-3 text-xs text-ink-3">
            This counts the types of the postings you match best, not a label for you. Only data postings have a job type, so other roles in your list are skipped.
          </p>
        </>
      ) : (
        <p className="mt-2 text-sm text-ink-2">
          Job types cover data postings only. Add data skills or pick a data role in the preferences, or widen the location, to see which type you fit.
        </p>
      )}
    </section>
  );
}
