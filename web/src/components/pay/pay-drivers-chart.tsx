import Link from "next/link";
import { fmtInt } from "@/lib/format";
import type { SalaryDriver, SalarySkill } from "@/lib/salary-model";

const STEPS = [10, 20, 25, 50, 100];

const signed = (pct: number) => `${pct > 0 ? "+" : pct < 0 ? "−" : ""}${Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0)}%`;
const crossesZero = (lo: number, hi: number) => lo <= 0 && hi >= 0;

/**
 * Diverging bars: the pay effect of the skills with the largest positive and negative coefficients in the model,
 * in percent against the same role, seniority and region group without the skill. The thin line is a 95%
 * company-cluster bootstrap interval; rows whose interval crosses zero are muted and drawn with a hollow end.
 * Pure HTML/CSS positioning on one shared linear axis, no client JavaScript; every row is focusable and a table with
 * every modelled skill sits underneath.
 */
export function PayDriversChart({ drivers, skills, bootstraps }: { drivers: SalaryDriver[]; skills: SalarySkill[]; bootstraps?: number }) {
  const rows = [...drivers].sort((a, b) => b.pct - a.pct);
  if (!rows.length) return <p className="text-sm text-ink-3">No skill has an effect large enough to list.</p>;
  const lo = Math.min(0, ...rows.map((r) => Math.min(r.pct, r.ci_low_pct)));
  const hi = Math.max(0, ...rows.map((r) => Math.max(r.pct, r.ci_high_pct)));
  const step = STEPS.find((s) => Math.ceil(hi / s) - Math.floor(lo / s) <= 8) ?? STEPS[STEPS.length - 1];
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = min; v <= max; v += step) ticks.push(v);
  const pos = (v: number) => `${((v - min) / (max - min || 1)) * 100}%`;
  const COLS = "lg:grid-cols-[11rem_1fr_9rem]";
  const clear = rows.filter((r) => !crossesZero(r.ci_low_pct, r.ci_high_pct)).length;

  return (
    <div>
      <div className={`grid grid-cols-1 gap-x-4 ${COLS}`} aria-hidden="true">
        <div className="hidden lg:block" />
        <div className="relative mx-2 h-5 text-xs text-ink-3">
          {ticks.map((t, i) => (
            <span key={t} className="tnum absolute top-0 whitespace-nowrap" style={{ left: pos(t), transform: i === 0 ? "translateX(-25%)" : i === ticks.length - 1 ? "translateX(-75%)" : "translateX(-50%)" }}>
              {t === 0 ? "0%" : signed(t)}
            </span>
          ))}
        </div>
        <div className="hidden lg:block" />
      </div>

      <ul aria-label="Pay effect of the skills with the largest coefficients, in percent, with 95% intervals" className="m-0 list-none p-0">
        {rows.map((r) => {
          const flat = crossesZero(r.ci_low_pct, r.ci_high_pct);
          const color = flat ? "var(--muted)" : r.pct > 0 ? "var(--s1)" : "var(--s2)";
          const left = r.pct >= 0 ? pos(0) : pos(r.pct);
          const width = `calc(${pos(Math.max(r.pct, 0))} - ${pos(Math.min(r.pct, 0))})`;
          const summary = `${r.name}: ${signed(r.pct)} (95% interval ${signed(r.ci_low_pct)} to ${signed(r.ci_high_pct)}), listed in ${r.n} salaried postings${flat ? "; the interval includes zero, so this could be noise" : ""}`;
          return (
            <li key={r.slug} className={`group relative grid grid-cols-1 items-center gap-x-4 gap-y-1 border-t border-line py-2 first:border-t-0 ${COLS}`}>
              <div className="min-w-0 lg:order-1">
                <Link href={`/skills/${r.slug}`} className={`text-sm font-medium no-underline hover:underline ${flat ? "text-ink-2" : "text-ink"}`}>
                  {r.name}
                </Link>
                <span className="tnum block text-xs text-ink-3">n = {fmtInt(r.n)}</span>
              </div>
              <div className="lg:order-3">
                <p className={`tnum text-sm ${flat ? "text-ink-3" : "font-semibold text-ink"}`}>{signed(r.pct)}</p>
                <p className="tnum text-xs text-ink-3">
                  [{signed(r.ci_low_pct)}, {signed(r.ci_high_pct)}]{flat ? " could be noise" : ""}
                </p>
              </div>
              <div tabIndex={0} role="img" aria-label={summary} className="relative mx-2 h-7 outline-offset-2 lg:order-2">
                {ticks.map((t) => (
                  <span key={t} className="absolute inset-y-0 w-px" style={{ left: pos(t), background: t === 0 ? "var(--ink-3)" : "var(--grid)" }} aria-hidden="true" />
                ))}
                <span className="absolute top-1/2 h-3.5 -translate-y-1/2 rounded-[2px]" style={{ left, width, background: color, opacity: flat ? 0.45 : 1 }} aria-hidden="true" />
                <span
                  className="absolute top-1/2 h-[2px] -translate-y-1/2 rounded-full"
                  style={{ left: pos(r.ci_low_pct), width: `calc(${pos(r.ci_high_pct)} - ${pos(r.ci_low_pct)})`, background: "var(--ink)", opacity: 0.7 }}
                  aria-hidden="true"
                />
              </div>
            </li>
          );
        })}
      </ul>

      <p className="mt-3 max-w-3xl text-xs text-ink-3">
        Bars show the model&rsquo;s effect for the skill, the line its 95% interval ({bootstraps ? `${fmtInt(bootstraps)} resamples` : "resamples"} of whole companies). {clear} of these {rows.length} have an interval that excludes zero; the rest are muted. With {fmtInt(skills.length)} skills in the model, a few of the clear ones are expected by luck alone, and the model shrinks every coefficient towards zero, so the true effects are probably smaller than the bars.
      </p>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-3 hover:text-ink">View all {fmtInt(skills.length)} modelled skills as a table</summary>
        <div className="mt-2 max-h-96 overflow-auto">
          <table className="data-table">
            <caption className="sr-only">Pay effect of every skill in the salary model, in percent, with 95% intervals</caption>
            <thead>
              <tr>
                <th scope="col">Skill</th>
                <th scope="col" className="num">Salaried postings</th>
                <th scope="col" className="num">Companies</th>
                <th scope="col" className="num">Effect</th>
                <th scope="col" className="num">95% interval</th>
              </tr>
            </thead>
            <tbody>
              {[...skills]
                .sort((a, b) => b.pct - a.pct)
                .map((s) => (
                  <tr key={s.slug}>
                    <th scope="row" className="!text-sm !normal-case !tracking-normal !text-ink font-medium">{s.name}</th>
                    <td className="num">{fmtInt(s.n)}</td>
                    <td className="num">{fmtInt(s.n_companies)}</td>
                    <td className="num whitespace-nowrap font-semibold">{signed(s.pct)}</td>
                    <td className="num whitespace-nowrap">
                      {signed(s.ci_low_pct)} to {signed(s.ci_high_pct)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
