import Link from "next/link";
import { crossesZero, fmtSignedUsd } from "./stats";
import { fmtInt, fmtUsd } from "@/lib/format";
import type { SkillPremium } from "@/lib/insights";

/**
 * Dot-and-interval chart: dot = difference in median advertised salary (with the skill minus
 * without), line = 95% bootstrap interval, one shared linear axis centred on $0. Rows whose
 * interval crosses zero are muted and drawn hollow (a second channel besides colour) and say so in words.
 * Pure HTML/CSS positioning, so it needs no JS; each row is focusable and shows its numbers on hover/focus,
 * and a table twin sits underneath.
 */
export function PremiumChart({ rows }: { rows: SkillPremium[] }) {
  const data = [...rows].sort((a, b) => b.diff - a.diff);
  const lo = Math.min(0, ...data.map((r) => r.ci_low));
  const hi = Math.max(0, ...data.map((r) => r.ci_high));
  const step = [10000, 20000, 25000, 50000, 100000].find((s) => (Math.ceil(hi / s) - Math.floor(lo / s)) <= 6) ?? 100000;
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = min; v <= max; v += step) ticks.push(v);
  const pos = (v: number) => `${((v - min) / (max - min || 1)) * 100}%`;
  const COLS = "sm:grid-cols-[9.5rem_1fr_11rem]";

  return (
    <div>
      <div className={`grid grid-cols-1 gap-x-4 ${COLS}`} aria-hidden="true">
        <div className="hidden sm:block" />
        <div className="relative mx-2 h-5 text-xs text-ink-3">
          {ticks.map((t, i) => (
            <span key={t} className="tnum absolute top-0 whitespace-nowrap" style={{ left: pos(t), transform: i === 0 ? "translateX(-25%)" : i === ticks.length - 1 ? "translateX(-75%)" : "translateX(-50%)" }}>
              {t === 0 ? "$0" : fmtSignedUsd(t)}
            </span>
          ))}
        </div>
        <div className="hidden sm:block" />
      </div>

      <ul aria-label="Difference in median advertised salary, with the skill versus without, with 95% intervals" className="m-0 list-none p-0">
        {data.map((r) => {
          const flat = crossesZero(r.ci_low, r.ci_high);
          const color = flat ? "var(--muted)" : r.diff > 0 ? "var(--s1)" : "var(--s2)";
          const summary = `${r.name}: median ${fmtUsd(r.median_with)} with the skill (${r.n_with} postings) against ${fmtUsd(r.median_without)} without (${r.n_without}); difference ${fmtSignedUsd(r.diff)}, 95% interval ${fmtSignedUsd(r.ci_low)} to ${fmtSignedUsd(r.ci_high)}${flat ? ", not distinguishable from zero at this sample size" : ""}`;
          return (
            <li key={r.slug} className={`group relative grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-0.5 border-t border-line py-2.5 first:border-t-0 ${COLS}`}>
              <div className="min-w-0 sm:order-1">
                <Link href={`/skills/${r.slug}`} className={`text-sm font-medium no-underline hover:underline ${flat ? "text-ink-2" : "text-ink"}`}>
                  {r.name}
                </Link>
                <span className="tnum block text-xs text-ink-3">
                  n = {fmtInt(r.n_with)} with &middot; {fmtInt(r.n_without)} without
                </span>
              </div>

              <div className="text-right sm:order-3 sm:text-left">
                <p className={`tnum text-sm ${flat ? "text-ink-3" : "font-semibold text-ink"}`}>
                  {fmtSignedUsd(r.diff)}
                  <span className="text-xs font-normal text-ink-3"> [{fmtSignedUsd(r.ci_low)}, {fmtSignedUsd(r.ci_high)}]</span>
                </p>
                {flat ? <p className="ml-auto max-w-[13rem] text-pretty text-xs leading-snug text-ink-3 sm:ml-0">not distinguishable from zero at this sample size</p> : null}
              </div>

              <div
                tabIndex={0}
                role="img"
                aria-label={summary}
                className="relative col-span-2 mx-2 h-8 outline-offset-2 sm:order-2 sm:col-span-1"
              >
                {ticks.map((t) => (
                  <span key={t} className="absolute inset-y-0 w-px" style={{ left: pos(t), background: t === 0 ? "var(--ink-3)" : "var(--grid)" }} aria-hidden="true" />
                ))}
                <span
                  className="absolute top-1/2 h-[2px] -translate-y-1/2 rounded-full"
                  style={{ left: pos(r.ci_low), width: `calc(${pos(r.ci_high)} - ${pos(r.ci_low)})`, background: color, opacity: flat ? 0.55 : 1 }}
                  aria-hidden="true"
                />
                <span
                  className="absolute top-1/2 box-border h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full"
                  style={{
                    left: pos(r.diff),
                    background: flat ? "var(--surface)" : color,
                    border: flat ? `2px solid ${color}` : "none",
                    boxShadow: "0 0 0 2px var(--surface)",
                  }}
                  aria-hidden="true"
                />
              </div>

              <div className="chart-tip !pointer-events-none absolute -top-1 left-0 hidden max-w-[19rem] -translate-y-full group-focus-within:block group-hover:block sm:left-[10.5rem]" role="presentation">
                <span className="tnum block">
                  With <strong>{r.name}</strong>: median {fmtUsd(r.median_with)} (n = {r.n_with})
                </span>
                <span className="tnum block">
                  Without: median {fmtUsd(r.median_without)} (n = {r.n_without})
                </span>
                <span className="tnum block font-semibold">
                  Difference {fmtSignedUsd(r.diff)}, 95% CI {fmtSignedUsd(r.ci_low)} to {fmtSignedUsd(r.ci_high)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-ink-3">
        <Key kind="solid" color="var(--s1)" label="higher pay with the skill, interval excludes $0" />
        <Key kind="solid" color="var(--s2)" label="lower pay with the skill, interval excludes $0" />
        <Key kind="hollow" color="var(--muted)" label="interval crosses $0: not distinguishable from zero" />
      </p>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-3 hover:text-ink">View data as table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="data-table">
            <caption className="sr-only">Skill pay premium: median advertised salary with and without each skill</caption>
            <thead>
              <tr>
                <th scope="col">Skill</th>
                <th scope="col" className="num">n with</th>
                <th scope="col" className="num">n without</th>
                <th scope="col" className="num">Median with</th>
                <th scope="col" className="num">Median without</th>
                <th scope="col" className="num">Difference</th>
                <th scope="col" className="num">95% CI</th>
                <th scope="col">Reading</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.slug}>
                  <th scope="row" className="!text-sm !normal-case !tracking-normal !text-ink font-medium">{r.name}</th>
                  <td className="num">{r.n_with}</td>
                  <td className="num">{r.n_without}</td>
                  <td className="num">{fmtUsd(r.median_with)}</td>
                  <td className="num">{fmtUsd(r.median_without)}</td>
                  <td className="num font-semibold">{fmtSignedUsd(r.diff)}</td>
                  <td className="num whitespace-nowrap">
                    {fmtSignedUsd(r.ci_low)} to {fmtSignedUsd(r.ci_high)}
                  </td>
                  <td className="text-ink-3">{crossesZero(r.ci_low, r.ci_high) ? "not distinguishable from zero" : r.diff > 0 ? "higher with skill" : "lower with skill"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function Key({ kind, color, label }: { kind: "solid" | "hollow"; color: string; label: string }) {
  return (
    <span className="flex items-center gap-2">
      <span
        aria-hidden="true"
        className="box-border inline-block h-3 w-3 rounded-full"
        style={{ background: kind === "solid" ? color : "var(--surface)", border: kind === "hollow" ? `2px solid ${color}` : "none" }}
      />
      {label}
    </span>
  );
}
