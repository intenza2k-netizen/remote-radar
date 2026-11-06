import type { ArchetypesDoc } from "@/lib/archetypes";
import { locationOptions, type Geo, type LocationOption, type Memberships } from "@/lib/geo";
import { hasModel, type SalaryModel, type SalaryModelDoc } from "@/lib/salary-model";

/**
 * The slice of the v4 snapshot files (`archetypes.json`, `salary_model.json`, `geo.json`) the matcher needs,
 * trimmed on the server before it is passed to the client component: no centroids, no 2-D plot coordinates,
 * no per-location skill lists. Each part is null when its file is missing, so the matcher simply leaves that
 * feature out and everything else keeps working. Type-only imports from `archetypes.ts` (it reads from disk).
 */
export type MatchExtras = {
  /** Job type (archetype) of each active data posting, by job id, with display names. */
  jobTypes: { names: Record<string, string>; assignment: Record<string, string> } | null;
  salaryModel: SalaryModel | null;
  geo: { memberships: Memberships; sanctioned: string[]; regions: LocationOption[]; countries: LocationOption[] } | null;
};

export function buildExtras(archetypes: ArchetypesDoc | null, salary: SalaryModelDoc | null, geo: Geo | null): MatchExtras {
  const jobTypes =
    archetypes && archetypes.archetypes.length && archetypes.points.length
      ? {
          names: Object.fromEntries(archetypes.archetypes.map((a) => [a.id, a.name])),
          assignment: Object.fromEntries(archetypes.points.map((p) => [p.id, p.a])),
        }
      : null;
  const options = geo ? locationOptions(geo.by_location) : null;
  return {
    jobTypes,
    salaryModel: hasModel(salary) ? salary : null,
    geo: geo && options && geo.memberships ? { memberships: geo.memberships, sanctioned: geo.sanctioned ?? [], regions: options.regions, countries: options.countries } : null,
  };
}
