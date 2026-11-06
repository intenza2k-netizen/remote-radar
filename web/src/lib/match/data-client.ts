import { decodeJobVectors } from "./vectors";
import type { DecodedVectors, JobVectorsFile, VocabEntry } from "./types";

/**
 * Client-side loaders for the two v2 snapshot files. Both are the site's own static files;
 * they are fetched once per page view and memoised. A missing or malformed file resolves to
 * null so the matcher can degrade (skills-only matching, or a vocabulary built from skills.json).
 */

let vocabPromise: Promise<VocabEntry[] | null> | null = null;
let vectorsPromise: Promise<{ decoded: DecodedVectors; queryPrefix: string } | null> | null = null;

export function loadVocab(): Promise<VocabEntry[] | null> {
  vocabPromise ??= fetch("/data/skill_vocab.json")
    .then((r) => (r.ok ? (r.json() as Promise<VocabEntry[]>) : null))
    .then((v) => (Array.isArray(v) && v.length ? v : null))
    .catch(() => null);
  return vocabPromise;
}

export function loadJobVectors(): Promise<{ decoded: DecodedVectors; queryPrefix: string } | null> {
  vectorsPromise ??= fetch("/data/job_vectors.json")
    .then((r) => (r.ok ? (r.json() as Promise<JobVectorsFile>) : null))
    .then((f) => (f ? { decoded: decodeJobVectors(f), queryPrefix: f.query_prefix } : null))
    .catch(() => null);
  return vectorsPromise;
}
