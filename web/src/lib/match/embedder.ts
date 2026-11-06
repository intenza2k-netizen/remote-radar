import type { WorkerIn, WorkerOut } from "./embed.worker";

/**
 * Main-thread handle for the embedding worker. Imported lazily (dynamic import) so neither this
 * file, the worker nor transformers.js is part of the page's initial JavaScript.
 */

export type ModelState =
  | { phase: "idle" }
  | { phase: "loading"; progress: number }
  | { phase: "ready" }
  | { phase: "error"; message: string };

export const MODEL_ID = "Xenova/bge-small-en-v1.5";

export class Embedder {
  private worker: Worker | null = null;
  private nextId = 1;
  private pending = new Map<number, { resolve: (v: Float32Array[]) => void; reject: (e: Error) => void }>();
  private startPromise: Promise<void> | null = null;

  constructor(private onState: (s: ModelState) => void) {}

  /** Start (or join) model loading. Rejects if the model cannot be loaded. */
  start(): Promise<void> {
    if (this.startPromise) return this.startPromise;
    this.startPromise = new Promise<void>((resolve, reject) => {
      try {
        const worker = new Worker(new URL("./embed.worker.ts", import.meta.url), { type: "module" });
        this.worker = worker;
        this.onState({ phase: "loading", progress: 0 });
        worker.onmessage = (e: MessageEvent<WorkerOut>) => {
          const m = e.data;
          if (m.type === "progress") this.onState({ phase: "loading", progress: m.progress });
          else if (m.type === "ready") {
            this.onState({ phase: "ready" });
            resolve();
          } else if (m.type === "embedded") {
            const p = this.pending.get(m.id);
            this.pending.delete(m.id);
            const vecs: Float32Array[] = [];
            for (let i = 0; i < m.data.length / m.dim; i++) vecs.push(m.data.slice(i * m.dim, (i + 1) * m.dim));
            p?.resolve(vecs);
          } else if (m.type === "error") {
            if (m.id != null) {
              const p = this.pending.get(m.id);
              this.pending.delete(m.id);
              p?.reject(new Error(m.message));
            } else {
              this.fail(m.message, reject);
            }
          }
        };
        worker.onerror = (e) => this.fail(e.message || "The model worker crashed", reject);
        const msg: WorkerIn = { type: "init", model: MODEL_ID, wasmBase: `${window.location.origin}/ort/` };
        worker.postMessage(msg);
      } catch (err) {
        this.fail(err instanceof Error ? err.message : String(err), reject);
      }
    });
    // A rejected start must not poison later retries from the same instance unnoticed.
    this.startPromise.catch(() => undefined);
    return this.startPromise;
  }

  private fail(message: string, reject: (e: Error) => void) {
    this.onState({ phase: "error", message });
    for (const p of this.pending.values()) p.reject(new Error(message));
    this.pending.clear();
    this.worker?.terminate();
    this.worker = null;
    this.startPromise = null;
    reject(new Error(message));
  }

  async embed(texts: string[]): Promise<Float32Array[]> {
    await this.start();
    const worker = this.worker;
    if (!worker) throw new Error("Model is not available");
    const id = this.nextId++;
    return new Promise<Float32Array[]>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      const msg: WorkerIn = { type: "embed", id, texts };
      worker.postMessage(msg);
    });
  }

  terminate() {
    this.worker?.terminate();
    this.worker = null;
    this.startPromise = null;
  }
}
