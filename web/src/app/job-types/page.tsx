import type { Metadata } from "next";
import Link from "next/link";
import { ArchetypeCard } from "@/components/archetypes/archetype-card";
import { TypeScatter } from "@/components/archetypes/type-scatter";
import { TypesTable } from "@/components/archetypes/types-table";
import { EmptyNote } from "@/components/insights/insight-section";
import { Container, PageHeader, Section } from "@/components/ui";
import { getJobs, getMeta, getSkillNames } from "@/lib/data";
import { fmtInt, fmtShare } from "@/lib/format";
import { getArchetypes, headline, nearestTypes } from "@/lib/archetypes";
import { getCompanySlugMap } from "@/lib/insights";

export const metadata: Metadata = {
  title: "Job types",
  description:
    "The kinds of data job in remote postings, found by clustering posting text: data analyst, BI analyst, analytics engineer, data engineer, data scientist, ML engineer and more, with their skills, seniority and advertised pay.",
  openGraph: {
    title: "Job types · Remote Radar",
    description: "Open data postings grouped by what they ask for: size, signature skills, seniority mix and median advertised pay per type.",
  },
};

export default function JobTypesPage() {
  const doc = getArchetypes();

  if (!doc) {
    return (
      <Container className="pb-8">
        <PageHeader eyebrow="Job types" title="Job types are not published yet" lede="This page reads archetypes.json, which the pipeline writes once there are enough open data postings with embeddings (at least 30). It will fill in after the next run." />
        <div className="mt-8">
          <EmptyNote>
            Nothing to show right now. Browse the <Link href="/jobs" className="link">job explorer</Link> or the <Link href="/skills" className="link">skills table</Link> instead.
          </EmptyNote>
        </div>
      </Container>
    );
  }

  const meta = getMeta();
  const jobs = getJobs();
  const byId = new Map(jobs.map((j) => [j.id, j]));
  const skillNames = getSkillNames();
  const sourceNames = Object.fromEntries(meta.sources.map((s) => [s.name, s.display_name]));
  const companySlugs = getCompanySlugMap();
  const { archetypes, method, points } = doc;

  const neighbours = new Map(archetypes.map((a) => [a.id, nearestTypes(doc, a.id, 2).map((n) => n.name)]));
  const labels: Record<string, string> = {};
  for (const p of points) {
    const j = byId.get(p.id);
    if (j) labels[p.id] = `${j.title} · ${j.company}`;
  }

  const scores = method.candidates.map((c) => c.silhouette);
  const lowScore = scores.length ? Math.min(...scores) : null;
  const highScore = scores.length ? Math.max(...scores) : null;
  const looseCount = archetypes.filter((a) => (a.silhouette ?? 1) < 0.05).length;

  return (
    <Container className="pb-8">
      <PageHeader
        eyebrow="Job types"
        title={`Data jobs come in ${archetypes.length} types`}
        lede={`${headline(doc)} The types come from clustering what postings say (title, skills and the start of the description), not from job titles, so each one is a summary of a crowd of postings, not a rule.`}
      />

      <Section
        id="map"
        title="Each dot is one open data posting"
        lede="Postings that ask for similar things sit close together. Colour and number show the type each posting was assigned to; click a type to isolate it."
      >
        <TypeScatter types={archetypes.map((a) => ({ id: a.id, name: a.name, n: a.n }))} points={points} labels={labels} variance={method.pca_variance} />
        <h3 className="mt-8 text-base font-semibold">The same picture as a table</h3>
        <p className="mb-3 mt-1 max-w-3xl text-sm text-ink-2">
          Types are numbered by size. &ldquo;Titles match&rdquo; is the share of a type&rsquo;s postings whose title belongs to the family it is named after. A type marked &ldquo;loose&rdquo; has fuzzy edges or mixed titles (see its card).
        </p>
        <TypesTable rows={archetypes.map((a) => ({ archetype: a, neighbours: neighbours.get(a.id) ?? [] }))} />
      </Section>

      <Section
        id="types"
        title="What each type asks for, and what it pays"
        lede="Signature skills are the ones a type lists far more often than data postings overall. Pay is the median of the advertised annual salary (converted to USD) over postings that state one, shown only when at least 5 do. It describes the adverts, not what people earn, and it is not adjusted for seniority or region."
      >
        <div className="space-y-6">
          {archetypes.map((a, i) => (
            <ArchetypeCard
              key={a.id}
              archetype={a}
              index={i}
              neighbours={neighbours.get(a.id) ?? []}
              examples={a.example_job_ids.map((id) => byId.get(id)).filter((j): j is NonNullable<typeof j> => j != null)}
              skillNames={skillNames}
              sourceNames={sourceNames}
              companySlugs={companySlugs}
            />
          ))}
        </div>
      </Section>

      <Section id="method" title="How this was made" lede="Short version: embed each posting, cluster the embeddings, name the clusters with rules.">
        <div className="prose-lite max-w-3xl">
          <ul>
            <li>
              <strong>Population.</strong> {fmtInt(method.n_jobs)} open postings that the extraction model labelled as a data role and that have an embedding. Other roles, and postings that are no longer listed, are left out.
            </li>
            <li>
              <strong>Embeddings.</strong> Each posting becomes 384 numbers from the same small open model the CV matcher runs in your browser, computed from its title, role, seniority, top skills and the first part of the description. Descriptions are not published, only these numbers.
            </li>
            <li>
              <strong>Clustering.</strong> Spherical k-means (k-means with cosine similarity), best of 10 seeded restarts for every k from {method.candidates[0]?.k ?? 6} to {method.candidates[method.candidates.length - 1]?.k ?? 12}. The mean silhouette of the chosen k is {method.silhouette != null ? method.silhouette.toFixed(2) : "n/a"}
              {lowScore != null && highScore != null ? ` (the range over all k is ${lowScore.toFixed(2)} to ${highScore.toFixed(2)})` : ""}. Silhouette runs from -1 to 1; text embeddings rarely score high, so read this as &ldquo;overlapping crowds with a clear centre&rdquo;, not &ldquo;separate boxes&rdquo;.
            </li>
            <li>
              <strong>Choosing k.</strong> Silhouette is flat across k, so it cannot pick the number alone. Among the values within 0.01 of the best score, the page uses the one whose clusters are named after the most different job families, and the smaller k on a tie: an extra cluster has to add a new kind of job, not split one that exists.
            </li>
            <li>
              <strong>Names and summaries.</strong> A cluster takes the name of the title family most of its postings belong to (a short, hand-written keyword list: data engineer, analytics engineer, BI analyst, and so on). If two clusters share a family, the skill that best sets one apart from the other is added in brackets. Summaries are sentences filled in from the numbers. No language model writes anything shown here.
            </li>
          </ul>
        </div>

        <h3 className="mt-6 text-base font-semibold">Limits</h3>
        <div className="prose-lite mt-2 max-w-3xl">
          <ul>
            <li>
              <strong>The clusters are a summary.</strong> Boundaries are fuzzy: the same title can land in different types depending on what the posting asks for
              {looseCount ? `, and ${looseCount === 1 ? "one type is" : `${looseCount} types are`} about as close to a neighbour as to itself` : ""}. A new run on new postings can move postings, sizes and even names.
            </li>
            <li>
              <strong>Only data postings.</strong> Jobs the extraction labelled software engineering, product or anything else are not here, so a data-flavoured job under another label is missing, and a mislabelled one can sit in the wrong type.
            </li>
            <li>
              <strong>The map is a 2-D shadow.</strong> {method.pca_variance && method.pca_variance.length >= 2 ? `The two axes keep ${fmtShare(method.pca_variance[0] + method.pca_variance[1])} of the variance.` : "The two axes keep a small part of the variance."} Overlap in the picture does not mean overlap in the clustering.
            </li>
            <li>
              <strong>Pay and seniority are thin.</strong> Many postings state no salary or no level, medians are advertised pay in USD at fixed exchange rates, and company boards bring many near-identical postings that count separately.
            </li>
          </ul>
        </div>
        <p className="mt-4 max-w-3xl text-sm text-ink-2">
          Want to see where your CV falls? Try <Link href="/match" className="link">Match my CV</Link>. The pipeline code is in <code className="rounded bg-surface-2 px-1">pipeline/src/radar/archetypes.py</code>.
        </p>

        {method.candidates.length ? (
          <details className="mt-4 max-w-3xl text-sm text-ink-2">
            <summary className="cursor-pointer text-ink-3 hover:text-ink">Silhouette for every k tried</summary>
            <div className="card mt-3 overflow-x-auto">
              <table className="data-table">
                <caption className="sr-only">Mean silhouette for each number of clusters tried</caption>
                <thead>
                  <tr>
                    <th scope="col">Clusters (k)</th>
                    <th scope="col" className="num">
                      Mean silhouette
                    </th>
                    <th scope="col">Used</th>
                  </tr>
                </thead>
                <tbody>
                  {method.candidates.map((c) => (
                    <tr key={c.k}>
                      <td className="tnum">{c.k}</td>
                      <td className="num">{c.silhouette.toFixed(3)}</td>
                      <td>{c.k === method.k ? "yes" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ) : null}
      </Section>
    </Container>
  );
}
