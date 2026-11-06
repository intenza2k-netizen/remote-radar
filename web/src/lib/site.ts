export const SITE_NAME = "Remote Radar";
export const SITE_TAGLINE = "What remote employers actually ask for";
export const SITE_DESCRIPTION =
  "A nightly-updated snapshot of the remote job market: which skills, seniority levels and salaries show up in postings from Remotive, Remote OK, Arbeitnow and Jobicy, extracted with an LLM.";

export const GITHUB_URL = "https://github.com/intenza2k-netizen/remote-radar";

export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://remote-radar-nine.vercel.app";

/** Attribution list. Always named on the methodology page regardless of snapshot contents. */
export const ATTRIBUTION = [
  { name: "Remotive", homepage: "https://remotive.com", note: "Remote jobs API" },
  { name: "Remote OK", homepage: "https://remoteok.com", note: "Remote jobs API; links must stay followed and credit Remote OK" },
  { name: "Arbeitnow", homepage: "https://www.arbeitnow.com", note: "Free job board API" },
  { name: "Jobicy", homepage: "https://jobicy.com", note: "Remote jobs API" },
] as const;

export const NAV = [
  { href: "/", label: "Overview" },
  { href: "/skills", label: "Skills" },
  { href: "/jobs", label: "Jobs" },
  { href: "/methodology", label: "Methodology" },
] as const;
