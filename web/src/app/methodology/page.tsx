import type { Metadata } from "next";
import { PipelineDiagram } from "@/components/pipeline-diagram";
import { AccuracyTable } from "@/components/pay/accuracy-table";
import { maeSentence, trainingSentence } from "@/components/pay/copy";
import { Container, PageHeader, Section } from "@/components/ui";
import { getEval, getMeta } from "@/lib/data";
import { fmtDateLong, fmtInt } from "@/lib/format";
import { hasModel } from "@/lib/salary-model";
import { getSalaryModel } from "@/lib/salary-model-data";
import { ATTRIBUTION } from "@/lib/site";
import { MIN_WEEK_JOBS, collectionStartPhrase } from "@/lib/weeks";
import type { EvalBackend } from "@/lib/types";

export const metadata: Metadata = {
  title: "Methodology",
  description: "How Remote Radar collects postings, extracts skills and salaries with an LLM, how accurate the extraction is, and what the data cannot tell you.",
  openGraph: { title: "Methodology · Remote Radar", description: "Pipeline, extraction accuracy, limitations and data attribution." },
};

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

type Col = { key: string; label: string; better: "high" | "low"; fmt: (b: EvalBackend) => string; value: (b: EvalBackend) => number };
const COLS: Col[] = [
  { key: "p", label: "Skills precision", better: "high", fmt: (b) => pct(b.skills_precision), value: (b) => b.skills_precision },
  { key: "r", label: "Skills recall", better: "high", fmt: (b) => pct(b.skills_recall), value: (b) => b.skills_recall },
  { key: "f1", label: "Skills F1", better: "high", fmt: (b) => pct(b.skills_f1), value: (b) => b.skills_f1 },
  { key: "sen", label: "Seniority", better: "high", fmt: (b) => pct(b.seniority_acc), value: (b) => b.seniority_acc },
  { key: "role", label: "Role", better: "high", fmt: (b) => pct(b.role_acc), value: (b) => b.role_acc },
  { key: "sal", label: "Salary", better: "high", fmt: (b) => pct(b.salary_acc), value: (b) => b.salary_acc },
  { key: "lat", label: "Median latency", better: "low", fmt: (b) => `${(b.median_latency_ms / 1000).toFixed(1)} s`, value: (b) => b.median_latency_ms },
  { key: "cost", label: "Cost / 1k jobs", better: "low", fmt: (b) => (b.cost_per_1k_usd === 0 ? "$0 (local)" : `$${b.cost_per_1k_usd.toFixed(2)}`), value: (b) => b.cost_per_1k_usd },
  { key: "fail", label: "Failures", better: "low", fmt: (b) => fmtInt(b.failures), value: (b) => b.failures },
];

export default function MethodologyPage() {
  const meta = getMeta();
  const evalData = getEval();
  const salaryDoc = getSalaryModel();
  const payModel = hasModel(salaryDoc) ? salaryDoc : null;

  // Source mix, computed from the snapshot (never hard-coded).
  const sourceTotal = meta.sources.reduce((n, x) => n + x.jobs, 0);
  const topSource = [...meta.sources].sort((a, b) => b.jobs - a.jobs)[0];
  const topSourceShare = topSource && sourceTotal ? topSource.jobs / sourceTotal : 0;
  const targeted = meta.sources.filter((x) => x.scope === "targeted");
  const targetedJobs = targeted.reduce((n, x) => n + x.jobs, 0);
  const targetedShare = sourceTotal ? targetedJobs / sourceTotal : 0;

  return (
    <Container className="pb-8">
      <PageHeader
        eyebrow="Methodology"
        title="How the numbers are made, and how far to trust them"
        lede="Remote Radar reads public job feeds every night, asks an LLM to turn each free-text posting into structured fields, and publishes a static snapshot. This page covers the pipeline, the measured accuracy of the extraction, and the limits of the data."
      />

      <Section id="pipeline" title="The pipeline" lede="Six steps from public API to the page you are reading.">
        <PipelineDiagram />
      </Section>

      <Section id="extraction" title="How extraction works">
        <div className="prose-lite">
          <p>
            Job boards give you a title, some HTML and, sometimes, a few tags. Everything a dashboard needs, such as which skills are required, how senior the role is and what it pays, is buried in prose. A language model reads each posting and returns a fixed JSON schema.
          </p>
          <ul>
            <li>
              <strong>Input.</strong> Title, company, location, the description converted from HTML to plain text, any salary text and the board&rsquo;s own tags.
            </li>
            <li>
              <strong>Output.</strong> Skills, seniority, role, employment type, remote regions and salary, validated against a schema. Invalid output gets one retry, then the job is recorded as a failure instead of guessed.
            </li>
            <li>
              <strong>Skill normalisation.</strong> Raw skill strings are mapped to canonical slugs through an alias table (&ldquo;Postgres&rdquo;, &ldquo;PostgreSQL&rdquo; and &ldquo;psql&rdquo; are one skill) so counts are not split across spellings.
            </li>
            <li>
              <strong>Salary.</strong> Structured fields from the board are used when present; otherwise the LLM reads the text. Ranges are annualised (hourly &times; 2,080, monthly &times; 12) and converted to USD with a static exchange-rate table.
            </li>
            <li>
              <strong>Two backends.</strong> The same prompt runs on a hosted Claude model or on a local open model through Ollama, so quality, speed and cost can be compared on a labelled sample. This snapshot was produced with <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[0.85em]">{meta.backend}</code> /{" "}
              <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[0.85em]">{meta.model}</code>.
            </li>
            <li>
              <strong>Deduplication.</strong> The same role is often cross-posted. Jobs are keyed on a normalised company and title hash and counted once.
            </li>
          </ul>
        </div>
      </Section>

      <Section
        id="evaluation"
        title="Extraction accuracy: Claude vs a local model"
        lede={
          evalData
            ? `Measured on ${fmtInt(evalData.n_labeled)} hand-labelled postings (run ${fmtDateLong(evalData.generated_at)}). The better value in each row is in bold.`
            : "Both backends are scored against a hand-labelled sample of postings."
        }
      >
        {evalData && evalData.backends.length ? (
          <>
            <div className="card overflow-x-auto">
              <table className="data-table [&_td]:!px-2 [&_th]:!px-2 sm:[&_td]:!px-3 sm:[&_th]:!px-3">
                <caption className="sr-only">Extraction quality, speed and cost by backend</caption>
                <thead>
                  <tr>
                    <th scope="col">Measure</th>
                    {evalData.backends.map((b) => (
                      <th key={`${b.backend}-${b.model}`} scope="col" className="num !normal-case !tracking-normal !text-ink">
                        <span className="block text-sm font-semibold">{b.model}</span>
                        <span className="block text-xs font-normal text-ink-3">{b.backend === "ollama" ? "local (Ollama)" : "hosted API"}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {COLS.map((c) => {
                    const vals = evalData.backends.map(c.value);
                    const best = c.better === "high" ? Math.max(...vals) : Math.min(...vals);
                    return (
                      <tr key={c.key}>
                        <th scope="row" className="max-w-[6.5rem] !whitespace-normal !text-sm !normal-case !tracking-normal !text-ink-2 font-medium sm:max-w-none">
                          {c.label}
                          <span className="ml-1.5 hidden text-xs font-normal text-ink-3 sm:inline">{c.better === "high" ? "higher is better" : "lower is better"}</span>
                        </th>
                        {evalData.backends.map((b) => {
                          const isBest = evalData.backends.length > 1 && c.value(b) === best;
                          return (
                            <td key={`${b.backend}-${b.model}`} className={`num ${isBest ? "font-bold text-ink" : "text-ink-2"}`}>
                              {c.fmt(b)}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="prose-lite mt-4">
              <p>
                Skills are scored as a set per posting (precision: how many extracted skills were right; recall: how many true skills were found). Seniority, role and salary are exact-match accuracy. Latency and cost are per posting, with cost shown per 1,000 postings.
                {meta.sample ? " The figures shown here belong to the sample snapshot and will be replaced by the first real evaluation run." : ""}
              </p>
            </div>
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-line-strong p-8 text-center text-ink-3">
            No evaluation has been published yet. Results appear here after the first run of the evaluation harness.
          </div>
        )}
      </Section>

      <Section
        id="pay-model"
        title="Pay estimator accuracy"
        lede={
          payModel
            ? `Fitted on ${trainingSentence(payModel)}. Scored on companies it had not seen, and compared with a plain median.`
            : "The pay estimator is only published when enough postings state a salary to test it on unseen companies."
        }
      >
        {payModel ? (
          <>
            <AccuracyTable model={payModel} />
            <div className="prose-lite mt-4">
              <ul>
                <li>
                  <strong>Held out by company.</strong> The salaried postings are split into 5 folds so that every company is wholly in one fold; each fold is predicted by a model that never saw that company. The shrinkage strength of the ridge regression is chosen again inside each training part, so no figure above was tuned on the postings it is scored on.
                </li>
                <li>
                  <strong>Baseline.</strong> The median advertised pay of the same role and seniority among the training folds (the role alone, then everything, when a group has fewer than 5 postings). {payModel.eval.note} The interval comes from a bootstrap that resamples whole companies; {maeSentence(payModel.eval)}.
                </li>
                <li>
                  <strong>What the error means.</strong> A median error of {Math.round(payModel.eval.median_ape * 100)}% means half of the postings were closer than that and half further. The model explains R&sup2; = {payModel.eval.r2_log.toFixed(2)} of the variation in log pay, so most of what separates one posting&rsquo;s pay from another&rsquo;s (the company, the exact country, the team, negotiation) is not in the model.
                </li>
                <li>
                  <strong>Not a forecast of your pay.</strong> It describes advertised pay (midpoints of stated ranges) of the {fmtInt(payModel.n_train)} postings that state one, in USD at static exchange rates. Skill effects are associations and can stand in for something unobserved.
                </li>
              </ul>
            </div>
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-line-strong p-8 text-center text-ink-3">
            {salaryDoc && "reason" in salaryDoc ? `Not published in this snapshot: ${salaryDoc.reason}.` : "No salary model has been published yet. It appears after the next pipeline run."}
          </div>
        )}
      </Section>

      <Section id="limitations" title="Known limitations">
        <div className="prose-lite">
          <ul>
            <li>
              <strong>Source bias.</strong> {meta.sources.length} sources are not the remote job market. They skew towards tech, startups and English-language postings, the company career boards are a hand-picked list of remote-friendly employers, and roles filled through referrals or recruiters never appear. Read shares as &ldquo;among these sources&rdquo;, not &ldquo;in the market&rdquo;.
            </li>
            {targeted.length ? (
              <li>
                <strong>Deliberately tilted towards data roles.</strong> {new Intl.ListFormat("en", { style: "long", type: "conjunction" }).format(targeted.map((x) => x.display_name))} {targeted.length === 1 ? "is" : "are"} queried with data-role filters (keywords, tags or industry), and supply {Math.round(targetedShare * 100)}% of postings ({fmtInt(targetedJobs)} of {fmtInt(sourceTotal)}). This project is built for data analysts and engineers, so data skills appear more often here than across all remote jobs. Compare skills with each other, not with the wider market.
              </li>
            ) : null}
            <li>
              <strong>Source mix.</strong>{" "}
              {topSource && topSourceShare >= 0.5
                ? `One board currently supplies most postings: ${topSource.display_name} accounts for ${Math.round(topSourceShare * 100)}% (${fmtInt(topSource.jobs)} of ${fmtInt(sourceTotal)}), so figures lean towards what it lists.`
                : topSource
                  ? `The largest contributor is ${topSource.display_name} at ${Math.round(topSourceShare * 100)}% of postings (${fmtInt(topSource.jobs)} of ${fmtInt(sourceTotal)}); the mix can shift from night to night.`
                  : "The source mix is not available."}
            </li>
            <li>
              <strong>The time series is young.</strong> It starts on the first collection date ({collectionStartPhrase(meta)}); earlier weeks only contain older postings that were still listed on the boards when collection began. Weeks with fewer than {MIN_WEEK_JOBS} postings are not plotted.
            </li>
            <li>
              <strong>Postings are not hires.</strong> A skill mentioned in many postings is requested often, which is not the same as being valued, paid more or hard to find. Skills listed in boilerplate inflate shares.
            </li>
            <li>
              <strong>LLM errors.</strong> Extraction is probabilistic. The model can miss a skill, infer one that was only implied, or misjudge seniority from a vague title. The evaluation table above is the best available estimate of how often; errors are not randomly distributed, and rarer skills are likelier to be wrong.
            </li>
            <li>
              <strong>Salary is partial and self-selected.</strong> Only about {meta.totals.jobs ? Math.round((meta.totals.with_salary / meta.totals.jobs) * 100) : 0}% of postings state pay, and those that do are not a random sample (transparent employers, certain regions). Ranges are reduced to their midpoint.
            </li>
            <li>
              <strong>The skill pay premium is adjusted for role, seniority and region, and for nothing else.</strong> On the Insights page, postings that mention a skill are compared with postings of the same role, seniority and region group (US or Canada, Europe, Latin America, Asia-Pacific, worldwide, mixed or other, unknown) that do not (least squares on log salary, one skill at a time, intervals from a bootstrap that resamples companies). Company, the other skills in a posting and the exact location are not controlled for, many skills rest on few employers, and only the postings that state a salary count, so the numbers are associations in advertised pay, not what learning a skill would add to yours.
            </li>
            <li>
              <strong>FX and annualisation are approximations.</strong> A static exchange-rate table converts to USD, so figures drift from real rates and ignore purchasing power. Hourly and monthly rates assume a full-time year, which overstates contract work.
            </li>
            <li>
              <strong>Small groups are noisy.</strong> Salary percentiles are only shown for groups with at least 5 postings, and weekly shares for rarer skills move a lot on a handful of jobs. The latest week is always partial.
            </li>
          </ul>
        </div>
      </Section>

      <Section id="attribution" title="Data sources and attribution" lede="All postings are published by their original boards. Remote Radar only stores derived fields and links back to the source.">
        <ul className="grid gap-3 sm:grid-cols-2" aria-label="Data sources">
          {ATTRIBUTION.map((s) => {
            const count = meta.sources.find((m) => m.display_name === s.name)?.jobs;
            return (
              <li key={s.name} className="card p-4">
                <a href={s.homepage} target="_blank" rel="noopener" className="link text-lg font-semibold">
                  {s.name}
                </a>
                <p className="mt-0.5 text-sm text-ink-3">{s.homepage.replace(/^https?:\/\//, "")}</p>
                <p className="mt-2 text-sm text-ink-2">
                  {s.note}
                  {count != null ? ` · ${fmtInt(count)} postings in this snapshot` : ""}
                </p>
              </li>
            );
          })}
        </ul>
        <div className="prose-lite mt-6">
          <p>
            Every job link on this site goes straight to the original posting, opens in a new tab and is a normal followed link (no <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[0.85em]">nofollow</code>), as Remote OK requires. Please apply on the source board, and check each board&rsquo;s own terms before reusing its data.
          </p>
        </div>
      </Section>
    </Container>
  );
}
