"use client";

import { useMemo, useState } from "react";
import { MatchCard } from "./match-card";
import { fmtInt, roleLabel } from "@/lib/format";
import type { ScoredJob } from "@/lib/match/types";

type Props = {
  matches: ScoredJob[];
  names: Record<string, string>;
  sourceNames: Record<string, string>;
  linkable: Set<string>;
  filteredOut: number;
};

type Sort = "match" | "pay" | "new";

export function ResultsList({ matches, names, sourceNames, linkable, filteredOut }: Props) {
  const [sort, setSort] = useState<Sort>("match");
  const [role, setRole] = useState("");
  const [needSalary, setNeedSalary] = useState(false);

  const roles = useMemo(() => {
    const m = new Map<string, number>();
    for (const x of matches) if (x.job.role) m.set(x.job.role, (m.get(x.job.role) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [matches]);

  // A role chosen earlier may not exist in a new set of matches; treat that as "all roles".
  const activeRole = role && roles.some(([r]) => r === role) ? role : "";

  // Rank numbers stay the match rank, whatever the current sort.
  const ranked = useMemo(() => matches.map((m, i) => ({ m, rank: i + 1 })), [matches]);
  const shown = useMemo(() => {
    const list = ranked.filter(({ m }) => (!activeRole || m.job.role === activeRole) && (!needSalary || m.job.salary));
    if (sort === "pay") list.sort((a, b) => (b.m.job.salary?.annual_usd_mid ?? -1) - (a.m.job.salary?.annual_usd_mid ?? -1) || a.rank - b.rank);
    else if (sort === "new") list.sort((a, b) => b.m.job.posted_at.localeCompare(a.m.job.posted_at) || a.rank - b.rank);
    return list;
  }, [ranked, activeRole, needSalary, sort]);

  const view = shown;

  return (
    <div>
      <form className="card grid grid-cols-2 gap-3 p-4 sm:grid-cols-[1fr_1fr_auto]" aria-label="Filter and sort your matches" onSubmit={(e) => e.preventDefault()}>
        <div>
          <label htmlFor="r-sort" className="mb-1 block text-xs font-medium text-ink-3">
            Sort by
          </label>
          <select id="r-sort" className="field w-full text-ellipsis" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="match">Best match</option>
            <option value="pay">Highest salary</option>
            <option value="new">Newest</option>
          </select>
        </div>
        <div>
          <label htmlFor="r-role" className="mb-1 block text-xs font-medium text-ink-3">
            Role
          </label>
          <select id="r-role" className="field w-full text-ellipsis" value={activeRole} onChange={(e) => setRole(e.target.value)}>
            <option value="">All roles</option>
            {roles.map(([r, n]) => (
              <option key={r} value={r}>
                {roleLabel(r)} ({n})
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-2 flex items-end sm:col-span-1">
          <label className="flex min-h-10 cursor-pointer items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" className="h-4 w-4 accent-[var(--s1)]" checked={needSalary} onChange={(e) => setNeedSalary(e.target.checked)} />
            Salary stated
          </label>
        </div>
      </form>

      <p className="mt-4 text-sm text-ink-2" aria-live="polite">
        Showing <strong className="font-semibold text-ink">{fmtInt(view.length)}</strong> of your {fmtInt(matches.length)} best matches
        {filteredOut > 0 ? <span className="text-ink-3"> ({fmtInt(filteredOut)} other jobs hidden by your preferences)</span> : null}
      </p>

      {view.length ? (
        <ol className="m-0 mt-3 flex list-none flex-col gap-3 p-0">
          {view.map(({ m, rank }) => (
            <MatchCard key={m.job.id} rank={rank} match={m} names={names} sourceNames={sourceNames} linkable={linkable} />
          ))}
        </ol>
      ) : (
        <div className="mt-4 rounded-lg border border-dashed border-line-strong p-8 text-center">
          <p className="font-medium">No matches with these filters</p>
          <p className="mt-1 text-sm text-ink-3">Clear the role filter or the salary requirement above, or relax your preferences.</p>
        </div>
      )}
    </div>
  );
}
