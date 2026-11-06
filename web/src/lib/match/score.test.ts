import { describe, expect, it } from "vitest";
import { COVERAGE_PRIOR, PRIOR_WEIGHT, SIM_CEIL, SIM_FLOOR, WEIGHTS } from "./constants";
import { gapHeadline, rankGaps } from "./gap";
import { passesFilters, scoreJob, scoreJobs, semanticScore, seniorityFit, skillCoverage } from "./score";
import { DEFAULT_PREFS, type Preferences } from "./types";
import type { Job } from "@/lib/types";

function job(id: string, over: Partial<Job> = {}): Job {
  return {
    id,
    title: `Job ${id}`,
    company: "Acme",
    url: `https://example.com/${id}`,
    source: "remotive",
    posted_at: "2026-11-01T00:00:00Z",
    location: null,
    remote_regions: ["worldwide"],
    role: "data",
    seniority: "mid",
    employment_type: "full_time",
    skills: ["sql", "python", "dbt"],
    salary: null,
    ...over,
  };
}

const base = { cvSkills: new Set(["sql", "python"]), level: "mid" as const, prefs: DEFAULT_PREFS, cosines: null };

describe("components", () => {
  it("stretches cosine between floor and ceiling", () => {
    expect(semanticScore(SIM_FLOOR)).toBe(0);
    expect(semanticScore(SIM_CEIL)).toBe(1);
    expect(semanticScore((SIM_FLOOR + SIM_CEIL) / 2)).toBeCloseTo(0.5);
    expect(semanticScore(0.1)).toBe(0);
    expect(semanticScore(0.99)).toBe(1);
  });
  it("shrinks coverage toward the prior for short skill lists", () => {
    expect(skillCoverage(0, 0)).toBeNull();
    expect(skillCoverage(1, 1)).toBeCloseTo((1 + PRIOR_WEIGHT * COVERAGE_PRIOR) / (1 + PRIOR_WEIGHT));
    expect(skillCoverage(5, 5)!).toBeGreaterThan(skillCoverage(1, 1)!);
    // A one-skill posting you match must not beat a rich posting you mostly match.
    expect(skillCoverage(8, 10)!).toBeGreaterThan(skillCoverage(1, 1)!);
    expect(skillCoverage(0, 6)!).toBeLessThan(skillCoverage(3, 6)! / 2);
  });
  it("rates seniority fit asymmetrically", () => {
    expect(seniorityFit("mid", "mid")).toBe(1);
    expect(seniorityFit("mid", "senior")!).toBeLessThan(seniorityFit("mid", "junior")!);
    expect(seniorityFit("mid", "principal")!).toBeLessThan(0.3);
    expect(seniorityFit("mid", "unspecified")).toBeGreaterThan(0.4);
    expect(seniorityFit(null, "mid")).toBeNull();
  });
});

describe("scoreJob", () => {
  it("lists matched and missing skills and weights sum to 1", () => {
    const s = scoreJob(job("a"), { ...base, cosines: new Map([["a", 0.7]]) });
    expect(s.breakdown.matchedSkills).toEqual(["sql", "python"]);
    expect(s.breakdown.missingSkills).toEqual(["dbt"]);
    expect(s.breakdown.contributions.reduce((t, c) => t + c.weight, 0)).toBeCloseTo(1);
    expect(s.breakdown.contributions.reduce((t, c) => t + c.points, 0)).toBeCloseTo(s.score);
    expect(s.breakdown.cosine).toBe(0.7);
  });
  it("renormalises when the model is unavailable (no semantic component)", () => {
    const s = scoreJob(job("a"), base);
    expect(s.breakdown.semantic).toBeNull();
    expect(s.breakdown.contributions.map((c) => c.key)).toEqual(["skills", "seniority"]);
    expect(s.breakdown.contributions[0].weight).toBeCloseTo(WEIGHTS.skills / (WEIGHTS.skills + WEIGHTS.seniority));
  });
  it("adds a role component only when roles are chosen", () => {
    const prefs: Preferences = { ...DEFAULT_PREFS, roles: ["data"] };
    expect(scoreJob(job("a"), { ...base, prefs }).breakdown.role).toBe(1);
    expect(scoreJob(job("a", { role: "sales" }), { ...base, prefs }).breakdown.role).toBe(0);
    expect(scoreJob(job("a"), base).breakdown.role).toBeNull();
  });
  it("scores 0..1", () => {
    const s = scoreJob(job("a", { skills: [] }), { ...base, cvSkills: new Set<string>(), level: null });
    expect(s.score).toBeGreaterThanOrEqual(0);
    expect(s.score).toBeLessThanOrEqual(1);
  });
});

describe("scoreJobs and filters", () => {
  const jobs = [
    job("good", { skills: ["sql", "python"] }),
    job("poor", { skills: ["figma", "sketch"], role: "design" }),
    job("paid", { salary: { min: 90000, max: 110000, currency: "USD", period: "year", annual_usd_mid: 100000 } }),
    job("cheap", { salary: { min: 30000, max: 40000, currency: "USD", period: "year", annual_usd_mid: 35000 } }),
    job("eu", { remote_regions: ["Germany"] }),
  ];
  it("ranks the better skill match first", () => {
    const r = scoreJobs({ jobs, ...base });
    expect(r[0].job.id).toBe("good");
    expect(r[r.length - 1].job.id).toBe("poor");
  });
  it("minimum salary hides only jobs that state a lower salary", () => {
    const ids = scoreJobs({ jobs, ...base, prefs: { ...DEFAULT_PREFS, minSalary: 60000 } }).map((s) => s.job.id);
    expect(ids).not.toContain("cheap");
    expect(ids).toContain("paid");
    expect(ids).toContain("good"); // salary not stated: kept
  });
  it("only-salary drops unstated pay", () => {
    const ids = scoreJobs({ jobs, ...base, prefs: { ...DEFAULT_PREFS, onlySalary: true } }).map((s) => s.job.id);
    expect(ids.sort()).toEqual(["cheap", "paid"]);
  });
  it("region keeps worldwide jobs and the matching region", () => {
    const prefs = { ...DEFAULT_PREFS, region: "Germany" };
    expect(jobs.every((j) => passesFilters(j, prefs))).toBe(true); // all worldwide or Germany
    expect(passesFilters(job("x", { remote_regions: ["Canada"] }), prefs)).toBe(false);
    expect(passesFilters(job("y", { remote_regions: ["USA"] }), { ...DEFAULT_PREFS, region: "US" })).toBe(true);
  });
});

describe("rankGaps", () => {
  const scored = [job("1", { skills: ["sql", "dbt", "airflow"] }), job("2", { skills: ["dbt", "airflow"] }), job("3", { skills: ["dbt", "spark"] })].map((j) => scoreJob(j, base));
  it("ranks missing skills by the number of matches that ask for them", () => {
    const gaps = rankGaps(scored);
    expect(gaps.map((g) => [g.slug, g.jobs])).toEqual([
      ["dbt", 3],
      ["airflow", 2],
      ["spark", 1],
    ]);
    expect(gaps[0].share).toBe(1);
  });
  it("breaks ties with global popularity", () => {
    const gaps = rankGaps(scored, (s) => (s === "spark" ? 100 : 0));
    expect(gaps.slice(0, 1)[0].slug).toBe("dbt");
    const tie = rankGaps([scored[2]], (s) => (s === "spark" ? 100 : 1));
    expect(tie[0].slug).toBe("spark");
  });
  it("writes the headline", () => {
    expect(gapHeadline(rankGaps(scored), 3, (s) => s)).toBe("dbt appears in 3 of your 3 best matches");
    expect(gapHeadline([], 3, (s) => s)).toBeNull();
  });
});
