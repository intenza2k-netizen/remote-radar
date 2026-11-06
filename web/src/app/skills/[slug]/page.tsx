import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BarList } from "@/components/charts/bar-list";
import { SkillTrendChart } from "@/components/charts/skill-trend-chart";
import { JobRow } from "@/components/job-row";
import { Container, Delta, Kpi, Section } from "@/components/ui";
import { TrendEmptyState } from "@/components/trend-empty";
import { reliableTrend, reliableWeeks, trendReady, windowClause } from "@/lib/weeks";
import { getJobs, getMeta, getSkill, getSkillIndex, getSkills } from "@/lib/data";
import { categoryLabel, fmtInt, fmtShare, fmtUsdShort } from "@/lib/format";

export function generateStaticParams() {
  return getSkills().map((s) => ({ slug: s.slug }));
}

export async function generateMetadata({ params }: PageProps<"/skills/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const skill = getSkill(slug);
  if (!skill) return { title: "Skill not found" };
  const description = `${skill.name} is mentioned in ${fmtShare(skill.share)} of remote job postings (${fmtInt(skill.count)} jobs).${
    skill.median_salary_usd ? ` Median advertised salary ${fmtUsdShort(skill.median_salary_usd)}.` : ""
  } Weekly trend and co-occurring skills.`;
  return {
    title: skill.name,
    description,
    openGraph: { title: `${skill.name} in remote jobs · Remote Radar`, description },
  };
}

function SkillSkeleton() {
  return (
    <Container>
      <div className="pt-8 text-sm">
        <Link href="/skills" className="link">
          &larr; All skills
        </Link>
      </div>
      <div className="mt-6 space-y-4" role="status" aria-label="Loading skill">
        <div className="h-4 w-40 animate-pulse rounded bg-surface-2" />
        <div className="h-14 w-72 animate-pulse rounded bg-surface-2" />
        <div className="h-24 animate-pulse rounded bg-surface-2" />
      </div>
    </Container>
  );
}

// Reading `params` is the only request-time input; the Suspense boundary gives navigations an instant shell.
// Every slug is also prerendered at build time via generateStaticParams.
export default function SkillPage({ params }: PageProps<"/skills/[slug]">) {
  return (
    <Suspense fallback={<SkillSkeleton />}>
      <SkillContent params={params} />
    </Suspense>
  );
}

async function SkillContent({ params }: { params: PageProps<"/skills/[slug]">["params"] }) {
  const { slug } = await params;
  const skill = getSkill(slug);
  if (!skill) notFound();

  const meta = getMeta();
  const index = getSkillIndex();
  const jobs = getJobs();
  const matching = jobs.filter((j) => j.skills.includes(skill.slug)).sort((a, b) => b.posted_at.localeCompare(a.posted_at));
  const recent = matching.slice(0, 8);

  const skillNames = Object.fromEntries([...index.values()].map((s) => [s.slug, s.name]));
  const sourceNames = Object.fromEntries(meta.sources.map((s) => [s.name, s.display_name]));

  const co = skill.cooccurring
    .filter((c) => index.has(c.slug))
    .slice(0, 12)
    .map((c) => ({ ...c, skill: index.get(c.slug)!, pct: skill.count ? c.count / skill.count : 0 }));

  const weeks = reliableWeeks(meta);
  const trendOk = trendReady(weeks);
  const trend = reliableTrend(skill.trend, weeks);
  const rank = [...getSkills()].sort((a, b) => b.count - a.count).findIndex((s) => s.slug === skill.slug) + 1;

  return (
    <Container>
      <div className="pt-8 text-sm">
        <Link href="/skills" className="link">
          &larr; All skills
        </Link>
      </div>
      <header className="pb-2 pt-4">
        <p className="eyebrow mb-3">
          {categoryLabel(skill.category)} &middot; #{rank} of {fmtInt(meta.totals.skills)} by postings
        </p>
        <h1 className="text-balance text-4xl font-semibold leading-tight tracking-tight sm:text-6xl">{skill.name}</h1>
        <p className="mt-4 max-w-2xl text-lg text-ink-2">
          Mentioned in {fmtShare(skill.share)} of remote job postings {windowClause(meta)}.
        </p>
      </header>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Kpi label="Postings" value={fmtInt(skill.count)} sub={`of ${fmtInt(meta.totals.jobs)} tracked`} />
        <Kpi label="Share of postings" value={fmtShare(skill.share)} />
        {skill.change_4w == null ? (
          <Kpi label="4-week change" value={<span className="text-ink-3">&mdash;</span>} sub="needs 8 weeks of history" />
        ) : (
          <Kpi label="4-week change" value={<Delta pp={skill.change_4w} />} sub="vs the previous 4 weeks" />
        )}
        <Kpi label="Median salary" value={skill.median_salary_usd ? fmtUsdShort(skill.median_salary_usd) : "n/a"} sub={skill.median_salary_usd ? "USD / year, postings with pay" : "too few postings with pay"} />
      </div>

      <Section
        id="trend"
        title={`${skill.name} demand, week by week`}
        lede={trendOk ? "Share of each week's postings that mention the skill. Weeks with fewer than 20 postings are left out; the latest week may be partial." : undefined}
      >
        {trendOk ? (
          <SkillTrendChart name={skill.name} trend={trend} />
        ) : (
          <TrendEmptyState meta={meta} reliableCount={weeks.length} what={`the weekly share of postings that mention ${skill.name}`}>
            <p className="text-sm font-medium text-ink-2">Right now</p>
            <p className="mt-1 text-pretty text-ink-2">
              <span className="text-3xl font-semibold tracking-tight text-ink">{fmtShare(skill.share)}</span>{" "}
              of the {fmtInt(meta.totals.jobs)} postings collected so far mention {skill.name} ({fmtInt(skill.count)} postings).
            </p>
          </TrendEmptyState>
        )}
      </Section>

      <div className="grid gap-x-12 lg:grid-cols-[1fr_1.15fr]">
        <Section
          id="cooccurring"
          title={`What ${skill.name} is requested with`}
          lede={`Of the ${fmtInt(skill.count)} postings that mention ${skill.name}, the share that also mention each skill.`}
        >
          {co.length ? (
            <BarList
              ariaLabel={`Skills that co-occur with ${skill.name}`}
              items={co.map((c) => ({
                key: c.slug,
                label: c.skill.name,
                href: `/skills/${c.slug}`,
                value: c.pct,
                valueLabel: fmtShare(c.pct),
                sub: fmtInt(c.count),
                title: `${c.skill.name} appears in ${fmtShare(c.pct)} of ${skill.name} postings (${fmtInt(c.count)} jobs)`,
              }))}
            />
          ) : (
            <p className="text-ink-3">No co-occurring skills recorded.</p>
          )}
        </Section>

        <Section
          id="jobs"
          title="Recent matching jobs"
          lede={
            <>
              Latest of {fmtInt(matching.length)} postings in the snapshot.{" "}
              <Link href={`/jobs?skill=${skill.slug}`} className="link">
                Open all in the job explorer
              </Link>
              .
            </>
          }
        >
          {recent.length ? (
            <ul className="m-0 list-none p-0">
              {recent.map((j) => (
                <JobRow key={j.id} job={j} skillNames={skillNames} sourceNames={sourceNames} maxSkills={4} />
              ))}
            </ul>
          ) : (
            <p className="text-ink-3">No postings in the published job list mention this skill.</p>
          )}
        </Section>
      </div>
    </Container>
  );
}
