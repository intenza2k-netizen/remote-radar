import Link from "next/link";
import { BarList } from "@/components/charts/bar-list";
import { Kpi } from "@/components/ui";
import { fmtInt, fmtShare } from "@/lib/format";
import { jobsHref, payLabel, roleCounts, selectionSentence, type GeoLocation } from "@/lib/geo";

/** Everything the data says about one chosen location. */
export function LocationResult({ row, listed }: { row: GeoLocation; listed: number }) {
  const pay = payLabel(row);
  const skills = row.top_skills.map((s) => ({
    key: s.slug,
    label: s.name,
    value: s.share,
    valueLabel: fmtShare(s.share),
  }));
  const roles = roleCounts(row).map(([label, n]) => ({ key: label, label, value: n, valueLabel: fmtInt(n) }));
  return (
    <div aria-live="polite">
      <h2 className="text-balance text-xl font-semibold leading-snug tracking-tight sm:text-2xl">{selectionSentence(row, listed)}</h2>

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Open remote postings" value={fmtInt(row.open_jobs)} sub={`${fmtShare(row.open_share)} of ${fmtInt(listed)} listed`} />
        <Kpi label="Of them data roles" value={fmtInt(row.data_jobs)} sub={row.open_jobs ? `${fmtShare(row.data_jobs / row.open_jobs)} of the open postings` : "none open"} />
        <Kpi label="Say worldwide" value={fmtInt(row.worldwide_jobs)} sub={`${fmtInt(row.explicit_jobs)} name ${row.kind === "macro" ? "this region or a larger one" : "your place or a region with it"}`} />
        <Kpi label="Median advertised pay" value={pay.value} sub={pay.sub} />
      </div>

      {row.open_jobs ? (
        <p className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
          <Link className="link" href={jobsHref(row.location)}>
            Browse the {fmtInt(row.open_jobs)} open postings
          </Link>
          {row.data_jobs ? (
            <Link className="link" href={jobsHref(row.location, { role: "data" })}>
              Only the {fmtInt(row.data_jobs)} data roles
            </Link>
          ) : null}
        </p>
      ) : null}

      <div className="mt-8 grid gap-8 lg:grid-cols-2">
        <section aria-labelledby="geo-skills-h">
          <h3 id="geo-skills-h" className="text-base font-semibold">
            What the open data jobs ask for
          </h3>
          <p className="mb-3 mt-1 text-sm text-ink-3">Share of the {fmtInt(row.data_jobs)} open data postings that list the skill.</p>
          {skills.length ? (
            <BarList items={skills} ariaLabel={`Skills most requested by data postings open to ${row.location}`} />
          ) : (
            <p className="card p-4 text-sm text-ink-2">
              {row.data_jobs ? "No skill appears in three or more of these data postings, so a ranking would be noise." : "No open data postings here, so there is no skill list."}
            </p>
          )}
        </section>
        <section aria-labelledby="geo-roles-h">
          <h3 id="geo-roles-h" className="text-base font-semibold">
            Which kinds of roles are open
          </h3>
          <p className="mb-3 mt-1 text-sm text-ink-3">All {fmtInt(row.open_jobs)} open postings by role.</p>
          {roles.length ? <BarList items={roles} ariaLabel={`Roles open to ${row.location}`} /> : <p className="card p-4 text-sm text-ink-2">Nothing is open here.</p>}
        </section>
      </div>
    </div>
  );
}
