import Link from "next/link";
import { JobRow } from "@/components/job-row";
import { SegmentedBar, type Segment } from "@/components/charts/segmented-bar";
import { fmtInt, fmtShare, fmtUsdShort, seniorityLabel } from "@/lib/format";
import { looseReasons, seniorityMix, typicalLevelText, type Archetype } from "@/lib/archetypes";
import type { Job } from "@/lib/types";
import { Marker } from "./marker";

/** One light-to-dark ramp of the accent colour for intern ... principal; "unspecified" is a neutral grey. */
const LEVEL_FILL: Record<string, string> = {
  intern: "color-mix(in srgb, var(--accent) 28%, var(--surface-2))",
  junior: "color-mix(in srgb, var(--accent) 42%, var(--surface-2))",
  mid: "color-mix(in srgb, var(--accent) 56%, var(--surface-2))",
  senior: "color-mix(in srgb, var(--accent) 72%, var(--surface-2))",
  lead: "color-mix(in srgb, var(--accent) 88%, var(--surface-2))",
  principal: "var(--accent)",
  unspecified: "var(--axis)",
};

type Props = {
  archetype: Archetype;
  /** 0-based position in the list; the number and marker match the scatter plot. */
  index: number;
  neighbours: string[];
  examples: Job[];
  skillNames: Record<string, string>;
  sourceNames: Record<string, string>;
  companySlugs: Record<string, string>;
};

export function ArchetypeCard({ archetype: a, index, neighbours, examples, skillNames, sourceNames, companySlugs }: Props) {
  const mix = seniorityMix(a);
  const segments: Segment[] = mix.map((m) => ({ key: m.level, label: seniorityLabel(m.level), value: m.n, color: LEVEL_FILL[m.level] ?? "var(--axis)" }));
  const level = typicalLevelText(a);
  const loose = looseReasons(a);
  const maxShare = Math.max(0.01, ...a.top_skills.map((s) => s.share));

  return (
    <article id={`type-${a.id}`} aria-labelledby={`type-${a.id}-h`} className="card scroll-mt-20 p-5 sm:p-6">
      <header className="flex items-start gap-3">
        <span className="mt-1 flex items-center gap-1.5 rounded-full border border-line-strong px-2 py-0.5 text-xs font-semibold text-ink-2">
          <Marker index={index} size={9} />
          <span className="tnum">{index + 1}</span>
        </span>
        <div className="min-w-0">
          <h3 id={`type-${a.id}-h`} className="text-xl font-semibold leading-snug tracking-tight">
            {a.name}
          </h3>
          <p className="mt-1 max-w-3xl text-sm text-ink-2">{a.summary}</p>
        </div>
      </header>

      <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
        <Fact label="Postings" value={fmtInt(a.n)} sub={`${fmtShare(a.share)} of data postings`} />
        <Fact
          label="Median advertised pay"
          value={a.median_salary_usd != null ? fmtUsdShort(a.median_salary_usd) : "Too few salaries"}
          sub={a.median_salary_usd != null ? `from ${fmtInt(a.salary_n)} postings that state pay` : `${fmtInt(a.salary_n)} state pay; a median needs 5`}
        />
        <Fact label="Typical level" value={level ? level.split(" (")[0] : "Mostly unstated"} sub={level ? level.slice(level.indexOf("(") + 1, -1) : `${fmtInt(a.seniority.unspecified ?? 0)} of ${fmtInt(a.n)} state none`} />
        <Fact
          label="Titles that match"
          value={a.family && a.family_share != null ? fmtShare(a.family_share) : "n/a"}
          sub={a.family ? `are titled like "${a.family.toLowerCase()}"` : "no common title family"}
        />
      </dl>

      {loose.length ? (
        <div className="mt-4 rounded-lg border border-line-strong bg-surface-2 px-3 py-2.5 text-sm text-ink-2" role="note">
          <p className="font-semibold text-ink">Read this one with care</p>
          <ul className="mt-1 list-disc pl-5">
            {loose.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-6 grid gap-8 md:grid-cols-2">
        <div>
          <h4 className="text-sm font-semibold">Signature skills</h4>
          <p className="mt-0.5 text-xs text-ink-3">Share of this type&rsquo;s postings that list the skill, and how many times more often than across all data postings.</p>
          {a.top_skills.length ? (
            <ul className="mt-3 space-y-2">
              {a.top_skills.map((s) => (
                <li key={s.slug} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 text-sm">
                  <div className="min-w-0">
                    <Link href={`/skills/${s.slug}`} className="block truncate text-ink no-underline hover:underline">
                      {skillNames[s.slug] ?? s.name}
                    </Link>
                    <span className="mt-1 block h-1.5 rounded-full bg-surface-2" aria-hidden="true">
                      <span className="block h-full rounded-full" style={{ width: `${Math.round((s.share / maxShare) * 100)}%`, background: "var(--bar)" }} />
                    </span>
                  </div>
                  <span className="tnum text-right text-xs text-ink-2">
                    {fmtShare(s.share)} <span className="text-ink-3">&middot;</span> {s.lift.toFixed(1)}&times;
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-ink-3">No skill is clearly more common here than in data postings overall.</p>
          )}
        </div>

        <div>
          <h4 className="text-sm font-semibold">Seniority</h4>
          <div className="mt-3">
            <SegmentedBar segments={segments} ariaLabel={`Seniority mix of ${a.name}`} />
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
              {mix.map((m) => (
                <li key={m.level} className="flex items-center gap-1.5">
                  <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: LEVEL_FILL[m.level] ?? "var(--axis)" }} />
                  {seniorityLabel(m.level)} <span className="tnum text-ink-3">{fmtShare(m.share)}</span>
                </li>
              ))}
            </ul>
          </div>

          <h4 className="mt-6 text-sm font-semibold">Common titles</h4>
          <p className="mt-0.5 text-xs text-ink-3">Level words, brackets and team names removed.</p>
          <ul className="mt-2 space-y-1 text-sm">
            {a.top_titles.map((t) => (
              <li key={t.title} className="flex justify-between gap-3">
                <span className="min-w-0 truncate text-ink">{t.title}</span>
                <span className="tnum shrink-0 text-ink-3">{fmtInt(t.n)}</span>
              </li>
            ))}
          </ul>
          {neighbours.length ? (
            <p className="mt-4 text-xs text-ink-3">
              Closest on the map: <span className="text-ink-2">{neighbours.join(" and ")}</span>.
            </p>
          ) : null}
        </div>
      </div>

      {examples.length ? (
        <div className="mt-6 border-t border-line pt-5">
          <h4 className="text-sm font-semibold">Typical postings</h4>
          <p className="mt-0.5 text-xs text-ink-3">The postings closest to the middle of this type, at most one per company. Links open the original posting.</p>
          <ul className="mt-4">
            {examples.map((j) => (
              <JobRow key={j.id} job={j} skillNames={skillNames} sourceNames={sourceNames} maxSkills={5} companySlugs={companySlugs} />
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

function Fact({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="mt-0.5">
        <span className="tnum block text-lg font-semibold leading-tight">{value}</span>
        {sub ? <span className="block text-xs text-ink-3">{sub}</span> : null}
      </dd>
    </div>
  );
}
