import { describe, expect, it } from "vitest";
import fixture from "./salary-model.fixtures.json";
import { contributions, hasModel, parseSalaryModel, pctOf, predictPay, profileSkills, regionGroupOf, regionKey, type SalaryModel } from "./salary-model";

// The fixture file is written by pipeline/tests/test_salary_model.py from radar.salary_model.predict_pay and
// radar.regions.region_group (regenerate: RADAR_WRITE_FIXTURES=1 pytest tests/test_salary_model.py).
const model = fixture.model as unknown as SalaryModel;

describe("predictPay: parity with radar.salary_model.predict_pay", () => {
  for (const { input, expected } of fixture.predict) {
    const name = `${input.role} / ${input.seniority} / ${input.regionGroup} / [${input.skills.join(", ")}]`;
    it(name, () => {
      const got = predictPay(model, input);
      expect(got.used_skills).toEqual(expected.used_skills);
      // Both sides round exp() of a sum of the same floats; a one-dollar slack covers summation order.
      for (const key of ["median", "low", "high"] as const) expect(Math.abs(got[key] - expected[key])).toBeLessThanOrEqual(1);
    });
  }
});

describe("regionGroupOf: parity with radar.regions.region_group", () => {
  for (const { regions, expected } of fixture.region_groups) {
    it(`${JSON.stringify(regions)} -> ${expected}`, () => {
      expect(regionGroupOf(regions)).toBe(expected);
    });
  }

  it("treats missing input as unknown", () => {
    expect(regionGroupOf(null)).toBe("unknown");
    expect(regionGroupOf(undefined)).toBe("unknown");
    expect(regionGroupOf(["", "  "])).toBe("unknown");
  });

  it("normalises keys like regions.region_key", () => {
    expect(regionKey("The  Netherlands")).toBe("netherlands");
    expect(regionKey("Côte d’Ivoire")).toBe("cote d’ivoire");
    expect(regionKey("Asia-Pacific")).toBe("asia pacific");
    expect(regionKey("Bosnia & Herzegovina")).toBe("bosnia and herzegovina");
    expect(regionKey("U.S.A.")).toBe("usa");
  });
});

describe("the profile rule", () => {
  it("ignores unknown skills and keeps the most frequent ones, not the best paid", () => {
    // kubernetes (0.12) and dbt (0.30) pay most, but sql, python, excel are more common in postings.
    expect(profileSkills(model, ["dbt", "kubernetes", "not-a-skill", "excel", "python", "sql", "dbt"])).toEqual(["sql", "python", "excel"]);
  });

  it("breaks frequency ties by slug", () => {
    // excel and power-bi both appear in 60 postings
    expect(profileSkills({ ...model, profile_max_skills: 1 }, ["power-bi", "excel"])).toEqual(["excel"]);
  });

  it("does not let extra skills change the estimate", () => {
    const base = { role: "data", seniority: "senior", regionGroup: "us_canada" };
    const three = predictPay(model, { ...base, skills: ["sql", "python", "excel"] });
    const six = predictPay(model, { ...base, skills: ["kubernetes", "dbt", "power-bi", "excel", "python", "sql"] });
    expect(six).toEqual(three);
  });

  it("counts an unseen level as the reference level", () => {
    const ref = predictPay(model, { role: "data", seniority: "senior", regionGroup: "us_canada", skills: [] });
    expect(predictPay(model, { role: "astronaut", seniority: "wizard", regionGroup: "mars", skills: [] })).toEqual(ref);
    expect(ref.median).toBe(Math.round(Math.exp(model.intercept)));
  });

  it("returns an ordered range around the median", () => {
    const e = predictPay(model, { role: "sales", seniority: "mid", regionGroup: "europe", skills: ["excel"] });
    expect(e.low).toBeLessThan(e.median);
    expect(e.median).toBeLessThan(e.high);
    expect(Math.abs(e.low - e.median * Math.exp(model.interval.low_log))).toBeLessThan(1);
    expect(Math.abs(e.high - e.median * Math.exp(model.interval.high_log))).toBeLessThan(1);
  });
});

describe("contributions", () => {
  it("lists role, seniority, region group and the skills that counted, in percent against the reference", () => {
    const rows = contributions(model, { role: "sales", seniority: "senior", regionGroup: "europe", skills: ["dbt", "sql", "python", "excel"] });
    expect(rows.map((r) => `${r.kind}:${r.key}`)).toEqual(["role:sales", "seniority:senior", "region:europe", "skill:sql", "skill:python", "skill:excel"]);
    expect(rows[0].pct).toBeCloseTo(pctOf(-0.2), 10);
    expect(rows[1].pct).toBe(0); // the reference level
    expect(rows[2].pct).toBeCloseTo(100 * (Math.exp(-0.35) - 1), 10);
  });
});

describe("parseSalaryModel", () => {
  it("accepts a model and the small unavailable document", () => {
    const complete = { ...fixture.model, levels: { role: {}, seniority: {}, region_group: {} }, eval: {}, drivers: [] };
    const parsed = parseSalaryModel(complete);
    expect(hasModel(parsed)).toBe(true);
    const unavailable = parseSalaryModel({ version: 1, reason: "only 12 postings state a salary" });
    expect(unavailable).toEqual({ version: 1, reason: "only 12 postings state a salary" });
    expect(hasModel(unavailable)).toBe(false);
    expect(hasModel(null)).toBe(false);
  });

  it("rejects a model that lacks the blocks the estimator needs", () => {
    expect(parseSalaryModel(fixture.model)).toBeNull(); // the fixture has no levels or eval block
  });

  it("rejects anything else", () => {
    for (const bad of [null, undefined, 3, "x", [], {}, { version: 1 }, { version: 0, stub: true }, { version: 1, coef: {} }]) {
      expect(parseSalaryModel(bad)).toBeNull();
    }
  });
});
