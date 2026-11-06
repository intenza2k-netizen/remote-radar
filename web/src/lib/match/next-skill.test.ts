import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { COVERED_MIN_LISTED, MIN_LISTING, isWellCovered, rankNextSkills, scoreWith, signedPct, skillPay } from "./next-skill";
import { SAMPLE_CV } from "./sample-cv";
import { scoreJobs } from "./score";
import { DEFAULT_PREFS, type Level, type ScoredJob } from "./types";
import { compileVocab, detectSkills } from "./vocab";
import type { SalaryModel } from "@/lib/salary-model";
import type { Job } from "@/lib/types";

function job(id: string, skills: string[], over: Partial<Job> = {}): Job {
  return {
    id,
    title: `Job ${id}`,
    company: "Acme",
    url: `https://example.com/${id}`,
    source: "remotive",
    posted_at: `2026-11-${String((Number(id.replace(/\D/g, "")) % 28) + 1).padStart(2, "0")}T00:00:00Z`,
    location: null,
    remote_regions: ["worldwide"],
    role: "data",
    seniority: "mid",
    employment_type: "full_time",
    skills,
    salary: null,
    ...over,
  };
}

/** Brute force: score everything again with the skill really added to the profile. */
function brute(jobs: Job[], cv: Set<string>, slug: string, level: Level | null, cosines: Map<string, number> | null, topN: number, pool: number) {
  const input = { jobs, level, prefs: DEFAULT_PREFS, cosines };
  const before = scoreJobs({ ...input, cvSkills: cv });
  const after = scoreJobs({ ...input, cvSkills: new Set([...cv, slug]) });
  const topBefore = new Set(before.slice(0, topN).map((m) => m.job.id));
  const entersTop = after.slice(0, topN).filter((m) => !topBefore.has(m.job.id)).length;
  const afterById = new Map(after.map((m) => [m.job.id, m]));
  let covered = 0;
  for (const m of before.slice(0, pool)) {
    const a = afterById.get(m.job.id) as ScoredJob;
    const was = isWellCovered(m.breakdown.matchedSkills.length, m.job.skills.length);
    const now = isWellCovered(a.breakdown.matchedSkills.length, a.job.skills.length);
    if (!was && now) covered++;
  }
  return { entersTop, covered };
}

/** Small seeded generator, so the synthetic market is the same on every run. */
function lcg(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
}

const ALL = ["sql", "python", "tableau", "dbt", "airflow", "spark", "aws", "excel", "looker", "r", "git", "docker"];
function market(n: number, seed: number) {
  const rnd = lcg(seed);
  const levels = ["junior", "mid", "senior", "unspecified"];
  const jobs: Job[] = [];
  const cosines = new Map<string, number>();
  for (let i = 0; i < n; i++) {
    const k = 2 + Math.floor(rnd() * 6);
    const skills = ALL.filter(() => rnd() < k / ALL.length);
    jobs.push(job(`j${i}`, skills, { seniority: levels[Math.floor(rnd() * levels.length)] }));
    cosines.set(`j${i}`, 0.5 + rnd() * 0.3);
  }
  return { jobs, cosines };
}

describe("isWellCovered", () => {
  it("needs two thirds of the listed skills and a minimum list length", () => {
    expect(COVERED_MIN_LISTED).toBe(3);
    expect(isWellCovered(2, 3)).toBe(true);
    expect(isWellCovered(1, 3)).toBe(false);
    expect(isWellCovered(4, 6)).toBe(true);
    expect(isWellCovered(3, 6)).toBe(false);
    expect(isWellCovered(2, 2)).toBe(false); // too short a list to tell
    expect(isWellCovered(1, 1)).toBe(false);
  });
});

describe("scoreWith", () => {
  const cv = new Set(["sql", "python"]);
  const jobs = [job("a", ["sql", "python", "dbt"]), job("b", ["sql", "tableau", "dbt", "airflow"]), job("c", ["sql", "python"])];
  const cosines = new Map([
    ["a", 0.7],
    ["b", 0.65],
    ["c", 0.6],
  ]);
  const scored = scoreJobs({ jobs, cvSkills: cv, level: "mid", prefs: DEFAULT_PREFS, cosines });
  const by = (id: string) => scored.find((m) => m.job.id === id) as ScoredJob;

  it("equals a full re-score with the skill added, for the one term that moves", () => {
    const full = scoreJobs({ jobs, cvSkills: new Set([...cv, "dbt"]), level: "mid", prefs: DEFAULT_PREFS, cosines });
    for (const id of ["a", "b"]) {
      expect(scoreWith(by(id), "dbt")).toBeCloseTo(full.find((m) => m.job.id === id)!.score, 12);
    }
  });

  it("is null for a posting that does not list the skill or when you already have it", () => {
    expect(scoreWith(by("c"), "dbt")).toBeNull();
    expect(scoreWith(by("a"), "sql")).toBeNull();
  });

  it("only ever raises a score", () => {
    expect(scoreWith(by("a"), "dbt")!).toBeGreaterThan(by("a").score);
  });
});

describe("rankNextSkills", () => {
  it("returns nothing when the profile has no skills or there are no matches", () => {
    const { jobs, cosines } = market(40, 1);
    const scored = scoreJobs({ jobs, cvSkills: new Set(), level: "mid", prefs: DEFAULT_PREFS, cosines });
    expect(rankNextSkills(scored, new Set())).toEqual([]);
    expect(rankNextSkills([], new Set(["sql"]))).toEqual([]);
  });

  it("matches a brute-force re-score for every skill (top 10 of a pool of 40)", () => {
    for (const seed of [1, 2, 3]) {
      const { jobs, cosines } = market(150, seed);
      const cv = new Set(["sql", "python", "git"]);
      const scored = scoreJobs({ jobs, cvSkills: cv, level: "mid", prefs: DEFAULT_PREFS, cosines });
      const rows = rankNextSkills(scored, cv, 50, 10, 40);
      expect(rows.length).toBeGreaterThan(3);
      for (const r of rows) {
        const b = brute(jobs, cv, r.slug, "mid", cosines, 10, 40);
        expect({ slug: r.slug, entersTop: r.entersTop, covered: r.covered }).toEqual({ slug: r.slug, ...b });
      }
    }
  });

  it("never proposes a skill you have or one that too few of your best matches list", () => {
    const { jobs, cosines } = market(150, 7);
    const cv = new Set(["sql", "python"]);
    const scored = scoreJobs({ jobs, cvSkills: cv, level: "mid", prefs: DEFAULT_PREFS, cosines });
    const rows = rankNextSkills(scored, cv, 50, 10, 40);
    for (const r of rows) {
      expect(cv.has(r.slug)).toBe(false);
      expect(r.listedBy).toBeGreaterThanOrEqual(MIN_LISTING);
    }
  });

  it("ranks by newly covered, then entries, then how many list it, then slug; and respects the limit", () => {
    const { jobs, cosines } = market(200, 11);
    const cv = new Set(["sql"]);
    const scored = scoreJobs({ jobs, cvSkills: cv, level: "mid", prefs: DEFAULT_PREFS, cosines });
    const all = rankNextSkills(scored, cv, 50);
    for (let i = 1; i < all.length; i++) {
      const a = all[i - 1];
      const b = all[i];
      const ka = [-a.covered, -a.entersTop, -a.listedBy, a.slug] as const;
      const kb = [-b.covered, -b.entersTop, -b.listedBy, b.slug] as const;
      const cmp = ka[0] - kb[0] || ka[1] - kb[1] || ka[2] - kb[2] || (ka[3] < kb[3] ? -1 : 1);
      expect(cmp).toBeLessThanOrEqual(0);
    }
    expect(rankNextSkills(scored, cv, 3)).toEqual(all.slice(0, 3));
  });

  it("counts newly covered postings in a hand-made market", () => {
    // a, b, c already have 2 of 3 skills; d goes from 1 of 3 to 2 of 3 with dbt; e lists 2 skills (too short to count).
    const jobs = [
      job("a1", ["sql", "python", "dbt"]),
      job("a2", ["sql", "python", "dbt"]),
      job("a3", ["sql", "python", "dbt"]),
      job("a4", ["sql", "tableau", "dbt"]),
      job("a5", ["sql", "dbt"]),
      ...Array.from({ length: 6 }, (_, i) => job(`z${i}`, ["excel", "r", "git"], { seniority: "senior" })),
    ];
    const cv = new Set(["sql", "python"]);
    const scored = scoreJobs({ jobs, cvSkills: cv, level: "mid", prefs: DEFAULT_PREFS, cosines: null });
    const dbt = rankNextSkills(scored, cv, 5, 3, 11).find((r) => r.slug === "dbt");
    expect(dbt).toMatchObject({ listedBy: 5, covered: 1 });
    // All eleven postings are in the pool; excel, r and git are each listed by six of them, so they are candidates too.
    expect(rankNextSkills(scored, cv, 10, 3, 11).map((r) => r.slug)).toEqual(expect.arrayContaining(["excel", "r", "git"]));
  });
});

describe("skillPay", () => {
  const model = {
    skills: [
      { slug: "dbt", name: "dbt", n: 30, n_companies: 12, pct: 8.4, ci_low_pct: 1.2, ci_high_pct: 15.9 },
      { slug: "sql", name: "SQL", n: 400, n_companies: 200, pct: 0.5, ci_low_pct: -6.8, ci_high_pct: 6.8 },
      { slug: "linux", name: "Linux", n: 40, n_companies: 20, pct: -21, ci_low_pct: -39, ci_high_pct: -3 },
    ],
  } as unknown as SalaryModel;

  it("passes the coefficient and its interval through", () => {
    expect(skillPay(model, "dbt")).toEqual({ pct: 8.4, low: 1.2, high: 15.9, distinguishable: true, n: 30, companies: 12 });
  });
  it("marks an interval that crosses zero as not distinguishable, and a negative one that does not as distinguishable", () => {
    expect(skillPay(model, "sql")!.distinguishable).toBe(false);
    expect(skillPay(model, "linux")!.distinguishable).toBe(true);
  });
  it("is null for a skill the model does not cover, or no model", () => {
    expect(skillPay(model, "cobol")).toBeNull();
    expect(skillPay(null, "dbt")).toBeNull();
  });
});

describe("signedPct", () => {
  it("rounds, signs with a true minus and never prints -0", () => {
    expect(signedPct(8.4)).toBe("+8%");
    expect(signedPct(-21.2)).toBe("−21%");
    expect(signedPct(0.2)).toBe("0%");
    expect(signedPct(-0.3)).toBe("0%");
  });
});

// The published snapshot and the built-in sample CV, without the language model (the matcher's skills + seniority fallback).
const dataDir = path.join(process.cwd(), "public", "data");
const haveData = fs.existsSync(path.join(dataDir, "jobs.json")) && fs.existsSync(path.join(dataDir, "skill_vocab.json"));
describe.skipIf(!haveData)("the sample CV on the published snapshot", () => {
  it("agrees with a brute-force re-score for the top suggestions and is fast", () => {
    const jobs = JSON.parse(fs.readFileSync(path.join(dataDir, "jobs.json"), "utf8")) as Job[];
    const vocab = JSON.parse(fs.readFileSync(path.join(dataDir, "skill_vocab.json"), "utf8"));
    const cv = new Set(detectSkills(SAMPLE_CV, compileVocab(vocab)).map((d) => d.slug));
    expect(cv.size).toBeGreaterThan(5);
    const scored = scoreJobs({ jobs, cvSkills: cv, level: "mid", prefs: DEFAULT_PREFS, cosines: null });
    const t0 = performance.now();
    const rows = rankNextSkills(scored, cv, 8);
    const ms = performance.now() - t0;
    expect(ms).toBeLessThan(500);
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows.slice(0, 4)) {
      const b = brute(jobs, cv, r.slug, "mid", null, 30, 100);
      expect({ entersTop: r.entersTop, covered: r.covered }).toEqual(b);
    }
  });
});
