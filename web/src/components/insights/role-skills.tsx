import Link from "next/link";
import { fmtInt, fmtShare, roleLabel } from "@/lib/format";
import type { RoleSkills } from "@/lib/insights";

const SMALL_ROLE = 30;
const SHOWN = 8;

function Bars({ items, max }: { items: RoleSkills["top"]; max: number }) {
  return (
    <ol className="m-0 list-none p-0">
      {items.map((s) => {
        const pct = Math.max(1.5, (s.share / max) * 100);
        return (
          <li key={s.slug} className="grid grid-cols-[8.75rem_1fr] items-center gap-x-2.5 py-[3px] text-sm">
            <Link href={`/skills/${s.slug}`} title={s.name} className="truncate text-ink no-underline hover:underline">
              {s.name}
            </Link>
            <div className="border-l border-[var(--axis)] pr-10">
              <div className="relative h-2.5">
                <div className="h-2.5 min-w-[2px] rounded-r-[4px]" style={{ width: `${pct}%`, background: "var(--bar)" }} aria-hidden="true" />
                <span className="tnum absolute top-1/2 ml-1.5 -translate-y-1/2 whitespace-nowrap text-xs font-semibold text-ink" style={{ left: `${pct}%` }}>
                  {fmtShare(s.share)}
                </span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Small multiples: one card per role, top skills as share-of-role bars. All cards share one scale
 * (the largest share anywhere), so a bar's length means the same thing in every card.
 */
export function RoleSkillsGrid({ rows }: { rows: RoleSkills[] }) {
  const max = Math.max(0.01, ...rows.flatMap((r) => r.top.map((t) => t.share)));
  return (
    <div>
      <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((r) => (
          <li key={r.role} className="card p-4">
            <h3 className="text-base font-semibold leading-tight">{roleLabel(r.role)}</h3>
            <p className="tnum mt-0.5 text-xs text-ink-3">
              n = {fmtInt(r.n)} postings
              {r.n < SMALL_ROLE ? <span className="text-ink-2"> &middot; small sample, shares move a lot</span> : null}
            </p>
            <div className="mt-3" role="group" aria-label={`Top skills in ${roleLabel(r.role)} postings, share of the role's postings`}>
              <Bars items={r.top.slice(0, SHOWN)} max={max} />
              {r.top.length > SHOWN ? (
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-ink-3 hover:text-ink">Show {r.top.length - SHOWN} more</summary>
                  <div className="mt-1">
                    <Bars items={r.top.slice(SHOWN)} max={max} />
                  </div>
                </details>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-3">All cards share one scale: the longest bar is {fmtShare(max)} of that role&rsquo;s postings.</p>
    </div>
  );
}
