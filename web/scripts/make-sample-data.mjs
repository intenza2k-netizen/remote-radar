#!/usr/bin/env node
/**
 * Generates a realistic SAMPLE snapshot into web/public/data/ following
 * PLAN.md section 4 ("Published snapshot"). The real pipeline overwrites these
 * files and omits `"sample": true` from meta.json.
 *
 *   node scripts/make-sample-data.mjs
 *
 * Deterministic: seeded PRNG; the only moving input is "now" (override with
 * SAMPLE_NOW=2026-11-06T09:00:00Z).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, "../public/data");

// ---------------------------------------------------------------- utilities
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
const rand = mulberry32(20261106);
const pick = (arr) => arr[Math.floor(rand() * arr.length)];
function weighted(items, weightOf) {
  const total = items.reduce((s, x) => s + weightOf(x), 0);
  let r = rand() * total;
  for (const x of items) {
    r -= weightOf(x);
    if (r <= 0) return x;
  }
  return items[items.length - 1];
}
function gauss() {
  let u = 0;
  let v = 0;
  while (u === 0) u = rand();
  while (v === 0) v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
function quantile(sorted, q) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}
const round = (x, step = 1) => Math.round(x / step) * step;
const r4 = (x) => Math.round(x * 10000) / 10000;

const NOW = process.env.SAMPLE_NOW ? new Date(process.env.SAMPLE_NOW) : new Date();
const DAY = 86400000;

function isoWeek(date) {
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((d - yearStart) / DAY + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}
function mondayOf(date) {
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dow = d.getUTCDay() || 7;
  return new Date(d.getTime() - (dow - 1) * DAY);
}

// ------------------------------------------------------------------ skills
// [slug, display, category, group affinities, weekly trend slope, salary premium]
// groups: de data eng, da analyst/scientist, ml ML, be backend, fe frontend,
// ops devops/SRE, mob mobile, pm product/management, des design, all = every role
const SKILLS = [
  ["python", "Python", "language", "de:.7 da:.62 ml:.92 be:.34 ops:.2", 0.022, 1.04],
  ["sql", "SQL", "language", "de:.82 da:.88 ml:.3 be:.3 pm:.1", 0.01, 1.0],
  ["javascript", "JavaScript", "language", "fe:.8 be:.36 mob:.15 des:.05", -0.01, 0.97],
  ["typescript", "TypeScript", "language", "fe:.66 be:.38 mob:.12", 0.04, 1.05],
  ["java", "Java", "language", "be:.34 de:.16 mob:.1", -0.01, 1.03],
  ["go", "Go", "language", "be:.28 ops:.3 de:.06", 0.022, 1.09],
  ["rust", "Rust", "language", "be:.08 ops:.06 de:.03", 0.035, 1.12],
  ["csharp", "C#", "language", "be:.14 fe:.03", -0.005, 1.0],
  ["cpp", "C++", "language", "be:.05 ml:.05 mob:.05", 0, 1.06],
  ["ruby", "Ruby", "language", "be:.14", -0.015, 1.0],
  ["php", "PHP", "language", "be:.1 fe:.06", -0.022, 0.88],
  ["kotlin", "Kotlin", "language", "mob:.4 be:.06", 0.006, 1.03],
  ["swift", "Swift", "language", "mob:.42", 0, 1.04],
  ["scala", "Scala", "language", "de:.13 be:.03", -0.012, 1.1],
  ["r", "R", "language", "da:.22 ml:.08", -0.008, 0.98],
  ["bash", "Bash", "language", "ops:.4 de:.1 be:.06", 0.002, 1.0],
  ["dart", "Dart", "language", "mob:.1", 0.01, 1.0],
  ["elixir", "Elixir", "language", "be:.05", 0.004, 1.08],
  ["matlab", "MATLAB", "language", "ml:.04 da:.03", -0.01, 0.97],
  ["react", "React", "framework", "fe:.78 be:.1 mob:.1", 0.02, 1.03],
  ["nextjs", "Next.js", "framework", "fe:.22 be:.03", 0.06, 1.05],
  ["vue", "Vue.js", "framework", "fe:.2", -0.004, 0.97],
  ["angular", "Angular", "framework", "fe:.15", -0.016, 0.98],
  ["svelte", "Svelte", "framework", "fe:.05", 0.02, 1.0],
  ["nodejs", "Node.js", "framework", "be:.34 fe:.22 de:.02", 0.004, 1.01],
  ["express", "Express", "framework", "be:.1 fe:.05", 0, 0.98],
  ["nestjs", "NestJS", "framework", "be:.07", 0.025, 1.02],
  ["django", "Django", "framework", "be:.14 ml:.04", -0.004, 1.0],
  ["flask", "Flask", "framework", "be:.06 ml:.07", -0.01, 0.98],
  ["fastapi", "FastAPI", "framework", "be:.1 ml:.14 de:.04", 0.06, 1.04],
  ["rails", "Ruby on Rails", "framework", "be:.13", -0.012, 1.0],
  ["spring", "Spring Boot", "framework", "be:.18", -0.004, 1.03],
  ["dotnet", ".NET", "framework", "be:.15", -0.004, 1.0],
  ["laravel", "Laravel", "framework", "be:.07", -0.014, 0.86],
  ["tailwind", "Tailwind CSS", "framework", "fe:.2", 0.04, 1.0],
  ["graphql", "GraphQL", "framework", "fe:.2 be:.18", -0.005, 1.04],
  ["rest-api", "REST APIs", "framework", "be:.5 fe:.3 mob:.2", 0.002, 1.0],
  ["react-native", "React Native", "framework", "mob:.35", 0.006, 1.02],
  ["flutter", "Flutter", "framework", "mob:.2", 0.01, 1.0],
  ["redux", "Redux", "framework", "fe:.14", -0.02, 0.98],
  ["jquery", "jQuery", "framework", "fe:.06", -0.06, 0.8],
  ["htmx", "HTMX", "framework", "be:.02 fe:.03", 0.03, 1.0],
  ["css", "CSS", "framework", "fe:.55 des:.2", -0.002, 0.95],
  ["html", "HTML", "framework", "fe:.55 des:.15", -0.003, 0.94],
  ["aws", "AWS", "cloud", "de:.5 be:.42 ops:.82 ml:.4 fe:.08", 0.014, 1.05],
  ["gcp", "Google Cloud", "cloud", "de:.28 be:.14 ops:.34 ml:.22", 0.006, 1.04],
  ["azure", "Azure", "cloud", "de:.2 be:.14 ops:.3 ml:.12", 0.002, 1.02],
  ["cloudflare", "Cloudflare", "cloud", "ops:.08 fe:.03 be:.03", 0.02, 1.0],
  ["serverless", "Serverless", "cloud", "be:.07 ops:.1", 0, 1.02],
  ["docker", "Docker", "devops", "ops:.78 be:.42 de:.32 ml:.26", 0.004, 1.02],
  ["kubernetes", "Kubernetes", "devops", "ops:.66 be:.2 de:.12 ml:.12", 0.015, 1.07],
  ["terraform", "Terraform", "devops", "ops:.52 de:.12 be:.06", 0.022, 1.07],
  ["ansible", "Ansible", "devops", "ops:.16", -0.015, 1.0],
  ["jenkins", "Jenkins", "devops", "ops:.12 be:.04", -0.025, 0.96],
  ["github-actions", "GitHub Actions", "devops", "ops:.22 be:.08 de:.06", 0.035, 1.0],
  ["gitlab-ci", "GitLab CI", "devops", "ops:.12 be:.04", 0, 1.0],
  ["ci-cd", "CI/CD", "devops", "ops:.6 be:.26 de:.18 fe:.1 mob:.12", 0.006, 1.02],
  ["linux", "Linux", "devops", "ops:.62 be:.2 de:.1", -0.003, 1.02],
  ["git", "Git", "tool", "all:.28 be:.3 fe:.3 de:.22 ml:.2 mob:.25", 0, 0.99],
  ["prometheus", "Prometheus", "devops", "ops:.22", 0.012, 1.04],
  ["grafana", "Grafana", "devops", "ops:.24 de:.05", 0.01, 1.02],
  ["datadog", "Datadog", "devops", "ops:.16 be:.07", 0.008, 1.03],
  ["observability", "Observability", "devops", "ops:.2 be:.07", 0.03, 1.05],
  ["helm", "Helm", "devops", "ops:.14", 0.01, 1.04],
  ["dbt", "dbt", "data", "de:.46 da:.3", 0.055, 1.04],
  ["airflow", "Apache Airflow", "data", "de:.46 ml:.06", 0.015, 1.05],
  ["spark", "Apache Spark", "data", "de:.34 ml:.14 da:.04", -0.012, 1.08],
  ["kafka", "Apache Kafka", "data", "de:.22 be:.12", 0.002, 1.08],
  ["snowflake", "Snowflake", "data", "de:.42 da:.24", 0.018, 1.05],
  ["databricks", "Databricks", "data", "de:.3 ml:.14 da:.08", 0.04, 1.06],
  ["bigquery", "BigQuery", "data", "de:.24 da:.22", 0.008, 1.02],
  ["redshift", "Amazon Redshift", "data", "de:.14 da:.06", -0.015, 1.0],
  ["pandas", "pandas", "data", "da:.42 ml:.5 de:.24 be:.04", 0.006, 1.0],
  ["numpy", "NumPy", "data", "ml:.4 da:.2", 0, 1.0],
  ["etl", "ETL / ELT", "data", "de:.6 da:.14", 0.004, 1.01],
  ["data-modeling", "Data Modeling", "data", "de:.34 da:.28", 0.012, 1.03],
  ["data-warehouse", "Data Warehousing", "data", "de:.3 da:.2", 0.004, 1.02],
  ["tableau", "Tableau", "data", "da:.38", -0.012, 0.97],
  ["power-bi", "Power BI", "data", "da:.34 de:.04", 0.002, 0.93],
  ["looker", "Looker", "data", "da:.2", -0.004, 1.0],
  ["excel", "Excel", "data", "da:.34 pm:.08", -0.01, 0.82],
  ["hadoop", "Hadoop", "data", "de:.07", -0.06, 1.0],
  ["flink", "Apache Flink", "data", "de:.06", 0.01, 1.1],
  ["dagster", "Dagster", "data", "de:.07", 0.03, 1.04],
  ["fivetran", "Fivetran", "data", "de:.1 da:.05", 0.012, 1.0],
  ["metabase", "Metabase", "data", "da:.06", 0.01, 0.96],
  ["data-visualization", "Data Visualization", "data", "da:.4 de:.05", 0.004, 0.99],
  ["statistics", "Statistics", "data", "da:.46 ml:.3", 0.002, 1.0],
  ["ab-testing", "A/B Testing", "data", "da:.22 pm:.12 ml:.06", 0.008, 1.02],
  ["data-quality", "Data Quality", "data", "de:.2 da:.1", 0.025, 1.01],
  ["delta-lake", "Delta Lake", "data", "de:.1", 0.03, 1.05],
  ["postgresql", "PostgreSQL", "database", "be:.42 de:.34 da:.1 fe:.06", 0.008, 1.02],
  ["mysql", "MySQL", "database", "be:.2 de:.08 fe:.04", -0.012, 0.95],
  ["mongodb", "MongoDB", "database", "be:.2 fe:.1 de:.06", -0.008, 0.98],
  ["redis", "Redis", "database", "be:.22 ops:.14", 0.002, 1.02],
  ["elasticsearch", "Elasticsearch", "database", "be:.1 ops:.08 de:.06", -0.01, 1.04],
  ["dynamodb", "DynamoDB", "database", "be:.09 de:.04", 0.004, 1.03],
  ["sqlite", "SQLite", "database", "mob:.1 be:.03", 0, 0.98],
  ["clickhouse", "ClickHouse", "database", "de:.06 be:.02", 0.03, 1.08],
  ["sql-server", "SQL Server", "database", "da:.1 de:.1 be:.06", -0.01, 0.95],
  ["oracle", "Oracle DB", "database", "de:.05 be:.03", -0.02, 0.97],
  ["machine-learning", "Machine Learning", "ai_ml", "ml:.92 da:.4 de:.1", 0.014, 1.08],
  ["deep-learning", "Deep Learning", "ai_ml", "ml:.42", 0.008, 1.1],
  ["pytorch", "PyTorch", "ai_ml", "ml:.5", 0.016, 1.1],
  ["tensorflow", "TensorFlow", "ai_ml", "ml:.26", -0.02, 1.06],
  ["scikit-learn", "scikit-learn", "ai_ml", "ml:.38 da:.22", 0, 1.03],
  ["llm", "LLMs", "ai_ml", "ml:.6 be:.07 da:.06 fe:.03 pm:.1", 0.12, 1.14],
  ["rag", "RAG", "ai_ml", "ml:.28 be:.03", 0.14, 1.14],
  ["langchain", "LangChain", "ai_ml", "ml:.2 be:.03", 0.09, 1.08],
  ["openai-api", "OpenAI API", "ai_ml", "ml:.2 be:.04 fe:.02", 0.07, 1.05],
  ["nlp", "NLP", "ai_ml", "ml:.3 da:.06", 0.01, 1.08],
  ["computer-vision", "Computer Vision", "ai_ml", "ml:.14", 0, 1.1],
  ["mlops", "MLOps", "ai_ml", "ml:.3 ops:.06 de:.06", 0.035, 1.1],
  ["hugging-face", "Hugging Face", "ai_ml", "ml:.2", 0.04, 1.08],
  ["vector-databases", "Vector Databases", "ai_ml", "ml:.14 be:.02", 0.09, 1.1],
  ["prompt-engineering", "Prompt Engineering", "ai_ml", "ml:.12 pm:.06 des:.02", 0.06, 1.04],
  ["mlflow", "MLflow", "ai_ml", "ml:.14", 0.01, 1.04],
  ["jira", "Jira", "tool", "pm:.5 be:.08 fe:.08 all:.06", -0.004, 0.96],
  ["postman", "Postman", "tool", "be:.06 all:.01", 0, 0.97],
  ["salesforce", "Salesforce", "tool", "pm:.06", -0.004, 0.96],
  ["jest", "Jest", "tool", "fe:.2 be:.05", 0, 0.99],
  ["cypress", "Cypress", "tool", "fe:.08", -0.005, 1.0],
  ["playwright", "Playwright", "tool", "fe:.1 be:.02", 0.04, 1.02],
  ["webpack", "Webpack", "tool", "fe:.1", -0.025, 0.98],
  ["vite", "Vite", "tool", "fe:.14", 0.025, 1.0],
  ["figma", "Figma", "design", "des:.9 pm:.2 fe:.14", 0.004, 0.97],
  ["ux-design", "UX Design", "design", "des:.8 pm:.08", 0, 0.98],
  ["ui-design", "UI Design", "design", "des:.7", 0, 0.97],
  ["user-research", "User Research", "design", "des:.45 pm:.3", 0.004, 0.99],
  ["design-systems", "Design Systems", "design", "des:.4 fe:.1", 0.014, 1.04],
  ["communication", "Communication", "business", "all:.34 pm:.7 des:.4", 0, 0.98],
  ["agile", "Agile", "business", "pm:.55 be:.14 fe:.14 de:.12 all:.1", -0.004, 0.99],
  ["scrum", "Scrum", "business", "pm:.32 all:.05", -0.008, 0.98],
  ["product-management", "Product Management", "business", "pm:.78", 0.004, 1.02],
  ["stakeholder-management", "Stakeholder Management", "business", "pm:.5 da:.14 de:.06", 0.014, 1.02],
  ["roadmapping", "Roadmapping", "business", "pm:.4", 0.006, 1.02],
  ["seo", "SEO", "business", "fe:.05 pm:.06", -0.004, 0.93],
  ["microservices", "Microservices", "other", "be:.34 ops:.2 fe:.03", 0.006, 1.04],
  ["system-design", "System Design", "other", "be:.34 de:.14 ops:.1 ml:.06", 0.016, 1.06],
  ["security", "Security", "other", "ops:.3 be:.14 fe:.04", 0.008, 1.05],
  ["oauth", "OAuth", "other", "be:.1", 0, 1.02],
  ["unit-testing", "Unit Testing", "other", "be:.3 fe:.28 mob:.2", 0, 1.0],
  ["tdd", "Test-Driven Development", "other", "be:.12 fe:.08", -0.006, 1.0],
  ["accessibility", "Accessibility", "other", "fe:.2 des:.28", 0.012, 1.0],
  ["websockets", "WebSockets", "other", "be:.07 fe:.06", 0, 1.02],
  ["sre", "Site Reliability", "other", "ops:.34", 0.008, 1.06],
].map(([slug, name, category, groups, slope, premium]) => {
  const g = {};
  for (const part of groups.split(" ")) {
    const [k, v] = part.split(":");
    g[k] = parseFloat(v);
  }
  return { slug, name, category, g, slope, premium };
});

// ------------------------------------------------------------------- roles
// [role, mix weight, [[group, scale]], salary multiplier, title stem]
// [enum role (ExtractedJob), mix weight, [[skill group, scale]], salary multiplier, title stem]
// Several title stems share one enum value (e.g. every flavour of engineer is software_engineering).
const ROLES = [
  ["data", 15, [["de", 1]], 1.06, "Data Engineer"],
  ["data", 12, [["da", 1]], 0.82, "Data Analyst"],
  ["data", 9, [["ml", 0.8], ["da", 0.85]], 1.04, "Data Scientist"],
  ["data", 8, [["ml", 1], ["be", 0.5]], 1.2, "Machine Learning Engineer"],
  ["software_engineering", 14, [["be", 1]], 1.08, "Backend Engineer"],
  ["software_engineering", 9, [["fe", 1]], 1.0, "Frontend Engineer"],
  ["software_engineering", 11, [["be", 0.75], ["fe", 0.8]], 1.02, "Full-Stack Engineer"],
  ["software_engineering", 3, [["mob", 1]], 1.04, "Mobile Engineer"],
  ["devops_sre", 8, [["ops", 1]], 1.1, "DevOps Engineer"],
  ["product", 5, [["pm", 1]], 1.08, "Product Manager"],
  ["design", 3, [["des", 1]], 0.94, "Product Designer"],
  ["management", 2, [["pm", 0.5], ["be", 0.45]], 1.28, "Engineering Manager"],
  ["marketing", 2, [["pm", 0.35]], 0.85, "Growth Marketing Manager"],
  ["sales", 1.5, [["pm", 0.3]], 0.95, "Account Executive"],
  ["support", 2, [["pm", 0.3]], 0.62, "Customer Support Specialist"],
  ["other", 1, [["pm", 0.3]], 0.8, "Operations Associate"],
].map(([role, weight, groups, mult, stem]) => ({ role, weight, groups, mult, stem }));

const SENIORITY = [
  // key, weight, base annual USD, title prefix
  ["intern", 1, 32000, "Intern"],
  ["junior", 8, 58000, "Junior"],
  ["mid", 28, 88000, ""],
  ["senior", 40, 128000, "Senior"],
  ["lead", 14, 150000, "Lead"],
  ["principal", 5, 185000, "Principal"],
  ["unspecified", 6, 100000, ""],
];

// ----------------------------------------------------------------- sources
const SOURCES = [
  { name: "remotive", display_name: "Remotive", homepage: "https://remotive.com", w: 34 },
  { name: "remoteok", display_name: "Remote OK", homepage: "https://remoteok.com", w: 29 },
  { name: "arbeitnow", display_name: "Arbeitnow", homepage: "https://www.arbeitnow.com", w: 15 },
  { name: "jobicy", display_name: "Jobicy", homepage: "https://jobicy.com", w: 22 },
];

// remote_regions are short free strings from the extractor; location is the board's own text.
const REGIONS = [
  { regions: ["worldwide"], location: "Worldwide", w: 40 },
  { regions: ["US"], location: "USA Only", w: 17 },
  { regions: ["EU"], location: "Europe", w: 15 },
  { regions: ["EU", "UK"], location: "UK & Europe", w: 5 },
  { regions: ["UK"], location: "United Kingdom", w: 5 },
  { regions: ["US", "Canada"], location: "US or Canada", w: 6 },
  { regions: ["Germany"], location: "Germany", w: 4 },
  { regions: ["LATAM"], location: "Latin America", w: 3 },
  { regions: ["APAC"], location: "Asia-Pacific", w: 2 },
  { regions: ["Canada"], location: "Canada", w: 2 },
];

const FX = { USD: 1, EUR: 1.08, GBP: 1.27 };

// --------------------------------------------------------------- companies
const NAME_A = ["North", "Blue", "Bright", "Iron", "Silver", "Open", "Nova", "Quant", "Pixel", "Cloud", "Atlas", "Ember", "Harbor", "Lumen", "Meridian", "Orbit", "Prism", "Rally", "Summit", "Tidal", "Vector", "Willow", "Zenith", "Cobalt", "Fable", "Granite", "Juniper", "Kestrel", "Lattice", "Maple", "Nimbus", "Onyx", "Paper", "Quartz", "Raven", "Signal", "Tern", "Umber", "Vivid", "Wren"];
const NAME_B = ["Labs", "Systems", "Analytics", "Health", "Works", "Cloud", "Data", "Software", "Logic", "Robotics", "Finance", "Commerce", "Security", "Media", "Networks", "AI", "Studio", "Pay", "Mobility", "Energy"];
const companies = [];
{
  const seen = new Set();
  while (companies.length < 210) {
    const n = `${pick(NAME_A)}${rand() < 0.5 ? " " : ""}${pick(NAME_B)}`;
    if (seen.has(n)) continue;
    seen.add(n);
    companies.push({ name: n, w: 1 / Math.pow(companies.length + 3, 0.55) });
  }
}

// ----------------------------------------------------------------- weeks
const thisMonday = mondayOf(NOW);
const weekStarts = Array.from({ length: 8 }, (_, i) => new Date(thisMonday.getTime() - (7 - i) * 7 * DAY));
const weekLabels = weekStarts.map(isoWeek);
const windowStart = weekStarts[0];
const lastWeekFrac = Math.min(1, Math.max(0.15, (NOW.getTime() - thisMonday.getTime()) / (7 * DAY)));

const TARGET_JOBS = 612;
const weekWeights = weekStarts.map((_, i) => (0.88 + 0.035 * i) * (i === 7 ? lastWeekFrac : 1));
const weekWeightSum = weekWeights.reduce((a, b) => a + b, 0);
const weekCounts = weekWeights.map((w) => Math.round((w / weekWeightSum) * TARGET_JOBS));

// ------------------------------------------------------------------ jobs
function skillProb(skill, role, weekIdx) {
  let p = 0;
  for (const [group, scale] of role.groups) {
    const gp = (skill.g[group] ?? 0) * scale;
    if (gp > p) p = gp;
  }
  const generic = (skill.g.all ?? 0) * 0.8;
  if (generic > p) p = generic;
  // trend: multiplicative drift centred on the middle of the window
  p *= Math.pow(1 + skill.slope, weekIdx - 3.5);
  return Math.min(0.97, p);
}

function stratified(items, weightOf, n) {
  const total = items.reduce((a, x) => a + weightOf(x), 0);
  const quotas = items.map((x) => (weightOf(x) / total) * n);
  const out = [];
  const rema = [];
  quotas.forEach((q, i) => {
    for (let k = 0; k < Math.floor(q); k += 1) out.push(items[i]);
    rema.push([q - Math.floor(q), i]);
  });
  rema.sort((a, b) => b[0] - a[0]);
  for (let k = 0; out.length < n; k += 1) out.push(items[rema[k % rema.length][1]]);
  return out.sort(() => rand() - 0.5);
}

const jobs = [];
let nextId = 41000;
for (let w = 0; w < 8; w += 1) {
  const start = weekStarts[w].getTime();
  const span = (w === 7 ? NOW.getTime() - start : 7 * DAY);
  const rolePlan = stratified(ROLES, (r) => r.weight, weekCounts[w]);
  const senPlan = stratified(SENIORITY, (x) => x[1], weekCounts[w]);
  for (let k = 0; k < weekCounts[w]; k += 1) {
    const role = rolePlan[k];
    const sen = senPlan[k];
    const [seniority, , baseSalary, prefix] = sen;
    const source = weighted(SOURCES, (s) => s.w);
    const region = weighted(REGIONS, (r) => r.w);
    const company = weighted(companies, (c) => c.w);

    // posted_at: weekday-heavy, within the week
    let t = start + Math.floor(rand() * span);
    const dow = new Date(t).getUTCDay();
    if ((dow === 0 || dow === 6) && rand() < 0.65 && w < 7) t -= (dow === 0 ? 2 : 1) * DAY;
    if (t < windowStart.getTime()) t = windowStart.getTime() + 3600_000;
    if (t > NOW.getTime()) t = NOW.getTime() - Math.floor(rand() * 6 * 3600_000);

    // employment type
    const et = rand();
    const employment_type = et < 0.85 ? "full_time" : et < 0.93 ? "contract" : et < 0.97 ? "part_time" : "unspecified";

    // title
    const stemVariants = [role.stem, role.stem, role.stem, `${role.stem} (Remote)`];
    let title = `${prefix ? `${prefix} ` : ""}${pick(stemVariants)}`;
    if (role.stem === "Data Analyst" && rand() < 0.25) title = title.replace("Data Analyst", "Analytics Engineer");

    const id = `${source.name}-${nextId++}`;
    jobs.push({
      id,
      title,
      company: company.name,
      // sample links only point at the source homepage (with a marker fragment)
      url: `${source.homepage}/#sample-${id}`,
      source: source.name,
      posted_at: new Date(t).toISOString().replace(/\.\d{3}Z$/, "Z"),
      location: region.location,
      remote_regions: region.regions,
      role: role.role,
      seniority,
      employment_type,
      skills: [],
      salary: null,
      _week: w,
      _ctx: { role, baseSalary, region, employment_type },
    });
  }
}

// ---- skills: stratified per (skill, week) so trends are signal, not noise ----
function sampleWithoutReplacement(items, weights, n) {
  return items
    .map((it, i) => ({ it, key: Math.pow(rand(), 1 / Math.max(weights[i], 1e-9)) }))
    .sort((a, b) => b.key - a.key)
    .slice(0, n)
    .map((x) => x.it);
}
const SKILL_SCALE = (() => {
  // scale probabilities so a job lists ~8 skills on average
  let total = 0;
  let n = 0;
  for (const j of jobs) {
    for (const s of SKILLS) total += skillProb(s, j._ctx.role, j._week);
    n += 1;
  }
  return 8.2 / (total / n);
})();
for (let w = 0; w < 8; w += 1) {
  const wk = jobs.filter((j) => j._week === w);
  for (const s of SKILLS) {
    const ps = wk.map((j) => Math.min(0.95, skillProb(s, j._ctx.role, w) * SKILL_SCALE));
    const expected = ps.reduce((a, b) => a + b, 0);
    const target = Math.max(0, Math.min(wk.length, Math.round(expected + 0.18 * Math.sqrt(expected) * gauss())));
    for (const j of sampleWithoutReplacement(wk, ps, target)) j.skills.push(s.slug);
  }
}
for (const j of jobs) {
  if (j.skills.length < 3) {
    const pool = SKILLS.filter((s) => (s.g[j._ctx.role.groups[0][0]] ?? 0) > 0.25 && !j.skills.includes(s.slug));
    while (j.skills.length < 3 && pool.length) j.skills.push(pool.splice(Math.floor(rand() * pool.length), 1)[0].slug);
  }
  if (j.skills.length > 14) j.skills = j.skills.sort(() => rand() - 0.5).slice(0, 14);
}

// ---- salary (depends on seniority, role and the skills listed) ----
const premiumOf = new Map(SKILLS.map((s) => [s.slug, s.premium]));
for (const j of jobs) {
  const { role, baseSalary, region, employment_type } = j._ctx;
  const w = j._week;
  const seniority = j.seniority;
  if (!(rand() < (seniority === "intern" ? 0.2 : 0.43))) continue;
  const premium = j.skills.reduce((acc, sl) => acc + premiumOf.get(sl), 0) / j.skills.length;
  const usdMid = baseSalary * role.mult * premium * Math.exp(0.15 * gauss()) * (1 + (w - 3.5) * 0.002);
  let currency = "USD";
  const cr = rand();
  if (["EU", "Germany"].includes(region.regions[0])) currency = cr < 0.75 ? "EUR" : "USD";
  else if (region.regions[0] === "UK") currency = cr < 0.85 ? "GBP" : "USD";
  else currency = cr < 0.06 ? "EUR" : "USD";
  let period = "year";
  const pr = rand();
  if (employment_type === "contract" && pr < 0.6) period = "hour";
  else if (currency === "EUR" && pr < 0.07) period = "month";
  const annualLocalMid = usdMid / FX[currency];
  const lo = annualLocalMid * (0.86 + rand() * 0.08);
  const hi = annualLocalMid * (1.08 + rand() * 0.1);
  let min;
  let max;
  if (period === "year") {
    const step = rand() < 0.6 ? 5000 : 1000;
    min = round(lo, step);
    max = round(hi, step);
  } else if (period === "month") {
    min = round(lo / 12, 100);
    max = round(hi / 12, 100);
  } else {
    min = round(lo / 2080, 1);
    max = round(hi / 2080, 1);
  }
  const mult = period === "year" ? 1 : period === "month" ? 12 : 2080;
  j.salary = { min, max, currency, period, annual_usd_mid: Math.round(((min + max) / 2) * mult * FX[currency]) };
}
for (const j of jobs) delete j._ctx;

jobs.sort((a, b) => b.posted_at.localeCompare(a.posted_at));

// ------------------------------------------------------------- aggregates
const jobsPerWeek = new Array(8).fill(0);
for (const j of jobs) jobsPerWeek[j._week] += 1;
const totalJobs = jobs.length;
const salaryOf = (j) => (j.salary ? j.salary.annual_usd_mid : null);

const bySkill = new Map(SKILLS.map((s) => [s.slug, []]));
for (const j of jobs) for (const s of j.skills) bySkill.get(s).push(j);

function median(values) {
  const v = values.filter((x) => x != null).sort((a, b) => a - b);
  return v.length ? quantile(v, 0.5) : null;
}

const skillsOut = SKILLS.map((s) => {
  const js = bySkill.get(s.slug);
  const weekly = new Array(8).fill(0);
  for (const j of js) weekly[j._week] += 1;
  const lastN = weekly.slice(4).reduce((a, b) => a + b, 0);
  const lastJobs = jobsPerWeek.slice(4).reduce((a, b) => a + b, 0);
  const prevN = weekly.slice(0, 4).reduce((a, b) => a + b, 0);
  const prevJobs = jobsPerWeek.slice(0, 4).reduce((a, b) => a + b, 0);
  const change = (lastN / lastJobs - prevN / prevJobs) * 100;
  const co = new Map();
  for (const j of js) for (const o of j.skills) if (o !== s.slug) co.set(o, (co.get(o) ?? 0) + 1);
  const sal = js.map(salaryOf).filter((x) => x != null);
  return {
    slug: s.slug,
    name: s.name,
    category: s.category,
    count: js.length,
    share: r4(js.length / totalJobs),
    change_4w: Math.round(change * 10) / 10,
    median_salary_usd: sal.length >= 4 ? Math.round(median(sal) / 500) * 500 : null,
    trend: weekLabels.map((week, i) => ({ week, count: weekly[i], share: r4(weekly[i] / jobsPerWeek[i]) })),
    cooccurring: [...co.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 12).map(([slug, count]) => ({ slug, count })),
  };
})
  .filter((s) => s.count >= 3)
  .sort((a, b) => b.count - a.count || a.slug.localeCompare(b.slug));

const keptSlugs = new Set(skillsOut.map((s) => s.slug));
for (const j of jobs) j.skills = j.skills.filter((s) => keptSlugs.has(s));

// roles
const rolesOut = [...new Set(ROLES.map((r) => r.role))].map((role) => {
  const js = jobs.filter((j) => j.role === role);
  return { role, count: js.length, median_salary_usd: (() => { const m = median(js.map(salaryOf)); const n = js.filter((j) => j.salary).length; return n >= 4 ? Math.round(m / 500) * 500 : null; })() };
}).sort((a, b) => b.count - a.count);

// salary distributions
function dist(key, values) {
  const v = values.sort((a, b) => a - b);
  return { key, n: v.length, p10: Math.round(quantile(v, 0.1)), p25: Math.round(quantile(v, 0.25)), median: Math.round(quantile(v, 0.5)), p75: Math.round(quantile(v, 0.75)), p90: Math.round(quantile(v, 0.9)) };
}
function groupDist(keyFn) {
  const m = new Map();
  for (const j of jobs) {
    const k = keyFn(j);
    const s = salaryOf(j);
    if (k == null || s == null) continue;
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(s);
  }
  return [...m.entries()].filter(([, v]) => v.length >= 5).map(([k, v]) => dist(k, v));
}
const senOrder = ["intern", "junior", "mid", "senior", "lead", "principal", "unspecified"];
const salaryOut = {
  by_seniority: groupDist((j) => j.seniority).sort((a, b) => senOrder.indexOf(a.key) - senOrder.indexOf(b.key)),
  by_role: groupDist((j) => j.role).sort((a, b) => b.median - a.median),
};

// sources
const sourcesOut = SOURCES.map((s) => ({
  name: s.name,
  display_name: s.display_name,
  homepage: s.homepage,
  jobs: jobs.filter((j) => j.source === s.name).length,
}));

const metaOut = {
  sample: true,
  generated_at: NOW.toISOString().replace(/\.\d{3}Z$/, "Z"),
  last_run_at: new Date(NOW.getTime() - 25 * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"),
  window_days: 56,
  backend: "claude",
  model: "claude-haiku-4-5",
  totals: {
    jobs: totalJobs,
    companies: new Set(jobs.map((j) => j.company)).size,
    with_salary: jobs.filter((j) => j.salary).length,
    skills: skillsOut.length,
  },
  sources: sourcesOut,
  weekly: weekLabels.map((week, i) => ({ week, jobs: jobsPerWeek[i] })),
};

const evalOut = {
  generated_at: new Date(NOW.getTime() - 3 * DAY).toISOString().replace(/\.\d{3}Z$/, "Z"),
  n_labeled: 150,
  backends: [
    { backend: "claude", model: "claude-haiku-4-5", skills_precision: 0.914, skills_recall: 0.872, skills_f1: 0.892, seniority_acc: 0.847, role_acc: 0.907, salary_acc: 0.933, median_latency_ms: 1840, cost_per_1k_usd: 1.46, failures: 1 },
    { backend: "ollama", model: "gemma4:12b", skills_precision: 0.846, skills_recall: 0.781, skills_f1: 0.812, seniority_acc: 0.74, role_acc: 0.833, salary_acc: 0.867, median_latency_ms: 6420, cost_per_1k_usd: 0, failures: 7 },
  ],
};

// ---------------------------------------------------------------- write
const jobsOut = jobs.map((j) => {
  const { _week, ...rest } = j;
  void _week;
  return rest;
});

mkdirSync(OUT, { recursive: true });
const write = (name, data) => writeFileSync(path.join(OUT, name), `${JSON.stringify(data)}\n`);
write("meta.json", metaOut);
write("skills.json", skillsOut);
write("roles.json", rolesOut);
write("salary.json", salaryOut);
write("jobs.json", jobsOut);
write("eval.json", evalOut);

console.log(
  `Sample snapshot written to ${OUT}\n  jobs=${totalJobs} companies=${metaOut.totals.companies} with_salary=${metaOut.totals.with_salary} skills=${skillsOut.length}\n  weeks=${weekLabels.join(", ")}\n  per week=${jobsPerWeek.join(", ")}`,
);
