"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { fmtInt, fmtUsdShort, roleLabel } from "@/lib/format";
import type { CompanyRow } from "@/lib/insights";

type SortKey = "name" | "jobs" | "median_salary_usd";
type Sort = { key: SortKey; dir: "asc" | "desc" };

const PAGE = 40;

function Th({ k, sort, onSort, children, className = "", num = false }: { k: SortKey; sort: Sort; onSort: (k: SortKey) => void; children: React.ReactNode; className?: string; num?: boolean }) {
  const active = sort.key === k;
  return (
    <th scope="col" className={`${num ? "num" : ""} ${className}`} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => onSort(k)} className={`inline-flex items-center gap-1 uppercase tracking-[0.04em] hover:text-ink ${active ? "text-ink" : ""} ${num ? "flex-row-reverse" : ""}`}>
        {children}
        <span aria-hidden className="text-[10px]">
          {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

/** Searchable, sortable company list. Search matches company names and top skills. */
export function CompaniesTable({ rows, sourceNames }: { rows: CompanyRow[]; sourceNames: Record<string, string> }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>({ key: "jobs", dir: "desc" });
  const [shown, setShown] = useState(PAGE);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = rows.filter((r) => !q || r.name.toLowerCase().includes(q) || r.top_skills.some((s) => s.name.toLowerCase().includes(q) || s.slug.includes(q)));
    const dir = sort.dir === "asc" ? 1 : -1;
    return list.sort((a, b) => {
      if (sort.key === "name") return a.name.localeCompare(b.name) * dir;
      const av = a[sort.key];
      const bv = b[sort.key];
      if (av == null && bv == null) return a.name.localeCompare(b.name);
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * dir || b.jobs - a.jobs || a.name.localeCompare(b.name);
    });
  }, [rows, query, sort]);

  function setSortKey(key: SortKey) {
    setSort((cur) => (cur.key === key ? { key, dir: cur.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "name" ? "asc" : "desc" }));
    setShown(PAGE);
  }

  const visible = filtered.slice(0, shown);

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="sm:w-80">
          <label htmlFor="company-search" className="sr-only">
            Search companies or skills
          </label>
          <input
            id="company-search"
            type="search"
            className="field w-full"
            placeholder="Search companies or skills"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setShown(PAGE);
            }}
          />
        </div>
        <p className="text-sm text-ink-3" aria-live="polite">
          {fmtInt(filtered.length)} of {fmtInt(rows.length)} companies
        </p>
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="data-table">
          <caption className="sr-only">Companies with remote postings: number of jobs, roles, top skills, median advertised salary and sources</caption>
          <thead>
            <tr>
              <Th sort={sort} onSort={setSortKey} k="name">Company</Th>
              <Th sort={sort} onSort={setSortKey} k="jobs" num>Jobs</Th>
              <th scope="col" className="hidden md:table-cell">Roles</th>
              <th scope="col" className="hidden lg:table-cell">Top skills</th>
              <Th sort={sort} onSort={setSortKey} k="median_salary_usd" num>Median salary</Th>
              <th scope="col" className="hidden md:table-cell">Sources</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => {
              const roles = r.roles.slice(0, 2).map((x) => `${roleLabel(x.role)} ${x.n}`);
              const more = r.roles.length - 2;
              return (
                <tr key={r.slug}>
                  <td>
                    <Link href={`/companies/${r.slug}`} className="font-medium text-ink no-underline hover:underline">
                      {r.name}
                    </Link>
                    <span className="block text-xs text-ink-3 md:hidden">{roles.join(", ")}{more > 0 ? ` +${more}` : ""}</span>
                  </td>
                  <td className="num">{fmtInt(r.jobs)}</td>
                  <td className="hidden text-ink-2 md:table-cell">
                    {roles.join(", ")}
                    {more > 0 ? <span className="text-ink-3"> +{more} more</span> : null}
                  </td>
                  <td className="hidden lg:table-cell">
                    <span className="flex flex-wrap gap-1.5">
                      {r.top_skills.slice(0, 3).map((s) => (
                        <Link key={s.slug} href={`/skills/${s.slug}`} className="inline-block rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink-2 no-underline hover:text-ink hover:underline">
                          {s.name}
                        </Link>
                      ))}
                    </span>
                  </td>
                  <td className="num">
                    {r.median_salary_usd != null ? (
                      <span title={`Median of ${r.n_salary} posting${r.n_salary === 1 ? "" : "s"} that state pay`}>
                        {fmtUsdShort(r.median_salary_usd)}
                        <span className="block text-xs text-ink-3">n = {r.n_salary}</span>
                      </span>
                    ) : (
                      <span className="text-ink-3">n/a</span>
                    )}
                  </td>
                  <td className="hidden text-ink-2 md:table-cell">{r.sources.map((s) => sourceNames[s] ?? s).join(", ")}</td>
                </tr>
              );
            })}
            {visible.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-10 text-center text-ink-3">
                  No companies match &ldquo;{query}&rdquo;.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {filtered.length > shown ? (
        <div className="mt-5 flex justify-center">
          <button type="button" className="btn" onClick={() => setShown((s) => s + PAGE)}>
            Show {Math.min(PAGE, filtered.length - shown)} more
          </button>
        </div>
      ) : null}
    </div>
  );
}
