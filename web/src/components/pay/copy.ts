import { fmtInt, fmtUsdShort } from "@/lib/format";
import type { SalaryEval, SalaryModel } from "@/lib/salary-model";

/** 0.2247 -> "22%". */
export const pctText = (share: number): string => `${Math.round(share * 100)}%`;

/** How big the gain over the baseline is, in words, from the percentage by which the error is lower. */
export function gainWord(gainPct: number): string {
  const g = Math.abs(gainPct);
  return g < 10 ? "small" : g < 25 ? "moderate" : "large";
}

/**
 * The one-sentence takeaway for the pay estimator section, from the held-out numbers only. It states the typical
 * miss first and says plainly when the model does not clearly beat a plain median.
 */
export function payHeadline(model: SalaryModel): string {
  const ev = model.eval;
  const miss = `Guessing a posting's advertised pay from its role, seniority, region and skills misses by about ${pctText(ev.median_ape)} on a typical posting from a company the model has not seen`;
  if (ev.verdict === "better") return `${miss}: a ${gainWord(ev.mae_gain_pct)} but real gain on a plain median of the same role and seniority.`;
  if (ev.verdict === "worse") return `${miss}: worse than a plain median of the same role and seniority, so treat the estimate with care.`;
  return `${miss}: no clear gain on a plain median of the same role and seniority.`;
}

/** "$51,356 against $54,335" style sentence for the error comparison, rounded to whole thousands. */
export function maeSentence(ev: SalaryEval): string {
  return `mean absolute error ${fmtUsdShort(ev.mae_usd)} against ${fmtUsdShort(ev.baseline.mae_usd)} for the baseline`;
}

/** One line on what the model was fitted on. */
export function trainingSentence(model: SalaryModel): string {
  return `${fmtInt(model.n_train)} postings that state a salary, from ${fmtInt(model.n_companies)} companies`;
}
