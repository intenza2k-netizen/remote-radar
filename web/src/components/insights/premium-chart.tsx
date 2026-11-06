"use client";

import Link from "next/link";
import { useState } from "react";
import { adjustedOf, crossesZero, fmtSignedPct, fmtSignedUsd } from "./stats";
import { fmtInt, fmtUsd } from "@/lib/format";
import type { SkillPremium } from "@/lib/types";

type Mode = "adjusted" | "raw";
type View = { diff: number; lo: number; hi: number };

const PCT_STEPS = [10, 20, 25, 50, 100, 200];
const USD_STEPS = [10000, 20000, 25000, 50000, 100000];

/** "+12% (≈ +$18k) [+5%, +19%]": the adjusted estimate as text, or a short reason when there is none. */
function adjustedText(r: SkillPremium): string {
  const a = adjustedOf(r);
  if (!a) return "no estimate (nothing varies within role, seniority and region)";
  const usd = a.usd != null ? ` (≈ ${fmtSignedUsd(a.usd)} at these postings’ pay)` : "";
  return `${fmtSignedPct(a.diff)}${usd} [${fmtSignedPct(a.ci_low)}, ${fmtSignedPct(a.ci_high)}]`;
}

const rawText = (r: SkillPremium) => `${fmtSignedUsd(r.diff)} [${fmtSignedUsd(r.ci_low)}, ${fmtSignedUsd(r.ci_high)}]`;

/**
 * Dot-and-interval chart with a switch between two measures of the same comparison (postings that mention
 * the skill against postings that do not):
 * - "Within role, seniority and region" (default): the percentage by which postings with the skill advertise
 *   more or less than postings of the same role, seniority and region group without it (least squares on log salary), in %;
 * - "Raw difference": the difference of the two median advertised salaries, in dollars.
 * The line is the 95% company-cluster bootstrap interval of the shown measure, on one shared linear axis
 * centred on zero. Rows whose interval crosses zero are muted and drawn hollow (a second channel besides
 * colour) and say so in words. Every row prints both numbers in text, so a reader sees how much role explains.
 * Pure HTML/CSS positioning; each row is focusable and shows its numbers on hover/focus, and a table twin
 * with every number sits underneath.
 */
export function PremiumChart({ rows, roleNote }: { rows: SkillPremium[]; roleNote?: string | null }) {
  const hasAdjusted = rows.some((r) => adjustedOf(r));
  const [chosen, setChosen] = useState<Mode>("adjusted");
  const mode: Mode = hasAdjusted ? chosen : "raw";
  const adjusted = mode === "adjusted";

  const viewOf = (r: SkillPremium): View | null => {
    if (!adjusted) return { diff: r.diff, lo: r.ci_low, hi: r.ci_high };
    const a = adjustedOf(r);
    return a ? { diff: a.diff, lo: a.ci_low, hi: a.ci_high } : null;
  };
  const fmt = adjusted ? fmtSignedPct : fmtSignedUsd;
  const zero = adjusted ? "0%" : "$0";

  const data = rows
    .map((r) => ({ r, v: viewOf(r) }))
    .sort((a, b) => (a.v && b.v ? b.v.diff - a.v.diff : a.v ? -1 : b.v ? 1 : 0));
  const views = data.flatMap((d) => (d.v ? [d.v] : []));
  const lo = Math.min(0, ...views.map((v) => v.lo));
  const hi = Math.max(0, ...views.map((v) => v.hi));
  const steps = adjusted ? PCT_STEPS : USD_STEPS;
  const step = steps.find((s) => Math.ceil(hi / s) - Math.floor(lo / s) <= 6) ?? steps[steps.length - 1];
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = min; v <= max; v += step) ticks.push(v);
  const pos = (v: number) => `${((v - min) / (max - min || 1)) * 100}%`;
  const COLS = "lg:grid-cols-[9.5rem_1fr_17rem]";

  return (
    <div>
      {hasAdjusted ? (
        <div role="group" aria-label="Which pay difference to show" className="flex flex-wrap gap-2">
          <button type="button" className="chip" aria-pressed={adjusted} onClick={() => setChosen("adjusted")}>
            Within role, seniority and region
          </button>
          <button type="button" className="chip" aria-pressed={!adjusted} onClick={() => setChosen("raw")}>
            Raw difference
          </button>
        </div>
      ) : null}

      <div aria-live="polite" className="mt-3 max-w-3xl text-pretty text-sm text-ink-2">
        {adjusted
          ? "Showing the difference against postings of the same role, seniority and region group, in percent. The raw dollar gap is printed under each row."
          : "Showing the raw difference of median salaries, in dollars, with no adjustment. Switch back to see how much of it is role, seniority and region."}
      </div>
      {roleNote ? <p className="mt-2 max-w-3xl text-pretty text-sm font-medium text-ink">{roleNote}</p> : null}

      <div className="mt-4">
        <div className={`grid grid-cols-1 gap-x-4 ${COLS}`} aria-hidden="true">
          <div className="hidden lg:block" />
          <div className="relative mx-2 h-5 text-xs text-ink-3">
            {ticks.map((t, i) => (
              <span key={t} className="tnum absolute top-0 whitespace-nowrap" style={{ left: pos(t), transform: i === 0 ? "translateX(-25%)" : i === ticks.length - 1 ? "translateX(-75%)" : "translateX(-50%)" }}>
                {t === 0 ? zero : fmt(t)}
              </span>
            ))}
          </div>
          <div className="hidden lg:block" />
        </div>

        <ul
          aria-label={adjusted ? "Pay difference within the same role, seniority and region, in percent, with 95% intervals" : "Raw difference in median advertised salary, with the skill versus without, with 95% intervals"}
          className="m-0 list-none p-0"
        >
          {data.map(({ r, v }) => {
            const flat = !v || crossesZero(v.lo, v.hi);
            const color = flat ? "var(--muted)" : v.diff > 0 ? "var(--s1)" : "var(--s2)";
            const sample = `${fmtInt(r.n_with)} with${r.n_companies ? ` (${fmtInt(r.n_companies)} companies)` : ""} · ${fmtInt(r.n_without)} without`;
            const summary =
              `${r.name}: within role, seniority and region ${adjustedText(r)}; raw gap ${rawText(r)} (median ${fmtUsd(r.median_with)} with the skill, ${r.n_with} postings` +
              `${r.n_companies ? ` from ${r.n_companies} companies` : ""}, against ${fmtUsd(r.median_without)} without, ${r.n_without} postings)` +
              `${flat ? "; the shown interval includes zero, so this cannot be told apart from no difference at this sample size" : ""}`;
            const primary = adjusted ? adjustedText(r) : rawText(r);
            const secondary = adjusted ? `raw gap: ${fmtSignedUsd(r.diff)}` : hasAdjusted ? `within role, seniority and region: ${adjustedText(r)}` : null;
            return (
              <li key={r.slug} className={`group relative grid grid-cols-1 items-center gap-x-4 gap-y-1 border-t border-line py-2.5 first:border-t-0 ${COLS}`}>
                <div className="min-w-0 lg:order-1">
                  <Link href={`/skills/${r.slug}`} className={`text-sm font-medium no-underline hover:underline ${flat ? "text-ink-2" : "text-ink"}`}>
                    {r.name}
                  </Link>
                  <span className="tnum block text-xs text-ink-3">n = {sample}</span>
                </div>

                <div className="lg:order-3">
                  <p className={`tnum text-sm ${flat ? "text-ink-3" : "text-ink"}`}>
                    <span className="text-xs font-normal text-ink-3">{adjusted ? "within role, seniority and region: " : "raw gap: "}</span>
                    <span className={flat ? "" : "font-semibold"}>{primary}</span>
                  </p>
                  {secondary ? <p className="tnum text-xs text-ink-3">{secondary}</p> : null}
                  {flat ? <p className="max-w-[17rem] text-pretty text-xs leading-snug text-ink-3">{v ? "interval includes zero: not distinguishable from no difference" : "no estimate for this skill"}</p> : null}
                </div>

                <div tabIndex={0} role="img" aria-label={summary} className="relative mx-2 h-8 outline-offset-2 lg:order-2">
                  {ticks.map((t) => (
                    <span key={t} className="absolute inset-y-0 w-px" style={{ left: pos(t), background: t === 0 ? "var(--ink-3)" : "var(--grid)" }} aria-hidden="true" />
                  ))}
                  {v ? (
                    <>
                      <span
                        className="absolute top-1/2 h-[2px] -translate-y-1/2 rounded-full"
                        style={{ left: pos(v.lo), width: `calc(${pos(v.hi)} - ${pos(v.lo)})`, background: color, opacity: flat ? 0.55 : 1 }}
                        aria-hidden="true"
                      />
                      <span
                        className="absolute top-1/2 box-border h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full"
                        style={{
                          left: pos(v.diff),
                          background: flat ? "var(--surface)" : color,
                          border: flat ? `2px solid ${color}` : "none",
                          boxShadow: "0 0 0 2px var(--surface)",
                        }}
                        aria-hidden="true"
                      />
                    </>
                  ) : null}
                </div>

                <div className="chart-tip !pointer-events-none absolute -top-1 left-0 hidden max-w-[19rem] -translate-y-full group-focus-within:block group-hover:block lg:left-[10.5rem]" role="presentation">
                  <span className="tnum block font-semibold">{r.name}</span>
                  <span className="tnum block">Within role, seniority and region: {adjustedText(r)}</span>
                  <span className="tnum block">Raw gap: {rawText(r)}</span>
                  <span className="tnum block">
                    Median {fmtUsd(r.median_with)} with (n = {r.n_with}
                    {r.n_companies ? `, ${r.n_companies} companies` : ""}) against {fmtUsd(r.median_without)} without (n = {r.n_without})
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      <p className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-ink-3">
        <Key kind="solid" color="var(--s1)" label={`higher pay with the skill, interval excludes ${zero}`} />
        <Key kind="solid" color="var(--s2)" label={`lower pay with the skill, interval excludes ${zero}`} />
        <Key kind="hollow" color="var(--muted)" label={`interval crosses ${zero}: not distinguishable from zero`} />
      </p>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-3 hover:text-ink">View data as table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="data-table">
            <caption className="sr-only">Skill pay premium: pay difference within role, seniority and region, and raw median advertised salary with and without each skill</caption>
            <thead>
              <tr>
                <th scope="col">Skill</th>
                <th scope="col" className="num">n with</th>
                <th scope="col" className="num">n without</th>
                <th scope="col" className="num">Within role, seniority and region</th>
                <th scope="col" className="num">95% CI</th>
                <th scope="col" className="num">Median with</th>
                <th scope="col" className="num">Median without</th>
                <th scope="col" className="num">Raw gap</th>
                <th scope="col" className="num">Raw 95% CI</th>
                <th scope="col">Reading (within role, seniority and region)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const a = adjustedOf(r);
                return (
                  <tr key={r.slug}>
                    <th scope="row" className="!text-sm !normal-case !tracking-normal !text-ink font-medium">{r.name}</th>
                    <td className="num">{r.n_with}</td>
                    <td className="num">{r.n_without}</td>
                    <td className="num font-semibold whitespace-nowrap">{a ? `${fmtSignedPct(a.diff)}${a.usd != null ? ` (≈ ${fmtSignedUsd(a.usd)} at these postings’ pay)` : ""}` : "n/a"}</td>
                    <td className="num whitespace-nowrap">{a ? `${fmtSignedPct(a.ci_low)} to ${fmtSignedPct(a.ci_high)}` : "n/a"}</td>
                    <td className="num">{fmtUsd(r.median_with)}</td>
                    <td className="num">{fmtUsd(r.median_without)}</td>
                    <td className="num">{fmtSignedUsd(r.diff)}</td>
                    <td className="num whitespace-nowrap">
                      {fmtSignedUsd(r.ci_low)} to {fmtSignedUsd(r.ci_high)}
                    </td>
                    <td className="text-ink-3">{!a ? "no estimate" : crossesZero(a.ci_low, a.ci_high) ? "not distinguishable from zero" : a.diff > 0 ? "higher with skill" : "lower with skill"}</td>
                  </tr>
                );
              })}
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
