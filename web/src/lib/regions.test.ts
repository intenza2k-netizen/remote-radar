import { describe, expect, it } from "vitest";
import { buildOptions } from "./match/options";
import { MIN_REGION_JOBS, regionOptions } from "./regions";
import { skillLabel } from "./format";
import type { Job } from "./types";

const jobs = (...regionLists: string[][]) => regionLists.map((remote_regions) => ({ remote_regions }));
const many = (region: string, n: number) => Array.from({ length: n }, () => [region]);

describe("regionOptions", () => {
  it("lists worldwide first, then regions by number of postings", () => {
    const opts = regionOptions(jobs(...many("Germany", 5), ...many("United States", 9), ...many("worldwide", 3), ...many("Canada", 5)));
    expect(opts.map((o) => o.value)).toEqual(["worldwide", "United States", "Canada", "Germany"]);
    expect(opts[0]).toEqual({ value: "worldwide", label: "Worldwide", count: 3 });
    expect(opts[1].count).toBe(9);
  });

  it("hides regions with fewer than 3 postings but keeps worldwide", () => {
    expect(MIN_REGION_JOBS).toBe(3);
    const opts = regionOptions(jobs(...many("Poland", 3), ...many("Laos", 2), ...many("Chile", 1), ...many("worldwide", 1)));
    expect(opts.map((o) => o.value)).toEqual(["worldwide", "Poland"]);
  });

  it("counts a posting once per region and breaks ties alphabetically", () => {
    const opts = regionOptions(jobs(["Spain", "Spain"], ["Spain"], ["Spain"], ["Italy"], ["Italy"], ["Italy"]));
    expect(opts).toEqual([
      { value: "Italy", label: "Italy", count: 3 },
      { value: "Spain", label: "Spain", count: 3 },
    ]);
  });

  it("keeps a selected value selectable even when it would be hidden or is unknown", () => {
    const base = jobs(...many("Poland", 3), ...many("Laos", 1));
    expect(regionOptions(base, { keep: "Laos" }).map((o) => o.value)).toEqual(["Poland", "Laos"]);
    expect(regionOptions(base, { keep: "Atlantis" }).map((o) => o.value)).toEqual(["Poland", "Atlantis"]);
  });
});

describe("matcher options", () => {
  it("use the same region list", () => {
    const list = [...many("United States", 4), ...many("Chile", 2)].map((remote_regions, i) => ({ id: String(i), role: "data", remote_regions }) as unknown as Job);
    expect(buildOptions(list).regions.map((r) => r.value)).toEqual(["United States"]);
  });
});

describe("skillLabel", () => {
  it("prefers the published name", () => {
    expect(skillLabel("meddpicc", { meddpicc: "MEDDPICC" })).toBe("MEDDPICC");
  });
  it("never shows a raw slug", () => {
    expect(skillLabel("business-strategy")).toBe("Business Strategy");
    expect(skillLabel("incident-response", {})).toBe("Incident Response");
  });
});
