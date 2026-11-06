import "server-only";
import fs from "node:fs";
import path from "node:path";
import type { Geo } from "./geo";

/**
 * Build-time loader for `geo.json` (PLAN.md section 6). The file is absent before the first
 * pipeline run that writes it, or when it is malformed: the loader then returns null and the pages
 * show an empty state (or leave the "open to" filter out) instead of failing the build.
 */
let cached: Geo | null | undefined;

export function getGeo(): Geo | null {
  if (cached !== undefined) return cached;
  try {
    const parsed = JSON.parse(fs.readFileSync(path.join(process.cwd(), "public", "data", "geo.json"), "utf8")) as Geo;
    cached = Array.isArray(parsed.by_location) && parsed.by_location.length > 0 && parsed.memberships ? parsed : null;
  } catch {
    cached = null;
  }
  return cached;
}
