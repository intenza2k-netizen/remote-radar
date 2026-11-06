import { describe, expect, it } from "vitest";
import { adjustedHeadlineRow, adjustedOf, certainGap, fmtSignedPct, headlineRow, mostRoleDrivenRow } from "./stats";

const row = (slug: string, diff: number, ci_low: number, ci_high: number) => ({ slug, diff, ci_low, ci_high });

describe("certainGap", () => {
  it("is the distance of the interval from zero in the direction of the gap", () => {
    expect(certainGap(row("a", 50, 20, 90))).toBe(20);
    expect(certainGap(row("b", -50, -90, -20))).toBe(20);
    expect(certainGap(row("c", 10, -5, 30))).toBe(-5);
    expect(certainGap(row("d", -10, -30, 5))).toBe(-5);
  });
});

describe("headlineRow", () => {
  it("picks by the interval's lower bound, not by the point estimate", () => {
    const rows = [
      row("fragile", 148000, 23000, 152000), // huge dot, interval barely clears zero
      row("solid", 40000, 30000, 52000),
      row("noise", 90000, -10000, 200000), // crosses zero: never the headline
    ];
    const pick = headlineRow(rows);
    expect(pick?.top.slug).toBe("solid");
    expect(pick?.clear).toBe(2);
  });

  it("works for negative gaps and returns null when every interval crosses zero", () => {
    expect(headlineRow([row("x", -40000, -60000, -25000), row("y", 20000, 10000, 30000)])?.top.slug).toBe("x");
    expect(headlineRow([row("n", 5000, -1000, 9000)])).toBeNull();
    expect(headlineRow([])).toBeNull();
  });
});

type Row = {
  slug: string;
  diff: number;
  ci_low: number;
  ci_high: number;
  adj_pct: number | null;
  adj_usd: number | null;
  adj_ci_low_pct: number | null;
  adj_ci_high_pct: number | null;
};
const prem = (slug: string, diff: number, lo: number, hi: number, adj: [number, number, number, number] | null): Row => ({
  slug,
  diff,
  ci_low: lo,
  ci_high: hi,
  adj_pct: adj ? adj[0] : null,
  adj_usd: adj ? adj[3] : null,
  adj_ci_low_pct: adj ? adj[1] : null,
  adj_ci_high_pct: adj ? adj[2] : null,
});

describe("fmtSignedPct", () => {
  it("rounds, signs and prints a true minus", () => {
    expect(fmtSignedPct(12.4)).toBe("+12%");
    expect(fmtSignedPct(-3.2)).toBe("−3%");
    expect(fmtSignedPct(0.2)).toBe("0%");
    expect(fmtSignedPct(-0.4)).toBe("0%");
  });
});

describe("adjustedOf and adjustedHeadlineRow", () => {
  it("is null without a full adjusted estimate", () => {
    expect(adjustedOf(prem("a", 1, 0, 2, null))).toBeNull();
    expect(adjustedOf({ diff: 1, ci_low: 0, ci_high: 2 })).toBeNull();
    expect(adjustedOf(prem("a", 1, 0, 2, [10, 5, 15, 8000]))).toEqual({ diff: 10, ci_low: 5, ci_high: 15, usd: 8000 });
  });

  it("picks by the adjusted interval and ignores rows without one", () => {
    const rows = [
      prem("raw-star", 90000, 60000, 120000, [3, -8, 14, 5000]), // big raw gap, role explains it
      prem("real", 20000, 5000, 35000, [18, 9, 27, 30000]),
      prem("none", 80000, 50000, 110000, null),
    ];
    const pick = adjustedHeadlineRow(rows);
    expect(pick?.top.slug).toBe("real");
    expect(pick?.clear).toBe(1);
    expect(pick?.tested).toBe(2);
    expect(adjustedHeadlineRow([prem("flat", 1, 0, 2, [1, -5, 7, 1000])])).toBeNull();
  });
});

describe("mostRoleDrivenRow", () => {
  it("names the skill that keeps the smallest part of a clear raw gap", () => {
    const rows = [
      prem("kept", 50000, 30000, 70000, [25, 15, 35, 44000]), // most of the gap survives
      prem("role", 60000, 40000, 80000, [10, -9, 29, 17000]), // loses 43k
      prem("flat", 90000, -10000, 190000, [0, -5, 5, 0]), // raw gap not clear: not a candidate
    ];
    const pick = mostRoleDrivenRow(rows);
    expect(pick?.row.slug).toBe("role");
    expect(pick?.lost).toBe(43000);
    expect(pick?.share).toBeCloseTo(17 / 60);
  });

  it("works for negative gaps and sign flips, and gives null when nothing shrinks", () => {
    expect(mostRoleDrivenRow([prem("neg", -40000, -60000, -20000, [-4, -20, 12, -7000])])?.lost).toBe(33000);
    expect(mostRoleDrivenRow([prem("flip", -40000, -60000, -20000, [8, -5, 22, 14000])])?.lost).toBe(54000);
    expect(mostRoleDrivenRow([prem("grows", 10000, 5000, 15000, [20, 10, 30, 35000])])).toBeNull();
    expect(mostRoleDrivenRow([prem("none", 10000, 5000, 15000, null)])).toBeNull();
  });
});
