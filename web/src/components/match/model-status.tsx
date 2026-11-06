import type { ReactNode } from "react";
import type { ModelState } from "@/lib/match/embedder";

export type EmbedPhase = "idle" | "working" | "done" | "failed" | "unavailable";

type Props = {
  model: ModelState;
  embed: EmbedPhase;
  hasVectors: boolean;
  onRetry: () => void;
};

/** One polite live region that tells the viewer which ranking they are looking at and why. */
export function ModelStatus({ model, embed, hasVectors, onRetry }: Props) {
  let body: ReactNode;
  let tone: "info" | "ok" | "warn" = "info";

  if (!hasVectors) {
    tone = "warn";
    body = <>Semantic data for the jobs is unavailable, so the ranking uses skills, seniority and role only.</>;
  } else if (model.phase === "error" || embed === "failed") {
    tone = "warn";
    body = (
      <>
        <span>
          The language model could not be loaded{model.phase === "error" ? ` (${model.message})` : ""}. The ranking uses skills, seniority and role only.
        </span>{" "}
        <button type="button" className="text-accent underline underline-offset-4" onClick={onRetry}>
          Try again
        </button>
      </>
    );
  } else if (model.phase === "loading" || model.phase === "idle") {
    const pct = model.phase === "loading" ? Math.round(model.progress * 100) : 0;
    body = (
      <div className="w-full">
        <p>
          Loading the language model (one-time download of about 30 MB, then cached){pct > 0 ? `: ${pct}%` : "..."} Showing a skills-based ranking meanwhile;
          it will update when the model is ready.
        </p>
        <div
          role="progressbar"
          aria-label="Language model download"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          className="mt-2 h-2 w-full overflow-hidden rounded-full bg-[var(--grid)]"
        >
          <div className="h-2 rounded-r-[4px] bg-[var(--bar)] transition-[width] duration-200" style={{ width: `${Math.max(pct, 2)}%` }} />
        </div>
      </div>
    );
  } else if (embed === "working") {
    body = <>Model loaded. Reading your CV with it...</>;
  } else {
    tone = "ok";
    body = <>Ranking includes semantic similarity from the language model, running locally in your browser.</>;
  }

  const dot = tone === "ok" ? "bg-[var(--s3)]" : tone === "warn" ? "bg-[var(--s4)]" : "bg-[var(--s1)]";
  return (
    <div role="status" aria-live="polite" className="card flex items-start gap-3 px-4 py-3 text-sm text-ink-2">
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">{body}</div>
    </div>
  );
}
