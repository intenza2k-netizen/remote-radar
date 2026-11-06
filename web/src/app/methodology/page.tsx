import type { Metadata } from "next";
import { PipelineDiagram } from "@/components/pipeline-diagram";
import { Container, PageHeader, Section } from "@/components/ui";
import { getEval, getMeta } from "@/lib/data";
import { fmtDateLong, fmtInt } from "@/lib/format";
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

  // Source mix, computed from the snapshot (never hard-coded).
  const sourceTotal = meta.sources.reduce((n, x) => n + x.jobs, 0);
  const topSource = [...meta.sources].sort((a, b) => b.jobs - a.jobs)[0];
  const topSourceShare = topSource && sourceTotal ? topSource.jobs / sourceTotal : 0;

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

      <Section id="limitations" title="Known limitations">
        <div className="prose-lite">
          <ul>
            <li>
              <strong>Source bias.</strong> Four boards are not the remote job market. They skew towards tech, startups, English-language postings and employers who pay to list or cross-post. Roles filled through referrals, recruiters or company career pages never appear. Read shares as &ldquo;among these boards&rdquo;, not &ldquo;in the market&rdquo;.
            </li>
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
