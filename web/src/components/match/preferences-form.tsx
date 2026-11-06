"use client";

import { fmtInt, seniorityLabel } from "@/lib/format";
import { MIN_SALARY_OPTIONS, type MatchOptions } from "@/lib/match/options";
import { LEVELS, type Level, type Preferences, type SeniorityGuess } from "@/lib/match/types";

type Props = {
  prefs: Preferences;
  onChange: (p: Preferences) => void;
  options: MatchOptions;
  guess: SeniorityGuess | null;
};

export function PreferencesForm({ prefs, onChange, options, guess }: Props) {
  const set = (patch: Partial<Preferences>) => onChange({ ...prefs, ...patch });
  const toggleRole = (role: string) => set({ roles: prefs.roles.includes(role) ? prefs.roles.filter((r) => r !== role) : [...prefs.roles, role] });

  const auto = guess?.level ? `Auto: ${seniorityLabel(guess.level)}` : "Auto (from your CV)";
  return (
    <fieldset className="card p-4 sm:p-5">
      <legend className="sr-only">Preferences</legend>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">Preferences</h2>
        <p className="text-sm text-ink-3">Optional. They change the ranking live.</p>
      </div>

      <div className="mt-3">
        <p id="pref-roles" className="mb-1.5 text-xs font-medium text-ink-3">
          Target roles (pick any; they get a ranking boost)
        </p>
        <div className="flex flex-wrap gap-2" role="group" aria-labelledby="pref-roles">
          {options.roles.map((r) => (
            <button key={r.value} type="button" className="chip" aria-pressed={prefs.roles.includes(r.value)} onClick={() => toggleRole(r.value)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3 lg:grid-cols-1">
        <div>
          <label htmlFor="pref-sen" className="mb-1 block text-xs font-medium text-ink-3">
            Your seniority
          </label>
          <select id="pref-sen" className="field w-full text-ellipsis" value={prefs.seniority} onChange={(e) => set({ seniority: e.target.value as Level | "" })}>
            <option value="">{auto}</option>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {seniorityLabel(l)}
              </option>
            ))}
          </select>
          {guess && !prefs.seniority ? <p className="mt-1 text-xs text-ink-3">{guess.reason}.</p> : null}
        </div>
        <div>
          <label htmlFor="pref-region" className="mb-1 block text-xs font-medium text-ink-3">
            Region (keeps worldwide jobs too)
          </label>
          <select id="pref-region" className="field w-full text-ellipsis" value={prefs.region} onChange={(e) => set({ region: e.target.value })}>
            <option value="">Anywhere</option>
            {options.regions.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label} ({fmtInt(r.count)})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="pref-min" className="mb-1 block text-xs font-medium text-ink-3">
            Min. salary (USD / yr)
          </label>
          <select id="pref-min" className="field w-full text-ellipsis" value={prefs.minSalary} onChange={(e) => set({ minSalary: Number(e.target.value) })}>
            <option value={0}>No minimum</option>
            {MIN_SALARY_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {fmtInt(m)}+
              </option>
            ))}
          </select>
          {prefs.minSalary > 0 && !prefs.onlySalary ? <p className="mt-1 text-xs text-ink-3">Jobs with no stated salary are kept.</p> : null}
        </div>
      </div>

      <label className="mt-3 flex min-h-10 cursor-pointer items-center gap-2 text-sm text-ink-2">
        <input type="checkbox" className="h-4 w-4 accent-[var(--s1)]" checked={prefs.onlySalary} onChange={(e) => set({ onlySalary: e.target.checked })} />
        Only jobs that state a salary
      </label>
    </fieldset>
  );
}
