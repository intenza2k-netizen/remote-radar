import Link from "next/link";
import { fmtDateTime } from "@/lib/format";
import { ATTRIBUTION, GITHUB_URL, SITE_NAME } from "@/lib/site";

export function SiteFooter({ generatedAt, sample }: { generatedAt: string; sample: boolean }) {
  return (
    <footer className="mt-24 border-t border-line">
      <div className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-10 text-sm text-ink-3 sm:px-6 md:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          <p className="text-ink-2">
            <strong className="font-semibold text-ink">{SITE_NAME}</strong> is a portfolio project: a nightly Python pipeline, an LLM extraction step and a static snapshot rendered by this site.
          </p>
          <p>
            Data updated <time dateTime={generatedAt}>{fmtDateTime(generatedAt)}</time>
            {sample ? " (sample data)" : ""}. Postings come from{" "}
            {ATTRIBUTION.map((s, i) => (
              <span key={s.name}>
                <a className="link" href={s.homepage} target="_blank" rel="noopener">
                  {s.name}
                </a>
                {i < ATTRIBUTION.length - 2 ? ", " : i === ATTRIBUTION.length - 2 ? " and " : ""}
              </span>
            ))}
            .
          </p>
        </div>
        <ul className="flex flex-wrap items-start gap-x-5 gap-y-2 md:justify-end">
          <li>
            <Link className="link" href="/methodology">
              Methodology
            </Link>
          </li>
          <li>
            <a className="link" href={GITHUB_URL} target="_blank" rel="noopener">
              GitHub
            </a>
          </li>
        </ul>
      </div>
    </footer>
  );
}
