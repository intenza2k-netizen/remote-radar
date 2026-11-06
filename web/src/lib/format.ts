/** Formatting helpers. Pure, locale- and timezone-pinned so SSR and client agree. */

const LOCALE = "en-US";

const intFmt = new Intl.NumberFormat(LOCALE);
export const fmtInt = (n: number) => intFmt.format(Math.round(n));

/** 0.3123 -> "31%", 0.043 -> "4.3%". */
export function fmtShare(share: number): string {
  const pct = share * 100;
  if (pct >= 9.95 || pct === 0) return `${Math.round(pct)}%`;
  return `${pct.toFixed(1)}%`;
}

/** Percentage-point change, signed: 2.34 -> "+2.3 pp". */
export function fmtPP(pp: number | null | undefined): string {
  if (pp == null) return "n/a";
  const v = Math.round(pp * 10) / 10;
  if (v === 0) return "0.0 pp";
  return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(1)} pp`;
}

/** 128400 -> "$128k". */
export function fmtUsdShort(n: number | null | undefined): string {
  if (n == null) return "n/a";
  if (n >= 1000) return `$${Math.round(n / 1000)}k`;
  return `$${Math.round(n)}`;
}

export function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "n/a";
  return `$${intFmt.format(Math.round(n))}`;
}

const CURRENCY_SYMBOL: Record<string, string> = { USD: "$", EUR: "€", GBP: "£", CAD: "CA$", AUD: "A$", CHF: "CHF " };

const PERIOD_LABEL: Record<string, string> = { year: "yr", month: "mo", hour: "hr", week: "wk", day: "day" };

/** Original-currency salary range: "$120k–$150k / yr" or "$55–$70 / hr". */
export function fmtSalaryRange(s: { min: number | null; max: number | null; currency: string; period: string }): string {
  const sym = CURRENCY_SYMBOL[s.currency] ?? `${s.currency} `;
  const one = (n: number) => {
    if (s.period === "year" && n >= 1000) return `${sym}${Math.round(n / 1000)}k`;
    if (n >= 10000) return `${sym}${Math.round(n / 1000)}k`;
    return `${sym}${intFmt.format(Math.round(n))}`;
  };
  const per = PERIOD_LABEL[s.period] ?? s.period;
  const { min, max } = s;
  if (min != null && max != null && min !== max) return `${one(min)}–${one(max)} / ${per}`;
  const v = max ?? min;
  return v == null ? "n/a" : `${one(v)} / ${per}`;
}

const dateShort = new Intl.DateTimeFormat(LOCALE, { month: "short", day: "numeric", timeZone: "UTC" });
const dateLong = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const dateTime = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" });

export const fmtDateShort = (iso: string) => dateShort.format(new Date(iso));
export const fmtDateLong = (iso: string) => dateLong.format(new Date(iso));
export const fmtDateTime = (iso: string) => dateTime.format(new Date(iso));

/** "2026-W45" -> UTC Monday of that ISO week. */
export function isoWeekStart(week: string): Date {
  const m = /^(\d{4})-W(\d{2})$/.exec(week);
  if (!m) return new Date(NaN);
  const year = Number(m[1]);
  const w = Number(m[2]);
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const dow = jan4.getUTCDay() || 7;
  const mondayWeek1 = new Date(jan4.getTime() - (dow - 1) * 86400000);
  return new Date(mondayWeek1.getTime() + (w - 1) * 7 * 86400000);
}

/** "2026-W45" -> "Nov 2" (week commencing). */
export function fmtWeek(week: string): string {
  const d = isoWeekStart(week);
  return Number.isNaN(d.getTime()) ? week : dateShort.format(d);
}

export function relativeTime(fromIso: string, nowMs: number): string {
  const diff = Math.max(0, nowMs - new Date(fromIso).getTime());
  const min = Math.round(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? "" : "s"} ago`;
  const day = Math.round(hr / 24);
  if (day < 14) return `${day} day${day === 1 ? "" : "s"} ago`;
  const wk = Math.round(day / 7);
  if (wk < 9) return `${wk} weeks ago`;
  const mo = Math.round(day / 30);
  return `${mo} months ago`;
}

export const CATEGORY_LABEL: Record<string, string> = {
  language: "Language",
  framework: "Framework",
  cloud: "Cloud",
  data: "Data",
  devops: "DevOps",
  database: "Database",
  ai_ml: "AI / ML",
  tool: "Tool",
  design: "Design",
  business: "Business",
  other: "Other",
};

export function categoryLabel(cat: string): string {
  return CATEGORY_LABEL[cat] ?? humanize(cat);
}

/** Fallback for any enum-like value without a curated label: "some_value" -> "Some value". */
export function humanize(s: string): string {
  const t = s.replace(/[_-]+/g, " ").trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : s;
}

export function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Ordered levels; "unspecified" is not a level and always sorts last. */
export const SENIORITY_ORDER = ["intern", "junior", "mid", "senior", "lead", "principal"];

const SENIORITY_LABEL: Record<string, string> = {
  intern: "Intern",
  junior: "Junior",
  mid: "Mid-level",
  senior: "Senior",
  lead: "Lead",
  principal: "Principal",
  unspecified: "Unspecified",
};

export function seniorityLabel(s: string | null | undefined): string {
  if (!s) return "Unspecified";
  return SENIORITY_LABEL[s] ?? humanize(s);
}

export function seniorityRank(s: string | null | undefined): number {
  const i = s ? SENIORITY_ORDER.indexOf(s) : -1;
  return i === -1 ? 99 : i; // "unspecified" and unknown values sort last
}

const EMPLOYMENT_LABEL: Record<string, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  unspecified: "Unspecified",
};
export const employmentLabel = (s: string | null | undefined) => (s ? (EMPLOYMENT_LABEL[s] ?? humanize(s)) : "Unspecified");

const ROLE_LABEL: Record<string, string> = {
  software_engineering: "Software engineering",
  data: "Data & analytics",
  devops_sre: "DevOps / SRE",
  product: "Product",
  design: "Design",
  marketing: "Marketing",
  sales: "Sales",
  support: "Support",
  management: "Management",
  other: "Other",
};
export const roleLabel = (s: string | null | undefined) => (s ? (ROLE_LABEL[s] ?? humanize(s)) : "Other");

/**
 * What to show for a skill slug. Uses the published name; for a slug nobody named (older snapshots)
 * the words of the slug are title-cased rather than shown as "business-strategy".
 */
export function skillLabel(slug: string, names?: Record<string, string>): string {
  return names?.[slug] ?? titleCase(slug.replace(/-/g, " "));
}

/** Regions are short free strings ("worldwide", "US", "EU", "Germany"); only all-lowercase values are capitalised. */
export const regionLabel = (s: string) => (s === s.toLowerCase() ? humanize(s) : s);
