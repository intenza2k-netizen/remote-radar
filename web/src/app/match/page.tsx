import type { Metadata } from "next";
import Link from "next/link";
import { MatchApp } from "@/components/match/match-app";
import { Container, PageHeader } from "@/components/ui";
import { getJobs, getMeta, getSkills } from "@/lib/data";
import { fmtInt } from "@/lib/format";
import { WEIGHTS } from "@/lib/match/constants";

const w = (x: number) => `${Math.round(x * 100)}%`;

const TITLE = "CV matcher";
const DESCRIPTION =
  "Paste or upload your CV and see which remote jobs fit, with an honest score breakdown and the skills you are missing. Everything runs in your browser; your CV is never uploaded.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: { title: `${TITLE} · Remote Radar`, description: DESCRIPTION },
  twitter: { card: "summary", title: `${TITLE} · Remote Radar`, description: DESCRIPTION },
};

export default function MatchPage() {
  const meta = getMeta();
  const jobs = getJobs();
  const skills = getSkills().map((s) => ({ slug: s.slug, name: s.name, count: s.count, category: s.category }));
  const sourceNames = Object.fromEntries(meta.sources.map((s) => [s.name, s.display_name]));
  return (
    <Container className="pb-12">
      <PageHeader
        eyebrow="CV matcher"
        title="Which remote jobs fit your CV?"
        lede={`Paste or upload your CV and get the best of ${fmtInt(jobs.length)} remote postings, scored by skills, seniority and meaning, with the skills you would still need. It all runs in your browser.`}
      />
      <MatchApp jobs={jobs} skills={skills} sourceNames={sourceNames} />
      <section className="mt-14 max-w-3xl" aria-labelledby="how-h">
        <h2 id="how-h" className="text-xl font-semibold tracking-tight">
          How the score works
        </h2>
        <div className="prose-lite mt-3 text-sm">
          <p>
            Each posting gets a weighted blend of four signals. <strong>Similarity ({w(WEIGHTS.semantic)})</strong>: how close the meaning of your CV is to the posting, measured with a
            small language model (<code>bge-small-en-v1.5</code>, 8-bit quantised so the one-time download is about 30 MB; the job vectors use the full-precision model, and the two agree to a cosine of about 0.99) that runs locally. Long CVs are cut into chunks and averaged together with a short summary of your
            skills and target roles. <strong>Skill coverage ({w(WEIGHTS.skills)})</strong>: the share of the skills the posting lists that your CV has. <strong>Seniority fit ({w(WEIGHTS.seniority)})</strong>:
            how close your level is to the one the posting asks for. <strong>Role ({w(WEIGHTS.role)})</strong>: only when you pick target roles.
          </p>
          <p>
            A signal that cannot be computed is dropped and the others are rescaled, which is what happens if the model cannot load: you then get a skills, seniority
            and role ranking. Skills come from matching the published vocabulary against your text (ambiguous names such as Go or R need the right capitalisation and
            nearby context). Postings are LLM-extracted, so skill lists are good but not perfect; see the <Link href="/methodology" className="link">methodology</Link>.
          </p>
        </div>
      </section>
    </Container>
  );
}
