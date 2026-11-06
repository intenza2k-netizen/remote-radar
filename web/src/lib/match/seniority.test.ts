import { describe, expect, it } from "vitest";
import { estimateYears, inferSeniority } from "./seniority";

describe("estimateYears", () => {
  it("reads stated years", () => {
    expect(estimateYears("Data analyst with 4 years of experience in SQL", 2026)).toBe(4);
    expect(estimateYears("8+ years experience building APIs", 2026)).toBe(8);
    expect(estimateYears("Over 3 yrs of professional experience; also 10 years as a chef", 2026)).toBe(10);
  });
  it("falls back to merged work date ranges and ignores education lines", () => {
    const text = "Analyst, Acme, 2020 - 2022\nSenior Analyst, Beta, 2022 - Present\nBSc Economics, University, 2012 - 2016";
    expect(estimateYears(text, 2026)).toBe(6);
  });
  it("returns null with no signal", () => {
    expect(estimateYears("I like data.", 2026)).toBeNull();
  });
});

describe("inferSeniority", () => {
  it("uses title words in the headline", () => {
    expect(inferSeniority("Senior Data Analyst\nSQL, Python", 2026).level).toBe("senior");
    expect(inferSeniority("Principal Software Engineer", 2026).level).toBe("principal");
    expect(inferSeniority("Junior Frontend Developer", 2026).level).toBe("junior");
    expect(inferSeniority("Engineering Manager and Tech Lead", 2026).level).toBe("lead");
    expect(inferSeniority("Head of Data at Acme", 2026).level).toBe("lead");
  });
  it("maps years to levels when there is no title", () => {
    expect(inferSeniority("Analyst with 1 year of experience", 2026).level).toBe("junior");
    expect(inferSeniority("Analyst with 4 years of experience", 2026).level).toBe("mid");
    expect(inferSeniority("Analyst with 7 years of experience", 2026).level).toBe("senior");
  });
  it("does not let an old 'Junior' title in the history override the years", () => {
    const text = `Data Analyst with 4 years of experience. ${"Good with data. ".repeat(30)}\nEXPERIENCE\nJunior Data Analyst, Old Co, 2020 - 2022`;
    const g = inferSeniority(text, 2026);
    expect(g.level).toBe("mid");
    expect(g.years).toBe(4);
  });
  it("is null when there is nothing to go on", () => {
    expect(inferSeniority("I am enthusiastic.", 2026).level).toBeNull();
  });
  it("explains itself", () => {
    expect(inferSeniority("Analyst with 4 years of experience", 2026).reason).toMatch(/4 years/);
  });
});
