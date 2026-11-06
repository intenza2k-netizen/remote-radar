import type { Metadata } from "next";
import { Suspense } from "react";
import { JobsExplorer } from "@/components/jobs-explorer";
import { Container, PageHeader } from "@/components/ui";
import { getJobs, getMeta, getSkills } from "@/lib/data";
import { fmtInt } from "@/lib/format";

export const metadata: Metadata = {
  title: "Jobs",
  description: "Explore remote job postings by skill, seniority, role, region and salary. Every result links to the original posting.",
  openGraph: { title: "Job explorer · Remote Radar", description: "Filter remote job postings by skill, seniority, role, region and salary." },
};

function ExplorerFallback() {
  return (
    <div className="card h-48 animate-pulse" role="status" aria-label="Loading job explorer">
      <span className="sr-only">Loading job explorer</span>
    </div>
  );
}

export default function JobsPage() {
  const meta = getMeta();
  const jobs = getJobs();
  const skills = getSkills().map((s) => ({ slug: s.slug, name: s.name, count: s.count, category: s.category }));
  const sourceNames = Object.fromEntries(meta.sources.map((s) => [s.name, s.display_name]));
  return (
    <Container className="pb-8">
      <PageHeader
        eyebrow="Jobs"
        title="Browse the postings behind the numbers"
        lede={`${fmtInt(jobs.length)} remote postings from the last 60 days. Each title opens the original listing on the board that published it.`}
      />
      <div className="mt-8">
        <Suspense fallback={<ExplorerFallback />}>
          <JobsExplorer jobs={jobs} skills={skills} sourceNames={sourceNames} />
        </Suspense>
      </div>
    </Container>
  );
}
