import Link from "next/link";
import { NavLinks } from "./nav-links";
import { ThemeToggle } from "./theme-toggle";
import { SITE_NAME } from "@/lib/site";

export function SiteHeader({ sample }: { sample: boolean }) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/90 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-1 px-4 py-2 sm:px-6">
        <Link href="/" className="flex items-center gap-2 py-1 font-semibold tracking-tight text-ink no-underline" aria-label={`${SITE_NAME} home`}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="10" stroke="var(--ink)" strokeWidth="1.6" />
            <circle cx="12" cy="12" r="5.5" stroke="var(--ink)" strokeWidth="1.6" opacity="0.55" />
            <path d="M12 12 19 6.5" stroke="var(--s1)" strokeWidth="2" strokeLinecap="round" />
            <circle cx="16.5" cy="14.5" r="1.8" fill="var(--s2)" />
          </svg>
          <span>{SITE_NAME}</span>
        </Link>
        <div className="order-2 flex items-center gap-2 sm:order-3">
          {sample ? (
            <span
              className="rounded-full border border-line-strong px-2.5 py-0.5 text-xs font-medium text-ink-2"
              title="This site is currently showing generated sample data, not live postings."
            >
              Sample data
            </span>
          ) : null}
          <ThemeToggle />
        </div>
        <div className="order-3 -ml-2.5 w-full sm:order-2 sm:ml-0 sm:w-auto">
          <NavLinks />
        </div>
      </div>
    </header>
  );
}
