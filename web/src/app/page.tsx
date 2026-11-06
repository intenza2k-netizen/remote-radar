import Link from "next/link";
import { BarList } from "@/components/charts/bar-list";
import { SalaryRange } from "@/components/charts/salary-range";
import { SegmentedBar } from "@/components/charts/segmented-bar";
import { TrendExplorer } from "@/components/charts/trend-explorer";
import { TrendEmptyState } from "@/components/trend-empty";
import { RelativeTime } from "@/components/relative-time";
import { Container, Kpi, Section } from "@/components/ui";
import { TECHNICAL, buildHeadline, medianSalaryOf, topSkills } from "@/lib/analytics";
import { reliableTrend, reliableWeeks, trendReady, windowCaption } from "@/lib/weeks";
import { getJobs, getMeta, getRoles, getSalary, getSkills } from "@/lib/data";
import { fmtDateLong, fmtInt, fmtPP, fmtShare, fmtUsdShort, roleLabel, seniorityLabel } from "@/lib/format";

const SOURCE_COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"];

export default function OverviewPage() {
  const meta = getMeta();
  const skills = getSkills();
  const roles = getRoles();
  const salary = getSalary();
  const jobs = getJobs();

  const headline = buildHeadline(meta, skills, medianSalaryOf(jobs));
  const top20 = topSkills(skills, 20);
  const total = meta.totals.jobs;
  const withSalaryPct = total ? meta.totals.with_salary / total : 0;
  const topRole = roles[0];
  const bySen = new Map(salary.by_seniority.map((r) => [r.key, r]));
  const mid = bySen.get("mid");
  const senior = bySen.get("senior");
  // Default to the five most requested *technical* skills (generic ones like "Communication" add little).
  const defaultTrend = skills
    .filter((s) => TECHNICAL.has(s.category))
    .slice(0, 5)
    .map((s) => s.slug);
  // Trend visuals only use weeks with enough postings (MIN_WEEK_JOBS).
  const weeks = reliableWeeks(meta);
  const trendOk = trendReady(weeks);
  const trendSkills = skills.map((s) => ({ slug: s.slug, name: s.name, category: s.category, count: s.count, trend: reliableTrend(s.trend, weeks) }));
  const defaultSkills = defaultTrend.map((slug) => skills.find((s) => s.slug === slug)!);

  return (
    <Container>
      {/* Hero: the headline sentence is generated from the snapshot */}
      <header className="pb-4 pt-10 sm:pt-16">
        <p className="eyebrow mb-4">
          Remote job market &middot; {windowCaption(meta)} &middot; {fmtDateLong(meta.generated_at)}
        </p>
        {headline ? (
          <>
            <h1 className="max-w-4xl text-balance text-4xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
              <Link href={`/skills/${headline.skill.slug}`} className="text-accent no-underline hover:underline">
                {headline.skill.name}
              </Link>{" "}
              appears in {fmtShare(headline.skill.share)} of remote job postings
            </h1>
            <p className="mt-5 max-w-2xl text-pretty text-lg text-ink-2 sm:text-xl">
              {headline.riser ? (
                <>
                  <Link href={`/skills/${headline.riser.slug}`} className="link">
                    {headline.riser.name}
                  </Link>{" "}
                  is climbing fastest ({fmtPP(headline.riser.change_4w)} in four weeks)
                  {headline.medianSalary ? <>, and the median advertised salary is {fmtUsdShort(headline.medianSalary)} a year.</> : "."}
                </>
              ) : headline.medianSalary ? (
                <>
                  Among the {fmtInt(meta.totals.with_salary)} postings that state pay, the median is {fmtUsdShort(headline.medianSalary)} a year.
                </>
              ) : null}{" "}
              Every figure below is extracted by an LLM from {fmtInt(total)} postings across {meta.sources.length} public sources.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/match" className="btn no-underline">
                Match my CV to these jobs
              </Link>
              <Link href="/insights" className="btn no-underline">
                See what pays and what clusters
              </Link>
            </div>
          </>
        ) : (
          <h1 className="text-4xl font-semibold tracking-tight">Remote Radar</h1>
        )}
      </header>

      <div className="mt-8 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4" role="list" aria-label="Key figures">
        <div role="listitem">
          <Kpi label="Jobs tracked" value={fmtInt(total)} sub={windowCaption(meta)} />
        </div>
        <div role="listitem">
          <Kpi label="Companies hiring" value={fmtInt(meta.totals.companies)} sub="with open remote listings" />
        </div>
        <div role="listitem">
          <Kpi label="With salary" value={fmtShare(withSalaryPct)} sub={`${fmtInt(meta.totals.with_salary)} postings state pay`} />
        </div>
        <div role="listitem">
          <Kpi label="Last updated" value={<RelativeTime iso={meta.generated_at} />} sub={`model: ${meta.model}`} />
        </div>
      </div>

      <Section
        id="top-skills"
        title="The 20 skills remote employers ask for most"
        lede={
          <>
            Share of all {fmtInt(total)} postings that mention each skill. A posting can list many skills, so shares add up to well over 100%.{" "}
            <Link href="/skills" className="link">
              Browse all {fmtInt(skills.length)} skills
            </Link>
            .
          </>
        }
      >
        <BarList
          ariaLabel="Top 20 skills by share of postings"
          items={top20.map((s) => ({
            key: s.slug,
            label: s.name,
            href: `/skills/${s.slug}`,
            value: s.share,
            valueLabel: fmtShare(s.share),
            sub: fmtInt(s.count),
            title: `${s.name}: ${fmtShare(s.share)} of postings (${fmtInt(s.count)} jobs)`,
          }))}
        />
        <p className="mt-3 text-xs text-ink-3">Bars show share of postings; the grey figure is the number of postings.</p>
      </Section>

      <Section
        id="trends"
        title="How demand is moving, week by week"
        lede={
          trendOk
            ? "Share of each week's postings that mention the skill. Starts with the five most requested technical skills; add up to six to compare. Weeks with fewer than 20 postings are left out, and the latest week may be partial."
            : "Share of each week's postings that mention the skill, once there is enough history to show it."
        }
      >
        {trendOk ? (
          <TrendExplorer skills={trendSkills} defaultSlugs={defaultTrend} />
        ) : (
          <TrendEmptyState meta={meta} reliableCount={weeks.length} what="how the share of postings mentioning each skill moves week by week">
            <p className="mb-3 text-sm font-medium text-ink-2">Share of all {fmtInt(total)} postings so far</p>
            <BarList
              ariaLabel="Current share of postings for the most requested technical skills"
              items={defaultSkills.map((s) => ({ key: s.slug, label: s.name, href: `/skills/${s.slug}`, value: s.share, valueLabel: fmtShare(s.share), sub: fmtInt(s.count) }))}
            />
          </TrendEmptyState>
        )}
      </Section>

      <div className="grid gap-x-12 lg:grid-cols-2">
        <Section
          id="roles"
          title={topRole ? `${roleLabel(topRole.role)} is the most common role (${fmtShare(topRole.count / total)})` : "Role mix"}
          lede="Share of postings by role as classified by the LLM."
        >
          <BarList
            ariaLabel="Postings by role"
            items={roles.map((r) => ({
              key: r.role,
              label: roleLabel(r.role),
              value: r.count,
              valueLabel: fmtShare(r.count / total),
              sub: fmtInt(r.count),
              title: `${roleLabel(r.role)}: ${fmtInt(r.count)} postings${r.median_salary_usd ? `, median ${fmtUsdShort(r.median_salary_usd)}` : ""}`,
            }))}
          />
        </Section>

        <Section
          id="salary"
          title={mid && senior ? `Seniors are advertised at ${fmtUsdShort(senior.median)}, mid-level at ${fmtUsdShort(mid.median)}` : "Advertised salary by seniority"}
          lede={`Annualised USD for the ${fmtInt(meta.totals.with_salary)} postings that state pay. Groups with fewer than 5 postings, and postings with unspecified seniority, are left out.`}
        >
          <SalaryRange rows={salary.by_seniority.filter((r) => r.key !== "unspecified")} ariaLabel="Salary distribution by seniority" labelFor={seniorityLabel} />
        </Section>
      </div>

      <Section
        id="sources"
        title="Where the postings come from"
        lede={
          <>
            Remote job boards, company career pages and Hacker News, deduplicated by company and title. Some sources are searched for data roles, so data jobs are deliberately over-represented. Every job on this site links to the original posting.{" "}
            <Link href="/methodology#attribution" className="link">
              Attribution and caveats
            </Link>
            .
          </>
        }
      >
        <div className="card p-4 sm:p-6">
          <SegmentedBar
            ariaLabel="Share of postings by source"
            segments={meta.sources.map((s, i) => ({ key: s.name, label: s.display_name, value: s.jobs, color: SOURCE_COLORS[i % SOURCE_COLORS.length] }))}
          />
          <ul className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-2" aria-label="Sources">
            {meta.sources.map((s, i) => (
              <li key={s.name} className="flex items-center gap-3 text-sm">
                <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SOURCE_COLORS[i % SOURCE_COLORS.length] }} />
                <a href={s.homepage} target="_blank" rel="noopener" className="link font-medium">
                  {s.display_name}
                </a>
                <span className="tnum ml-auto text-ink-2">
                  {fmtInt(s.jobs)} <span className="text-ink-3">({fmtShare(s.jobs / total)})</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </Section>
    </Container>
  );
}
