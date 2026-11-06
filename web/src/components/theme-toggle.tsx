"use client";

/**
 * Light/dark toggle. The resolved theme lives on <html data-theme>, which the
 * inline script in the root layout sets before first paint; icons switch via CSS,
 * so this component needs no React state and cannot cause a hydration mismatch.
 */
export function ThemeToggle() {
  function toggle() {
    const root = document.documentElement;
    const current =
      root.dataset.theme === "dark" || root.dataset.theme === "light"
        ? root.dataset.theme
        : window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    const next = current === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("rr-theme", next);
    } catch {
      /* storage may be blocked; the choice then lasts for this page view only */
    }
  }

  return (
    <button type="button" onClick={toggle} className="btn !min-h-9 !w-9 !p-0" aria-label="Toggle light and dark theme" title="Toggle theme">
      <svg className="theme-sun" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
      <svg className="theme-moon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
      </svg>
    </button>
  );
}
