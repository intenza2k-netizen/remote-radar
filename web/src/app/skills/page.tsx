import type { Metadata } from "next";
import { SkillsTable } from "@/components/skills-table";
import { Container, PageHeader } from "@/components/ui";
import { reliableTrend, reliableWeeks, trendReady, weekPos, windowClause } from "@/lib/weeks";
import { getMeta, getSkills } from "@/lib/data";
import { fmtInt } from "@/lib/format";

export const metadata: Metadata = {
  title: "Skills",
  description: "Every skill extracted from remote job postings: how many jobs mention it, its share, four-week change, median advertised salary and weekly trend.",
  openGraph: { title: "Skills · Remote Radar", description: "Searchable, sortable table of skills in remote job postings." },
};

export default function SkillsPage() {
  const meta = getMeta();
  const skills = getSkills();
  const weeks = reliableWeeks(meta);
  const trendOk = trendReady(weeks);
  const hasChange = skills.some((s) => s.change_4w != null);
  const rows = skills.map((s) => ({
    slug: s.slug,
    name: s.name,
    category: s.category,
    count: s.count,
    share: s.share,
    change_4w: s.change_4w,
    median_salary_usd: s.median_salary_usd,
    trend: trendOk ? reliableTrend(s.trend, weeks).map((t) => t.share) : [],
  }));
  return (
    <Container className="pb-8">
      <PageHeader
        eyebrow="Skills"
        title={`${fmtInt(skills.length)} skills in ${fmtInt(meta.totals.jobs)} remote job postings`}
        lede={`Share is the fraction of postings ${windowClause(meta)} that mention the skill.${hasChange ? " Change compares the last four weeks with the four before, in percentage points (pp)." : ""}${trendOk ? "" : " Weekly trends appear once two weeks have 20+ postings."}`}
      />
      <div className="mt-8">
        <SkillsTable rows={rows} weekPositions={weeks.map(weekPos)} showChange={hasChange} />
      </div>
    </Container>
  );
}
