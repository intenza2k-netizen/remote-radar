import { describe, expect, it } from "vitest";
import { gainWord, maeSentence, payHeadline, pctText } from "./copy";
import type { SalaryModel } from "@/lib/salary-model";

const model = (verdict: "better" | "similar" | "worse", gain: number) =>
  ({
    n_train: 1764,
    n_companies: 517,
    eval: {
      median_ape: 0.2247,
      mae_usd: 51356,
      mae_gain_pct: gain,
      verdict,
      baseline: { name: "median", mae_usd: 54335, median_ape: 0.2296, r2_log: 0.14 },
    },
  }) as unknown as SalaryModel;

describe("pay copy", () => {
  it("rounds shares to whole percents", () => {
    expect(pctText(0.2247)).toBe("22%");
    expect(pctText(0.795)).toBe("80%");
  });

  it("calls a 5% error reduction small, not impressive", () => {
    expect(gainWord(5.5)).toBe("small");
    expect(gainWord(15)).toBe("moderate");
    expect(gainWord(40)).toBe("large");
  });

  it("says plainly when the model does not beat the baseline", () => {
    expect(payHeadline(model("better", 5.5))).toMatch(/about 22%.*small but real gain/);
    expect(payHeadline(model("similar", 1))).toMatch(/no clear gain/);
    expect(payHeadline(model("worse", -8))).toMatch(/worse than a plain median/);
  });

  it("compares error in dollars", () => {
    expect(maeSentence(model("better", 5.5).eval)).toBe("mean absolute error $51k against $54k for the baseline");
  });
});
