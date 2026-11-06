import { fmtInt, fmtShare, fmtUsdShort, seniorityLabel } from "@/lib/format";
import { looseReasons, typicalLevel, type Archetype } from "@/lib/archetypes";
import { Marker } from "./marker";

export type TypeRow = { archetype: Archetype; neighbours: string[] };

/** The scatter plot as a table: every number the picture encodes, plus which types sit next to each other. */
export function TypesTable({ rows }: { rows: TypeRow[] }) {
  return (
    <div className="card overflow-x-auto">
      <table className="data-table min-w-[44rem]">
        <caption className="sr-only">Job types: size, median advertised pay, typical seniority, how well titles match and which types sit next to each other on the map</caption>
        <thead>
          <tr>
            <th scope="col">Type</th>
            <th scope="col" className="num">
              Postings
            </th>
            <th scope="col" className="num">
              Median pay
            </th>
            <th scope="col">Typical level</th>
            <th scope="col" className="num">
              Titles match
            </th>
            <th scope="col">Closest on the map</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ archetype: a, neighbours }, i) => {
            const level = typicalLevel(a);
            const loose = looseReasons(a).length > 0;
            return (
              <tr key={a.id}>
                <td>
                  <a href={`#type-${a.id}`} className="inline-flex items-center gap-2 text-ink no-underline hover:underline">
                    <Marker index={i} />
                    <span className="tnum font-semibold">{i + 1}</span>
                    <span className="whitespace-normal">{a.name}</span>
                  </a>
                  {loose ? <span className="ml-2 whitespace-nowrap text-xs font-normal text-ink-3">loose</span> : null}
                </td>
                <td className="num whitespace-nowrap">
                  {fmtInt(a.n)} <span className="text-ink-3">({fmtShare(a.share)})</span>
                </td>
                <td className="num">
                  {a.median_salary_usd != null ? (
                    <>
                      {fmtUsdShort(a.median_salary_usd)} <span className="text-ink-3">n={fmtInt(a.salary_n)}</span>
                    </>
                  ) : (
                    <span className="text-ink-3">too few (n={fmtInt(a.salary_n)})</span>
                  )}
                </td>
                <td>{level ? seniorityLabel(level.level) : <span className="text-ink-3">mostly unstated</span>}</td>
                <td className="num">{a.family_share != null && a.family ? fmtShare(a.family_share) : <span className="text-ink-3">n/a</span>}</td>
                <td className="text-ink-2">{neighbours.join(", ") || "n/a"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
