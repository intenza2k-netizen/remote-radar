import Link from "next/link";
import { employmentLabel, fmtDateShort, fmtSalaryRange, fmtUsdShort, roleLabel, seniorityLabel, skillLabel } from "@/lib/format";
import type { Job } from "@/lib/types";

type Props = {
  job: Job;
  skillNames: Record<string, string>;
  sourceNames: Record<string, string>;
  maxSkills?: number;
  /** Company name to /companies/<slug>. Omit (e.g. on a company page) to show plain text. */
  companySlugs?: Record<string, string>;
};

/**
 * One posting. The title links to the ORIGINAL posting in a new tab with
 * rel="noopener" only: no nofollow (Remote OK requires followed links) and the
 * source board is always named.
 */
export function JobRow({ job, skillNames, sourceNames, maxSkills = 6, companySlugs }: Props) {
  const source = sourceNames[job.source] ?? job.source;
  const companySlug = companySlugs?.[job.company];
  const shown = job.skills.slice(0, maxSkills);
  const more = job.skills.length - shown.length;
  const pay = job.salary;
  const showUsd = pay && !(pay.currency === "USD" && pay.period === "year");
  return (
    <li className="border-b border-line py-4 first:pt-0 last:border-b-0">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0">
          <h3 className="text-base font-semibold leading-snug">
            <a href={job.url} target="_blank" rel="noopener" className="text-ink no-underline hover:underline">
              {job.title}
              <svg className="ml-1 inline-block align-[-1px] text-ink-3" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path d="M4.5 2.5h5v5M9.5 2.5 3 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="sr-only"> (opens the original posting on {source} in a new tab)</span>
            </a>
          </h3>
          <p className="mt-0.5 text-sm text-ink-2">
            {companySlug ? (
              <Link href={`/companies/${companySlug}`} className="text-ink-2 no-underline hover:text-ink hover:underline">
                {job.company}
              </Link>
            ) : (
              job.company
            )}
            {job.location ? <span className="text-ink-3"> &middot; {job.location}</span> : null}
          </p>
          <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-3">
            <span>{seniorityLabel(job.seniority)}</span>
            <span>{roleLabel(job.role)}</span>
            <span>{employmentLabel(job.employment_type)}</span>
          </p>
          {shown.length ? (
            <ul className="mt-2.5 flex flex-wrap gap-1.5" aria-label="Skills">
              {shown.map((slug) => (
                <li key={slug}>
                  <Link href={`/skills/${slug}`} className="inline-block rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink-2 no-underline hover:text-ink hover:underline">
                    {skillLabel(slug, skillNames)}
                  </Link>
                </li>
              ))}
              {more > 0 ? <li className="px-1 py-0.5 text-xs text-ink-3">+{more} more</li> : null}
            </ul>
          ) : null}
        </div>
        <div className="shrink-0 text-sm sm:text-right">
          {pay ? (
            <p className="tnum font-semibold text-ink">
              {fmtSalaryRange(pay)}
              {showUsd ? <span className="block text-xs font-normal text-ink-3">&asymp; {fmtUsdShort(pay.annual_usd_mid)} / yr</span> : null}
            </p>
          ) : (
            <p className="text-ink-3">Salary not stated</p>
          )}
          <p className="mt-1 text-xs text-ink-3">
            via <span className="font-medium text-ink-2">{source}</span> &middot; <time dateTime={job.posted_at}>{fmtDateShort(job.posted_at)}</time>
          </p>
        </div>
      </div>
    </li>
  );
}
