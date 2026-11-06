"use client";

import { SkillPicker, type PickerOption } from "@/components/skill-picker";
import type { DetectedSkill } from "@/lib/match/types";

type Props = {
  skills: string[];
  names: Record<string, string>;
  mentions: Map<string, DetectedSkill>;
  options: PickerOption[];
  onAdd: (slug: string) => void;
  onRemove: (slug: string) => void;
  onReset: () => void;
  edited: boolean;
};

export function SkillChips({ skills, names, mentions, options, onAdd, onRemove, onReset, edited }: Props) {
  return (
    <section className="card p-4 sm:p-5" aria-labelledby="skills-h">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="skills-h" className="text-base font-semibold">
          Skills found in your CV
        </h2>
        {edited ? (
          <button type="button" className="text-sm text-accent underline underline-offset-4" onClick={onReset}>
            Reset to detected
          </button>
        ) : null}
      </div>
      <p className="mt-1 text-sm text-ink-3">Remove anything that is wrong, add anything that was missed. Matching updates as you go.</p>

      {skills.length ? (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Detected skills">
          {skills.map((s) => {
            const m = mentions.get(s);
            const label = names[s] ?? s;
            return (
              <li key={s}>
                <span
                  className="inline-flex items-center gap-1 rounded-full border border-line-strong bg-surface py-1 pl-3 pr-1 text-sm"
                  title={m ? `Mentioned ${m.mentions} time${m.mentions === 1 ? "" : "s"} in your CV` : "Added by you"}
                >
                  <span className="text-ink">{label}</span>
                  <button
                    type="button"
                    className="grid h-6 w-6 place-items-center rounded-full text-ink-3 hover:bg-surface-2 hover:text-ink"
                    aria-label={`Remove ${label}`}
                    onClick={() => onRemove(s)}
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
      ) : (
        <p className="mt-3 rounded-lg border border-dashed border-line-strong p-4 text-sm text-ink-2">
          No known skills were detected. Add the ones you have below; the ranking then also uses seniority, role and the language model.
        </p>
      )}

      <div className="mt-3 max-w-sm">
        <p className="mb-1 text-xs font-medium text-ink-3">Add a skill</p>
        <SkillPicker label="Add a skill you have" options={options} selected={skills} onPick={onAdd} placeholder="Search skills..." />
      </div>
    </section>
  );
}
