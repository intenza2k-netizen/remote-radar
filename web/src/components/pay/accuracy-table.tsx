import { fmtInt, fmtUsd } from "@/lib/format";
import type { SalaryModel } from "@/lib/salary-model";
import { pctText } from "./copy";

/**
 * Held-out accuracy of the salary model next to the baseline, both scored on the same company-grouped folds.
 * The better value in each row is in bold. The text under the table repeats the verdict in words.
 */
export function AccuracyTable({ model }: { model: SalaryModel }) {
  const ev = model.eval;
  const rows = [
    { label: "Mean absolute error", model: ev.mae_usd, base: ev.baseline.mae_usd, fmt: fmtUsd, better: "low" as const },
    { label: "Median absolute percentage error", model: ev.median_ape, base: ev.baseline.median_ape, fmt: pctText, better: "low" as const },
    { label: "R² on log pay", model: ev.r2_log, base: ev.baseline.r2_log, fmt: (v: number) => v.toFixed(2), better: "high" as const },
  ];
  return (
    <div>
      <div className="card overflow-x-auto">
        <table className="data-table">
          <caption className="sr-only">Held-out accuracy of the salary model and of the baseline</caption>
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col" className="num">Salary model</th>
              <th scope="col" className="num">Baseline: {ev.baseline.name}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const modelWins = r.better === "low" ? r.model < r.base : r.model > r.base;
              return (
                <tr key={r.label}>
                  <th scope="row" className="!whitespace-normal !text-sm !normal-case !tracking-normal !text-ink-2 font-medium">
                    {r.label}
                    <span className="ml-1.5 hidden text-xs font-normal text-ink-3 sm:inline">{r.better === "high" ? "higher is better" : "lower is better"}</span>
                  </th>
                  <td className={`num ${modelWins ? "font-bold text-ink" : "text-ink-2"}`}>{r.fmt(r.model)}</td>
                  <td className={`num ${modelWins ? "text-ink-2" : "font-bold text-ink"}`}>{r.fmt(r.base)}</td>
                </tr>
              );
            })}
            <tr>
              <th scope="row" className="!whitespace-normal !text-sm !normal-case !tracking-normal !text-ink-2 font-medium">
                80% range holds the actual pay
                <span className="ml-1.5 hidden text-xs font-normal text-ink-3 sm:inline">target 80%</span>
              </th>
              <td className="num text-ink-2">{pctText(ev.coverage)}</td>
              <td className="num text-ink-3">n/a</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-3 max-w-3xl text-sm text-ink-2">
        {ev.note} Scored on {fmtInt(ev.n)} postings in {ev.folds} folds; {ev.method}.
      </p>
    </div>
  );
}
