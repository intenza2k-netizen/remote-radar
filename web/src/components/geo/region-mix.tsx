import { BarList } from "@/components/charts/bar-list";
import { fmtInt, fmtShare, fmtUsdShort } from "@/lib/format";
import { regionGroupLabel, type RegionMixRow } from "@/lib/geo";

/** Postings of the 8-week window by the coarse region they are open to. */
export function RegionMix({ rows }: { rows: RegionMixRow[] }) {
  const items = rows.map((r) => ({
    key: r.group,
    label: regionGroupLabel(r.group),
    value: r.n,
    valueLabel: fmtShare(r.share),
    sub: r.median_salary_usd == null ? undefined : fmtUsdShort(r.median_salary_usd),
    title: `${fmtInt(r.n)} postings${r.median_salary_usd == null ? "" : `, median advertised pay ${fmtUsdShort(r.median_salary_usd)}`}`,
  }));
  return (
    <div className="card p-4 sm:p-5">
      <BarList items={items} ariaLabel="Share of postings by the region they are open to" />
    </div>
  );
}
