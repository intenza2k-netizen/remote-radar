import type { Metadata } from "next";
import Link from "next/link";
import { EmptyNote, InsightSection } from "@/components/insights/insight-section";
import { LiftChart } from "@/components/insights/lift-chart";
import { PremiumChart } from "@/components/insights/premium-chart";
import { RoleSkillsGrid } from "@/components/insights/role-skills";
import { SkillNetwork } from "@/components/insights/skill-network";
import { PaySection } from "@/components/pay/pay-section";
import { Container, PageHeader } from "@/components/ui";
import { getMeta } from "@/lib/data";
import { fmtInt, roleLabel } from "@/lib/format";
import { buildNetwork, getInsights, graphHeadline, liftHeadline, prepareLift, premiumHeadline, premiumRoleNote, roleSkillsHeadline, strongestPairs } from "@/lib/insights";
import { windowCaption } from "@/lib/weeks";

export const metadata: Metadata = {
  title: "Insights",
  description:
    "Which skills carry a pay premium within the same role, seniority and region (with confidence intervals), what separates senior from junior postings, how skills cluster, and the top skills per role in remote job postings.",
  openGraph: {
    title: "Insights · Remote Radar",
    description: "Role-, seniority- and region-adjusted skill pay premiums with 95% intervals, senior vs junior skill lift, a skill co-occurrence map and top skills per role.",
  },
};

const JUMPS = [
  { href: "#premium", label: "Pay premium" },
  { href: "#pay", label: "Pay estimator" },
  { href: "#seniority", label: "Senior vs junior" },
  { href: "#map", label: "Skill map" },
  { href: "#roles", label: "Skills by role" },
];

export default function InsightsPage() {
  const meta = getMeta();
  const insights = getInsights();

  if (!insights) {
    return (
      <Container className="pb-8">
        <PageHeader eyebrow="Insights" title="Analysis is not published yet" lede="This page reads insights.json, which the nightly pipeline writes. It will fill in after the next run." />
        <div className="mt-8">
          <EmptyNote>
            Nothing to show right now. In the meantime, the <Link href="/skills" className="link">skills table</Link> and the <Link href="/jobs" className="link">job explorer</Link> are up to date.
          </EmptyNote>
        </div>
      </Container>
    );
  }

  const { skill_premium, seniority_lift, skill_graph, role_skills } = insights;
  const liftAll = prepareLift(seniority_lift);
  // A role with no senior or no junior postings has nothing to compare.
  const lift = liftAll.filter((r) => r.n_senior > 0 && r.n_junior > 0 && r.rows.length > 0);
  const liftSkipped = liftAll.filter((r) => !lift.includes(r));
  const network = skill_graph.nodes.length ? buildNetwork(skill_graph) : null;
  const pairs = strongestPairs(skill_graph, 12);
  const premiumTested = skill_premium.length;
  const chance = (premiumTested * 0.05).toFixed(1);

  return (
    <Container className="pb-8">
      <PageHeader
        eyebrow="Insights"
        title="What the postings say, and how far to trust it"
        lede={`${fmtInt(meta.totals.jobs)} remote postings (${windowCaption(meta)}); ${fmtInt(meta.totals.with_salary)} of them state a salary. Every comparison below shows its sample size, and rows that could be noise are greyed out rather than hidden.`}
      />
      <nav aria-label="On this page" className="mt-6 flex flex-wrap gap-2">
        {JUMPS.map((j) => (
          <a key={j.href} href={j.href} className="chip no-underline">
            {j.label}
          </a>
        ))}
      </nav>

      <div className="mt-10 space-y-14 sm:space-y-20">
        <InsightSection
          id="premium"
          name="Skill pay premium"
          headline={premiumHeadline(skill_premium) ?? "Not enough salaried postings yet to compare pay by skill."}
          howTo={
            <>
              Each row compares postings that mention a skill with postings of the same role, seniority and region group that do not, on advertised yearly salary. +12% means those postings advertise 12% more. The line is a 95% interval; greyed rows cross zero and could be noise. Switch to <em>raw difference</em> to see the plain gap in medians: the difference between the two views is the part explained by role, seniority and region.
            </>
          }
          details={
            <>
              <p>
                The adjusted view is a least-squares fit of log salary on the skill plus role (ten groups), seniority (intern to principal, or unspecified) and region group (US or Canada, Europe, Latin America, Asia-Pacific, worldwide, mixed or other, unknown), one skill at a time. The dollar figure is that percentage at the pay level of the postings that list the skill: what they advertise minus what they would advertise without the skill, all else equal. Not controlled for: company, the other skills a posting lists and the exact location (country, city, time zone), so a skill can still stand in for one of these.
              </p>
              <p>
                Postings from one company are not independent (a company board can bring dozens at similar pay), so each of the 1,000 bootstrap resamples draws whole <em>companies</em> with replacement and keeps all of a drawn company&rsquo;s salaried postings; both views use the same resamples, and a skill that rests on one or two employers gets a wide line. The intervals are not corrected for multiple comparisons{premiumTested ? `: with ${premiumTested} skills tested, about ${chance} "clear" rows would appear from luck alone` : ""}. Only skills with at least 15 salaried postings from at least 5 different companies are tested, and the headline is the skill whose adjusted interval stays furthest from zero, not the one with the biggest dot. This describes advertised pay and is an association, not a cause: it is not what learning a skill would add to your pay.
              </p>
            </>
          }
        >
          {skill_premium.length ? <PremiumChart rows={skill_premium} roleNote={premiumRoleNote(skill_premium)} /> : <EmptyNote>No skill has 15 or more salaried postings from at least 5 companies yet.</EmptyNote>}
        </InsightSection>

        <PaySection />

        <InsightSection
          id="seniority"
          name="What separates senior from junior postings"
          headline={liftHeadline(lift) ?? "Not enough senior and junior postings yet to compare skills."}
          howTo={
            <>
              Pick a role. Each row shows the share of senior postings (senior, lead, principal) and of junior postings (intern, junior, mid-level) that mention a skill; postings with unspecified seniority are left out. Lift is the senior share divided by the junior share. Greyed rows have a 95% interval (Newcombe) for the share difference that includes zero, so they could be noise. Only the ten skills with the largest lift are listed, so even clear rows probably overstate the real gap. Postings are counted one by one here (unlike the pay premium above), so a company that posts many similar roles can sway a share.
            </>
          }
        >
          {lift.length ? <LiftChart roles={lift} /> : <EmptyNote>No role has 30 or more postings with both senior and junior levels yet.</EmptyNote>}
          {liftSkipped.length ? (
            <p className="mt-4 text-xs text-ink-3">
              Not compared:{" "}
              {liftSkipped
                .map((r) => `${roleLabel(r.role)} (${r.n_senior === 0 ? "no senior postings" : r.n_junior === 0 ? "no junior postings" : `only ${r.n_junior} junior postings and no skill seen often enough`}, n = ${r.n_senior + r.n_junior})`)
                .join("; ")}
              .
            </p>
          ) : null}
        </InsightSection>

        <InsightSection
          id="map"
          name="Skill map"
          headline={graphHeadline(skill_graph) ?? "Not enough co-occurring skills yet to draw a map."}
          howTo={
            <>
              Each bubble is one of the {fmtInt(skill_graph.nodes.length)} most requested skills (area = postings, colour = category; the chips filter by category). A line joins two skills that appear together in at least 3 postings. Lines are ranked by pointwise mutual information (PMI): how much more often the pair occurs than if the two were independent, so a pair of two rare skills can outrank two common ones. Position comes from a force layout that pulls strongly coupled skills together; read clusters, not exact distances. Click a bubble to open the skill.
            </>
          }
        >
          {network ? (
            <>
              <SkillNetwork data={network} />
              <div className="mt-8">
                <h3 className="text-base font-semibold">Strongest pairs, as a table</h3>
                <p className="mt-1 max-w-3xl text-sm text-ink-3">The same data in text form. Pairs seen in fewer than 5 postings are left out when enough better-supported pairs exist.</p>
                <div className="mt-3 overflow-x-auto">
                  <table className="data-table">
                    <caption className="sr-only">Skill pairs with the highest pointwise mutual information</caption>
                    <thead>
                      <tr>
                        <th scope="col">Pair</th>
                        <th scope="col" className="num">Postings together</th>
                        <th scope="col" className="num">PMI</th>
                        <th scope="col" className="num">Times chance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pairs.map((p) => (
                        <tr key={`${p.a}|${p.b}`}>
                          <th scope="row" className="!text-sm !normal-case !tracking-normal !text-ink font-medium">
                            <Link href={`/skills/${p.a}`} className="text-ink no-underline hover:underline">
                              {p.aName}
                            </Link>{" "}
                            <span className="text-ink-3">+</span>{" "}
                            <Link href={`/skills/${p.b}`} className="text-ink no-underline hover:underline">
                              {p.bName}
                            </Link>
                          </th>
                          <td className="num">{fmtInt(p.count)}</td>
                          <td className="num">{p.pmi.toFixed(2)}</td>
                          <td className="num">{fmtInt(p.times)}×</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : (
            <EmptyNote>The skill graph is empty in this snapshot.</EmptyNote>
          )}
        </InsightSection>

        <InsightSection
          id="roles"
          name="Top skills by role"
          headline={roleSkillsHeadline(role_skills) ?? "No role has enough postings yet to list its top skills."}
          howTo={
            <>
              One card per role. A bar is the share of that role&rsquo;s postings that mention the skill, on one scale shared by every card so bar lengths are comparable. Roles with fewer than 30 postings are flagged: one or two postings move their shares a lot.
            </>
          }
        >
          {role_skills.length ? <RoleSkillsGrid rows={role_skills} /> : <EmptyNote>No role summaries in this snapshot.</EmptyNote>}
        </InsightSection>
      </div>
    </Container>
  );
}
