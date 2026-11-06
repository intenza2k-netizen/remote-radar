import { MAX_FILE_BYTES } from "./constants";

/**
 * Turn an uploaded CV into plain text, entirely in the browser. The file is read with
 * `File.arrayBuffer()` and never sent anywhere. pdfjs-dist and mammoth are imported on
 * demand, so they cost nothing until someone actually uploads a PDF or a DOCX.
 */

export type ParsedFile = { text: string; kind: "pdf" | "docx" | "text" };

export class ParseError extends Error {}

function kindOf(file: File): ParsedFile["kind"] | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf") || file.type === "application/pdf") return "pdf";
  if (name.endsWith(".docx") || file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document") return "docx";
  if (name.endsWith(".txt") || name.endsWith(".md") || file.type.startsWith("text/")) return "text";
  return null;
}

export async function extractTextFromFile(file: File): Promise<ParsedFile> {
  if (file.size > MAX_FILE_BYTES) throw new ParseError(`That file is ${(file.size / 1048576).toFixed(1)} MB; the limit is ${MAX_FILE_BYTES / 1048576} MB.`);
  const kind = kindOf(file);
  if (!kind) throw new ParseError("Unsupported file type. Upload a PDF, DOCX or plain-text file, or paste the text.");
  let text: string;
  try {
    if (kind === "text") text = await file.text();
    else if (kind === "docx") text = await docxText(await file.arrayBuffer());
    else text = await pdfText(await file.arrayBuffer());
  } catch (err) {
    if (err instanceof ParseError) throw err;
    throw new ParseError(`Could not read that ${kind.toUpperCase()}: ${err instanceof Error ? err.message : "unknown error"}. Try pasting the text instead.`);
  }
  text = tidy(text);
  if (!text) {
    throw new ParseError(
      kind === "pdf" ? "No text found in that PDF. It may be a scan (an image); paste the text or export a text-based PDF." : "No text found in that file.",
    );
  }
  return { text, kind };
}

/** Normalise whitespace and bullets from extracted text without losing line structure. */
export function tidy(raw: string): string {
  return raw
    .replace(/\r\n?/g, "\n")
    .replace(/ /g, " ")
    .replace(/[•●▪‣·]/g, "-")
    .replace(/[ \t]+/g, " ")
    .replace(/ ?\n ?/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

async function docxText(buf: ArrayBuffer): Promise<string> {
  const mod = await import("mammoth/mammoth.browser");
  const mammoth = (mod as unknown as { default?: typeof mod }).default ?? mod;
  const res = await mammoth.extractRawText({ arrayBuffer: buf });
  return res.value;
}

type TextItem = { str: string; hasEOL?: boolean; transform?: number[] };

async function pdfText(buf: ArrayBuffer): Promise<string> {
  const pdfjs = await import("pdfjs-dist");
  // Run pdf.js's own worker (bundled by Next, served from this site) as a module worker.
  const worker = new Worker(new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url), { type: "module" });
  pdfjs.GlobalWorkerOptions.workerPort = worker;
  try {
    const task = pdfjs.getDocument({ data: new Uint8Array(buf) });
    const pdf = await task.promise;
    const pages: string[] = [];
    const maxPages = Math.min(pdf.numPages, 30);
    for (let p = 1; p <= maxPages; p++) {
      const page = await pdf.getPage(p);
      const content = await page.getTextContent();
      let out = "";
      let lastY: number | null = null;
      for (const raw of content.items) {
        const item = raw as TextItem;
        if (typeof item.str !== "string") continue;
        const y = item.transform?.[5];
        if (lastY != null && y != null && Math.abs(y - lastY) > 2 && !out.endsWith("\n")) out += "\n";
        out += item.str;
        if (item.hasEOL) out += "\n";
        if (y != null) lastY = y;
      }
      pages.push(out);
    }
    await task.destroy();
    return pages.join("\n\n");
  } finally {
    pdfjs.GlobalWorkerOptions.workerPort = null;
    worker.terminate();
  }
}
