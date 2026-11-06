#!/usr/bin/env node
/**
 * Generates STAND-IN v2 snapshot files into web/public/data/ (PLAN.md section 5) so the web
 * app can be built and tested before the real pipeline has published them. Each section only
 * writes files that do not exist yet: it never overwrites real pipeline output.
 *
 *   node scripts/make-sample-v2.mjs
 *
 * Sections (each owned by one web worker; edit only your own):
 *   // MATCH     skill_vocab.json, job_vectors.json           (CV matcher)
 *   // INSIGHTS  insights.json, companies.json                (insights / companies pages)
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DATA = path.join(ROOT, "public", "data");
mkdirSync(DATA, { recursive: true });
const readData = (name) => JSON.parse(readFileSync(path.join(DATA, name), "utf8"));
const have = (name) => existsSync(path.join(DATA, name));

// =================================================================== MATCH
// Stand-ins for skill_vocab.json (from the pipeline's aliases.yaml) and job_vectors.json
// (real bge-small embeddings of the real jobs.json titles, computed in Node with transformers.js).

async function matchSection() {
  if (!have("skill_vocab.json")) await makeVocab();
  else console.log("MATCH: skill_vocab.json exists, left untouched");
  if (!have("job_vectors.json")) await makeVectors();
  else console.log("MATCH: job_vectors.json exists, left untouched");
}

/** Short or ambiguous bare words that the browser must only accept with case and context rules. */
const AMBIGUOUS = new Set(["go", "r", "c", "ai", "ml", "ps", "sem", "excel", "swift", "apex"]);

async function makeVocab() {
  const yamlPath = path.resolve(ROOT, "..", "pipeline", "src", "radar", "skills", "aliases.yaml");
  const yaml = (await import("js-yaml")).default;
  const doc = yaml.load(readFileSync(yamlPath, "utf8"));
  const out = [];
  for (const [slug, info] of Object.entries(doc.skills)) {
    const name = String(info.display ?? slug);
    const raw = [slug.replace(/-/g, " "), name, ...(info.aliases ?? []).map(String)];
    const patterns = [...new Set(raw.map((p) => p.trim().toLowerCase()).filter(Boolean))];
    const strict = patterns.some((p) => AMBIGUOUS.has(p)) || (name.length <= 2 && /^[a-z]+$/i.test(name));
    out.push({ slug, name, category: info.category ?? "other", patterns, strict });
  }
  writeFileSync(path.join(DATA, "skill_vocab.json"), JSON.stringify(out));
  console.log(`MATCH: wrote skill_vocab.json (${out.length} skills, ${out.filter((v) => v.strict).length} strict) [STAND-IN]`);
}

const ROLE_TEXT = {
  software_engineering: "software engineering",
  data: "data and analytics",
  devops_sre: "devops and site reliability",
  product: "product management",
  design: "design",
  marketing: "marketing",
  sales: "sales",
  support: "customer support",
  management: "management",
  other: "other",
};

async function makeVectors() {
  const jobs = readData("jobs.json");
  const skills = readData("skills.json");
  const names = Object.fromEntries(skills.map((s) => [s.slug, s.name]));
  const { pipeline, env } = await import("@huggingface/transformers");
  // Models must never land on C:. Same cache the pipeline uses.
  env.cacheDir = process.env.RADAR_MODEL_CACHE || "F:\\Models\\remote-radar";
  console.log(`MATCH: loading Xenova/bge-small-en-v1.5 (q8) from ${env.cacheDir}`);
  const extractor = await pipeline("feature-extraction", "Xenova/bge-small-en-v1.5", { dtype: "q8" });

  // Passage text mirrors the contract: title + role + seniority + top skills (no descriptions published).
  const passage = (j) => {
    const top = j.skills.slice(0, 8).map((s) => names[s] ?? s.replace(/-/g, " ")).join(", ");
    const level = j.seniority && j.seniority !== "unspecified" ? `${j.seniority} level. ` : "";
    return `${j.title}. ${ROLE_TEXT[j.role] ?? "other"}. ${level}${top ? `Skills: ${top}.` : ""}`;
  };

  const dim = 384;
  const bytes = new Int8Array(jobs.length * dim);
  const scales = [];
  const BATCH = 16;
  for (let i = 0; i < jobs.length; i += BATCH) {
    const batch = jobs.slice(i, i + BATCH);
    const t = await extractor(batch.map(passage), { pooling: "cls", normalize: true });
    for (let b = 0; b < batch.length; b++) {
      const v = t.data.subarray(b * dim, (b + 1) * dim);
      let max = 0;
      for (const x of v) max = Math.max(max, Math.abs(x));
      const scale = max / 127 || 1;
      scales.push(scale);
      for (let k = 0; k < dim; k++) bytes[(i + b) * dim + k] = Math.round(v[k] / scale);
    }
    process.stdout.write(`\rMATCH: embedded ${Math.min(i + BATCH, jobs.length)}/${jobs.length}`);
  }
  process.stdout.write("\n");
  const file = {
    model: "Xenova/bge-small-en-v1.5",
    python_model: "BAAI/bge-small-en-v1.5",
    dim,
    normalized: true,
    pooling: "cls",
    query_prefix: "Represent this sentence for searching relevant passages: ",
    encoding: "int8-base64",
    ids: jobs.map((j) => j.id),
    scales,
    data: Buffer.from(bytes.buffer).toString("base64"),
    sample: true,
  };
  writeFileSync(path.join(DATA, "job_vectors.json"), JSON.stringify(file));
  console.log(`MATCH: wrote job_vectors.json (${jobs.length} x ${dim}) [STAND-IN: title + role + skills only]`);
}

await matchSection();
// =================================================================== END MATCH

// =================================================================== INSIGHTS
// (owned by the /insights worker: add your stand-in generators below this line)
// insights.json and companies.json, derived from the real jobs.json and skills.json.
// Written only when missing; method mirrors PLAN.md section 5 (bootstrap CI of the difference of
// medians with 1000 resamples and a fixed seed; PMI edges; top 80 skills).
{
  const wantInsights = !have("insights.json");
  const wantCompanies = !have("companies.json");
  const write = (f, data) => {
    writeFileSync(path.join(DATA, f), JSON.stringify(data));
    console.log(`INSIGHTS: wrote ${f} [STAND-IN]`);
  };
  if (!wantInsights && !wantCompanies) {
    console.log("INSIGHTS: insights.json and companies.json exist, left untouched");
  } else {
    const jobs = readData("jobs.json");
    const skillsMeta = new Map(readData("skills.json").map((s) => [s.slug, s]));

    function mulberry32(seed) {
      let a = seed >>> 0;
      return () => {
        a = (a + 0x6d2b79f5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    }
    const median = (arr) => {
      if (!arr.length) return null;
      const v = [...arr].sort((a, b) => a - b);
      const m = Math.floor(v.length / 2);
      return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
    };
    const quantile = (sorted, q) => {
      const pos = (sorted.length - 1) * q;
      const lo = Math.floor(pos);
      const hi = Math.ceil(pos);
      return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
    };
    const r4 = (x) => Math.round(x * 10000) / 10000;
    const nameOf = (slug) => skillsMeta.get(slug)?.name ?? slug;
    const catOf = (slug) => skillsMeta.get(slug)?.category ?? "other";

    if (wantInsights) {
      const rand = mulberry32(20261106);
      const bootstrapDiff = (a, b) => {
        const res = [];
        for (let i = 0; i < 1000; i++) {
          const ra = Array.from({ length: a.length }, () => a[Math.floor(rand() * a.length)]);
          const rb = Array.from({ length: b.length }, () => b[Math.floor(rand() * b.length)]);
          res.push(median(ra) - median(rb));
        }
        res.sort((x, y) => x - y);
        return [quantile(res, 0.025), quantile(res, 0.975)];
      };

      // skill_premium: skills with >= 15 salaried postings.
      const salaried = jobs.filter((j) => j.salary);
      const withCount = new Map();
      for (const j of salaried) for (const s of new Set(j.skills)) withCount.set(s, (withCount.get(s) ?? 0) + 1);
      const skill_premium = [];
      for (const [slug, n] of withCount) {
        if (n < 15) continue;
        const w = salaried.filter((j) => j.skills.includes(slug)).map((j) => j.salary.annual_usd_mid);
        const wo = salaried.filter((j) => !j.skills.includes(slug)).map((j) => j.salary.annual_usd_mid);
        if (wo.length < 5) continue;
        const [lo, hi] = bootstrapDiff(w, wo);
        const mw = median(w);
        const mwo = median(wo);
        skill_premium.push({
          slug,
          name: nameOf(slug),
          n_with: w.length,
          n_without: wo.length,
          median_with: Math.round(mw),
          median_without: Math.round(mwo),
          diff: Math.round(mw - mwo),
          ci_low: Math.round(lo),
          ci_high: Math.round(hi),
        });
      }
      skill_premium.sort((a, b) => b.diff - a.diff);

      // seniority_lift: roles with >= 30 postings.
      const SENIOR = new Set(["senior", "lead", "principal"]);
      const JUNIOR = new Set(["intern", "junior", "mid"]);
      const roles = [...new Set(jobs.map((j) => j.role).filter(Boolean))];
      const seniority_lift = [];
      for (const role of roles) {
        const inRole = jobs.filter((j) => j.role === role);
        if (inRole.length < 30) continue;
        const sen = inRole.filter((j) => SENIOR.has(j.seniority));
        const jun = inRole.filter((j) => JUNIOR.has(j.seniority));
        if (!sen.length || !jun.length) continue;
        const slugs = new Set(inRole.flatMap((j) => j.skills));
        const rows = [];
        for (const slug of slugs) {
          const cs = sen.filter((j) => j.skills.includes(slug)).length;
          const cj = jun.filter((j) => j.skills.includes(slug)).length;
          if (cs + cj < 3) continue;
          // Add-half smoothing keeps lift finite when a skill never appears in one group.
          const lift = (cs + 0.5) / (sen.length + 1) / ((cj + 0.5) / (jun.length + 1));
          rows.push({ slug, name: nameOf(slug), share_senior: r4(cs / sen.length), share_junior: r4(cj / jun.length), lift: Math.round(lift * 100) / 100 });
        }
        rows.sort((a, b) => b.lift - a.lift);
        seniority_lift.push({ role, n_senior: sen.length, n_junior: jun.length, skills: rows.slice(0, 10) });
      }

      // skill_graph: top 80 skills, PMI edges (count >= 3, max 250).
      const N = jobs.length;
      const counts = new Map();
      for (const j of jobs) for (const s of new Set(j.skills)) counts.set(s, (counts.get(s) ?? 0) + 1);
      const top = [...counts.entries()]
        .filter(([s]) => skillsMeta.has(s))
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, 80);
      const topSet = new Set(top.map(([s]) => s));
      const pair = new Map();
      for (const j of jobs) {
        const ss = [...new Set(j.skills)].filter((s) => topSet.has(s)).sort();
        for (let i = 0; i < ss.length; i++)
          for (let k = i + 1; k < ss.length; k++) {
            const key = `${ss[i]}|${ss[k]}`;
            pair.set(key, (pair.get(key) ?? 0) + 1);
          }
      }
      const edges = [];
      for (const [key, c] of pair) {
        if (c < 3) continue;
        const [a, b] = key.split("|");
        edges.push({ a, b, count: c, pmi: r4(Math.log2((c * N) / (counts.get(a) * counts.get(b)))) });
      }
      edges.sort((x, y) => y.pmi - x.pmi || y.count - x.count);
      const skill_graph = {
        nodes: top.map(([slug, count]) => ({ slug, name: nameOf(slug), category: catOf(slug), count })),
        edges: edges.slice(0, 250),
      };

      // role_skills: top 12 per role (roles with >= 10 postings).
      const role_skills = roles
        .map((role) => {
          const inRole = jobs.filter((j) => j.role === role);
          const c = new Map();
          for (const j of inRole) for (const s of new Set(j.skills)) c.set(s, (c.get(s) ?? 0) + 1);
          const topSkills = [...c.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 12);
          return { role, n: inRole.length, top: topSkills.map(([slug, k]) => ({ slug, name: nameOf(slug), share: r4(k / inRole.length) })) };
        })
        .filter((r) => r.n >= 10)
        .sort((a, b) => b.n - a.n);

      write("insights.json", { skill_premium, seniority_lift, skill_graph, role_skills });
    }

    if (wantCompanies) {
      const slugify = (s) =>
        s
          .normalize("NFKD")
          .replace(/[̀-ͯ]/g, "")
          .toLowerCase()
          .replace(/&/g, " and ")
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "") || "company";
      const byCompany = new Map();
      for (const j of jobs) {
        const arr = byCompany.get(j.company) ?? [];
        arr.push(j);
        byCompany.set(j.company, arr);
      }
      const used = new Set();
      const companies = [];
      for (const [name, js] of byCompany) {
        let slug = slugify(name);
        for (let i = 2; used.has(slug); i++) slug = `${slugify(name)}-${i}`;
        used.add(slug);
        const tally = (f) => js.reduce((m, j) => ((m[f(j)] = (m[f(j)] ?? 0) + 1), m), {});
        const sk = new Map();
        for (const j of js) for (const s of new Set(j.skills)) sk.set(s, (sk.get(s) ?? 0) + 1);
        companies.push({
          slug,
          name,
          jobs: js.length,
          roles: tally((j) => j.role ?? "other"),
          seniority: tally((j) => j.seniority ?? "unspecified"),
          top_skills: [...sk.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 8).map(([s, count]) => ({ slug: s, name: nameOf(s), count })),
          median_salary_usd: median(js.filter((j) => j.salary).map((j) => j.salary.annual_usd_mid)),
          sources: [...new Set(js.map((j) => j.source))].sort(),
          job_ids: js.map((j) => j.id),
        });
      }
      companies.sort((a, b) => b.jobs - a.jobs || a.name.localeCompare(b.name));
      write("companies.json", companies);
    }
  }
}
