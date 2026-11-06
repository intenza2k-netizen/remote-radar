import { describe, expect, it } from "vitest";
import { compileVocab, detectSkills, vocabFromSkills } from "./vocab";
import type { VocabEntry } from "./types";

const V = (slug: string, name: string, patterns: string[], strict = false): VocabEntry => ({ slug, name, category: "other", patterns, strict });

const vocab = compileVocab([
  V("python", "Python", ["python", "python3"]),
  V("sql", "SQL", ["sql", "t-sql"]),
  V("react", "React", ["react", "reactjs"]),
  V("react-native", "React Native", ["react native"]),
  V("cpp", "C++", ["c++", "cpp"]),
  V("csharp", "C#", ["c#", "csharp"]),
  V("c", "C", ["c", "c language"], true),
  V("go", "Go", ["go", "golang"], true),
  V("r", "R", ["r", "r language", "rstats"], true),
  V("excel", "Excel", ["excel", "microsoft excel", "vlookup"], true),
  V("nodejs", "Node.js", ["node.js", "nodejs", "node js"]),
  V("machine-learning", "Machine Learning", ["machine learning", "ml"], true),
  V("tableau", "Tableau", ["tableau"]),
  V("ci-cd", "CI/CD", ["ci/cd"]),
]);

const slugs = (text: string) => detectSkills(text, vocab).map((d) => d.slug).sort();

describe("detectSkills: word boundaries", () => {
  it("is case-insensitive for plain patterns", () => {
    expect(slugs("Built pipelines in PYTHON and sql.")).toEqual(["python", "sql"]);
  });
  it("does not match inside other words", () => {
    expect(slugs("Pythonic code, sqlite and reactive systems")).toEqual([]);
  });
  it("treats hyphen and space as the same separator", () => {
    expect(slugs("machine-learning and Machine   Learning")).toEqual(["machine-learning"]);
    expect(detectSkills("machine-learning and Machine Learning", vocab)[0].mentions).toBe(2);
  });
  it("handles symbols: c++, c#, node.js, ci/cd", () => {
    expect(slugs("Wrote C++ and C# services on Node.js with CI/CD")).toEqual(["ci-cd", "cpp", "csharp", "nodejs"]);
  });
  it("prefers the longer pattern and consumes it", () => {
    expect(slugs("Shipped a React Native app")).toEqual(["react-native"]);
    expect(slugs("React and React Native")).toEqual(["react", "react-native"]);
  });
  it("counts mentions", () => {
    expect(detectSkills("SQL, SQL and more SQL", vocab)).toEqual([{ slug: "sql", mentions: 3 }]);
  });
  it("does not crash on empty text", () => {
    expect(detectSkills("", vocab)).toEqual([]);
  });
});

describe("detectSkills: strict patterns", () => {
  it("accepts Go only when capitalised and near programming words", () => {
    expect(slugs("Backend services in Go and Python")).toEqual(["go", "python"]);
    expect(slugs("I wrote Go programming code every day")).toEqual(["go"]);
    expect(slugs("Ready to go. Let's go to the market. Go-to-market strategy.")).toEqual([]);
    expect(slugs("go programming language")).toEqual([]); // wrong case
  });
  it("accepts golang unconditionally (not ambiguous)", () => {
    expect(slugs("Experienced with golang")).toEqual(["go"]);
  });
  it("accepts R as a standalone token near stats words or other skills", () => {
    expect(slugs("Statistical analysis in R")).toEqual(["r"]);
    expect(slugs("Skills: Python, R, SQL")).toEqual(["python", "r", "sql"]);
    expect(slugs("Worked in R&D on hardware")).toEqual([]);
    expect(slugs("Plan A or plan B, or R maybe")).toEqual([]);
    expect(slugs("A tidy dataset, ggplot2 and tidyverse in r")).toEqual([]); // lower-case r is not accepted
  });
  it("does not read C inside C++ / C# / sentences", () => {
    expect(slugs("C++ and C#")).toEqual(["cpp", "csharp"]);
    expect(slugs("Vitamin C, plan C and Option C")).toEqual([]);
    expect(slugs("Embedded C programming")).toEqual(["c"]);
  });
  it("accepts Excel only next to other skills, never in prose", () => {
    expect(slugs("We excel at problem solving")).toEqual([]);
    expect(slugs("Excel in your role and learn fast")).toEqual([]);
    expect(slugs("SQL, Excel, Tableau")).toEqual(["excel", "sql", "tableau"]);
    expect(slugs("Microsoft Excel and VLOOKUP")).toEqual(["excel"]);
  });
  it("requires uppercase for short acronyms", () => {
    expect(slugs("Applied ML for ranking, with Python")).toContain("machine-learning");
    expect(slugs("html and ml stuff")).toEqual([]);
  });
});

describe("strict_patterns (per-pattern strictness)", () => {
  const v = compileVocab([
    { slug: "python", name: "Python", category: "language", patterns: ["python", "py"], strict: false, strict_patterns: ["py"] },
    { slug: "react", name: "React", category: "framework", patterns: ["react", "reactjs"], strict: true, strict_patterns: ["react"] },
    { slug: "go", name: "Go", category: "language", patterns: ["go", "golang"], strict: true, strict_patterns: ["go"] },
  ]);
  const s = (x: string) => detectSkills(x, v).map((d) => d.slug).sort();
  it("treats only the listed patterns as strict", () => {
    expect(s("I write python every day")).toEqual(["python"]);
    expect(s("a py script")).toEqual([]); // "py" lower-case is not accepted
    expect(s("reactjs and golang")).toEqual(["go", "react"]);
  });
  it("accepts a risky word with an unmistakable tool context", () => {
    expect(s("Built UIs as a React developer")).toEqual(["react"]);
    expect(s("We react quickly to change")).toEqual([]);
    expect(s("Reaction time matters")).toEqual([]);
  });
});

describe("vocabFromSkills", () => {
  it("builds a usable fallback vocabulary", () => {
    const v = compileVocab(vocabFromSkills([{ slug: "power-bi", name: "Power BI", category: "tool" }]));
    expect(detectSkills("Dashboards in Power BI", v).map((d) => d.slug)).toEqual(["power-bi"]);
  });
});

describe("performance", () => {
  it("scans a long CV with a large vocabulary quickly", () => {
    const big = compileVocab(Array.from({ length: 700 }, (_, i) => V(`skill-${i}`, `Skill ${i}`, [`skill ${i}`, `sk${i}x`, `alias number ${i}`])));
    const text = "Worked with sql, python and skill 5 on many things. ".repeat(400);
    const t0 = performance.now();
    detectSkills(text, big);
    expect(performance.now() - t0).toBeLessThan(1500);
  });
});
