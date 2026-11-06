import Link from "next/link";
import { employmentLabel, fmtDateShort, fmtSalaryRange, fmtUsdShort, roleLabel, seniorityLabel, skillLabel } from "@/lib/format";
import type { ScoredJob } from "@/lib/match/types";

type Props = {
  rank: number;
  match: ScoredJob;
  names: Record<string, string>;
  sourceNames: Record<string, string>;
  /** Slugs that have a /skills/<slug> page. */
  linkable: Set<string>;
};

/** Thin single-hue bar: 8px, 4px rounded data end, square baseline. */
export function MatchBar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100);
  return (
    <div role="img" aria-label={`${label}: ${pct}%`} className="h-2 w-full overflow-hidden rounded-[2px] bg-[var(--grid)]">
      <div className="h-2 min-w-[2px] rounded-r-[4px]" style={{ width: `${Math.max(1, pct)}%`, background: "var(--bar)" }} />
    </div>
  );
}

function SkillTag({ slug, names, linkable, variant }: { slug: string; names: Record<string, string>; linkable: Set<string>; variant: "have" | "missing" }) {
  const label = skillLabel(slug, names);
  const cls =
    variant === "have"
      ? "bg-accent-wash text-ink"
      : "border border-dashed border-line-strong text-ink-2";
  const inner = (
    <>
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" className="shrink-0">
        {variant === "have" ? (
          <path d="M1.5 5.4 4 7.9 8.6 2.3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        ) : (
          <path d="M5 1.5v7M1.5 5h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        )}
      </svg>
      <span>{label}</span>
      <span className="sr-only">{variant === "have" ? " (you have this)" : " (you are missing this)"}</span>
    </>
  );
  const base = `inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs no-underline ${cls}`;
  return linkable.has(slug) ? (
    <Link href={`/skills/${slug}`} className={`${base} hover:underline`}>
      {inner}
    </Link>
  ) : (
    <span className={base}>{inner}</span>
  );
}

const SIGNAL_LABEL = { semantic: "Similarity to your CV", skills: "Skill coverage", seniority: "Seniority fit", role: "Role preference" } as const;

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

export function MatchCard({ rank, match, names, sourceNames, linkable }: Props) {
  const { job, score, breakdown: b } = match;
  const source = sourceNames[job.source] ?? job.source;
  const pay = job.salary;
  const showUsd = pay && !(pay.currency === "USD" && pay.period === "year");
  const detail: Record<string, string> = {
    semantic: b.cosine != null ? `Cosine similarity ${b.cosine.toFixed(2)}, stretched to a 0 to 100% scale` : "",
    skills: `You have ${b.matchedSkills.length} of the ${job.skills.length} skills listed. Short lists are pulled slightly toward a neutral 30%.`,
    seniority: b.seniorityNote,
    role: b.role === 1 ? "A role you picked" : "Not one of the roles you picked",
  };
  const unused = [
    b.semantic == null ? "Similarity is not used for this posting (no language-model score available)." : null,
    b.skills == null ? (job.skills.length === 0 ? "Skill coverage is not used (the posting lists no skills)." : "Skill coverage is not used (no skills in your profile).") : null,
    b.seniority == null ? "Seniority fit is not used (your level is unknown)." : null,
  ].filter(Boolean);

  return (
    <li className="card p-4 sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0 flex-1">
          <p className="tnum text-xs text-ink-3">#{rank}</p>
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
            {job.company}
            {job.location ? <span className="text-ink-3"> &middot; {job.location}</span> : null}
          </p>
          <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-3">
            <span>{seniorityLabel(job.seniority)}</span>
            <span>{roleLabel(job.role)}</span>
            <span>{employmentLabel(job.employment_type)}</span>
            <span>
              via <span className="font-medium text-ink-2">{source}</span> &middot; <time dateTime={job.posted_at}>{fmtDateShort(job.posted_at)}</time>
            </span>
          </p>
        </div>
        <div className="shrink-0 sm:w-44 sm:text-right">
          <p className="tnum text-2xl font-semibold leading-none tracking-tight">
            {pct(score)} <span className="text-sm font-normal text-ink-3">match</span>
          </p>
          <div className="mt-2">
            <MatchBar value={score} label={`Match score for ${job.title}`} />
          </div>
          <p className="tnum mt-2 text-sm">
            {pay ? (
              <>
                <span className="font-semibold text-ink">{fmtSalaryRange(pay)}</span>
                {showUsd ? <span className="block text-xs text-ink-3">&asymp; {fmtUsdShort(pay.annual_usd_mid)} / yr</span> : null}
              </>
            ) : (
              <span className="text-ink-3">Salary not stated</span>
            )}
          </p>
        </div>
      </div>

      {b.matchedSkills.length || b.missingSkills.length ? (
        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 sm:gap-4">
          <div>
            <p className="mb-1 font-medium text-ink-3">You have ({b.matchedSkills.length})</p>
            {b.matchedSkills.length ? (
              <ul className="flex flex-wrap gap-1.5" aria-label="Matched skills">
                {b.matchedSkills.slice(0, 8).map((s) => (
                  <li key={s}>
                    <SkillTag slug={s} names={names} linkable={linkable} variant="have" />
                  </li>
                ))}
                {b.matchedSkills.length > 8 ? <li className="px-1 py-0.5 text-ink-3">+{b.matchedSkills.length - 8} more</li> : null}
              </ul>
            ) : (
              <p className="text-ink-3">None of the listed skills</p>
            )}
          </div>
          <div>
            <p className="mb-1 font-medium text-ink-3">Missing ({b.missingSkills.length})</p>
            {b.missingSkills.length ? (
              <ul className="flex flex-wrap gap-1.5" aria-label="Missing skills">
                {b.missingSkills.slice(0, 8).map((s) => (
                  <li key={s}>
                    <SkillTag slug={s} names={names} linkable={linkable} variant="missing" />
                  </li>
                ))}
                {b.missingSkills.length > 8 ? <li className="px-1 py-0.5 text-ink-3">+{b.missingSkills.length - 8} more</li> : null}
              </ul>
            ) : (
              <p className="text-ink-3">Nothing missing</p>
            )}
          </div>
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-3">This posting lists no specific skills.</p>
      )}

      <details className="group mt-3 border-t border-line pt-2">
        <summary className="cursor-pointer select-none rounded-md py-1 text-sm font-medium text-ink-2 hover:text-ink">Why this match</summary>
        <div className="mt-2 text-sm">
          <ul className="m-0 list-none p-0">
            {b.contributions.map((c) => (
              <li key={c.key} className="grid grid-cols-[1fr_auto] items-start gap-x-4 gap-y-1 border-b border-line py-2 last:border-b-0">
                <div className="min-w-0">
                  <p className="font-medium text-ink">{SIGNAL_LABEL[c.key]}</p>
                  <p className="text-xs text-ink-3">{detail[c.key]}</p>
                  <div className="mt-1.5 max-w-xs">
                    <MatchBar value={c.value} label={SIGNAL_LABEL[c.key]} />
                  </div>
                </div>
                <p className="tnum whitespace-nowrap text-right text-xs text-ink-2">
                  <span className="font-semibold text-ink">{pct(c.value)}</span> &times; {pct(c.weight)} weight
                  <span className="block text-ink-3">= {(c.points * 100).toFixed(1)} points</span>
                </p>
              </li>
            ))}
          </ul>
          <p className="tnum mt-2 flex items-baseline justify-between gap-4 text-sm">
            <span className="font-medium text-ink">Total</span>
            <span className="font-semibold text-ink">{pct(score)}</span>
          </p>
          {unused.length ? <p className="mt-2 text-xs text-ink-3">{unused.join(" ")}</p> : null}
          <p className="mt-2 text-xs text-ink-3">
            Weights come from <code>src/lib/match/constants.ts</code>; unused signals are dropped and the rest are rescaled to 100%.
          </p>
        </div>
      </details>
    </li>
  );
}
