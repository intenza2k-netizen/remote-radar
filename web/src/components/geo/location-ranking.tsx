"use client";

import { useMemo, useState } from "react";
import { BarList } from "@/components/charts/bar-list";
import { fmtInt, fmtShare, fmtUsdShort } from "@/lib/format";
import { rankLocations, type GeoLocation } from "@/lib/geo";

const CHART_ROWS = 15;
const TABLE_STEP = 25;

type Kind = GeoLocation["kind"];
type View = "chart" | "table";

function Toggle<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1.5">
      {options.map(([v, text]) => (
        <button key={v} type="button" className="chip" aria-pressed={value === v} onClick={() => onChange(v)}>
          {text}
        </button>
      ))}
    </div>
  );
}

/**
 * Locations ranked by open data postings: a bar chart of the top 15 with a table of all of them as
 * the alternative. Worldwide postings count for every location, so the bars differ by the postings
 * that name a place or its region, on top of a floor shared by all.
 */
export function LocationRanking({ rows, listed, selected, onSelect }: { rows: GeoLocation[]; listed: number; selected: string; onSelect: (location: string) => void }) {
  const [kind, setKind] = useState<Kind>("country");
  const [view, setView] = useState<View>("chart");
  const [shown, setShown] = useState(TABLE_STEP);
  const ranked = useMemo(() => rankLocations(rows, kind), [rows, kind]);
  const noun = kind === "country" ? "countries" : "regions";

  const items = ranked.slice(0, CHART_ROWS).map((r) => ({
    key: r.location,
    label: r.location,
    value: r.data_jobs,
    valueLabel: fmtInt(r.data_jobs),
    title: `${r.location}: ${fmtInt(r.data_jobs)} open data postings, ${fmtInt(r.open_jobs)} open postings in all (${fmtShare(r.open_share)} of ${fmtInt(listed)})`,
  }));

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Toggle<Kind>
          label="Show"
          value={kind}
          options={[
            ["country", "Countries"],
            ["macro", "Regions"],
          ]}
          onChange={(k) => {
            setKind(k);
            setShown(TABLE_STEP);
          }}
        />
        <Toggle<View>
          label="View as"
          value={view}
          options={[
            ["chart", "Chart"],
            ["table", "Table"],
          ]}
          onChange={setView}
        />
      </div>

      {view === "chart" ? (
        <div className="card mt-4 p-4 sm:p-5">
          <BarList items={items} ariaLabel={`Top ${items.length} ${noun} by open data postings`} />
        </div>
      ) : (
        <div className="card mt-4 overflow-x-auto">
          <table className="data-table">
            <caption className="sr-only">All {noun} ranked by open data postings</caption>
            <thead>
              <tr>
                <th scope="col">{kind === "country" ? "Country" : "Region"}</th>
                <th scope="col" className="num">
                  Data jobs
                </th>
                <th scope="col" className="num">
                  Open jobs
                </th>
                <th scope="col" className="num">
                  Share
                </th>
                <th scope="col" className="num">
                  Median pay
                </th>
              </tr>
            </thead>
            <tbody>
              {ranked.slice(0, shown).map((r) => (
                <tr key={r.location} className={r.location === selected ? "bg-accent-wash" : undefined}>
                  <td className="!p-0">
                    <button type="button" className="block w-full px-3 py-2.5 text-left text-ink hover:underline" onClick={() => onSelect(r.location)} aria-label={`Show details for ${r.location}`}>
                      {r.location}
                    </button>
                  </td>
                  <td className="num">{fmtInt(r.data_jobs)}</td>
                  <td className="num">{fmtInt(r.open_jobs)}</td>
                  <td className="num">{fmtShare(r.open_share)}</td>
                  <td className="num">{r.median_salary_usd == null ? <span className="text-ink-3">n/a</span> : `${fmtUsdShort(r.median_salary_usd)} (n=${r.salary_n})`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {view === "table" && ranked.length > shown ? (
        <div className="mt-4 flex justify-center">
          <button type="button" className="btn" onClick={() => setShown((n) => n + TABLE_STEP)}>
            Show {Math.min(TABLE_STEP, ranked.length - shown)} more
          </button>
        </div>
      ) : null}
      <p className="mt-3 text-xs text-ink-3">
        Pay is the median of open postings that state it, shown only with at least 5 of them. {view === "table" ? "Click a name to see its details above." : "Bars show open data postings; hover a bar, or switch to the table, for all open postings."}
      </p>
    </div>
  );
}
