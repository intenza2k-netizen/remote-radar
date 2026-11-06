"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { JobRow } from "./job-row";
import { LocationSelect } from "./geo/location-select";
import { SkillPicker, type PickerOption } from "./skill-picker";
import { fmtInt, roleLabel, seniorityLabel, seniorityRank, skillLabel } from "@/lib/format";
import { isOpenTo, type LocationOptions, type Memberships } from "@/lib/geo";
import { regionOptions } from "@/lib/regions";
import type { Job } from "@/lib/types";

type Props = {
  jobs: Job[];
  /** Region membership lists and locations for the "Open to applicants in" filter (geo.json); the filter is hidden without them. */
  openTo?: { memberships: Memberships; sanctioned?: readonly string[]; options: LocationOptions };
  skills: PickerOption[];
  /** Display names for every skill slug used by `jobs` (the picker list only has the published top skills). */
  skillNames?: Record<string, string>;
  sourceNames: Record<string, string>;
  companySlugs?: Record<string, string>;
};

const PAGE = 25;
const MIN_OPTIONS = [50000, 75000, 100000, 125000, 150000, 200000];

type Filters = {
  q: string;
  skills: string[];
  seniority: string;
  role: string;
  region: string;
  openTo: string;
  hasSalary: boolean;
  min: number;
  sort: "new" | "pay";
};

function parse(sp: URLSearchParams): Filters {
  const min = Number(sp.get("min"));
  return {
    q: sp.get("q") ?? "",
    skills: sp.getAll("skill"),
    seniority: sp.get("seniority") ?? "",
    role: sp.get("role") ?? "",
    region: sp.get("region") ?? "",
    openTo: sp.get("open_to") ?? "",
    hasSalary: sp.get("salary") === "1",
    min: Number.isFinite(min) && min > 0 ? min : 0,
    sort: sp.get("sort") === "pay" ? "pay" : "new",
  };
}

function serialize(f: Filters): string {
  const sp = new URLSearchParams();
  if (f.q) sp.set("q", f.q);
  for (const s of f.skills) sp.append("skill", s);
  if (f.seniority) sp.set("seniority", f.seniority);
  if (f.role) sp.set("role", f.role);
  if (f.region) sp.set("region", f.region);
  if (f.openTo) sp.set("open_to", f.openTo);
  if (f.hasSalary) sp.set("salary", "1");
  if (f.min) sp.set("min", String(f.min));
  if (f.sort !== "new") sp.set("sort", f.sort);
  return sp.toString();
}

export function JobsExplorer({ jobs, openTo, skills, skillNames: publishedNames, companySlugs, sourceNames }: Props) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const filters = useMemo(() => parse(new URLSearchParams(searchParams.toString())), [searchParams]);
  const [shown, setShown] = useState(PAGE);
  const [qText, setQText] = useState(filters.q);
  const qTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const skillNames = useMemo(() => ({ ...publishedNames, ...Object.fromEntries(skills.map((s) => [s.slug, s.name])) }), [publishedNames, skills]);

  const options = useMemo(() => {
    const seniority = new Set<string>();
    const roles = new Set<string>();
    for (const j of jobs) {
      if (j.seniority) seniority.add(j.seniority);
      if (j.role) roles.add(j.role);
    }
    return {
      seniority: [...seniority].sort((a, b) => seniorityRank(a) - seniorityRank(b)),
      roles: [...roles].sort((a, b) => roleLabel(a).localeCompare(roleLabel(b))),
    };
  }, [jobs]);
  // Worldwide first, then by number of postings; regions with under 3 postings are hidden.
  const regions = useMemo(() => regionOptions(jobs, { keep: filters.region }), [jobs, filters.region]);

  function commit(next: Filters) {
    const qs = serialize(next);
    // Next.js syncs native history updates into useSearchParams without a server round trip.
    window.history.replaceState(null, "", qs ? `${pathname}?${qs}` : pathname);
    setShown(PAGE);
  }
  function update(patch: Partial<Filters>) {
    commit({ ...filters, ...patch });
  }

  const results = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    const list = jobs.filter((j) => {
      if (q && !(j.title.toLowerCase().includes(q) || j.company.toLowerCase().includes(q))) return false;
      if (filters.skills.length && !filters.skills.every((s) => j.skills.includes(s))) return false;
      if (filters.seniority && j.seniority !== filters.seniority) return false;
      if (filters.role && j.role !== filters.role) return false;
      if (filters.region && !j.remote_regions.includes(filters.region)) return false;
      if (filters.openTo && openTo && !isOpenTo(j, filters.openTo, openTo.memberships, openTo.sanctioned)) return false;
      if ((filters.hasSalary || filters.min) && !j.salary) return false;
      if (filters.min && (j.salary?.annual_usd_mid ?? 0) < filters.min) return false;
      return true;
    });
    if (filters.sort === "pay") list.sort((a, b) => (b.salary?.annual_usd_mid ?? -1) - (a.salary?.annual_usd_mid ?? -1));
    else list.sort((a, b) => b.posted_at.localeCompare(a.posted_at));
    return list;
  }, [jobs, filters, openTo]);

  const active =
    filters.q || filters.skills.length || filters.seniority || filters.role || filters.region || (openTo && filters.openTo) || filters.hasSalary || filters.min ? true : false;

  function clearAll() {
    if (qTimer.current) clearTimeout(qTimer.current);
    setQText("");
    commit({ q: "", skills: [], seniority: "", role: "", region: "", openTo: "", hasSalary: false, min: 0, sort: filters.sort });
  }

  const visible = results.slice(0, shown);

  return (
    <div>
      {/* One filter row above the results; every filter scopes the list below */}
      <form className="card grid grid-cols-2 gap-3 p-4 lg:grid-cols-4" role="search" aria-label="Filter jobs" onSubmit={(e) => e.preventDefault()}>
        <div className="col-span-2 sm:col-span-1">
          <label htmlFor="f-q" className="mb-1 block text-xs font-medium text-ink-3">
            Title or company
          </label>
          <input
            id="f-q"
            type="search"
            className="field w-full"
            placeholder="e.g. analytics engineer"
            value={qText}
            onChange={(e) => {
              const value = e.target.value;
              setQText(value);
              if (qTimer.current) clearTimeout(qTimer.current);
              qTimer.current = setTimeout(() => commit({ ...filters, q: value }), 200);
            }}
          />
        </div>
        <div className="col-span-2 sm:col-span-1">
          <span className="mb-1 block text-xs font-medium text-ink-3">Skills (jobs must mention all)</span>
          <SkillPicker label="Filter by skill" options={skills} selected={filters.skills} onPick={(slug) => update({ skills: [...filters.skills, slug] })} placeholder="Add a skill..." />
        </div>
        <div>
          <label htmlFor="f-sen" className="mb-1 block text-xs font-medium text-ink-3">
            Seniority
          </label>
          <select id="f-sen" className="field w-full text-ellipsis" value={filters.seniority} onChange={(e) => update({ seniority: e.target.value })}>
            <option value="">Any seniority</option>
            {options.seniority.map((s) => (
              <option key={s} value={s}>
                {seniorityLabel(s)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="f-role" className="mb-1 block text-xs font-medium text-ink-3">
            Role
          </label>
          <select id="f-role" className="field w-full text-ellipsis" value={filters.role} onChange={(e) => update({ role: e.target.value })}>
            <option value="">Any role</option>
            {options.roles.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="f-region" className="mb-1 block text-xs font-medium text-ink-3">
            Region
          </label>
          <select id="f-region" className="field w-full text-ellipsis" value={filters.region} onChange={(e) => update({ region: e.target.value })}>
            <option value="">Anywhere</option>
            {regions.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label} ({fmtInt(r.count)})
              </option>
            ))}
          </select>
        </div>
        {openTo ? (
          <div>
            <label htmlFor="f-open" className="mb-1 block text-xs font-medium text-ink-3">
              Open to applicants in
            </label>
            <LocationSelect id="f-open" value={filters.openTo} onChange={(v) => update({ openTo: v })} options={openTo.options} emptyLabel="Anywhere" keep={filters.openTo} />
          </div>
        ) : null}
        <div>
          <label htmlFor="f-min" className="mb-1 block text-xs font-medium text-ink-3">
            Min. salary (USD / yr)
          </label>
          <select id="f-min" className="field w-full text-ellipsis" value={filters.min} onChange={(e) => update({ min: Number(e.target.value) })}>
            <option value={0}>No minimum</option>
            {MIN_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {fmtInt(m)}+
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="f-sort" className="mb-1 block text-xs font-medium text-ink-3">
            Sort by
          </label>
          <select id="f-sort" className="field w-full text-ellipsis" value={filters.sort} onChange={(e) => update({ sort: e.target.value === "pay" ? "pay" : "new" })}>
            <option value="new">Newest first</option>
            <option value="pay">Highest salary first</option>
          </select>
        </div>
        <div className="col-span-2 flex items-end sm:col-span-1">
          <label className="flex min-h-10 cursor-pointer items-center gap-2 text-sm text-ink-2">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[var(--s1)]"
              checked={filters.hasSalary || filters.min > 0}
              disabled={filters.min > 0}
              onChange={(e) => update({ hasSalary: e.target.checked })}
            />
            Only jobs that state a salary
          </label>
        </div>
      </form>

      {filters.skills.length ? (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Selected skills">
          {filters.skills.map((s) => (
            <li key={s}>
              <span className="inline-flex items-center gap-1 rounded-full border border-line-strong bg-surface py-1 pl-3 pr-1 text-sm">
                <Link href={`/skills/${s}`} className="text-ink no-underline hover:underline">
                  {skillLabel(s, skillNames)}
                </Link>
                <button
                  type="button"
                  className="grid h-6 w-6 place-items-center rounded-full text-ink-3 hover:bg-surface-2 hover:text-ink"
                  aria-label={`Remove ${skillLabel(s, skillNames)} filter`}
                  onClick={() => update({ skills: filters.skills.filter((x) => x !== s) })}
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                    <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-6 flex items-center justify-between gap-4 border-b border-line pb-3">
        <p className="text-sm text-ink-2" aria-live="polite">
          <strong className="font-semibold text-ink">{fmtInt(results.length)}</strong> of {fmtInt(jobs.length)} jobs
        </p>
        {active ? (
          <button type="button" className="text-sm text-accent underline underline-offset-4" onClick={clearAll}>
            Clear all filters
          </button>
        ) : null}
      </div>

      {results.length ? (
        <ul className="m-0 mt-4 list-none p-0">
          {visible.map((j) => (
            <JobRow key={j.id} job={j} skillNames={skillNames} sourceNames={sourceNames} companySlugs={companySlugs} />
          ))}
        </ul>
      ) : (
        <div className="mt-8 rounded-lg border border-dashed border-line-strong p-10 text-center">
          <p className="font-medium">No jobs match these filters</p>
          <p className="mt-1 text-sm text-ink-3">Try removing a skill or lowering the salary minimum.</p>
          <button type="button" className="btn mt-4" onClick={clearAll}>
            Clear all filters
          </button>
        </div>
      )}

      {results.length > shown ? (
        <div className="mt-6 flex justify-center">
          <button type="button" className="btn" onClick={() => setShown((s) => s + PAGE)}>
            Show {Math.min(PAGE, results.length - shown)} more
          </button>
        </div>
      ) : null}
    </div>
  );
}
