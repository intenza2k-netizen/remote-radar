"use client";

import { useId, useMemo, useState } from "react";
import { SkillPicker, type PickerOption } from "@/components/skill-picker";
import { fmtInt, fmtUsdShort, roleLabel, seniorityLabel, seniorityRank } from "@/lib/format";
import { contributions, predictPay, regionGroupLabel, type Contribution, type SalaryModel } from "@/lib/salary-model";
import { maeSentence, pctText } from "./copy";

/** Levels with fewer salaried postings than this get a warning: the model mostly falls back on the overall pattern. */
const THIN_LEVEL = 20;
const DEFAULT_SKILLS = ["sql", "python"];

type Props = {
  model: SalaryModel;
  /** Category of every modelled skill slug (from skills.json), for the picker's side label. */
  categories?: Record<string, string>;
};

const signed = (pct: number) => (Math.abs(pct) < 0.05 ? "0%" : `${pct > 0 ? "+" : "−"}${Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0)}%`);

/** Axis maximum that leaves room for the upper end of the range, on a round number. */
function axisTop(high: number): number {
  const step = high > 400_000 ? 100_000 : high > 160_000 ? 50_000 : 25_000;
  return Math.max(step * 4, Math.ceil((high * 1.08) / step) * step);
}

export function PayEstimator({ model, categories = {} }: Props) {
  const uid = useId();
  const [role, setRole] = useState(model.reference.role);
  const [seniority, setSeniority] = useState(model.reference.seniority);
  const [region, setRegion] = useState(model.reference.region_group);
  const [skills, setSkills] = useState<string[]>(() => DEFAULT_SKILLS.filter((s) => s in model.coef.skill));

  const names = useMemo(() => Object.fromEntries(model.skills.map((s) => [s.slug, s.name])), [model]);
  const options: PickerOption[] = useMemo(
    () => model.skills.map((s) => ({ slug: s.slug, name: s.name, count: s.n, category: categories[s.slug] ?? "other" })),
    [model, categories],
  );
  const roleOptions = useMemo(() => Object.entries(model.levels.role).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])), [model]);
  const seniorityOptions = useMemo(() => Object.entries(model.levels.seniority).sort((a, b) => seniorityRank(a[0]) - seniorityRank(b[0])), [model]);
  const regionOptions = useMemo(() => Object.entries(model.levels.region_group).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])), [model]);

  const input = { role, seniority, regionGroup: region, skills };
  const est = predictPay(model, input);
  const counted = new Set(est.used_skills);
  const moves = contributions(model, input);
  const reference = Math.round(Math.exp(model.intercept));
  const ignored = skills.filter((s) => !counted.has(s));

  const thin: string[] = [];
  if ((model.levels.role[role] ?? 0) < THIN_LEVEL) thin.push(`${roleLabel(role)} roles (${model.levels.role[role] ?? 0} postings)`);
  if ((model.levels.seniority[seniority] ?? 0) < THIN_LEVEL) thin.push(`${seniorityLabel(seniority)} postings (${model.levels.seniority[seniority] ?? 0})`);
  if ((model.levels.region_group[region] ?? 0) < THIN_LEVEL) thin.push(`${regionGroupLabel(region)} postings (${model.levels.region_group[region] ?? 0})`);

  const ev = model.eval;
  const top = axisTop(est.high);
  const pos = (v: number) => `${Math.min(100, Math.max(0, (v / top) * 100))}%`;
  const ticks = [0, 1, 2, 3, 4].map((i) => (top / 4) * i);
  const isReference = role === model.reference.role && seniority === model.reference.seniority && region === model.reference.region_group && skills.length === 0;

  function reset() {
    setRole(model.reference.role);
    setSeniority(model.reference.seniority);
    setRegion(model.reference.region_group);
    setSkills([]);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <form className="card space-y-4 self-start p-4 sm:p-5" onSubmit={(e) => e.preventDefault()} aria-label="Pay estimator inputs">
        <Field id={`${uid}-role`} label="Role">
          <select id={`${uid}-role`} className="field w-full" value={role} onChange={(e) => setRole(e.target.value)}>
            {roleOptions.map(([value, n]) => (
              <option key={value} value={value}>
                {roleLabel(value)} (n = {fmtInt(n)})
              </option>
            ))}
          </select>
        </Field>
        <Field id={`${uid}-sen`} label="Seniority">
          <select id={`${uid}-sen`} className="field w-full" value={seniority} onChange={(e) => setSeniority(e.target.value)}>
            {seniorityOptions.map(([value, n]) => (
              <option key={value} value={value}>
                {seniorityLabel(value)} (n = {fmtInt(n)})
              </option>
            ))}
          </select>
        </Field>
        <Field id={`${uid}-reg`} label="Where the job is open">
          <select id={`${uid}-reg`} className="field w-full" value={region} onChange={(e) => setRegion(e.target.value)}>
            {regionOptions.map(([value, n]) => (
              <option key={value} value={value}>
                {regionGroupLabel(value)} (n = {fmtInt(n)})
              </option>
            ))}
          </select>
        </Field>

        <div>
          <p className="mb-1.5 text-sm font-medium text-ink">Skills</p>
          <SkillPicker label="Add a skill to the estimate" options={options} selected={skills} onPick={(slug) => setSkills((prev) => [...prev, slug])} placeholder="Add a skill..." />
          <p className="mt-1.5 text-xs text-ink-3">The number beside a skill is how many postings with a stated salary list it.</p>
          {skills.length ? (
            <ul className="mt-3 flex flex-wrap gap-2" aria-label="Selected skills">
              {skills.map((s) => {
                const used = counted.has(s);
                return (
                  <li key={s}>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border py-1 pl-3 pr-1 text-sm ${used ? "border-line-strong bg-surface text-ink" : "border-dashed border-line-strong bg-surface text-ink-3"}`}
                      title={used ? undefined : "Not counted: the estimate uses only the most common skills (see the note below)"}
                    >
                      {names[s] ?? s}
                      {used ? null : <span className="text-xs">(not counted)</span>}
                      <button
                        type="button"
                        className="grid h-6 w-6 place-items-center rounded-full text-ink-3 hover:bg-surface-2 hover:text-ink"
                        aria-label={`Remove ${names[s] ?? s}`}
                        onClick={() => setSkills((prev) => prev.filter((x) => x !== s))}
                      >
                        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                          <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                        </svg>
                      </button>
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {ignored.length ? (
            <p className="mt-2 text-xs text-ink-3">
              Only the {model.profile_max_skills} most common skills count (the median posting lists {model.profile_max_skills}), chosen by how often postings list them and not by how much they pay, so a long list cannot inflate the number.
            </p>
          ) : null}
        </div>

        <button type="button" className="btn" onClick={reset} disabled={isReference}>
          Reset to the reference profile
        </button>
      </form>

      <div className="space-y-6">
        <div className="card p-4 sm:p-6" aria-live="polite">
          <p className="eyebrow">Estimated advertised pay</p>
          <p className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="tnum text-4xl font-semibold tracking-tight sm:text-5xl">{fmtUsdShort(est.median)}</span>
            <span className="text-base text-ink-2">a year, typical</span>
          </p>
          <p className="tnum mt-1 text-lg text-ink">
            {fmtUsdShort(est.low)} to {fmtUsdShort(est.high)}
            <span className="ml-2 text-sm text-ink-3">80% range</span>
          </p>

          <div role="img" aria-label={`Estimated range ${fmtUsdShort(est.low)} to ${fmtUsdShort(est.high)} with a typical value of ${fmtUsdShort(est.median)}, on a scale from $0 to ${fmtUsdShort(top)}`} className="mt-5">
            <div className="relative h-10">
              {ticks.map((t) => (
                <span key={t} className="absolute inset-y-0 w-px" style={{ left: pos(t), background: t === 0 ? "var(--ink-3)" : "var(--grid)" }} aria-hidden="true" />
              ))}
              <span className="absolute top-1/2 h-5 -translate-y-1/2 rounded-[3px]" style={{ left: pos(est.low), width: `calc(${pos(est.high)} - ${pos(est.low)})`, background: "var(--range)" }} aria-hidden="true" />
              <span className="absolute top-1/2 h-8 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-sm" style={{ left: pos(est.median), background: "var(--ink)" }} aria-hidden="true" />
            </div>
            <div className="relative mt-1 h-4 text-xs text-ink-3" aria-hidden="true">
              {ticks.map((t, i) => (
                <span key={t} className="tnum absolute top-0 whitespace-nowrap" style={{ left: pos(t), transform: i === 0 ? "none" : i === ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>
                  {fmtUsdShort(t)}
                </span>
              ))}
            </div>
          </div>

          <div className="mt-5 rounded-lg bg-surface-2 p-3 text-sm leading-relaxed text-ink-2">
            <p>
              <strong className="font-semibold text-ink">How wrong it is.</strong> On postings from companies the model had never seen, the estimate was off by a median of{" "}
              <strong className="tnum font-semibold text-ink">{pctText(ev.median_ape)}</strong> and {pctText(ev.coverage)} of them fell inside an 80% range built the same way as this one. A plain median of the same role and seniority was off by {pctText(ev.baseline.median_ape)}; {maeSentence(ev)}.
            </p>
            <p className="mt-1.5">{ev.note}</p>
          </div>

          {thin.length ? <p className="mt-3 text-sm text-ink-2">Thin evidence: the data has few {thin.join(", ")}, so this part of the estimate leans on the overall pattern.</p> : null}
        </div>

        <div className="card p-4 sm:p-6">
          <h3 className="text-base font-semibold">How each input moves the estimate</h3>
          <p className="mt-1 max-w-2xl text-sm text-ink-3">
            Percent against the reference profile ({roleLabel(model.reference.role)}, {seniorityLabel(model.reference.seniority)}, {regionGroupLabel(model.reference.region_group)}, no skills), which comes to about {fmtUsdShort(reference)}. The effects multiply, so they do not simply add up.
          </p>
          <MoveList moves={moves} names={names} />
        </div>
      </div>
    </div>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
    </div>
  );
}

const KIND_LABEL: Record<Contribution["kind"], string> = { role: "Role", seniority: "Seniority", region: "Region", skill: "Skill" };

function MoveList({ moves, names }: { moves: Contribution[]; names: Record<string, string> }) {
  const biggest = Math.max(...moves.map((m) => Math.abs(m.pct)));
  const scale = Math.max(25, Math.ceil(biggest / 25) * 25);
  const labelOf = (m: Contribution) => (m.kind === "role" ? roleLabel(m.key) : m.kind === "seniority" ? seniorityLabel(m.key) : m.kind === "region" ? regionGroupLabel(m.key) : (names[m.key] ?? m.key));
  return (
    <ul className="mt-4 list-none p-0" aria-label="Effect of each input on the estimate, in percent">
      {moves.map((m) => {
        const width = (Math.abs(m.pct) / scale) * 50;
        const color = m.pct >= 0 ? "var(--s1)" : "var(--s2)";
        const flat = Math.abs(m.pct) < 0.05;
        return (
          <li key={`${m.kind}-${m.key}`} className="grid grid-cols-[minmax(0,7.5rem)_1fr_3.5rem] items-center gap-x-3 border-t border-line py-2 first:border-t-0 sm:grid-cols-[minmax(0,11rem)_1fr_4rem]">
            <span className="min-w-0 text-sm leading-tight text-ink">
              <span className="block text-xs text-ink-3">{KIND_LABEL[m.kind]}</span>
              <span className="block truncate" title={labelOf(m)}>{labelOf(m)}</span>
            </span>
            <span className="relative block h-3" aria-hidden="true">
              <span className="absolute inset-y-0 left-1/2 w-px" style={{ background: "var(--ink-3)" }} />
              {flat ? null : (
                <span
                  className="absolute top-0 h-3 rounded-[2px]"
                  style={{ background: color, width: `${width}%`, left: m.pct >= 0 ? "50%" : `${50 - width}%` }}
                />
              )}
            </span>
            <span className="tnum text-right text-sm font-medium text-ink">
              {flat ? (m.kind === "skill" ? "0%" : "reference") : signed(m.pct)}
              <span className="sr-only"> against the reference</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

