import type { Metadata } from "next";
import Link from "next/link";
import { CompaniesTable } from "@/components/insights/companies-table";
import { EmptyNote } from "@/components/insights/insight-section";
import { Container, PageHeader } from "@/components/ui";
import { getJobs, getMeta } from "@/lib/data";
import { fmtInt } from "@/lib/format";
import { companyRows, getCompanies } from "@/lib/insights";
import { windowCaption } from "@/lib/weeks";

export const metadata: Metadata = {
  title: "Companies",
  description: "Companies hiring remotely: number of open postings, roles, top skills, median advertised salary (with sample size) and the boards they post on.",
  openGraph: { title: "Companies · Remote Radar", description: "Searchable, sortable list of companies with remote postings." },
};

export default function CompaniesPage() {
  const meta = getMeta();
  const companies = getCompanies();

  if (!companies.length) {
    return (
      <Container className="pb-8">
        <PageHeader eyebrow="Companies" title="Company data is not published yet" lede="This page reads companies.json, which the nightly pipeline writes. It will fill in after the next run." />
        <div className="mt-8">
          <EmptyNote>
            Nothing to show right now. Browse the <Link href="/jobs" className="link">job explorer</Link> instead.
          </EmptyNote>
        </div>
      </Container>
    );
  }

  const rows = companyRows(companies, getJobs());
  const sourceNames = Object.fromEntries(meta.sources.map((s) => [s.name, s.display_name]));
  const multi = companies.filter((c) => c.jobs >= 2).length;

  return (
    <Container className="pb-8">
      <PageHeader
        eyebrow="Companies"
        title={`${fmtInt(companies.length)} companies hiring remotely`}
        lede={`Companies with at least one posting ${windowCaption(meta) === "collected so far" ? "collected so far" : `in the ${windowCaption(meta)}`}; ${fmtInt(multi)} have two or more. Median salary uses only postings that state pay, and its n is shown: with 1 or 2 salaried postings it is an anecdote, not a company norm.`}
      />
      <div className="mt-8">
        <CompaniesTable rows={rows} sourceNames={sourceNames} />
      </div>
    </Container>
  );
}
