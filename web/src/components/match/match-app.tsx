"use client";

import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { CvInput, type FileInfo } from "./cv-input";
import { GapPanel } from "./gap-panel";
import { JobTypeFit } from "./job-type-fit";
import { ModelStatus, type EmbedPhase } from "./model-status";
import { NextSkillPanel } from "./next-skill-panel";
import { PayEstimate } from "./pay-estimate";
import { PreferencesForm } from "./preferences-form";
import { PrivacyNote } from "./privacy-note";
import { ResultsList } from "./results-list";
import { SkillChips } from "./skill-chips";
import { useStoredLocation } from "@/components/geo/use-stored-location";
import type { PickerOption } from "@/components/skill-picker";
import { roleLabel, seniorityLabel, skillLabel } from "@/lib/format";
import { TOP_N } from "@/lib/match/constants";
import { loadJobVectors, loadVocab } from "@/lib/match/data-client";
import type { Embedder, ModelState } from "@/lib/match/embedder";
import type { MatchExtras } from "@/lib/match/extras";
import { gapHeadline, rankGaps } from "@/lib/match/gap";
import { jobTypeMix } from "@/lib/match/job-types";
import { filterByLocation, locationStatus, regionGroupForLocation, validLocation } from "@/lib/match/location";
import { rankNextSkills } from "@/lib/match/next-skill";
import { buildOptions } from "@/lib/match/options";
import { buildPayProfile, estimateForProfile } from "@/lib/match/pay-profile";
import { SAMPLE_CV } from "@/lib/match/sample-cv";
import { scoreJobs } from "@/lib/match/score";
import { inferSeniority } from "@/lib/match/seniority";
import { DEFAULT_PREFS, type DetectedSkill, type Preferences, type SeniorityGuess, type VocabEntry } from "@/lib/match/types";
import { chunkCv, combineVectors, similarities, summaryText } from "@/lib/match/vectors";
import { compileVocab, detectSkills, vocabFromSkills } from "@/lib/match/vocab";
import { regionGroupLabel } from "@/lib/salary-model";
import type { Job } from "@/lib/types";

type Props = {
  jobs: Job[];
  /** Skills that exist in the market snapshot (skills.json): names, counts, and which slugs have a /skills page. */
  skills: PickerOption[];
  /** Display name of every skill slug used by `jobs` (skills.json only has the top 300). */
  skillNames?: Record<string, string>;
  sourceNames: Record<string, string>;
  /** Job types, pay model and location data from the v4 snapshot files; each part is null when its file is missing. */
  extras: MatchExtras;
};

type Analysis = { text: string; detected: DetectedSkill[]; guess: SeniorityGuess; fallbackVocab: boolean };
type JobVecs = Awaited<ReturnType<typeof loadJobVectors>>;

export function MatchApp({ jobs, skills: marketSkills, skillNames, sourceNames, extras }: Props) {
  const [text, setText] = useState("");
  const [fileInfo, setFileInfo] = useState<FileInfo | null>(null);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFS);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [skills, setSkills] = useState<string[]>([]);
  const [vocab, setVocab] = useState<VocabEntry[] | null>(null);
  const [jobVecs, setJobVecs] = useState<JobVecs>(null);
  const [model, setModel] = useState<ModelState>({ phase: "idle" });
  const [embedPhase, setEmbedPhase] = useState<EmbedPhase>("idle");
  const [textVecs, setTextVecs] = useState<Float32Array[] | null>(null);
  const [cvVec, setCvVec] = useState<Float32Array | null>(null);
  const [busy, setBusy] = useState(false);
  const { jobTypes, salaryModel, geo } = extras;
  const [storedLocation, setLocation] = useStoredLocation();

  const embedderRef = useRef<Embedder | null>(null);
  const runId = useRef(0);
  const summarised = useRef(false);

  // Warm the site's own small data files while the visitor is still reading or pasting.
  useEffect(() => {
    const warm = () => {
      void loadVocab();
      void loadJobVectors();
    };
    if ("requestIdleCallback" in window) {
      const h = window.requestIdleCallback(warm);
      return () => window.cancelIdleCallback(h);
    }
    const t = setTimeout(warm, 800);
    return () => clearTimeout(t);
  }, []);

  useEffect(
    () => () => {
      runId.current++;
      embedderRef.current?.terminate();
    },
    [],
  );

  const options = useMemo(() => buildOptions(jobs), [jobs]);
  const countOf = useMemo(() => new Map(marketSkills.map((s) => [s.slug, s.count])), [marketSkills]);
  const linkable = useMemo(() => new Set(marketSkills.map((s) => s.slug)), [marketSkills]);
  const names = useMemo(() => {
    const m: Record<string, string> = {};
    for (const v of vocab ?? []) m[v.slug] = v.name;
    Object.assign(m, skillNames); // published names for every skill in jobs.json
    for (const s of marketSkills) m[s.slug] = s.name; // curated names win
    // Only reached with an older snapshot that has no skill_names: "exploratory-data-analysis" -> "Exploratory Data Analysis".
    for (const j of jobs) for (const s of j.skills) if (!m[s]) m[s] = skillLabel(s);
    return m;
  }, [vocab, marketSkills, skillNames, jobs]);
  const pickerOptions = useMemo<PickerOption[]>(() => {
    const base = vocab ? vocab.map((v) => ({ slug: v.slug, name: v.name, category: v.category, count: countOf.get(v.slug) ?? 0 })) : marketSkills;
    return [...base].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }, [vocab, marketSkills, countOf]);

  const level = prefs.seniority || analysis?.guess.level || null;
  const mentions = useMemo(() => new Map((analysis?.detected ?? []).map((d) => [d.slug, d])), [analysis]);
  const edited = useMemo(() => {
    const det = (analysis?.detected ?? []).map((d) => d.slug);
    return det.length !== skills.length || det.some((s) => !skills.includes(s));
  }, [analysis, skills]);

  // ---- embedding ----------------------------------------------------------------------------
  const getEmbedder = useCallback(async () => {
    if (!embedderRef.current) {
      const { Embedder } = await import("@/lib/match/embedder");
      embedderRef.current = new Embedder(setModel);
    }
    return embedderRef.current;
  }, []);

  const embedText = useCallback(
    async (id: number, cv: string, prefix: string) => {
      setEmbedPhase("working");
      setTextVecs(null);
      setCvVec(null);
      summarised.current = false;
      try {
        const embedder = await getEmbedder();
        const vecs = await embedder.embed(chunkCv(cv).map((c) => prefix + c));
        if (id !== runId.current) return;
        setTextVecs(vecs);
        setEmbedPhase("done");
      } catch {
        if (id === runId.current) setEmbedPhase("failed");
      }
    },
    [getEmbedder],
  );

  // The "skills and roles" summary is re-embedded (one short passage) when chips, roles or level change.
  const queryPrefix = jobVecs?.queryPrefix ?? "";
  useEffect(() => {
    const embedder = embedderRef.current;
    if (!textVecs || !embedder) return;
    let cancelled = false;
    const run = async () => {
      const s = summaryText(
        skills.map((x) => skillLabel(x, names)),
        prefs.roles.map(roleLabel),
        level ? seniorityLabel(level) : null,
      );
      let vec: Float32Array | null = null;
      if (s) {
        try {
          vec = (await embedder.embed([queryPrefix + s]))[0];
        } catch {
          vec = null;
        }
      }
      if (cancelled) return;
      summarised.current = true;
      setCvVec(combineVectors(textVecs, vec));
    };
    const t = setTimeout(run, summarised.current ? 350 : 0);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [textVecs, skills, prefs.roles, level, names, queryPrefix]);

  // ---- analysis -----------------------------------------------------------------------------
  const analyse = useCallback(
    async (cv: string) => {
      const id = ++runId.current;
      setBusy(true);
      const [vocabLoaded, vecs] = await Promise.all([loadVocab(), loadJobVectors()]);
      if (id !== runId.current) return;
      const entries = vocabLoaded ?? vocabFromSkills(marketSkills);
      const detected = detectSkills(cv, compileVocab(entries));
      setVocab(vocabLoaded);
      setJobVecs(vecs);
      setAnalysis({ text: cv, detected, guess: inferSeniority(cv), fallbackVocab: !vocabLoaded });
      setSkills(detected.map((d) => d.slug));
      setBusy(false);
      if (vecs) void embedText(id, cv, vecs.queryPrefix);
      else {
        setEmbedPhase("unavailable");
        setTextVecs(null);
        setCvVec(null);
      }
    },
    [marketSkills, embedText],
  );

  const retryModel = useCallback(() => {
    if (!analysis || !jobVecs) return;
    const id = ++runId.current;
    void embedText(id, analysis.text, jobVecs.queryPrefix);
  }, [analysis, jobVecs, embedText]);

  async function handleFile(f: File) {
    setParsing(true);
    setParseError(null);
    try {
      const { extractTextFromFile } = await import("@/lib/match/parse-file");
      const r = await extractTextFromFile(f);
      setText(r.text);
      setFileInfo({ name: f.name, kind: r.kind, chars: r.text.length });
      void analyse(r.text);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "Could not read that file.");
    } finally {
      setParsing(false);
    }
  }

  function clearAll() {
    runId.current++;
    setText("");
    setFileInfo(null);
    setParseError(null);
    setAnalysis(null);
    setSkills([]);
    setTextVecs(null);
    setCvVec(null);
    setEmbedPhase("idle");
    setBusy(false);
  }

  // ---- results ------------------------------------------------------------------------------
  const cosines = useMemo(() => (cvVec && jobVecs ? similarities(cvVec, jobVecs.decoded) : null), [cvVec, jobVecs]);
  // "I can work from": only postings open to the chosen location are scored at all. A remembered value that is not
  // one of this snapshot's options is ignored.
  const locationOpts = useMemo(() => (geo ? { regions: geo.regions, countries: geo.countries } : null), [geo]);
  const location = useMemo(
    () => (geo ? validLocation(storedLocation, [...geo.regions, ...geo.countries].map((o) => o.value)) : ""),
    [geo, storedLocation],
  );
  const located = useMemo(() => filterByLocation(jobs, location, geo?.memberships ?? null, geo?.sanctioned), [jobs, location, geo]);
  const locationNote = locationStatus(location, jobs.length, located);
  const locationPayNote = useMemo(() => {
    if (!location || !salaryModel) return "";
    const group = regionGroupForLocation(location);
    return group ? `The pay estimate uses ${regionGroupLabel(group)}.` : "The pay estimate uses US or Canada (this location is in none of the model's region groups).";
  }, [location, salaryModel]);
  const scored = useMemo(
    () => (analysis ? scoreJobs({ jobs: located.kept, cvSkills: new Set(skills), level, prefs, cosines }) : []),
    [analysis, located, skills, level, prefs, cosines],
  );
  const top = useMemo(() => scored.slice(0, TOP_N), [scored]);
  const gaps = useMemo(() => rankGaps(top, (s) => countOf.get(s) ?? 0), [top, countOf]);
  const headline = useMemo(() => gapHeadline(gaps, top.length, (s) => skillLabel(s, names)), [gaps, top.length, names]);
  const stale = analysis != null && analysis.text !== text;

  // Which job type you fit, and the pay estimate for your profile.
  const assignment = useMemo(() => (jobTypes ? new Map(Object.entries(jobTypes.assignment)) : null), [jobTypes]);
  const mix = useMemo(() => (assignment && jobTypes ? jobTypeMix(scored, assignment, jobTypes.names, TOP_N) : null), [scored, assignment, jobTypes]);
  const payResult = useMemo(() => {
    if (!salaryModel) return null;
    const profile = buildPayProfile({ roles: prefs.roles, level, location, skills });
    return profile ? estimateForProfile(salaryModel, profile, skills) : null;
  }, [salaryModel, prefs.roles, level, location, skills]);

  // Next skill to learn: re-scores only the skills part, and runs one render behind so typing in the skill box stays smooth.
  const deferredScored = useDeferredValue(scored);
  const deferredSkills = useDeferredValue(skills);
  const nextSkills = useMemo(() => rankNextSkills(deferredScored, new Set(deferredSkills)), [deferredScored, deferredSkills]);

  return (
    <div className="mt-8 flex flex-col gap-6">
      <PrivacyNote />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)] lg:items-start">
        <CvInput
          text={text}
          onText={(t) => {
            setText(t);
            setFileInfo(null);
          }}
          fileInfo={fileInfo}
          onFile={handleFile}
          parsing={parsing}
          parseError={parseError}
          onSample={() => {
            setText(SAMPLE_CV);
            setFileInfo(null);
            setParseError(null);
            void analyse(SAMPLE_CV);
          }}
          onClear={clearAll}
          onAnalyse={() => void analyse(text)}
          busy={busy}
          stale={stale}
          hasResults={analysis != null}
        />
        <PreferencesForm
          prefs={prefs}
          onChange={setPrefs}
          options={options}
          guess={analysis?.guess ?? null}
          locations={locationOpts}
          location={location}
          onLocation={setLocation}
          locationNote={locationNote}
          locationPayNote={locationPayNote}
        />
      </div>

      {analysis ? (
        <>
          {analysis.fallbackVocab ? (
            <p className="rounded-lg border border-dashed border-line-strong p-3 text-sm text-ink-2" role="status">
              The skill vocabulary file could not be loaded, so detection uses the skills seen in current postings only.
            </p>
          ) : null}
          <SkillChips
            skills={skills}
            names={names}
            mentions={mentions}
            options={pickerOptions}
            onAdd={(s) => setSkills((cur) => (cur.includes(s) ? cur : [...cur, s]))}
            onRemove={(s) => setSkills((cur) => cur.filter((x) => x !== s))}
            onReset={() => setSkills(analysis.detected.map((d) => d.slug))}
            edited={edited}
          />
          <ModelStatus model={model} embed={embedPhase} hasVectors={jobVecs != null} onRetry={retryModel} />

          {top.length && (mix || salaryModel) ? (
            <div className={`grid gap-6 ${mix && salaryModel ? "md:grid-cols-2" : ""} md:items-start`}>
              {mix ? <JobTypeFit mix={mix} limit={TOP_N} /> : null}
              {salaryModel ? <PayEstimate model={salaryModel} result={payResult} location={location} names={names} /> : null}
            </div>
          ) : null}

          {top.length ? (
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_23rem] lg:items-start">
              <aside
                className="flex flex-col gap-6 lg:sticky lg:top-20 lg:order-2 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-1"
                aria-label="Skills to learn"
              >
                <GapPanel headline={headline} gaps={gaps} total={top.length} names={names} linkable={linkable} />
                <NextSkillPanel rows={nextSkills} names={names} linkable={linkable} model={salaryModel} topN={TOP_N} hasSkills={skills.length > 0} />
              </aside>
              <div className="min-w-0">
                <h2 className="text-2xl font-semibold tracking-tight">Your best matches</h2>
                <p className="mb-4 mt-1 text-sm text-ink-3">
                  Each score is a transparent blend of similarity, skills, seniority and role. Open &ldquo;Why this match&rdquo; on any card to see the arithmetic.
                </p>
                <ResultsList matches={top} names={names} sourceNames={sourceNames} linkable={linkable} filteredOut={jobs.length - scored.length} />
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-line-strong p-10 text-center">
              <p className="font-medium">No jobs pass your preferences</p>
              <p className="mt-1 text-sm text-ink-3">Remove the location, region, salary or &ldquo;only jobs that state a salary&rdquo; filter to see matches.</p>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
