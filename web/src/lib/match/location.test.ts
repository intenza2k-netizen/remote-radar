import { describe, expect, it } from "vitest";
import { DEFAULT_REGION_GROUP, filterByLocation, locationStatus, regionGroupForLocation, validLocation } from "./location";
import type { Memberships } from "@/lib/geo";

const memberships: Memberships = {
  Europe: ["Estonia", "Germany", "France"],
  EU: ["Estonia", "Germany", "France"],
  "North America": ["Canada", "United States"],
};
const j = (id: string, remote_regions: string[]) => ({ id, remote_regions });
const jobs = [
  j("ww", ["worldwide"]),
  j("us", ["United States"]),
  j("eu", ["EU"]),
  j("ee", ["Estonia"]),
  j("de", ["Germany"]),
  j("none", []),
  j("na", ["North America"]),
];

describe("filterByLocation", () => {
  it("keeps everything when no location is chosen", () => {
    const r = filterByLocation(jobs, "", memberships);
    expect(r.kept).toHaveLength(jobs.length);
    expect(r.excluded).toBe(0);
  });

  it("applies isOpenTo: worldwide, the country itself and a region containing it", () => {
    const r = filterByLocation(jobs, "Estonia", memberships);
    expect(r.kept.map((x) => x.id)).toEqual(["ww", "eu", "ee"]);
    expect(r.excluded).toBe(4);
  });

  it("counts the postings that state no region among the excluded", () => {
    const r = filterByLocation(jobs, "Estonia", memberships);
    expect(r.unknown).toBe(1);
    expect(r.unknown).toBeLessThanOrEqual(r.excluded);
  });

  it("needs the whole region for a region location", () => {
    const r = filterByLocation(jobs, "Europe", memberships);
    expect(r.kept.map((x) => x.id)).toEqual(["ww", "eu"]);
  });

  it("does not let worldwide postings open to a sanctioned place", () => {
    const r = filterByLocation(jobs, "Cuba", memberships, ["Cuba"]);
    expect(r.kept).toHaveLength(0);
  });

  it("keeps all jobs when the membership data is missing", () => {
    expect(filterByLocation(jobs, "Estonia", null).kept).toHaveLength(jobs.length);
  });

  it("keeps the order of the input", () => {
    const r = filterByLocation([...jobs].reverse(), "Estonia", memberships);
    expect(r.kept.map((x) => x.id)).toEqual(["ee", "eu", "ww"]);
  });
});

describe("regionGroupForLocation", () => {
  it("maps countries and regions to the pay model's groups", () => {
    expect(regionGroupForLocation("Estonia")).toBe("europe");
    expect(regionGroupForLocation("EU")).toBe("europe");
    expect(regionGroupForLocation("Canada")).toBe("us_canada");
    expect(regionGroupForLocation("North America")).toBe("us_canada");
    expect(regionGroupForLocation("Brazil")).toBe("latam");
    expect(regionGroupForLocation("India")).toBe("apac");
  });

  it("is null for no location and for places in no group, so the caller falls back", () => {
    expect(regionGroupForLocation("")).toBeNull();
    expect(regionGroupForLocation("South Africa")).toBeNull();
    expect(regionGroupForLocation("Middle East")).toBeNull();
    expect(DEFAULT_REGION_GROUP).toBe("us_canada");
  });
});

describe("validLocation", () => {
  it("ignores a remembered value that is not an option any more", () => {
    expect(validLocation("Estonia", ["Estonia", "Europe"])).toBe("Estonia");
    expect(validLocation("Atlantis", ["Estonia", "Europe"])).toBe("");
    expect(validLocation(null, ["Estonia"])).toBe("");
    expect(validLocation(42, ["Estonia"])).toBe("");
  });
});

describe("locationStatus", () => {
  it("is empty without a location", () => {
    expect(locationStatus("", 100, { excluded: 0, unknown: 0 })).toBe("");
  });
  it("says how many postings were excluded, and how many of those state no region", () => {
    expect(locationStatus("Estonia", 3267, { excluded: 3064, unknown: 309 })).toBe(
      "203 of 3,267 postings are open to applicants in Estonia; 3,064 excluded, 309 of them because they do not say where they hire.",
    );
    expect(locationStatus("Estonia", 10, { excluded: 4, unknown: 0 })).toBe("6 of 10 postings are open to applicants in Estonia; 4 excluded.");
  });
});
