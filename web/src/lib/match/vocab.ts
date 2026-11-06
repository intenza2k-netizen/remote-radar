import { STRICT_CONTEXT_CHARS } from "./constants";
import type { DetectedSkill, VocabEntry } from "./types";

/**
 * Skill detection: match the published skill vocabulary against CV text.
 *
 * - Plain patterns match case-insensitively on word boundaries that understand
 *   symbols ("c++", "c#", "node.js", ".net", "ci/cd"); spaces and hyphens inside a
 *   pattern are interchangeable ("machine learning" = "machine-learning").
 * - Longer patterns win over shorter ones at the same position, and matched text is
 *   consumed ("react native" does not also count as "react").
 * - `strict` patterns ("go", "r", "c", "ai", "excel", ...) are ambiguous words. They are
 *   accepted only when the CV spells them the way the skill is spelled (Go, R, AI, Excel,
 *   never "go" or "excel" in prose) AND the text around them looks like a skill mention:
 *   a programming/statistics context word, or (for real English words) a neighbouring
 *   skill such as "SQL, Excel, Tableau".
 */

export type CompiledVocab = {
  entries: Map<string, VocabEntry>;
  loose: RegExp | null;
  looseSlug: Map<string, string>;
  strict: RegExp | null;
  /** normalised pattern -> [slug, original lowercase pattern] */
  strictSlug: Map<string, [string, string]>;
};

const SEP = "[\\s\\-–—]+";
const WORD = "\\p{L}\\p{N}_";

function normKey(s: string): string {
  return s.toLowerCase().replace(/[\s\-–—]+/g, " ").trim();
}

function escapeChar(c: string): string {
  return /[.*+?^${}()|[\]\\\/]/.test(c) ? `\\${c}` : c;
}

function patternSource(pattern: string): string {
  const p = pattern.trim().toLowerCase();
  let out = "";
  let i = 0;
  while (i < p.length) {
    const c = p[i];
    if (/[\s\-–—]/.test(c)) {
      while (i < p.length && /[\s\-–—]/.test(p[i])) i++;
      out += SEP;
      continue;
    }
    out += escapeChar(c);
    i++;
  }
  return out;
}

function buildRegex(patterns: string[]): RegExp | null {
  if (!patterns.length) return null;
  const sorted = [...new Set(patterns)].sort((a, b) => b.length - a.length);
  const body = sorted.map(patternSource).join("|");
  // Lookbehind: not glued to a preceding letter/digit. Lookahead: not followed by a letter/digit,
  // and not by "++" or "#" (so "c" never matches inside "c++" / "c#").
  return new RegExp(`(?<![${WORD}])(?:${body})(?![${WORD}])(?!\\+\\+|#)`, "giu");
}

/**
 * Which patterns need the strict rules. The pipeline lists them per skill in `strict_patterns`
 * (Python's alias "py" is strict, "python" is not; for "go" the pattern "go" is, "golang" is not).
 * For older files without that list, fall back to a heuristic on `strict`: only short or bare-word
 * patterns of a strict skill are ambiguous.
 */
function isAmbiguous(pattern: string, v: VocabEntry): boolean {
  if (v.strict_patterns) return v.strict_patterns.some((p) => p.trim().toLowerCase() === pattern);
  if (!v.strict) return false;
  if (/[\s\-–—]/.test(pattern)) return false;
  return pattern.length <= 3 || pattern === v.slug || pattern === v.name.toLowerCase();
}

export function compileVocab(vocab: VocabEntry[]): CompiledVocab {
  const entries = new Map<string, VocabEntry>();
  const looseSlug = new Map<string, string>();
  const strictSlug = new Map<string, [string, string]>();
  for (const v of vocab) {
    entries.set(v.slug, v);
    for (const raw of v.patterns) {
      const p = raw.trim().toLowerCase();
      if (!p) continue;
      const key = normKey(p);
      if (isAmbiguous(p, v)) {
        if (!strictSlug.has(key)) strictSlug.set(key, [v.slug, p]);
      } else if (!looseSlug.has(key)) {
        looseSlug.set(key, v.slug);
      }
    }
  }
  return {
    entries,
    loose: buildRegex([...looseSlug.keys()]),
    looseSlug,
    strict: buildRegex([...strictSlug.keys()]),
    strictSlug,
  };
}

/** Fallback vocabulary built from `skills.json` when `skill_vocab.json` is unavailable. */
export function vocabFromSkills(skills: { slug: string; name: string; category: string }[]): VocabEntry[] {
  return skills.map((s) => {
    const name = s.name.toLowerCase();
    const patterns = [...new Set([name, s.slug.replace(/-/g, " ")])];
    return { slug: s.slug, name: s.name, category: s.category, patterns, strict: name.length <= 3 };
  });
}

const CONTEXT = new RegExp(
  "\\b(programming|languages?|code|coding|scripts?|scripting|software|developers?|engineers?|engineering|backend|back-end|" +
    "microservices?|concurrency|goroutines?|statistic\\w*|regression|ggplot\\w*|tidyverse|dplyr|shiny|rstudio|cran|packages|" +
    "machine learning|deep learning|models?|modell?ing|nlp|llms?|neural|pipelines?|analytics)\\b",
  "i",
);

// Stronger evidence for real English words ("React", "Excel", "Spring"): says the word is used as a tool.
const STRONG_CONTEXT =
  /\b(programming|code|coding|developers?|engineers?|engineering|software|front-?end|back-?end|full-?stack|frameworks?|librar(?:y|ies)|stack|components|hooks|apps?|applications?|spreadsheets?|pivot|macros?)\b/i;

function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function caseOk(found: string, entry: VocabEntry, pattern: string): boolean {
  if (found === entry.name) return true;
  if (!/\s/.test(pattern) && pattern.length <= 3 && found === pattern.toUpperCase()) return true;
  return found === capitalise(pattern);
}

type Range = { start: number; end: number };

function near(ranges: Range[], start: number, end: number, dist: number): boolean {
  for (const r of ranges) {
    if (r.start >= start && r.end <= end) continue; // same span
    if (r.start - end <= dist && start - r.end <= dist) return true;
  }
  return false;
}

export function detectSkills(rawText: string, compiled: CompiledVocab): DetectedSkill[] {
  const text = rawText.normalize("NFKC");
  const counts = new Map<string, number>();
  const taken: Range[] = [];
  const bump = (slug: string) => counts.set(slug, (counts.get(slug) ?? 0) + 1);

  if (compiled.loose) {
    for (const m of text.matchAll(compiled.loose)) {
      const slug = compiled.looseSlug.get(normKey(m[0]));
      if (!slug) continue;
      const start = m.index ?? 0;
      taken.push({ start, end: start + m[0].length });
      bump(slug);
    }
  }

  if (compiled.strict) {
    for (const m of text.matchAll(compiled.strict)) {
      const found = m[0];
      const start = m.index ?? 0;
      const end = start + found.length;
      const hit = compiled.strictSlug.get(normKey(found));
      if (!hit) continue;
      const [slug, pattern] = hit;
      const entry = compiled.entries.get(slug);
      if (!entry || !caseOk(found, entry, pattern)) continue;
      if (taken.some((r) => start >= r.start && end <= r.end)) continue;
      const next = text.slice(end, end + 4);
      const prev = text.charAt(start - 1);
      // "R&D", "Q&R", "Go-to-market"
      if (found.length <= 2 && (next.startsWith("&") || prev === "&")) continue;
      if (/^-to\b/i.test(next)) continue;

      const W = STRICT_CONTEXT_CHARS;
      let ok: boolean;
      if (found.length <= 3) {
        const around = text.slice(Math.max(0, start - W), Math.min(text.length, end + W));
        ok = CONTEXT.test(around) || near(taken, start, end, W);
      } else {
        // Real English words ("Excel", "Swift", "React"): a neighbouring skill ("SQL, Excel, Tableau")
        // or an unmistakable tool context ("React developer", "Excel spreadsheets").
        const around = text.slice(Math.max(0, start - W), Math.min(text.length, end + W));
        ok = near(taken, start, end, Math.round(W / 2)) || STRONG_CONTEXT.test(around);
      }
      if (!ok) continue;
      bump(slug);
    }
  }

  return [...counts.entries()].map(([slug, mentions]) => ({ slug, mentions })).sort((a, b) => b.mentions - a.mentions || a.slug.localeCompare(b.slug));
}
