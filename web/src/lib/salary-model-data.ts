import "server-only";
import fs from "node:fs";
import path from "node:path";
import { parseSalaryModel, type SalaryModelDoc } from "./salary-model";

/**
 * Build-time loader for `salary_model.json` (PLAN.md section 6). The file is absent before the first pipeline
 * run that writes it and may be the small "not enough salaried postings" document: the loader returns null for a
 * missing or malformed file and the unavailable document as is, so pages show an empty state instead of failing
 * the build. Use `hasModel` from `salary-model.ts` to tell a usable model from the unavailable document.
 */
let cached: SalaryModelDoc | null | undefined;

export function getSalaryModel(): SalaryModelDoc | null {
  if (cached !== undefined) return cached;
  try {
    cached = parseSalaryModel(JSON.parse(fs.readFileSync(path.join(process.cwd(), "public", "data", "salary_model.json"), "utf8")));
  } catch {
    cached = null;
  }
  return cached;
}
