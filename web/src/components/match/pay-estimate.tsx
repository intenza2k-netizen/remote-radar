import Link from "next/link";
import { pctText } from "@/components/pay/copy";
import { fmtInt, fmtUsdShort, roleLabel, seniorityLabel, skillLabel } from "@/lib/format";
import { regionText, type PayResult } from "@/lib/match/pay-profile";
import { regionGroupLabel, type SalaryModel } from "@/lib/salary-model";

type Props = {
  model: SalaryModel;
  /** Null while no estimate is possible: no seniority from the CV and none chosen. */
  result: PayResult | null;
  location: string;
  names: Record<string, string>;
};

/**
 * Estimated pay for your profile: the model's 80% range first, the held-out error next to it, then the inputs.
 * The middle of the range is shown as a smaller second figure, never on its own.
 */
export function PayEstimate({ model, result, location, names }: Props) {
  const ev = model.eval;
  const level = Math.round(model.interval.level * 100);
  return (
    <section className="card p-4 sm:p-5" aria-labelledby="pay-h">
      <p className="eyebrow">Estimated pay for your profile</p>
      {result ? (
        <div aria-live="polite">
          <h2 id="pay-h" className="mt-1 text-lg font-semibold leading-snug">
            <span className="sr-only">Advertised pay for a profile like yours, {level}% range: </span>
            <span className="tnum text-3xl font-semibold tracking-tight sm:text-4xl">
              {fmtUsdShort(result.estimate.low)} to {fmtUsdShort(result.estimate.high)}
            </span>
            <span className="ml-2 text-sm font-normal text-ink-3">a year, {level}% range</span>
          </h2>
          <p className="mt-2 text-sm text-ink-2">
            <strong className="font-semibold text-ink">How far to trust it:</strong> on postings from companies the model had not seen, a typical estimate missed by{" "}
            <strong className="tnum font-semibold text-ink">{pctText(ev.median_ape)}</strong> (mean absolute error {fmtUsdShort(ev.mae_usd)}), and{" "}
            <span className="tnum">{pctText(ev.coverage)}</span> of those postings landed inside their {level}% range, so some do fall outside it. The middle of this range is about{" "}
            <span className="tnum">{fmtUsdShort(result.estimate.median)}</span>; the range, not that figure, is the answer.
          </p>
        </div>
      ) : (
        <>
          <h2 id="pay-h" className="mt-1 text-lg font-semibold leading-snug">
            Pick your seniority to see a pay range
          </h2>
          <p className="mt-2 text-sm text-ink-2" aria-live="polite">
            No title or years of experience were found in your CV, and seniority moves pay more than most skills, so no estimate is shown. Choose your seniority in the
            preferences.
          </p>
        </>
      )}

      {result ? (
        <>
          <ul className="mt-3 flex flex-col gap-1 text-sm text-ink-2" aria-label="What the estimate is based on">
            <li>
              <span className="text-ink-3">Role:</span> {roleLabel(result.profile.role)}
              {result.profile.roleIsDefault ? " (default; pick a target role above to change it)" : ""}
            </li>
            <li>
              <span className="text-ink-3">Seniority:</span> {seniorityLabel(result.profile.seniority)}
            </li>
            <li>
              <span className="text-ink-3">Where:</span> {regionText(result.profile, location)}
            </li>
            <li>
              <span className="text-ink-3">Skills counted:</span>{" "}
              {result.skillsCounted.length ? result.skillsCounted.map((s) => skillLabel(s, names)).join(", ") : "none"}
              {result.skillsLeftOut > 0
                ? ` (the model counts at most ${model.profile_max_skills}, the most common first; ${fmtInt(result.skillsLeftOut)} more of yours ${result.skillsLeftOut === 1 ? "is" : "are"} not counted)`
                : ""}
            </li>
          </ul>
          {result.thinRegion ? (
            <p className="mt-2 text-xs text-ink-2" role="note">
              Thin data: only {fmtInt(result.regionPostings)} of the {fmtInt(model.n_train)} postings the model learned from are in the &ldquo;{regionGroupLabel(result.profile.regionGroup)}&rdquo; group,
              so this part of the estimate is shaky.
            </p>
          ) : null}
        </>
      ) : null}

      <p className="mt-3 text-xs text-ink-3">
        This is what postings like yours <em>advertise</em>, not what you would be offered; it ignores company, exact location and negotiation. Change the inputs and see how
        the model works in the{" "}
        <Link href="/insights#pay" className="link">
          pay estimator
        </Link>
        .
      </p>
    </section>
  );
}
