"use client";

import { useRef, useState, type DragEvent } from "react";
import { fmtInt } from "@/lib/format";
import { MIN_CV_CHARS } from "@/lib/match/constants";

export type FileInfo = { name: string; kind: "pdf" | "docx" | "text"; chars: number };

type Props = {
  text: string;
  onText: (t: string) => void;
  fileInfo: FileInfo | null;
  /** Picked file; the parent parses it (lazy-loaded) and reports status back. */
  onFile: (f: File) => void;
  parsing: boolean;
  parseError: string | null;
  onSample: () => void;
  onClear: () => void;
  onAnalyse: () => void;
  busy: boolean;
  /** True when the text differs from what the current results are based on. */
  stale: boolean;
  hasResults: boolean;
};

export function CvInput({ text, onText, fileInfo, onFile, parsing, parseError, onSample, onClear, onAnalyse, busy, stale, hasResults }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const chars = text.trim().length;
  const tooShort = chars < MIN_CV_CHARS;

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  }

  return (
    <div className="card p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor="cv-text" className="text-base font-semibold">
          Your CV
        </label>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn" onClick={() => fileRef.current?.click()} disabled={parsing}>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M8 11V2.5M4.5 6 8 2.5 11.5 6M2.5 11v2.5h11V11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Upload PDF or DOCX
          </button>
          <button type="button" className="btn" onClick={onSample}>
            Try a sample CV
          </button>
          {text ? (
            <button type="button" className="btn" onClick={onClear}>
              Clear
            </button>
          ) : null}
        </div>
        <input
          ref={fileRef}
          id="cv-file"
          type="file"
          className="sr-only"
          tabIndex={-1}
          aria-label="Upload a CV file (PDF, DOCX or plain text)"
          accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) onFile(f);
          }}
        />
      </div>

      <div
        className={`mt-3 rounded-lg ${drag ? "outline-2 outline-dashed outline-[var(--accent)]" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <textarea
          id="cv-text"
          className="field block min-h-[15rem] w-full resize-y leading-relaxed"
          style={{ fontFamily: "var(--font-geist-mono), ui-monospace, monospace", fontSize: "0.8125rem" }}
          placeholder="Paste your CV here, drop a PDF or DOCX onto this box, or use the buttons above. Plain text works best: summary, experience, skills."
          spellCheck={false}
          value={text}
          onChange={(e) => onText(e.target.value)}
          aria-describedby="cv-hint"
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm text-ink-3" id="cv-hint">
        <p role="status" aria-live="polite" className="min-w-0">
          {parsing ? (
            "Reading the file in your browser..."
          ) : parseError ? (
            <span className="text-[var(--s8)]" role="alert">
              {parseError}
            </span>
          ) : fileInfo ? (
            <>
              Extracted <strong className="tnum font-semibold text-ink-2">{fmtInt(fileInfo.chars)}</strong> characters from {fileInfo.name}. Check the text below and fix anything the
              extraction got wrong.
            </>
          ) : (
            <>
              <strong className="tnum font-semibold text-ink-2">{fmtInt(chars)}</strong> characters{chars > 0 && tooShort ? ` (add a little more: at least ${MIN_CV_CHARS})` : ""}. Editable.
            </>
          )}
        </p>
        <p className="text-xs">Processed on this device only.</p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onAnalyse}
          disabled={tooShort || busy || parsing}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-transparent bg-ink px-5 text-sm font-semibold text-bg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
        >
          {hasResults ? (stale ? "Update matches" : "Re-run matching") : "Find matching jobs"}
        </button>
        {stale && hasResults ? <p className="text-sm text-ink-2">You edited the text. Update to refresh skills and matches.</p> : null}
        {!hasResults && tooShort ? <p className="text-sm text-ink-3">Paste at least a few lines, or try the sample CV.</p> : null}
      </div>
    </div>
  );
}
