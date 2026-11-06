import { describe, expect, it } from "vitest";
import { jobTypeMix, jobTypeSentence } from "./job-types";

const names = { analyst: "Data analyst", bi: "BI / reporting analyst", eng: "Data engineer" };
const m = (id: string) => ({ job: { id } });

describe("jobTypeMix", () => {
  const assignment = new Map([
    ["a1", "analyst"],
    ["a2", "analyst"],
    ["a3", "analyst"],
    ["b1", "bi"],
    ["e1", "eng"],
    ["e2", "eng"],
  ]);

  it("counts the job types of the best data matches, most first", () => {
    const mix = jobTypeMix([m("a1"), m("b1"), m("a2"), m("e1"), m("a3")], assignment, names);
    expect(mix.total).toBe(5);
    expect(mix.rows.map((r) => [r.name, r.jobs])).toEqual([
      ["Data analyst", 3],
      ["BI / reporting analyst", 1],
      ["Data engineer", 1],
    ]);
    expect(mix.rows[0].share).toBeCloseTo(0.6);
  });

  it("skips postings that have no job type (not data roles) without using up the limit", () => {
    const mix = jobTypeMix([m("x1"), m("a1"), m("x2"), m("b1"), m("e1")], assignment, names, 2);
    expect(mix.total).toBe(2);
    expect(mix.rows.map((r) => r.name)).toEqual(["BI / reporting analyst", "Data analyst"]);
  });

  it("stops after the limit, so later matches do not count", () => {
    const mix = jobTypeMix([m("a1"), m("a2"), m("e1"), m("e2")], assignment, names, 3);
    expect(mix.total).toBe(3);
    expect(mix.rows.find((r) => r.id === "eng")?.jobs).toBe(1);
  });

  it("breaks ties by name and falls back to the id for an unknown type", () => {
    const mix = jobTypeMix([m("b1"), m("e1"), m("q")], new Map([...assignment, ["q", "mystery"]]), names);
    expect(mix.rows.map((r) => r.name)).toEqual(["BI / reporting analyst", "Data engineer", "mystery"]);
  });

  it("is empty when no match is a data posting", () => {
    const mix = jobTypeMix([m("x1"), m("x2")], assignment, names);
    expect(mix).toEqual({ total: 0, rows: [] });
    expect(jobTypeSentence(mix)).toBeNull();
  });
});

describe("jobTypeSentence", () => {
  it("reads like the spec", () => {
    const rows = [{ id: "analyst", name: "Data analyst", jobs: 18, share: 0.6 }];
    expect(jobTypeSentence({ total: 30, rows })).toBe("18 of your 30 best data matches are Data analyst postings");
  });
  it("does not say best when fewer than the limit exist, and handles one", () => {
    expect(jobTypeSentence({ total: 12, rows: [{ id: "a", name: "Data analyst", jobs: 7, share: 0.58 }] })).toBe("7 of your 12 data matches are Data analyst postings");
    expect(jobTypeSentence({ total: 1, rows: [{ id: "a", name: "Data analyst", jobs: 1, share: 1 }] })).toBe("1 of your 1 data match is a Data analyst posting");
  });
});
