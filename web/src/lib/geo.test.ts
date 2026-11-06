import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import fixture from "./geo.fixtures.json";
import {
  findLocation,
  isOpenTo,
  jobsHref,
  leadSentence,
  locationOptions,
  openVia,
  payLabel,
  rankLocations,
  selectionSentence,
  type GeoLocation,
  type Memberships,
} from "./geo";

describe("openVia / isOpenTo: parity with radar.geo", () => {
  // Cases computed by the Python implementation (pipeline/tests/test_geo.py writes this file).
  const memberships = fixture.memberships as Memberships;
  const sanctioned = fixture.sanctioned;

  it("has a useful number of cases", () => {
    expect(fixture.cases.length).toBeGreaterThan(200);
  });

  it("agrees with Python on every fixture case", () => {
    const wrong = fixture.cases.filter((c) => openVia(c.regions, c.location, memberships, sanctioned) !== c.via);
    expect(wrong.map((c) => `${JSON.stringify(c.regions)} -> ${c.location}`)).toEqual([]);
  });

  it("isOpenTo is openVia !== null", () => {
    for (const c of fixture.cases) {
      expect(isOpenTo({ remote_regions: c.regions }, c.location, memberships, sanctioned)).toBe(c.via !== null);
    }
  });
});

describe("the open-to rule", () => {
  const m: Memberships = {
    EU: ["Estonia", "Germany"],
    EEA: ["Estonia", "Germany", "Norway"],
    Europe: ["Estonia", "Germany", "Norway", "United Kingdom"],
    "North America": ["United States", "Canada"],
  };
  const open = (regions: string[], where: string) => isOpenTo({ remote_regions: regions }, where, m);

  it("never opens a posting without regions", () => {
    expect(open([], "Estonia")).toBe(false);
    expect(open([], "Europe")).toBe(false);
  });
  it("opens worldwide postings to everything", () => {
    expect(open(["worldwide"], "Estonia")).toBe(true);
    expect(open(["worldwide"], "Japan")).toBe(true);
    expect(open(["worldwide"], "EEA")).toBe(true);
    expect(open(["United States", "worldwide"], "Estonia")).toBe(true);
  });
  it("opens a country posting to that country only", () => {
    expect(open(["Estonia"], "Estonia")).toBe(true);
    expect(open(["Estonia"], "Germany")).toBe(false);
    expect(open(["United States"], "Estonia")).toBe(false);
  });
  it("opens a macro posting to its members", () => {
    expect(open(["EU"], "Estonia")).toBe(true);
    expect(open(["EU"], "Norway")).toBe(false);
    expect(open(["EEA"], "Norway")).toBe(true);
    expect(open(["Europe"], "United Kingdom")).toBe(true);
    expect(open(["North America"], "Estonia")).toBe(false);
  });
  it("needs only one matching element of a mixed list", () => {
    expect(open(["United States", "EU"], "Estonia")).toBe(true);
    expect(open(["United States", "Canada"], "Estonia")).toBe(false);
  });
  it("requires a posting to cover all of a macro location", () => {
    expect(open(["Germany", "Estonia"], "EU")).toBe(false);
    expect(open(["EU"], "Europe")).toBe(false);
    expect(open(["Europe"], "EU")).toBe(true);
    expect(open(["EEA"], "EEA")).toBe(true);
  });
  it("does not count worldwide for sanctioned places, but still counts naming them", () => {
    const blocked = ["Cuba"];
    const is = (regions: string[], where: string) => isOpenTo({ remote_regions: regions }, where, m, blocked);
    expect(is(["worldwide"], "Cuba")).toBe(false);
    expect(is(["worldwide"], "Estonia")).toBe(true);
    expect(is(["Cuba"], "Cuba")).toBe(true);
    expect(is(["worldwide", "Cuba"], "Cuba")).toBe(true);
    expect(isOpenTo({ remote_regions: ["worldwide"] }, "Cuba", m)).toBe(true); // no list given: plain rule
  });
  it("is not confused by region names that are object keys", () => {
    expect(open(["constructor"], "Estonia")).toBe(false);
    expect(open(["Estonia"], "constructor")).toBe(false);
  });
});

describe("agrees with the published geo.json counts", () => {
  const dir = path.join(__dirname, "..", "..", "public", "data");
  const geoFile = path.join(dir, "geo.json");
  const jobsFile = path.join(dir, "jobs.json");
  const available = fs.existsSync(geoFile) && fs.existsSync(jobsFile);

  it.skipIf(!available)("counts the same open postings as the pipeline for every location", () => {
    const geo = JSON.parse(fs.readFileSync(geoFile, "utf8"));
    const jobs = JSON.parse(fs.readFileSync(jobsFile, "utf8")) as { remote_regions: string[]; role: string | null }[];
    if (!geo.by_location) return; // placeholder document from before the pipeline wrote real data
    // A snapshot published by a different run than jobs.json would not compare; skip rather than fail.
    if (geo.summary && geo.summary.listed_jobs !== jobs.length) return;
    const mismatches: string[] = [];
    for (const row of geo.by_location as GeoLocation[]) {
      const open = jobs.filter((j) => isOpenTo(j, row.location, geo.memberships, geo.sanctioned ?? []));
      const data = open.filter((j) => j.role === "data").length;
      if (open.length !== row.open_jobs || data !== row.data_jobs) mismatches.push(`${row.location}: web ${open.length}/${data}, python ${row.open_jobs}/${row.data_jobs}`);
    }
    expect(mismatches).toEqual([]);
  });
});

const row = (over: Partial<GeoLocation> & { location: string }): GeoLocation => ({
  kind: "country",
  open_jobs: 100,
  open_share: 0.1,
  data_jobs: 30,
  worldwide_jobs: 40,
  explicit_jobs: 60,
  median_salary_usd: null,
  salary_n: 0,
  top_skills: [],
  by_role: { data: 30, sales: 70 },
  ...over,
});

describe("lists and sentences", () => {
  const rows = [
    row({ location: "Germany", data_jobs: 20, open_jobs: 90 }),
    row({ location: "Estonia", data_jobs: 25, open_jobs: 80 }),
    row({ location: "Chad", data_jobs: 25, open_jobs: 95 }),
    row({ location: "Nowhere", data_jobs: 99, open_jobs: 0 }),
    row({ location: "Europe", kind: "macro", data_jobs: 10, open_jobs: 50 }),
  ];

  it("ranks by open data postings, then open postings, then name, and drops empty locations", () => {
    expect(rankLocations(rows, "country").map((r) => r.location)).toEqual(["Chad", "Estonia", "Germany"]);
    expect(rankLocations(rows, "macro").map((r) => r.location)).toEqual(["Europe"]);
  });

  it("builds alphabetical region and country options with counts", () => {
    const o = locationOptions(rows);
    expect(o.countries.map((c) => c.value)).toEqual(["Chad", "Estonia", "Germany", "Nowhere"]);
    expect(o.regions).toEqual([{ value: "Europe", label: "Europe", count: 50 }]);
  });

  it("finds a location by exact name", () => {
    expect(findLocation(rows, "Estonia")?.open_jobs).toBe(80);
    expect(findLocation(rows, "")).toBeUndefined();
    expect(findLocation(rows, "Atlantis")).toBeUndefined();
  });

  it("describes a selection", () => {
    const text = selectionSentence(row({ location: "Estonia" }), 1000);
    expect(text).toContain("100 of 1,000 remote postings (10%)");
    expect(text).toContain("30 of them data roles");
    expect(text).toContain("40% of the open postings say worldwide");
    expect(selectionSentence(row({ location: "Estonia", data_jobs: 1 }), 1000)).toContain("1 of them a data role");
    expect(selectionSentence(row({ location: "Estonia", data_jobs: 0 }), 1000)).toContain("none of them a data role");
    expect(selectionSentence(row({ location: "Estonia", worldwide_jobs: 100, explicit_jobs: 0 }), 1000)).toContain("All of them say worldwide");
    expect(selectionSentence(row({ location: "Estonia", worldwide_jobs: 0, explicit_jobs: 100 }), 1000)).toContain("None says worldwide");
    expect(selectionSentence(row({ location: "Europe", kind: "macro" }), 1000)).toContain("anywhere in Europe");
    expect(selectionSentence(row({ location: "Chad", open_jobs: 0, data_jobs: 0, worldwide_jobs: 0, explicit_jobs: 0 }), 1000)).toBe("No listed remote posting is open to applicants in Chad.");
  });

  it("states pay only with a median", () => {
    expect(payLabel(row({ location: "A", median_salary_usd: 98000, salary_n: 12 }))).toEqual({ value: "$98k", sub: "median of 12 postings that state pay" });
    expect(payLabel(row({ location: "A", salary_n: 3 })).value).toBe("n/a");
    expect(payLabel(row({ location: "A", salary_n: 0 })).sub).toContain("no open posting");
  });

  it("leads with the US-only share", () => {
    const summary = { listed_jobs: 1000, data_jobs: 300, worldwide_jobs: 30, worldwide_data_jobs: 10, us_only_jobs: 520, us_only_data_jobs: 100, unknown_jobs: 90, unknown_data_jobs: 20 };
    const text = leadSentence({ summary, by_location: [row({ location: "Europe", kind: "macro", open_jobs: 120 })], unknown_jobs: 90 });
    expect(text).toContain("52% of the 1,000 remote postings are open to the United States only");
    expect(text).toContain("Only 3.0% say worldwide");
    expect(text).toContain("9.0% do not say");
    expect(text).toContain("anywhere in Europe can apply to 12%");
    expect(leadSentence({ by_location: [], unknown_jobs: 0 })).toContain("Pick where you live");
  });

  it("links the job explorer with the open_to parameter", () => {
    expect(jobsHref("Estonia")).toBe("/jobs?open_to=Estonia");
    expect(jobsHref("Bosnia and Herzegovina", { role: "data" })).toBe("/jobs?open_to=Bosnia+and+Herzegovina&role=data");
  });
});
