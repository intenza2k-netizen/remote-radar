import { EmptyNote, InsightSection } from "@/components/insights/insight-section";
import { getSkillIndex } from "@/lib/data";
import { fmtInt } from "@/lib/format";
import { hasModel } from "@/lib/salary-model";
import { getSalaryModel } from "@/lib/salary-model-data";
import { payHeadline, trainingSentence } from "./copy";
import { PayDriversChart } from "./pay-drivers-chart";
import { PayEstimator } from "./pay-estimator";

/** The "Pay estimator" block of the Insights page: estimator, held-out error, caveats and the skill pay drivers. */
export function PaySection() {
  const doc = getSalaryModel();
  const model = hasModel(doc) ? doc : null;

  if (!model) {
    return (
      <InsightSection
        id="pay"
        name="Pay estimator"
        headline="Not enough salaried postings yet to estimate pay."
        howTo={<>The estimator is fitted on postings that state a salary and is only published when there are enough of them to test it on companies it has not seen.</>}
      >
        <EmptyNote>{doc && "reason" in doc ? `Not published in this snapshot: ${doc.reason}.` : "salary_model.json is not published in this snapshot yet. It appears after the next pipeline run."}</EmptyNote>
      </InsightSection>
    );
  }

  const index = getSkillIndex();
  const categories = Object.fromEntries(model.skills.map((s) => [s.slug, index.get(s.slug)?.category ?? "other"]));
  const ev = model.eval;

  return (
    <InsightSection
      id="pay"
      name="Pay estimator"
      headline={payHeadline(model)}
      howTo={
        <>
          Pick a role, a seniority, where the job is open and some skills. The big number is the typical yearly pay a posting with that profile advertises, and the band is the range that held 80% of postings from companies the model had never seen. The error is printed right under it, and the list below shows how much each choice moves the number. Try the same profile in different regions: that is where most of the difference comes from.
        </>
      }
      details={
        <>
          <p>
            The model is a ridge regression of the natural log of advertised yearly pay (midpoint of the stated range, in USD) on dummies for role, seniority and region group, plus an indicator for each of the {fmtInt(model.skills.length)} skills that appear in at least 15 salaried postings from at least 5 companies. The reference level of each group is its most common level, and one shrinkage strength ({model.alpha}) is shared by all coefficients except the intercept. Because it works on log pay, an effect is a percentage and effects multiply. It was fitted on {trainingSentence(model)}.
          </p>
          <p>
            Accuracy is measured in 5 folds in which every company sits wholly in one fold, so a company&rsquo;s pay habits cannot leak from training into testing, and the shrinkage strength is chosen again inside each training part. MAE is {fmtInt(ev.mae_usd)} dollars against {fmtInt(ev.baseline.mae_usd)} for the baseline, which predicts the median pay of the same role and seniority (falling back to the role, then to everything, when a group has fewer than 5 postings). The 80% range comes from the 10th and 90th percentile of the held-out errors on the log scale, so it widens with pay; its {Math.round(ev.coverage * 100)}% coverage is itself measured on folds the range was not built from. The mean-error comparison uses a bootstrap that resamples whole companies: the model&rsquo;s error is {Math.abs(ev.mae_gain_pct).toFixed(1)}% {ev.mae_gain_pct >= 0 ? "lower" : "higher"} (95% interval {ev.mae_gain_ci_pct[0].toFixed(1)}% to {ev.mae_gain_ci_pct[1].toFixed(1)}%).
          </p>
          <p>
            A reader&rsquo;s skills are counted by a profile rule: only skills the model knows, at most {model.profile_max_skills} of them (the median posting lists that many), ordered by how often postings list them and not by their coefficient. Scoring the postings with that cap gives a median error of {Math.round(ev.capped.median_ape * 100)}%, so the rule costs little accuracy.
          </p>
        </>
      }
    >
      <PayEstimator model={model} categories={categories} />

      <div className="mt-6 max-w-3xl rounded-lg border border-line bg-surface p-4 text-sm leading-relaxed text-ink-2">
        <p className="font-semibold text-ink">Read this before quoting the number</p>
        <ul className="mt-2 list-disc space-y-1.5 pl-5">
          <li>
            <strong className="font-semibold text-ink">It is advertised pay, not what people earn.</strong> Offers, bonuses, equity and negotiation are not in the data, and each posting is reduced to the midpoint of its range.
          </li>
          <li>
            <strong className="font-semibold text-ink">Only {fmtInt(model.n_train)} postings state a salary.</strong> Employers that publish pay are not a random sample, so the model describes them and not the whole market.
          </li>
          <li>
            <strong className="font-semibold text-ink">Skills are associations, not causes.</strong> A skill can stand in for something the model cannot see (the company, the exact country, a team), so adding it to your CV is not a promise of a raise.
          </li>
          <li>
            <strong className="font-semibold text-ink">The band is wide on purpose.</strong> Postings with the same profile differ a lot; a narrow band would be false precision.
          </li>
        </ul>
      </div>

      <div className="mt-12">
        <h3 className="text-base font-semibold">Skills with the largest pay effects in the model</h3>
        <p className="mt-1 max-w-3xl text-sm text-ink-3">
          The effect of a skill with role, seniority and region group held fixed, in percent, from the same model. It differs from the premium chart above because every skill is fitted together here and the coefficients are shrunk towards zero.
        </p>
        <div className="mt-4">
          <PayDriversChart drivers={model.drivers} skills={model.skills} bootstraps={model.bootstraps} />
        </div>
      </div>
    </InsightSection>
  );
}
