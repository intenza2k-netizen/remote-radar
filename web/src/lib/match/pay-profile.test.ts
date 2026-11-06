import { describe, expect, it } from "vitest";
import { buildPayProfile, estimateForProfile, regionText, THIN_REGION_POSTINGS } from "./pay-profile";
import { predictPay, type SalaryModel } from "@/lib/salary-model";

const sk = (slug: string, n: number) => ({ slug, name: slug, n, n_companies: 50, pct: 1, ci_low_pct: -5, ci_high_pct: 7 });
const model = {
  version: 1,
  target: "log annual_usd_mid",
  alpha: 3,
  n_train: 1000,
  n_companies: 100,
  intercept: 11.5,
  reference: { role: "data", seniority: "senior", region_group: "us_canada" },
  coef: {
    role: { sales: -0.2 },
    seniority: { mid: -0.25, junior: -0.4 },
    region_group: { europe: -0.35, apac: -0.5 },
    skill: { sql: 0.01, python: 0.05, tableau: 0.02, dbt: 0.2, airflow: 0.1 },
  },
  levels: { role: { data: 500, sales: 100 }, seniority: { senior: 400, mid: 200 }, region_group: { us_canada: 800, europe: 121, apac: 10 } },
  skills: [sk("python", 500), sk("sql", 400), sk("tableau", 100), sk("airflow", 40), sk("dbt", 20)],
  profile_max_skills: 3,
  interval: { low_log: -0.5, high_log: 0.45, level: 0.8 },
  eval: {},
  drivers: [],
} as unknown as SalaryModel;

const base = { roles: [] as string[], level: "mid" as const, location: "", skills: ["sql", "python"] };

describe("buildPayProfile", () => {
  it("has no profile when the seniority is unknown", () => {
    expect(buildPayProfile({ ...base, level: null })).toBeNull();
  });

  it("defaults the role to data and the region group to US or Canada, and says so", () => {
    const p = buildPayProfile(base)!;
    expect(p.input).toEqual({ role: "data", seniority: "mid", regionGroup: "us_canada", skills: ["sql", "python"] });
    expect(p.roleIsDefault).toBe(true);
    expect(p.regionSource).toBe("default");
  });

  it("uses the picked role, with data winning when it is one of several", () => {
    expect(buildPayProfile({ ...base, roles: ["sales"] })!.input.role).toBe("sales");
    expect(buildPayProfile({ ...base, roles: ["sales"] })!.roleIsDefault).toBe(false);
    expect(buildPayProfile({ ...base, roles: ["sales", "support"] })!.input.role).toBe("sales");
    expect(buildPayProfile({ ...base, roles: ["sales", "data"] })!.input.role).toBe("data");
  });

  it("takes the region group from the location", () => {
    const p = buildPayProfile({ ...base, location: "Estonia" })!;
    expect(p.regionGroup).toBe("europe");
    expect(p.regionSource).toBe("location");
    expect(buildPayProfile({ ...base, location: "Canada" })!.regionGroup).toBe("us_canada");
  });

  it("falls back to the default for a location in none of the groups", () => {
    const p = buildPayProfile({ ...base, location: "South Africa" })!;
    expect(p.regionGroup).toBe("us_canada");
    expect(p.regionSource).toBe("unmapped");
  });

  it("passes the level as the model's seniority", () => {
    expect(buildPayProfile({ ...base, level: "junior" })!.input.seniority).toBe("junior");
  });
});

describe("estimateForProfile", () => {
  it("is exactly predictPay of the assembled input", () => {
    const p = buildPayProfile({ ...base, location: "Estonia" })!;
    const r = estimateForProfile(model, p, base.skills);
    expect(r.estimate).toEqual(predictPay(model, p.input));
    expect(r.estimate.low).toBeLessThan(r.estimate.median);
    expect(r.estimate.median).toBeLessThan(r.estimate.high);
  });

  it("moves with seniority and region: europe/mid pays less than the reference", () => {
    const ref = estimateForProfile(model, buildPayProfile({ ...base, level: "senior" })!, base.skills).estimate.median;
    const eu = estimateForProfile(model, buildPayProfile({ ...base, level: "mid", location: "Estonia" })!, base.skills).estimate.median;
    expect(eu).toBeLessThan(ref);
  });

  it("applies the profile rule: at most profile_max_skills, the most frequent, and reports the rest as left out", () => {
    const skills = ["dbt", "airflow", "tableau", "sql", "python", "not-modelled"];
    const r = estimateForProfile(model, buildPayProfile({ ...base, skills })!, skills);
    expect(r.skillsCounted).toEqual(["python", "sql", "tableau"]);
    expect(r.skillsLeftOut).toBe(3);
  });

  it("warns when the region group rests on few postings", () => {
    const thin = estimateForProfile(model, buildPayProfile({ ...base, location: "India" })!, base.skills);
    expect(thin.regionPostings).toBe(10);
    expect(thin.regionPostings).toBeLessThan(THIN_REGION_POSTINGS);
    expect(thin.thinRegion).toBe(true);
    const ok = estimateForProfile(model, buildPayProfile({ ...base, location: "Estonia" })!, base.skills);
    expect(ok.thinRegion).toBe(false);
  });
});

describe("regionText", () => {
  it("names the group and where it came from", () => {
    expect(regionText(buildPayProfile({ ...base, location: "Estonia" })!, "Estonia")).toBe("Europe (from Estonia)");
    expect(regionText(buildPayProfile(base)!, "")).toContain("US or Canada (the default");
    expect(regionText(buildPayProfile({ ...base, location: "South Africa" })!, "South Africa")).toContain("South Africa is in none of the model's region groups");
  });
});
