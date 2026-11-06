import type { Metadata } from "next";
import Link from "next/link";
import { LocationExplorer } from "@/components/geo/location-explorer";
import { RegionMix } from "@/components/geo/region-mix";
import { EmptyNote } from "@/components/insights/insight-section";
import { Container, PageHeader, Section } from "@/components/ui";
import { getJobs, getMeta } from "@/lib/data";
import { fmtInt, fmtShare } from "@/lib/format";
import { leadSentence } from "@/lib/geo";
import { getGeo } from "@/lib/geo-data";

const DESCRIPTION =
  "Remote often means remote within one country. Pick where you live and see how many remote postings, and how many data roles, are actually open to applicants there, what they pay and which skills they ask for.";

export const metadata: Metadata = {
  title: "Locations",
  description: DESCRIPTION,
  openGraph: { title: "Where you can work from · Remote Radar", description: DESCRIPTION },
};

export default function LocationsPage() {
  const geo = getGeo();

  if (!geo) {
    return (
      <Container className="pb-8">
        <PageHeader eyebrow="Locations" title="Location data is not published yet" lede="This page reads geo.json, which the nightly pipeline writes. It will fill in after the next run." />
        <div className="mt-8">
          <EmptyNote>
            Nothing to show right now. Browse the <Link href="/jobs" className="link">job explorer</Link> instead.
          </EmptyNote>
        </div>
      </Container>
    );
  }

  const meta = getMeta();
  const listed = geo.summary?.listed_jobs ?? meta.totals.active ?? getJobs().length;
  const unknown = geo.summary?.unknown_jobs ?? geo.unknown_jobs;
  const windowJobs = geo.region_mix.reduce((n, r) => n + r.n, 0);
  const sanctioned = geo.sanctioned ?? [];
  const usCanada =geo.region_mix.find((r) => r.group === "us_canada");

  return (
    <Container className="pb-12">
      <PageHeader eyebrow="Locations" title="Where can you work from?" lede={leadSentence(geo)} />

      <div className="mt-8">
        <LocationExplorer rows={geo.by_location} listed={listed} />
      </div>

      <Section
        id="mix"
        title={usCanada ? `${fmtShare(usCanada.share)} of remote postings are aimed at the United States or Canada` : "Who remote postings are open to"}
        lede={`Each of the ${fmtInt(windowJobs)} postings of the last eight weeks, closed or still open, put into one group by the places it names. Any mention of the United States, Canada or North America counts as the first group; a mix such as "Germany, India" lands in "Other or mixed". The figure after the percentage is the median advertised pay of that group, shown with at least 5 postings that state pay.`}
      >
        <RegionMix rows={geo.region_mix} />
      </Section>

      <Section id="caveats" title="What this can and cannot tell you">
        <div className="prose-lite text-sm">
          <ul>
            <li>
              <strong>Postings state regions vaguely.</strong> The place is read from free text by a language model, then mapped to country and region names. &quot;Remote (EMEA)&quot; or &quot;US time zones&quot; may be read more narrowly or more broadly than the employer meant.
            </li>
            <li>
              <strong>&quot;Worldwide&quot; may still have limits.</strong> Many employers that say worldwide still need overlap with a time zone, or can only hire where they have a legal entity or a contractor agreement. Treat worldwide postings as open in principle, and check the posting.
              {sanctioned.length ? ` Worldwide is not counted as open to places under comprehensive sanctions (${sanctioned.join(", ")}): only a posting that names them is.` : ""}
            </li>
            <li>
              <strong>{fmtInt(unknown)} listed postings name no region at all</strong> ({fmtShare(listed ? unknown / listed : 0)}). They are left out of every count above rather than guessed at, so the real numbers are somewhat higher for everyone.
            </li>
            <li>
              <strong>Regions are matched by membership.</strong> A posting for &quot;EU&quot; is open to Estonia because Estonia is one of the 27 members; a posting for &quot;Germany&quot; is not open to &quot;Europe&quot;. When you choose a region, a posting must cover all of it. Mexico counts as Latin America, not North America; the United Kingdom and Switzerland count as Europe but not as EU.
            </li>
            <li>
              <strong>Pay is what is advertised.</strong> Only postings that state a salary count, converted to US dollars a year at a fixed rate, so a location with few of them shows no figure.
            </li>
          </ul>
        </div>
      </Section>
    </Container>
  );
}
