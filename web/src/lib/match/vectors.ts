import { CHUNK_CHARS, CHUNK_OVERLAP, MAX_CHUNKS, SUMMARY_WEIGHT } from "./constants";
import type { DecodedVectors, JobVectorsFile } from "./types";

/** Decode `job_vectors.json` (int8-base64 plus one scale per row) into float vectors, once. */
export function decodeJobVectors(file: JobVectorsFile): DecodedVectors {
  if (file.encoding !== "int8-base64") throw new Error(`Unsupported vector encoding: ${file.encoding}`);
  const { dim, ids, scales } = file;
  const bin = atob(file.data);
  if (bin.length !== ids.length * dim) throw new Error(`Vector data has ${bin.length} bytes, expected ${ids.length * dim}`);
  if (scales.length !== ids.length) throw new Error("Vector scales do not match ids");
  const out = new Float32Array(ids.length * dim);
  for (let r = 0; r < ids.length; r++) {
    const scale = scales[r];
    const base = r * dim;
    for (let c = 0; c < dim; c++) {
      // charCodeAt gives 0..255; reinterpret as signed int8.
      const b = bin.charCodeAt(base + c);
      out[base + c] = (b > 127 ? b - 256 : b) * scale;
    }
  }
  return { ids, dim, vectors: out };
}

export function dot(a: Float32Array, aOff: number, b: Float32Array, bOff: number, dim: number): number {
  let s = 0;
  for (let i = 0; i < dim; i++) s += a[aOff + i] * b[bOff + i];
  return s;
}

export function normalize(v: Float32Array): Float32Array {
  let n = 0;
  for (let i = 0; i < v.length; i++) n += v[i] * v[i];
  n = Math.sqrt(n);
  if (n === 0) return v;
  const out = new Float32Array(v.length);
  for (let i = 0; i < v.length; i++) out[i] = v[i] / n;
  return out;
}

/** Cosine similarity of one (unit) query vector with every job vector, keyed by job id. */
export function similarities(query: Float32Array, jobs: DecodedVectors): Map<string, number> {
  const q = normalize(query);
  const out = new Map<string, number>();
  for (let r = 0; r < jobs.ids.length; r++) {
    // Job vectors are unit length up to int8 rounding; divide by the norm to remove that noise.
    const base = r * jobs.dim;
    let n = 0;
    for (let i = 0; i < jobs.dim; i++) n += jobs.vectors[base + i] * jobs.vectors[base + i];
    const d = dot(q, 0, jobs.vectors, base, jobs.dim);
    out.set(jobs.ids[r], n > 0 ? d / Math.sqrt(n) : 0);
  }
  return out;
}

/**
 * Split CV text into chunks of about CHUNK_CHARS characters, breaking at paragraph, line or
 * sentence boundaries, with a small overlap. At most MAX_CHUNKS chunks are kept (evenly
 * spread over the CV if it is longer than that).
 */
export function chunkCv(text: string): string[] {
  const clean = text.replace(/\r\n?/g, "\n").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  if (!clean) return [];
  if (clean.length <= CHUNK_CHARS) return [clean];
  const chunks: string[] = [];
  let pos = 0;
  while (pos < clean.length) {
    let end = Math.min(clean.length, pos + CHUNK_CHARS);
    if (end < clean.length) {
      const window = clean.slice(pos + Math.floor(CHUNK_CHARS * 0.6), end);
      const cut = Math.max(window.lastIndexOf("\n\n"), window.lastIndexOf("\n"), window.lastIndexOf(". "));
      if (cut > 0) end = pos + Math.floor(CHUNK_CHARS * 0.6) + cut + 1;
    }
    chunks.push(clean.slice(pos, end).trim());
    if (end >= clean.length) break;
    pos = Math.max(end - CHUNK_OVERLAP, pos + 1);
  }
  if (chunks.length <= MAX_CHUNKS) return chunks;
  const picked: string[] = [];
  for (let i = 0; i < MAX_CHUNKS; i++) picked.push(chunks[Math.round((i * (chunks.length - 1)) / (MAX_CHUNKS - 1))]);
  return picked;
}

/** The short "skills and roles" passage that is embedded next to the CV chunks. */
export function summaryText(skillNames: string[], roleLabels: string[], levelLabel: string | null): string {
  const parts: string[] = [];
  if (levelLabel) parts.push(`${levelLabel} candidate`);
  if (roleLabels.length) parts.push(`looking for ${roleLabels.join(", ")} roles`);
  if (skillNames.length) parts.push(`skills: ${skillNames.join(", ")}`);
  return parts.join(". ");
}

/** Mean of the chunk vectors plus the summary vector (counted SUMMARY_WEIGHT times), normalised. */
export function combineVectors(chunkVecs: Float32Array[], summaryVec: Float32Array | null): Float32Array | null {
  const dim = chunkVecs[0]?.length ?? summaryVec?.length;
  if (!dim) return null;
  const sum = new Float32Array(dim);
  for (const v of chunkVecs) for (let i = 0; i < dim; i++) sum[i] += v[i];
  if (summaryVec) for (let i = 0; i < dim; i++) sum[i] += SUMMARY_WEIGHT * summaryVec[i];
  return normalize(sum);
}
