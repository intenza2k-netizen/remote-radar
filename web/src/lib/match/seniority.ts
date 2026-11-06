import { YEARS_TO_LEVEL } from "./constants";
import { seniorityLabel } from "@/lib/format";
import type { Level, SeniorityGuess } from "./types";

const ROLE_NOUNS =
  "engineer|developer|analyst|scientist|designer|manager|consultant|specialist|architect|marketer|recruiter|writer|researcher|accountant|administrator|coordinator|programmer|strategist|officer|producer|editor|technician|representative|executive|associate|director|owner";

// Order matters: first pattern that matches wins within one text position, higher levels listed first.
const TITLE_PATTERNS: { re: RegExp; level: Level }[] = [
  { re: new RegExp(`\\b(principal|staff|distinguished)\\s+(?:[\\w&/.-]+\\s+){0,2}(?:${ROLE_NOUNS})\\b`, "i"), level: "principal" },
  { re: /\b(?:head of|director of|vp of|vice president|chief)\b|\b(?:team|tech|technical) lead\b/i, level: "lead" },
  { re: new RegExp(`\\b(?:lead|head)\\s+(?:[\\w&/.-]+\\s+){0,2}(?:${ROLE_NOUNS})\\b`, "i"), level: "lead" },
  { re: new RegExp(`\\b(?:senior|sr\\.?)\\s+(?:[\\w&/.-]+\\s+){0,2}(?:${ROLE_NOUNS})\\b`, "i"), level: "senior" },
  { re: new RegExp(`\\b(?:intern|internship|working student|trainee)\\b`, "i"), level: "intern" },
  { re: new RegExp(`\\b(?:junior|jr\\.?|graduate|entry[- ]level)\\s+(?:[\\w&/.-]+\\s+){0,2}(?:${ROLE_NOUNS})\\b`, "i"), level: "junior" },
];

const EDU_LINE = /\b(bachelor|master|msc|bsc|b\.sc|m\.sc|mba|ph\.?d|degree|university|college|school|diploma|education|gpa|thesis|certificat\w*|course|bootcamp)\b/i;

export function inferSeniority(text: string, nowYear = new Date().getFullYear()): SeniorityGuess {
  const years = estimateYears(text, nowYear);

  // Title words: look at the first lines (headline / most recent role) before the rest.
  const head = text.slice(0, 400);
  let titled: { level: Level; phrase: string } | null = null;
  // Titles further down are usually older roles ("Junior Analyst" in 2019), so they only count
  // when the CV gives no years of experience at all.
  for (const scope of years == null ? [head, text] : [head]) {
    for (const { re, level } of TITLE_PATTERNS) {
      const m = re.exec(scope);
      if (m && (!titled || levelRank(level) > levelRank(titled.level))) {
        titled = { level, phrase: m[0].trim().replace(/\s+/g, " ").slice(0, 40) };
      }
    }
    if (titled) break;
  }
  if (titled) {
    // A lone "intern" in the work history of an experienced person is not their level.
    if ((titled.level === "intern" && years != null && years >= 3) || (titled.level === "junior" && years != null && years >= 5)) titled = null;
  }
  if (titled) return { level: titled.level, years, reason: `Title in your CV: "${titled.phrase}"` };

  if (years != null) {
    let level: Level = "junior";
    for (const t of YEARS_TO_LEVEL) if (years >= t.minYears) level = t.level;
    return { level, years, reason: `${formatYears(years)} of experience` };
  }
  return { level: null, years: null, reason: "No years of experience or seniority title found" };
}

function levelRank(l: Level): number {
  return ["intern", "junior", "mid", "senior", "lead", "principal"].indexOf(l);
}

function formatYears(y: number): string {
  return `${Number.isInteger(y) ? y : y.toFixed(1)} year${y === 1 ? "" : "s"}`;
}

/** Stated years ("5+ years of experience") first, else the span covered by work-history date ranges. */
export function estimateYears(text: string, nowYear: number): number | null {
  let stated = 0;
  for (const m of text.matchAll(/\b(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b(?:\s+of)?(?:\s+(?:professional|relevant|hands-on|industry|total|working))?\s*(?:experience|exp\b|in\b|as\b|working)/gi)) {
    const n = Number(m[1]);
    if (n > stated && n <= 45) stated = n;
  }
  if (stated > 0) return stated;

  const ranges: [number, number][] = [];
  const re = /\b((?:19|20)\d{2})\s*(?:[-–—]|to)\s*((?:19|20)\d{2}|present|current|now|today|ongoing)\b/gi;
  for (const line of text.split(/\r?\n/)) {
    if (EDU_LINE.test(line)) continue;
    for (const m of line.matchAll(re)) {
      const a = Number(m[1]);
      const b = /^\d/.test(m[2]) ? Number(m[2]) : nowYear;
      if (b >= a && b <= nowYear + 1 && a >= 1970) ranges.push([a, b]);
    }
  }
  if (!ranges.length) return null;
  ranges.sort((x, y) => x[0] - y[0]);
  let total = 0;
  let [cs, ce] = ranges[0];
  for (const [s, e] of ranges.slice(1)) {
    if (s <= ce) ce = Math.max(ce, e);
    else {
      total += ce - cs;
      [cs, ce] = [s, e];
    }
  }
  total += ce - cs;
  return total > 0 ? total : null;
}

export function describeLevel(level: Level | null): string {
  return level ? seniorityLabel(level) : "Not detected";
}
