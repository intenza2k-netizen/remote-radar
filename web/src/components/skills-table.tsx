"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Sparkline } from "./charts/sparkline";
import { Delta } from "./ui";
import { MIN_WEEK_JOBS } from "@/lib/weeks";
import { categoryLabel, fmtInt, fmtShare, fmtUsdShort } from "@/lib/format";

export type SkillRow = {
  slug: string;
  name: string;
  category: string;
  count: number;
  share: number;
  change_4w: number | null;
  median_salary_usd: number | null;
  trend: number[];
};

type SortKey = "name" | "category" | "count" | "change_4w" | "median_salary_usd";

const PAGE = 40;

type Sort = { key: SortKey; dir: "asc" | "desc" };

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


export function SkillsTable({ rows, weekPositions, showChange }: { rows: SkillRow[]; weekPositions: number[]; showChange: boolean }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "count", dir: "desc" });
  const [shown, setShown] = useState(PAGE);

  const categories = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of rows) m.set(r.category, (m.get(r.category) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [rows]);

  const maxShare = useMemo(() => Math.max(...rows.map((r) => r.share), 0.0001), [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = rows.filter((r) => (!category || r.category === category) && (!q || r.name.toLowerCase().includes(q) || r.slug.includes(q)));
    const dir = sort.dir === "asc" ? 1 : -1;
    return list.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir;
      return ((av as number) - (bv as number)) * dir || a.name.localeCompare(b.name);
    });
  }, [rows, query, category, sort]);

  function setSortKey(key: SortKey) {
    setSort((cur) => (cur.key === key ? { key, dir: cur.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "name" || key === "category" ? "asc" : "desc" }));
  }

  const visible = filtered.slice(0, shown);

  return (
    <div>
      {/* One filter row above the table */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="sm:w-80">
            <label htmlFor="skill-search" className="sr-only">
              Search skills
            </label>
            <input
              id="skill-search"
              type="search"
              className="field w-full"
              placeholder="Search skills (e.g. python, dbt)"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setShown(PAGE);
              }}
            />
          </div>
          <p className="text-sm text-ink-3" aria-live="polite">
            {fmtInt(filtered.length)} of {fmtInt(rows.length)} skills
          </p>
        </div>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by category">
          <button type="button" className="chip" aria-pressed={category === null} onClick={() => { setCategory(null); setShown(PAGE); }}>
            All
          </button>
          {categories.map(([c, n]) => (
            <button key={c} type="button" className="chip" aria-pressed={category === c} onClick={() => { setCategory(category === c ? null : c); setShown(PAGE); }}>
              {categoryLabel(c)} <span className="opacity-60">{n}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="data-table">
          <caption className="sr-only">Skills by number of postings, share, four-week change and median salary</caption>
          <thead>
            <tr>
              <Th sort={sort} onSort={setSortKey} k="name">Skill</Th>
              <Th sort={sort} onSort={setSortKey} k="category" className="hidden md:table-cell">Category</Th>
              <Th sort={sort} onSort={setSortKey} k="count" num className="hidden sm:table-cell">Postings</Th>
              <th scope="col" className="num">Share</th>
              {showChange ? (
                <Th sort={sort} onSort={setSortKey} k="change_4w" num>4-week change</Th>
              ) : null}
              <Th sort={sort} onSort={setSortKey} k="median_salary_usd" num className="hidden md:table-cell">Median salary</Th>
              <th scope="col" className="hidden sm:table-cell">Weekly trend</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.slug}>
                <td>
                  <Link href={`/skills/${r.slug}`} className="font-medium text-ink no-underline hover:underline">
                    {r.name}
                  </Link>
                  <span className="block text-xs text-ink-3 md:hidden">{categoryLabel(r.category)}</span>
                </td>
                <td className="hidden text-ink-2 md:table-cell">{categoryLabel(r.category)}</td>
                <td className="num hidden sm:table-cell">{fmtInt(r.count)}</td>
                <td className="num">
                  <span className="inline-flex items-center justify-end gap-2">
                    <span className="hidden h-2 w-16 sm:block" aria-hidden>
                      <span className="block h-2 rounded-r-[3px]" style={{ width: `${(r.share / maxShare) * 100}%`, background: "var(--bar)", minWidth: 2 }} />
                    </span>
                    <span className="inline-block min-w-[3ch] font-medium text-ink">{fmtShare(r.share)}</span>
                  </span>
                </td>
                {showChange ? (
                  <td className="num">
                    <Delta pp={r.change_4w} />
                  </td>
                ) : null}
                <td className="num hidden md:table-cell">{r.median_salary_usd ? fmtUsdShort(r.median_salary_usd) : <span className="text-ink-3">n/a</span>}</td>
                <td className="hidden sm:table-cell">
                  {r.trend.length >= 2 ? (
                    <Sparkline values={r.trend} xs={weekPositions} label={`${r.name}: weekly share of postings, from ${fmtShare(r.trend[0])} to ${fmtShare(r.trend[r.trend.length - 1])}`} />
                  ) : (
                    <span role="img" aria-label={`Trend not available yet: needs two weeks with ${MIN_WEEK_JOBS} or more postings`} title={`Needs two weeks with ${MIN_WEEK_JOBS}+ postings`} className="text-ink-3">
                      &mdash;
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {visible.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-10 text-center text-ink-3">
                  No skills match &ldquo;{query}&rdquo;.
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
