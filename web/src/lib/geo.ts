/**
 * "Where you can work from": types for `geo.json` (PLAN.md section 6), the open-to rule and the
 * sentences built from it. Pure and dependency-free so client components and tests can import it;
 * the build-time loader is in `geo-data.ts`.
 *
 * The rule is the same one `radar.geo.open_via` applies in Python, and `geo.fixtures.json`
 * (computed by Python) keeps the two in step. A posting is OPEN TO location L when its canonical
 * `remote_regions` contain
 *   - "worldwide" (not counted for the sanctioned places in `geo.sanctioned`: Cuba, Iran, North Korea,
 *     Syria ...; only a posting that names them is open to them); or
 *   - L itself; or
 *   - a macro region that contains L (EU, EEA, Europe and EMEA contain Estonia). When L is itself
 *     a macro region the posting must cover all of it ("Europe" is open to Europe and EMEA, not to a
 *     posting that lists only Germany and France).
 * A posting without any region is "unknown" and never open.
 */

import { fmtInt, fmtShare, fmtUsdShort, roleLabel } from "./format";

export type Memberships = Record<string, readonly string[]>;

export type GeoLocation = {
  location: string;
  kind: "country" | "macro";
  /** Listed postings open to the location (worldwide ones included). */
  open_jobs: number;
  /** open_jobs / listed postings, 0..1. */
  open_share: number;
  /** Open postings with role "data". */
  data_jobs: number;
  /** Open postings that list "worldwide". */
  worldwide_jobs: number;
  /** Open postings that do not list "worldwide": they name the location or a region containing it. */
  explicit_jobs: number;
  /** Median advertised annual USD of open postings; null below 5 salaried postings. */
  median_salary_usd: number | null;
  salary_n: number;
  /** Skills of the open data postings (at least 3 postings each), share of those postings. */
  top_skills: { slug: string; name: string; share: number }[];
  by_role: Record<string, number>;
};

export type RegionMixRow = { group: string; n: number; share: number; median_salary_usd: number | null };

export type GeoSummary = {
  listed_jobs: number;
  data_jobs: number;
  worldwide_jobs: number;
  worldwide_data_jobs: number;
  us_only_jobs: number;
  us_only_data_jobs: number;
  unknown_jobs: number;
  unknown_data_jobs: number;
};

export type Geo = {
  version: number;
  memberships: Memberships;
  macros: string[];
  /** Comprehensively sanctioned places: "worldwide" does not open a posting to them. */
  sanctioned?: string[];
  by_location: GeoLocation[];
  region_mix: RegionMixRow[];
  unknown_jobs: number;
  summary?: GeoSummary;
  unmapped?: { region: string; n: number }[];
};

// ------------------------------------------------------------------ the rule

export type OpenVia = "worldwide" | "explicit";

const WORLDWIDE = "worldwide";

const setCache = new WeakMap<object, Map<string, Set<string>>>();

/** Membership lists as sets, built once per `memberships` object. A Map, so a region called "constructor" is not special. */
function membershipSets(memberships: Memberships): Map<string, Set<string>> {
  let sets = setCache.get(memberships);
  if (!sets) {
    sets = new Map(Object.entries(memberships).map(([macro, members]) => [macro, new Set(members)]));
    setCache.set(memberships, sets);
  }
  return sets;
}

/**
 * How a posting with canonical `regions` is open to `location`: "worldwide" when it lists worldwide,
 * "explicit" when it names the location or a macro region covering it, null when it is not open
 * (including a posting without regions).
 */
export function openVia(
  regions: readonly string[] | null | undefined,
  location: string,
  memberships: Memberships,
  sanctioned: readonly string[] = [],
): OpenVia | null {
  const values = regions ?? [];
  if (!sanctioned.includes(location) && values.some((r) => r.toLowerCase() === WORLDWIDE)) return "worldwide";
  const sets = membershipSets(memberships);
  const target = sets.get(location); // undefined when the location is a country
  for (const region of values) {
    if (region === location) return "explicit";
    const covering = sets.get(region);
    if (!covering) continue;
    if (!target) {
      if (covering.has(location)) return "explicit";
    } else if ([...target].every((c) => covering.has(c))) {
      return "explicit";
    }
  }
  return null;
}

/** The open-to rule for one posting. */
export function isOpenTo(job: { remote_regions: readonly string[] }, location: string, memberships: Memberships, sanctioned: readonly string[] = []): boolean {
  return openVia(job.remote_regions, location, memberships, sanctioned) !== null;
}

// ------------------------------------------------------------------ pickers and rankings

export type LocationOption = { value: string; label: string; count: number };
export type LocationOptions = { regions: LocationOption[]; countries: LocationOption[] };

/** Select options: regions and countries, each alphabetical, with how many postings are open to them. */
export function locationOptions(rows: readonly Pick<GeoLocation, "location" | "kind" | "open_jobs">[]): LocationOptions {
  const make = (kind: GeoLocation["kind"]) =>
    rows
      .filter((r) => r.kind === kind)
      .map((r) => ({ value: r.location, label: r.location, count: r.open_jobs }))
      .sort((a, b) => a.label.localeCompare(b.label));
  return { regions: make("macro"), countries: make("country") };
}

/** Countries or regions ranked by open data postings (then all open postings, then name). */
export function rankLocations(rows: readonly GeoLocation[], kind: GeoLocation["kind"]): GeoLocation[] {
  return rows
    .filter((r) => r.kind === kind && r.open_jobs > 0)
    .sort((a, b) => b.data_jobs - a.data_jobs || b.open_jobs - a.open_jobs || a.location.localeCompare(b.location));
}

export function findLocation(rows: readonly GeoLocation[], name: string): GeoLocation | undefined {
  return name ? rows.find((r) => r.location === name) : undefined;
}

export const REGION_GROUP_LABEL: Record<string, string> = {
  us_canada: "United States or Canada",
  europe: "Europe",
  latam: "Latin America",
  apac: "Asia-Pacific",
  worldwide: "Worldwide",
  other_or_mixed: "Other or mixed",
  unknown: "Not stated",
};

export const regionGroupLabel = (group: string) => REGION_GROUP_LABEL[group] ?? group;

// ------------------------------------------------------------------ sentences

const pct = (n: number, total: number) => fmtShare(total ? n / total : 0);

/**
 * The page's lead: how much of "remote" is closed to anyone outside the United States. Falls back to
 * a plainer sentence when the summary block is missing (an older snapshot).
 */
export function leadSentence(geo: Pick<Geo, "summary" | "by_location" | "unknown_jobs">): string {
  const s = geo.summary;
  if (!s || s.listed_jobs === 0) return "Many remote postings are limited to one country or region. Pick where you live to see how many are open to you.";
  const europe = findLocation(geo.by_location, "Europe");
  const europeBit = europe ? ` A candidate anywhere in Europe can apply to ${pct(europe.open_jobs, s.listed_jobs)} of them.` : "";
  return `${pct(s.us_only_jobs, s.listed_jobs)} of the ${fmtInt(s.listed_jobs)} remote postings are open to the United States only. Only ${pct(s.worldwide_jobs, s.listed_jobs)} say worldwide, and ${pct(s.unknown_jobs, s.listed_jobs)} do not say at all.${europeBit}`;
}

/** What the chosen location means in numbers. `listed` is the number of listed postings. */
export function selectionSentence(row: GeoLocation, listed: number): string {
  const where = row.kind === "macro" ? `anywhere in ${row.location}` : `in ${row.location}`;
  if (row.open_jobs === 0) return `No listed remote posting is open to applicants ${where}.`;
  let text = `${fmtInt(row.open_jobs)} of ${fmtInt(listed)} remote postings (${fmtShare(row.open_share)}) are open to applicants ${where}`;
  text += row.data_jobs ? `, ${fmtInt(row.data_jobs)} of them ${row.data_jobs === 1 ? "a data role" : "data roles"}.` : ", none of them a data role.";
  if (row.worldwide_jobs === row.open_jobs) text += " All of them say worldwide; none names your location or a region containing it.";
  else if (row.worldwide_jobs) text += ` ${pct(row.worldwide_jobs, row.open_jobs)} of the open postings say worldwide; the rest name ${row.kind === "macro" ? "this region or a larger one" : "your country or a region that contains it"}.`;
  else text += ` None says worldwide; every one names ${row.kind === "macro" ? "this region or a larger one" : "your country or a region that contains it"}.`;
  return text;
}

/** Role counts of the open postings, largest first, as `[label, n]`. */
export function roleCounts(row: GeoLocation, limit = 6): [string, number][] {
  return Object.entries(row.by_role)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([role, n]) => [roleLabel(role), n]);
}

export function payLabel(row: GeoLocation): { value: string; sub: string } {
  if (row.median_salary_usd == null) {
    return { value: "n/a", sub: row.salary_n ? `only ${row.salary_n} open postings state pay (5 needed)` : "no open posting states pay" };
  }
  return { value: fmtUsdShort(row.median_salary_usd), sub: `median of ${fmtInt(row.salary_n)} postings that state pay` };
}

/** Link to the job explorer, filtered to postings open to `location`. */
export function jobsHref(location: string, extra: Record<string, string> = {}): string {
  const sp = new URLSearchParams({ open_to: location, ...extra });
  return `/jobs?${sp.toString()}`;
}
