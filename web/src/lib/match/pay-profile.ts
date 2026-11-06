import { DEFAULT_REGION_GROUP, regionGroupForLocation } from "./location";
import type { Level } from "./types";
import { predictPay, regionGroupLabel, type PayEstimate, type PayInput, type RegionGroup, type SalaryModel } from "@/lib/salary-model";

/**
 * Estimated pay for your profile. This file only assembles the model's input from what the matcher already knows
 * (target role, seniority, location, CV skills); the model and the profile rule (at most `profile_max_skills`
 * skills, picked by market frequency, never by coefficient) are `predictPay` in `lib/salary-model.ts`.
 */

/** A region group with fewer salaried postings than this in the training data gets a warning. */
export const THIN_REGION_POSTINGS = 30;

export type PayProfile = {
  input: PayInput;
  role: string;
  /** True when no target role was picked and the estimate uses the data role. */
  roleIsDefault: boolean;
  seniority: Level;
  regionGroup: RegionGroup;
  /** Where the region group came from: the location you chose, or the default because you chose none / it is in no group. */
  regionSource: "location" | "default" | "unmapped";
};

/**
 * The preferred role: data when nothing is picked or data is among the picks (the site is about data roles),
 * otherwise the first pick. Null seniority (no title or years in the CV and none chosen) gives no profile: the
 * model's "unspecified" level is postings that state none, which says nothing about you.
 */
export function buildPayProfile(args: { roles: readonly string[]; level: Level | null; location: string; skills: readonly string[] }): PayProfile | null {
  if (!args.level) return null;
  const roleIsDefault = args.roles.length === 0;
  const role = roleIsDefault || args.roles.includes("data") ? "data" : args.roles[0];
  const fromLocation = regionGroupForLocation(args.location);
  const regionGroup = fromLocation ?? DEFAULT_REGION_GROUP;
  return {
    input: { role, seniority: args.level, regionGroup, skills: args.skills },
    role,
    roleIsDefault,
    seniority: args.level,
    regionGroup,
    regionSource: fromLocation ? "location" : args.location ? "unmapped" : "default",
  };
}

export type PayResult = {
  estimate: PayEstimate;
  profile: PayProfile;
  /** Salaried postings behind the region group in the training data. */
  regionPostings: number;
  /** Set when the region group rests on fewer than THIN_REGION_POSTINGS salaried postings. */
  thinRegion: boolean;
  /** Your skills the model counted, and how many of yours it did not (not modelled, or beyond the profile cap). */
  skillsCounted: string[];
  skillsLeftOut: number;
};

export function estimateForProfile(model: SalaryModel, profile: PayProfile, cvSkills: readonly string[]): PayResult {
  const estimate = predictPay(model, profile.input);
  const regionPostings = model.levels.region_group[profile.regionGroup] ?? 0;
  const distinct = new Set(cvSkills);
  return {
    estimate,
    profile,
    regionPostings,
    thinRegion: regionPostings < THIN_REGION_POSTINGS,
    skillsCounted: estimate.used_skills,
    skillsLeftOut: distinct.size - estimate.used_skills.length,
  };
}

/** The region group and why it is that one, as a phrase: "Europe (from Estonia)". */
export function regionText(profile: PayProfile, location: string): string {
  const label = regionGroupLabel(profile.regionGroup);
  if (profile.regionSource === "location") return `${label} (from ${location})`;
  if (profile.regionSource === "unmapped") return `${label} (the default: ${location} is in none of the model's region groups)`;
  return `${label} (the default: choose where you can work from to change it)`;
}
