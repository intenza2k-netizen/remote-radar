import { describe, expect, it } from "vitest";
import { headline, looseReasons, nearestTypes, parseArchetypes, payRange, seniorityMix, typicalLevel, typicalLevelText, type Archetype, type ArchetypesDoc } from "./archetypes";

function arch(id: string, over: Partial<Archetype> = {}): Archetype {
  return {
    id,
    name: id.toUpperCase(),
    summary: "",
    family: null,
    family_share: 1,
    n: 100,
    share: 0.25,
    median_salary_usd: 100000,
    salary_n: 40,
    silhouette: 0.2,
    seniority: { senior: 60, mid: 20, unspecified: 20 },
    top_skills: [],
    top_titles: [],
    example_job_ids: [],
    ...over,
  };
}

function doc(archetypes: Archetype[], points: ArchetypesDoc["points"] = []): ArchetypesDoc {
  return {
    version: 1,
    method: { algorithm: "x", k: archetypes.length, seed: 1, silhouette: 0.13, candidates: [], n_jobs: archetypes.reduce((s, a) => s + a.n, 0) },
    archetypes,
    points,
  };
}

describe("parseArchetypes", () => {
  it("returns null for anything that is not a document with archetypes", () => {
    expect(parseArchetypes(null)).toBeNull();
    expect(parseArchetypes([])).toBeNull();
    expect(parseArchetypes({ version: 1, archetypes: [], points: [] })).toBeNull();
    expect(parseArchetypes({ version: 1, method: {} })).toBeNull();
  });

  it("keeps valid archetypes, fills optional fields and drops points of unknown archetypes", () => {
    const parsed = parseArchetypes({
      version: 1,
      method: { k: 1, n_jobs: 40 },
      archetypes: [{ id: "a", name: "A", n: 40 }, { id: "bad" }],
      points: [
        { id: "j1", a: "a", x: 0.1, y: -0.2 },
        { id: "j2", a: "zzz", x: 0, y: 0 },
        { id: "j3", a: "a", x: Number.NaN, y: 0 },
      ],
    });
    expect(parsed?.archetypes.map((a) => a.id)).toEqual(["a"]);
    expect(parsed?.archetypes[0]).toMatchObject({ median_salary_usd: null, salary_n: 0, top_skills: [], example_job_ids: [], seniority: {} });
    expect(parsed?.points.map((p) => p.id)).toEqual(["j1"]);
    expect(parsed?.method.n_jobs).toBe(40);
  });
});

describe("seniority", () => {
  it("orders the mix by level with unspecified last and skips empty levels", () => {
    const mix = seniorityMix({ n: 100, seniority: { unspecified: 20, senior: 50, junior: 10, lead: 20 } });
    expect(mix.map((m) => m.level)).toEqual(["junior", "senior", "lead", "unspecified"]);
    expect(mix[1]).toEqual({ level: "senior", n: 50, share: 0.5 });
  });

  it("names the most common stated level and its share of stated postings", () => {
    const t = typicalLevel({ n: 100, seniority: { senior: 60, mid: 20, unspecified: 20 } });
    expect(t?.level).toBe("senior");
    expect(t?.share).toBeCloseTo(0.75);
    expect(t?.statedShare).toBeCloseTo(0.8);
    expect(typicalLevelText({ n: 100, seniority: { senior: 60, mid: 20, unspecified: 20 } })).toBe("Senior (75% of those that state a level)");
  });

  it("gives no typical level when most postings state none", () => {
    expect(typicalLevel({ n: 100, seniority: { unspecified: 100 } })).toBeNull();
    expect(typicalLevel({ n: 100, seniority: { senior: 20, unspecified: 80 } })).toBeNull();
    expect(typicalLevelText({ n: 49, seniority: { unspecified: 49 } })).toBeNull();
  });
});

describe("looseReasons", () => {
  it("is empty for a well-defined cluster", () => {
    expect(looseReasons(arch("a"))).toEqual([]);
  });

  it("flags a low silhouette and mixed titles separately", () => {
    const low = looseReasons(arch("a", { silhouette: -0.02 }));
    expect(low).toHaveLength(1);
    expect(low[0]).toContain("-0.02");
    const mixed = looseReasons(arch("a", { family: "Analytics engineer", family_share: 0.45 }));
    expect(mixed).toHaveLength(1);
    expect(mixed[0]).toContain("45%");
    expect(mixed[0]).toContain("analytics engineer");
    expect(looseReasons(arch("a", { silhouette: 0.0, family: "Data analyst", family_share: 0.3 }))).toHaveLength(2);
  });

  it("does not flag clusters with no silhouette or title family published", () => {
    expect(looseReasons({ name: "A", family: null, family_share: 0 })).toEqual([]);
  });
});

describe("headline and pay range", () => {
  it("states size and the spread of median pay between types", () => {
    const d = doc([arch("a", { name: "Data analyst", median_salary_usd: 95049, n: 200 }), arch("b", { name: "ML engineer", median_salary_usd: 202500, n: 300 }), arch("c", { name: "Annotation", median_salary_usd: null, salary_n: 0, n: 50 })]);
    expect(payRange(d.archetypes)?.low.id).toBe("a");
    expect(payRange(d.archetypes)?.high.id).toBe("b");
    const h = headline(d);
    expect(h).toContain("550 open data postings fall into 3 job types");
    expect(h).toContain("$95k (Data analyst) to $203k (ML engineer)");
  });

  it("falls back to the size sentence when fewer than two types have a median", () => {
    const d = doc([arch("a", { name: "A", n: 90, median_salary_usd: null }), arch("b", { name: "B", n: 10, median_salary_usd: 90000 })]);
    expect(payRange(d.archetypes)).toBeNull();
    expect(headline(d)).toBe("100 open data postings fall into 2 job types; the largest, A, holds 90% of them.");
  });
});

describe("nearestTypes", () => {
  it("orders the other types by distance between plot centres", () => {
    const d = doc(
      [arch("a"), arch("b"), arch("c"), arch("d")],
      [
        { id: "1", a: "a", x: 0, y: 0 },
        { id: "2", a: "b", x: 0.2, y: 0 },
        { id: "3", a: "c", x: 0.9, y: 0.1 },
        { id: "4", a: "d", x: -0.5, y: 0 },
      ],
    );
    expect(nearestTypes(d, "a", 2).map((x) => x.id)).toEqual(["b", "d"]);
    expect(nearestTypes(d, "c", 1).map((x) => x.id)).toEqual(["b"]);
    expect(nearestTypes(d, "missing")).toEqual([]);
  });
});
