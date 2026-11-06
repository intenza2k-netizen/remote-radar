"use client";

import Link from "next/link";
import { useState } from "react";
import { fmtLift, fmtShareDiffPP } from "./stats";
import { fmtInt, fmtShare, roleLabel } from "@/lib/format";
import type { RoleLiftPrepared } from "@/lib/insights";

/** Group sizes below this get an explicit small-sample warning. */
const SMALL_GROUP = 20;

/**
 * Role selector + dumbbell chart. For the chosen role each row shows the share of junior postings
 * (light dot) and of senior postings (dark dot) that mention a skill, joined by a line. Rows whose
 * Newcombe 95% interval for the difference includes zero are greyed and flagged as possible noise.
 */
export function LiftChart({ roles }: { roles: RoleLiftPrepared[] }) {
  const [role, setRole] = useState(roles[0]?.role ?? "");
  const cur = roles.find((r) => r.role === role) ?? roles[0];
  if (!cur) return null;

  const maxShare = Math.max(0.05, ...cur.rows.flatMap((r) => [r.share_senior, r.share_junior]));
  const step = [0.1, 0.2, 0.25, 0.5].find((s) => Math.ceil((maxShare * 1.05) / s) <= 5) ?? 0.5;
  const top = Math.ceil((maxShare * 1.05) / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + 1e-9; v += step) ticks.push(Math.round(v * 1000) / 1000);
  const pos = (v: number) => `${(v / top) * 100}%`;
  const COLS = "sm:grid-cols-[9.5rem_1fr_9.5rem]";
  const small = Math.min(cur.n_senior, cur.n_junior) < SMALL_GROUP;
  const clear = cur.rows.filter((r) => r.clear && r.diff > 0).sort((a, b) => b.diff - a.diff);
  const sentence = clear.length
    ? `In ${roleLabel(cur.role).toLowerCase()} postings, ${clear[0].name} shows the clearest gap: ${fmtShare(clear[0].share_senior)} of senior postings mention it against ${fmtShare(clear[0].share_junior)} of junior ones.`
    : `In ${roleLabel(cur.role).toLowerCase()} postings, none of these skills separates senior from junior beyond what chance could produce with groups this size.`;

  return (
    <div>
      <div role="group" aria-label="Choose a role" className="flex flex-wrap gap-2">
        {roles.map((r) => (
          <button key={r.role} type="button" className="chip" aria-pressed={r.role === cur.role} onClick={() => setRole(r.role)}>
            {roleLabel(r.role)} <span className="tnum opacity-60">{fmtInt(r.n_senior + r.n_junior)}</span>
          </button>
        ))}
      </div>

      <div className="mt-5" aria-live="polite">
        <p className="max-w-3xl text-pretty text-base font-medium text-ink">{sentence}</p>
        <p className="tnum mt-1 text-sm text-ink-3">
          Senior postings n = {fmtInt(cur.n_senior)} &middot; junior postings n = {fmtInt(cur.n_junior)}
          {small ? (
            <span className="text-ink-2"> &mdash; a small group: treat every row here as a rough guide.</span>
          ) : null}
        </p>
      </div>

      <div className="mt-5">
        <div className={`grid grid-cols-1 gap-x-4 ${COLS}`} aria-hidden="true">
          <div className="hidden sm:block" />
          <div className="relative mx-2 h-5 text-xs text-ink-3">
            {ticks.map((t, i) => (
              <span key={t} className="tnum absolute top-0" style={{ left: pos(t), transform: i === 0 ? "none" : i === ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>
                {Math.round(t * 100)}%
              </span>
            ))}
          </div>
          <div className="hidden sm:block" />
        </div>

        <ul aria-label={`Share of senior and junior ${roleLabel(cur.role)} postings that mention each skill`} className="m-0 list-none p-0">
          {cur.rows.map((r) => {
            const ink = r.clear ? "var(--bar)" : "var(--muted)";
            const soft = r.clear ? "var(--bar-soft)" : "var(--axis)";
            const cs = Math.round(r.share_senior * cur.n_senior);
            const cj = Math.round(r.share_junior * cur.n_junior);
            const summary = `${r.name}: ${fmtShare(r.share_senior)} of senior postings (${cs} of ${cur.n_senior}) against ${fmtShare(r.share_junior)} of junior (${cj} of ${cur.n_junior}); ${fmtLift(r.lift)} lift; ${r.clear ? "difference clears chance" : "could be noise at this sample size"}`;
            const a = Math.min(r.share_senior, r.share_junior);
            const b = Math.max(r.share_senior, r.share_junior);
            return (
              <li key={r.slug} className={`group relative grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-0.5 border-t border-line py-2.5 first:border-t-0 ${COLS}`}>
                <div className="min-w-0 sm:order-1">
                  <Link href={`/skills/${r.slug}`} className={`text-sm font-medium no-underline hover:underline ${r.clear ? "text-ink" : "text-ink-2"}`}>
                    {r.name}
                  </Link>
                </div>
                <div className="text-right sm:order-3 sm:text-left">
                  <p className={`tnum text-sm ${r.clear ? "font-semibold text-ink" : "text-ink-3"}`}>
                    {fmtLift(r.lift)} <span className="text-xs font-normal text-ink-3">{fmtShareDiffPP(r.diff)}</span>
                  </p>
                  {!r.clear ? <p className="text-xs leading-snug text-ink-3">could be noise</p> : null}
                </div>
                <div tabIndex={0} role="img" aria-label={summary} className="relative col-span-2 mx-2 h-8 outline-offset-2 sm:order-2 sm:col-span-1">
                  {ticks.map((t) => (
                    <span key={t} className="absolute inset-y-0 w-px" style={{ left: pos(t), background: t === 0 ? "var(--axis)" : "var(--grid)" }} aria-hidden="true" />
                  ))}
                  <span className="absolute top-1/2 h-[2px] -translate-y-1/2" style={{ left: pos(a), width: `calc(${pos(b)} - ${pos(a)})`, background: ink, opacity: 0.6 }} aria-hidden="true" />
                  <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: pos(r.share_junior), background: soft, boxShadow: "0 0 0 2px var(--surface)" }} aria-hidden="true" />
                  <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: pos(r.share_senior), background: ink, boxShadow: "0 0 0 2px var(--surface)" }} aria-hidden="true" />
                </div>
                <div className="chart-tip !pointer-events-none absolute -top-1 left-0 hidden max-w-[19rem] -translate-y-full group-focus-within:block group-hover:block sm:left-[10.5rem]" role="presentation">
                  <span className="tnum block">
                    Senior: <strong>{fmtShare(r.share_senior)}</strong> ({cs} of {cur.n_senior})
                  </span>
                  <span className="tnum block">
                    Junior: <strong>{fmtShare(r.share_junior)}</strong> ({cj} of {cur.n_junior})
                  </span>
                  <span className="tnum block">
                    Difference {fmtShareDiffPP(r.diff)}, 95% CI {fmtShareDiffPP(r.ci_low)} to {fmtShareDiffPP(r.ci_high)}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>

        <p className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-ink-3">
          <span className="flex items-center gap-2">
            <span aria-hidden className="inline-block h-3 w-3 rounded-full" style={{ background: "var(--bar-soft)" }} /> share of junior postings
          </span>
          <span className="flex items-center gap-2">
            <span aria-hidden className="inline-block h-3 w-3 rounded-full" style={{ background: "var(--bar)" }} /> share of senior postings
          </span>
          <span className="flex items-center gap-2">
            <span aria-hidden className="inline-block h-3 w-3 rounded-full" style={{ background: "var(--muted)" }} /> grey: gap could be noise
          </span>
        </p>

        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-ink-3 hover:text-ink">View data as table</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="data-table">
              <caption className="sr-only">Senior versus junior {roleLabel(cur.role)} postings: share mentioning each skill</caption>
              <thead>
                <tr>
                  <th scope="col">Skill</th>
                  <th scope="col" className="num">Senior (n = {cur.n_senior})</th>
                  <th scope="col" className="num">Junior (n = {cur.n_junior})</th>
                  <th scope="col" className="num">Lift</th>
                  <th scope="col" className="num">Difference</th>
                  <th scope="col" className="num">95% CI</th>
                  <th scope="col">Reading</th>
                </tr>
              </thead>
              <tbody>
                {cur.rows.map((r) => (
                  <tr key={r.slug}>
                    <th scope="row" className="!text-sm !normal-case !tracking-normal !text-ink font-medium">{r.name}</th>
                    <td className="num">{fmtShare(r.share_senior)}</td>
                    <td className="num">{fmtShare(r.share_junior)}</td>
                    <td className="num">{fmtLift(r.lift)}</td>
                    <td className="num font-semibold">{fmtShareDiffPP(r.diff)}</td>
                    <td className="num whitespace-nowrap">
                      {fmtShareDiffPP(r.ci_low)} to {fmtShareDiffPP(r.ci_high)}
                    </td>
                    <td className="text-ink-3">{r.clear ? (r.diff > 0 ? "more common in senior" : "more common in junior") : "could be noise"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    </div>
  );
}
