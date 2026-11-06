import "server-only";
import fs from "node:fs";
import path from "node:path";
import type { EvalData, Job, Meta, Role, SalaryData, Skill } from "./types";

/**
 * Build-time loaders for the published snapshot.
 *
 * Synchronous `fs` reads are "predictable" I/O, so every page that uses them is
 * prerendered into the static shell (no runtime fetching, no API routes).
 * Results are memoised per process so a build reads each file once.
 */
const DATA_DIR = path.join(process.cwd(), "public", "data");

const cache = new Map<string, unknown>();

function readJson<T>(file: string): T {
  const hit = cache.get(file);
  if (hit !== undefined) return hit as T;
  const raw = fs.readFileSync(path.join(DATA_DIR, file), "utf8");
  const parsed = JSON.parse(raw) as T;
  cache.set(file, parsed);
  return parsed;
}

function readOptionalJson<T>(file: string): T | null {
  try {
    return readJson<T>(file);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw err;
  }
}

export function getMeta(): Meta {
  return readJson<Meta>("meta.json");
}

export function getSkills(): Skill[] {
  return readJson<Skill[]>("skills.json");
}

export function getSkill(slug: string): Skill | undefined {
  return getSkills().find((s) => s.slug === slug);
}

/**
 * Display name for every skill slug in the snapshot: the published `meta.skill_names` (all slugs that
 * appear in jobs.json) overlaid with the `skills.json` names. Pages should render skill slugs only
 * through this map (see `skillLabel`), never the raw slug.
 */
export function getSkillNames(): Record<string, string> {
  const names: Record<string, string> = { ...(getMeta().skill_names ?? {}) };
  for (const s of getSkills()) names[s.slug] = s.name;
  return names;
}

export function getSkillIndex(): Map<string, Skill> {
  return new Map(getSkills().map((s) => [s.slug, s]));
}

export function getRoles(): Role[] {
  return readJson<Role[]>("roles.json");
}

export function getSalary(): SalaryData {
  return readJson<SalaryData>("salary.json");
}

export function getJobs(): Job[] {
  return readJson<Job[]>("jobs.json");
}

/** `eval.json` is absent before the first eval run; callers must handle null. */
export function getEval(): EvalData | null {
  return readOptionalJson<EvalData>("eval.json");
}
