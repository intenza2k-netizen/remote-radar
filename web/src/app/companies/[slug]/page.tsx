import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BarList, type BarItem } from "@/components/charts/bar-list";
import { JobRow } from "@/components/job-row";
import { Container, Kpi, Section } from "@/components/ui";
import { getJobs, getMeta, getSkillIndex } from "@/lib/data";
import { fmtInt, fmtShare, fmtUsdShort, roleLabel, seniorityLabel, seniorityRank } from "@/lib/format";
import { getCompanies, getCompany, salaryOf } from "@/lib/insights";

/** Cache Components rejects an empty list, so a missing companies.json yields one placeholder that renders as 404. */
const PLACEHOLDER = "__none__";

export function generateStaticParams() {
  const slugs = getCompanies().map((c) => ({ slug: c.slug }));
  return slugs.length ? slugs : [{ slug: PLACEHOLDER }];
}

export async function generateMetadata({ params }: PageProps<"/companies/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const c = getCompany(slug);
  if (!c) return { title: "Company not found" };
  const skills = c.top_skills.slice(0, 3).map((s) => s.name);
  const description = `${c.name} has ${fmtInt(c.jobs)} remote posting${c.jobs === 1 ? "" : "s"} in the snapshot.${skills.length ? ` Most requested: ${skills.join(", ")}.` : ""}${
    c.median_salary_usd ? ` Median advertised salary ${fmtUsdShort(c.median_salary_usd)}.` : ""
  } Roles, seniority mix and links to the original postings.`;
  return { title: `${c.name} remote jobs`, description, openGraph: { title: `${c.name} · Remote Radar`, description } };
}

function CompanySkeleton() {
  return (
    <Container>
      <div className="pt-8 text-sm">
        <Link href="/companies" className="link">
          &larr; All companies
        </Link>
      </div>
      <div className="mt-6 space-y-4" role="status" aria-label="Loading company">
        <div className="h-4 w-40 animate-pulse rounded bg-surface-2" />
        <div className="h-14 w-72 animate-pulse rounded bg-surface-2" />
        <div className="h-24 animate-pulse rounded bg-surface-2" />
      </div>
    </Container>
  );
}

export default function CompanyPage({ params }: PageProps<"/companies/[slug]">) {
  return (
    <Suspense fallback={<CompanySkeleton />}>
      <CompanyContent params={params} />
    </Suspense>
  );
}

/** A count breakdown as ranked bars, or one sentence when there is only a single category (a one-bar chart says nothing). */
function Mix({ entries, total, label, ariaLabel }: { entries: { key: string; label: string; n: number }[]; total: number; label: string; ariaLabel: string }) {
  if (entries.length === 1) {
    return (
      <p className="text-ink-2">
        All {fmtInt(total)} posting{total === 1 ? " is" : "s are"} {label} ({entries[0].label}).
      </p>
    );
  }
  const items: BarItem[] = entries.map((e) => ({ key: e.key, label: e.label, value: e.n, valueLabel: fmtInt(e.n), sub: fmtShare(e.n / total) }));
  return <BarList items={items} ariaLabel={ariaLabel} />;
}

async function CompanyContent({ params }: { params: PageProps<"/companies/[slug]">["params"] }) {
  const { slug } = await params;
  const company = getCompany(slug);
  if (!company) notFound();

  const meta = getMeta();
  const allJobs = getJobs();
  const ids = new Set(company.job_ids);
  let jobs = allJobs.filter((j) => ids.has(j.id));
  if (!jobs.length) jobs = allJobs.filter((j) => j.company === company.name);
  jobs = [...jobs].sort((a, b) => b.posted_at.localeCompare(a.posted_at));

  const index = getSkillIndex();
  const skillNames = Object.fromEntries([...index.values()].map((s) => [s.slug, s.name]));
  const sourceNames = Object.fromEntries(meta.sources.map((s) => [s.name, s.display_name]));

  const pay = salaryOf(jobs);
  const market = salaryOf(allJobs);
  const roles = Object.entries(company.roles)
    .map(([k, n]) => ({ key: k, label: roleLabel(k), n }))
    .sort((a, b) => b.n - a.n || a.label.localeCompare(b.label));
  const levels = Object.entries(company.seniority)
    .map(([k, n]) => ({ key: k, label: seniorityLabel(k), n }))
    .sort((a, b) => seniorityRank(a.key) - seniorityRank(b.key));
  const roleTotal = roles.reduce((s, r) => s + r.n, 0) || 1;
  const levelTotal = levels.reduce((s, r) => s + r.n, 0) || 1;
  const hasUnspecified = levels.some((l) => l.key === "unspecified");
  const srcLabel = company.sources.map((s) => sourceNames[s] ?? s).join(", ");

  const salarySub =
    pay.n === 0
      ? "no posting states pay"
      : pay.n < 5
        ? `n = ${pay.n} posting${pay.n === 1 ? "" : "s"} with pay: too few for a typical value${pay.n > 1 && pay.min != null && pay.max != null ? ` (range ${fmtUsdShort(pay.min)}–${fmtUsdShort(pay.max)})` : ""}`
        : `n = ${pay.n} postings with pay, USD / year${market.median != null ? `; all companies ${fmtUsdShort(market.median)} (n = ${market.n})` : ""}`;

  return (
    <Container>
      <div className="pt-8 text-sm">
        <Link href="/companies" className="link">
          &larr; All companies
        </Link>
      </div>
      <header className="pb-2 pt-4">
        <p className="eyebrow mb-3">Company</p>
        <h1 className="text-balance text-4xl font-semibold leading-tight tracking-tight sm:text-6xl">{company.name}</h1>
        <p className="mt-4 max-w-2xl text-lg text-ink-2">
          {fmtInt(company.jobs)} remote posting{company.jobs === 1 ? "" : "s"} in the snapshot, collected from {srcLabel}.
        </p>
      </header>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Kpi label="Postings" value={fmtInt(company.jobs)} sub={`of ${fmtInt(meta.totals.jobs)} tracked`} />
        <Kpi label="Role groups" value={fmtInt(roles.length)} sub={roles[0] ? `most: ${roles[0].label}` : undefined} />
        <Kpi label="Median salary" value={pay.median != null ? fmtUsdShort(pay.median) : "n/a"} sub={salarySub} />
        <Kpi label={company.sources.length === 1 ? "Source" : "Sources"} value={fmtInt(company.sources.length)} sub={srcLabel} />
      </div>

      <div className="grid gap-x-12 lg:grid-cols-2">
        <Section id="roles" title="What they hire for" lede="Postings by role group.">
          <Mix entries={roles} total={roleTotal} label="in one role group" ariaLabel={`${company.name} postings by role`} />
        </Section>
        <Section
          id="seniority"
          title="At what level"
          lede={hasUnspecified ? "Postings by seniority; “Unspecified” means the posting does not say." : "Postings by seniority."}
        >
          <Mix entries={levels} total={levelTotal} label="at one level" ariaLabel={`${company.name} postings by seniority`} />
        </Section>
      </div>

      <Section id="skills" title={`Skills ${company.name} asks for`} lede="Number of its postings that mention each skill. Follow a skill to see how it looks across the whole market.">
        {company.top_skills.length ? (
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0" aria-label="Most requested skills">
            {company.top_skills.map((s) => (
              <li key={s.slug}>
                <Link href={`/skills/${s.slug}`} className="chip no-underline">
                  {s.name} <span className="tnum opacity-60">{fmtInt(s.count)}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-ink-3">No skills were extracted from this company&rsquo;s postings.</p>
        )}
      </Section>

      <Section id="jobs" title={`${company.name} postings`} lede="Each title opens the original listing on the board that published it, in a new tab.">
        {jobs.length ? (
          <ul className="m-0 list-none p-0">
            {jobs.map((j) => (
              <JobRow key={j.id} job={j} skillNames={skillNames} sourceNames={sourceNames} maxSkills={5} />
            ))}
          </ul>
        ) : (
          <p className="text-ink-3">These postings are no longer in the published job list.</p>
        )}
      </Section>
    </Container>
  );
}
