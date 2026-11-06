#!/usr/bin/env node
/**
 * Copies the ONNX Runtime WebAssembly files used by the CV matcher's embedding worker from
 * node_modules into public/ort/, so the browser loads them from this site and not from a
 * third-party CDN (transformers.js defaults to jsDelivr). Runs before `dev` and `build`.
 * public/ort/ is generated, not source: do not commit it.
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const from = path.join(root, "node_modules", "onnxruntime-web", "dist");
const to = path.join(root, "public", "ort");
const files = ["ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm"];

mkdirSync(to, { recursive: true });
for (const f of files) {
  const src = path.join(from, f);
  if (!existsSync(src)) {
    console.error(`copy-ort: missing ${src}. Run "npm install" first.`);
    process.exit(1);
  }
  const dst = path.join(to, f);
  if (f.endsWith(".mjs")) {
    // Vendored, minified code: keep it out of the project's lint run.
    const body = `/* eslint-disable */\n${readFileSync(src, "utf8")}`;
    if (!existsSync(dst) || readFileSync(dst, "utf8") !== body) writeFileSync(dst, body);
  } else if (!existsSync(dst) || statSync(dst).size !== statSync(src).size) copyFileSync(src, dst);
}
console.log(`copy-ort: ${files.length} files in public/ort/`);
