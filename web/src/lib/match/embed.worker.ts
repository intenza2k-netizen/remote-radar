/**
 * Web Worker that runs the embedding model (transformers.js, ONNX Runtime WASM) off the main thread.
 * It only ever receives text from the page and returns number arrays; it has no other channel.
 * Network access is limited to what transformers.js needs: the model files on the Hugging Face Hub
 * (then cached by the browser) and the ONNX Runtime WASM files, which this site serves itself.
 */
import { env, pipeline } from "@huggingface/transformers";

export type WorkerIn =
  | { type: "init"; model: string; wasmBase: string }
  | { type: "embed"; id: number; texts: string[] };

export type WorkerOut =
  | { type: "progress"; progress: number; file?: string }
  | { type: "ready" }
  | { type: "error"; message: string; id?: number }
  | { type: "embedded"; id: number; dim: number; data: Float32Array };

type Extractor = (texts: string[], opts: { pooling: "cls"; normalize: boolean }) => Promise<{ data: Float32Array | number[]; dims: number[] }>;

const ctx = self as unknown as {
  postMessage(msg: WorkerOut, transfer?: Transferable[]): void;
  onmessage: ((e: MessageEvent<WorkerIn>) => void) | null;
};

let extractor: Extractor | null = null;
let initPromise: Promise<void> | null = null;

function init(model: string, wasmBase: string): Promise<void> {
  if (initPromise) return initPromise;
  initPromise = (async () => {
    // Models come from the Hub only; never probe this site's own /models path.
    env.allowLocalModels = false;
    env.useBrowserCache = true;
    // Serve the ONNX Runtime WASM from this site instead of a third-party CDN.
    const wasm = env.backends.onnx.wasm;
    if (wasm) {
      wasm.wasmPaths = { mjs: `${wasmBase}ort-wasm-simd-threaded.mjs`, wasm: `${wasmBase}ort-wasm-simd-threaded.wasm` };
    }

    // One overall percentage from the per-file download events.
    const files = new Map<string, { loaded: number; total: number }>();
    const report = (file?: string) => {
      let loaded = 0;
      let total = 0;
      for (const f of files.values()) {
        loaded += f.loaded;
        total += f.total;
      }
      ctx.postMessage({ type: "progress", progress: total ? Math.min(1, loaded / total) : 0, file });
    };

    const pipe = await pipeline("feature-extraction", model, {
      device: "wasm",
      dtype: "q8",
      progress_callback: (e: { status: string; file?: string; loaded?: number; total?: number }) => {
        if (!e.file) return;
        if (e.status === "progress" && e.total) {
          files.set(e.file, { loaded: e.loaded ?? 0, total: e.total });
          report(e.file);
        } else if (e.status === "done") {
          const f = files.get(e.file);
          if (f) files.set(e.file, { loaded: f.total, total: f.total });
          report(e.file);
        }
      },
    });
    extractor = pipe as unknown as Extractor;
    ctx.postMessage({ type: "ready" });
  })();
  initPromise.catch(() => {
    initPromise = null;
  });
  return initPromise;
}

ctx.onmessage = async (e) => {
  const msg = e.data;
  if (msg.type === "init") {
    try {
      await init(msg.model, msg.wasmBase);
    } catch (err) {
      ctx.postMessage({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
    return;
  }
  if (msg.type === "embed") {
    try {
      if (!extractor) throw new Error("Model is not loaded");
      // CLS pooling + L2 normalisation, as BGE models expect.
      const out = await extractor(msg.texts, { pooling: "cls", normalize: true });
      const data = out.data instanceof Float32Array ? out.data.slice() : Float32Array.from(out.data);
      const dim = out.dims[out.dims.length - 1];
      ctx.postMessage({ type: "embedded", id: msg.id, dim, data }, [data.buffer]);
    } catch (err) {
      ctx.postMessage({ type: "error", message: err instanceof Error ? err.message : String(err), id: msg.id });
    }
  }
};
