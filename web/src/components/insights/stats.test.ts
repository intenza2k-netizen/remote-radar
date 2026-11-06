import { describe, expect, it } from "vitest";
import { certainGap, headlineRow } from "./stats";

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
