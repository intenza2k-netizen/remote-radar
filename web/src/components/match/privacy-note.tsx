export function PrivacyNote() {
  return (
    <aside className="card flex gap-3 p-4 sm:p-5" aria-labelledby="privacy-h">
      <svg className="mt-0.5 shrink-0 text-[var(--s3)]" width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="4.5" y="10.5" width="15" height="10" rx="2.2" stroke="currentColor" strokeWidth="1.7" />
        <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
        <circle cx="12" cy="15.5" r="1.4" fill="currentColor" />
      </svg>
      <div className="text-sm text-ink-2">
        <h2 id="privacy-h" className="text-base font-semibold text-ink">
          Your CV never leaves this browser
        </h2>
        <p className="mt-1 max-w-3xl">
          Reading, skill detection and matching all run on your device. Nothing is uploaded, logged or stored: close the tab and it is gone. The only network
          requests are this site&apos;s own job data and, the first time you run a match, the language model (about 30 MB, downloaded once from Hugging Face and
          cached by your browser). You can check the Network tab yourself.
        </p>
      </div>
    </aside>
  );
}
