import { fmtPP, fmtShare, fmtUsdShort } from "./format";
import type { Job, Meta, Skill } from "./types";
import { windowClause } from "./weeks";

/** Categories that read as "skills a candidate learns" (excludes soft/business filler). */
export const TECHNICAL = new Set(["language", "framework", "cloud", "data", "devops", "database", "ai_ml", "tool"]);

export type Headline = {
  /** Subject skill, e.g. Python. */
  skill: Skill;
  /** Plain-text sentence, used for metadata. */
  text: string;
  riser: Skill | null;
  medianSalary: number | null;
};

/** Window length as words: 56 days -> "8 weeks". */
export function windowLabel(days: number): string {
  if (days % 7 === 0) return `${days / 7} weeks`;
  return `${days} days`;
}

export function medianSalaryOf(jobs: Job[]): number | null {
  const v = jobs.flatMap((j) => (j.salary ? [j.salary.annual_usd_mid] : [])).sort((a, b) => a - b);
  if (!v.length) return null;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

export function buildHeadline(meta: Meta, skills: Skill[], medianSalary: number | null): Headline | null {
  const technical = skills.filter((s) => TECHNICAL.has(s.category));
  const top = [...technical].sort((a, b) => b.share - a.share)[0] ?? skills[0];
  if (!top) return null;
  const minCount = Math.max(10, Math.round(meta.totals.jobs * 0.02));
  const riser =
    [...skills]
      .filter((s) => s.change_4w != null && s.count >= minCount && TECHNICAL.has(s.category))
      .sort((a, b) => (b.change_4w ?? 0) - (a.change_4w ?? 0))[0] ?? null;

  const text = `${top.name} appears in ${fmtShare(top.share)} of remote job postings ${windowClause(meta)}${
    riser ? `; ${riser.name} is climbing fastest (${fmtPP(riser.change_4w)})` : ""
  }${medianSalary ? `. Median advertised salary: ${fmtUsdShort(medianSalary)}` : ""}.`;
  return { skill: top, text, riser, medianSalary };
}

export function topSkills(skills: Skill[], n: number): Skill[] {
  return [...skills].sort((a, b) => b.count - a.count).slice(0, n);
}
