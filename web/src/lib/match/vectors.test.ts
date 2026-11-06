import { describe, expect, it } from "vitest";
import { chunkCv, combineVectors, decodeJobVectors, normalize, similarities, summaryText } from "./vectors";
import { CHUNK_CHARS, MAX_CHUNKS } from "./constants";
import type { JobVectorsFile } from "./types";

function encode(rows: number[][]): JobVectorsFile {
  const dim = rows[0].length;
  const bytes = new Int8Array(rows.length * dim);
  const scales: number[] = [];
  rows.forEach((row, r) => {
    const scale = Math.max(...row.map(Math.abs)) / 127;
    scales.push(scale);
    row.forEach((v, c) => (bytes[r * dim + c] = Math.round(v / scale)));
  });
  return {
    model: "m",
    dim,
    normalized: true,
    pooling: "cls",
    query_prefix: "q: ",
    encoding: "int8-base64",
    ids: rows.map((_, i) => `job-${i}`),
    scales,
    data: Buffer.from(bytes.buffer).toString("base64"),
  };
}

describe("decodeJobVectors", () => {
  it("round-trips int8 + scale within quantisation error", () => {
    const rows = [
      [0.6, -0.8, 0, 0],
      [0, 0.1, -0.99, 0.05],
    ];
    const d = decodeJobVectors(encode(rows));
    expect(d.ids).toEqual(["job-0", "job-1"]);
    expect(d.dim).toBe(4);
    rows.flat().forEach((v, i) => expect(d.vectors[i]).toBeCloseTo(v, 2));
  });
  it("handles negative int8 values (sign reinterpretation)", () => {
    const d = decodeJobVectors(encode([[-1, 1]]));
    expect(d.vectors[0]).toBeCloseTo(-1, 3);
    expect(d.vectors[1]).toBeCloseTo(1, 3);
  });
  it("rejects bad shapes and encodings", () => {
    const f = encode([[1, 0]]);
    expect(() => decodeJobVectors({ ...f, encoding: "float32" })).toThrow();
    expect(() => decodeJobVectors({ ...f, ids: ["a", "b"] })).toThrow();
  });
});

describe("similarities", () => {
  it("returns cosine per job id", () => {
    const d = decodeJobVectors(encode([[1, 0], [0, 1], [0.7071, 0.7071]]));
    const s = similarities(Float32Array.from([2, 0]), d); // unnormalised query is fine
    expect(s.get("job-0")).toBeCloseTo(1, 2);
    expect(s.get("job-1")).toBeCloseTo(0, 2);
    expect(s.get("job-2")).toBeCloseTo(0.7071, 2);
  });
});

describe("chunking and combining", () => {
  it("keeps a short CV as one chunk", () => {
    expect(chunkCv("Short CV\nSQL")).toEqual(["Short CV\nSQL"]);
    expect(chunkCv("   ")).toEqual([]);
  });
  it("splits long CVs under the size limit and caps the count", () => {
    const line = "Built dashboards and reports for the business team. ";
    const long = Array.from({ length: 400 }, () => line).join("\n");
    const chunks = chunkCv(long);
    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.length).toBeLessThanOrEqual(MAX_CHUNKS);
    for (const c of chunks) expect(c.length).toBeLessThanOrEqual(CHUNK_CHARS);
  });
  it("normalises the combined vector", () => {
    const v = combineVectors([Float32Array.from([1, 0]), Float32Array.from([0, 1])], Float32Array.from([1, 0]));
    expect(Math.hypot(v![0], v![1])).toBeCloseTo(1);
    expect(v![0]).toBeGreaterThan(v![1]); // summary pulls toward the first axis
    expect(combineVectors([], null)).toBeNull();
    expect(normalize(Float32Array.from([3, 4]))[0]).toBeCloseTo(0.6);
  });
  it("writes the summary passage", () => {
    expect(summaryText(["SQL", "Python"], ["Data & analytics"], "Mid-level")).toBe("Mid-level candidate. looking for Data & analytics roles. skills: SQL, Python");
    expect(summaryText([], [], null)).toBe("");
  });
});
