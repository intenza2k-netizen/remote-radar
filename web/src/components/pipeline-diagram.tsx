type Node = { title: string; lines: [string, string]; accent?: boolean };

const NODES: Node[] = [
  { title: "1  Sources", lines: ["5 job boards, 3 career-page", "APIs, Hacker News"] },
  { title: "2  Normalize", lines: ["HTML to text, salary parse,", "company + title dedupe"] },
  { title: "3  LLM extraction", lines: ["skills, seniority, role, pay", "Claude or local Gemma"], accent: true },
  { title: "4  Aggregate", lines: ["weekly trends, co-occurrence,", "salary percentiles in USD"] },
  { title: "5  Publish", lines: ["static JSON snapshot", "written to web/public/data"] },
  { title: "6  This site", lines: ["Next.js, prerendered,", "reads only the snapshot"] },
];

const FONT = "var(--font-geist-sans), system-ui, sans-serif";

function Box({ x, y, w, h, node }: { x: number; y: number; w: number; h: number; node: Node }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={10} fill="var(--surface)" stroke={node.accent ? "var(--s1)" : "var(--border-strong)"} strokeWidth={node.accent ? 2 : 1} />
      <text x={x + 14} y={y + 27} fontSize={14} fontWeight={600} fill="var(--ink)" fontFamily={FONT}>
        {node.title}
      </text>
      <text x={x + 14} y={y + 49} fontSize={12} fill="var(--ink-2)" fontFamily={FONT}>
        {node.lines[0]}
      </text>
      <text x={x + 14} y={y + 66} fontSize={12} fill="var(--ink-2)" fontFamily={FONT}>
        {node.lines[1]}
      </text>
    </g>
  );
}

/** Inline SVG pipeline diagram; all colors are CSS variables so both themes work. Horizontal on wide screens, vertical on narrow ones. */
export function PipelineDiagram() {
  const bw = 196;
  const bh = 80;
  const gap = 40;
  const vh = NODES.length * bh + (NODES.length - 1) * 34;

  return (
    <figure className="card m-0 p-4 sm:p-6">
      {/* Wide layout: two rows of three so text stays readable */}
      <svg className="mx-auto hidden w-full max-w-3xl md:block" viewBox={`-2 -2 ${3 * bw + 2 * gap + 4} ${2 * bh + 74}`} role="img" aria-labelledby="pipe-title pipe-desc">
        <title id="pipe-title">Remote Radar data pipeline</title>
        <desc id="pipe-desc">
          Postings are fetched from remote job boards, company career pages and Hacker News, normalized and deduplicated, passed through an LLM that extracts skills, seniority, role and salary, aggregated into weekly statistics, published as a static JSON snapshot and rendered by this site. The pipeline runs nightly.
        </desc>
        <defs>
          <marker id="arrow-h" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M1 1 9 5 1 9" fill="none" stroke="var(--ink-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </marker>
        </defs>
        {NODES.slice(0, 3).map((n, i) => (
          <Box key={n.title} x={i * (bw + gap)} y={0} w={bw} h={bh} node={n} />
        ))}
        {NODES.slice(3).map((n, i) => (
          <Box key={n.title} x={i * (bw + gap)} y={bh + 70} w={bw} h={bh} node={n} />
        ))}
        {/* row 1 arrows */}
        {[0, 1].map((i) => (
          <line key={`a${i}`} x1={i * (bw + gap) + bw + 4} y1={bh / 2} x2={(i + 1) * (bw + gap) - 4} y2={bh / 2} stroke="var(--ink-3)" strokeWidth={1.5} markerEnd="url(#arrow-h)" />
        ))}
        {/* wrap from node 3 down to node 4 */}
        <path
          d={`M${2 * (bw + gap) + bw / 2} ${bh + 4} V${bh + 35} H${bw / 2} V${bh + 66}`}
          fill="none"
          stroke="var(--ink-3)"
          strokeWidth={1.5}
          strokeLinejoin="round"
          markerEnd="url(#arrow-h)"
        />
        {/* row 2 arrows */}
        {[0, 1].map((i) => (
          <line key={`b${i}`} x1={i * (bw + gap) + bw + 4} y1={bh + 70 + bh / 2} x2={(i + 1) * (bw + gap) - 4} y2={bh + 70 + bh / 2} stroke="var(--ink-3)" strokeWidth={1.5} markerEnd="url(#arrow-h)" />
        ))}
        <text x={(3 * bw + 2 * gap) / 2} y={bh + 28} textAnchor="middle" fontSize={11} fill="var(--ink-3)" fontFamily={FONT} className="tnum">
          runs nightly
        </text>
      </svg>

      {/* Narrow layout: one column */}
      <svg className="mx-auto w-full max-w-sm md:hidden" viewBox={`-2 -2 ${bw + 124} ${vh + 4}`} role="img" aria-label="Remote Radar data pipeline, in six steps: sources, normalize, LLM extraction, aggregate, publish, this site.">
        <defs>
          <marker id="arrow-v" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M1 1 9 5 1 9" fill="none" stroke="var(--ink-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </marker>
        </defs>
        {NODES.map((n, i) => (
          <g key={n.title}>
            <Box x={0} y={i * (bh + 34)} w={bw + 120} h={bh} node={n} />
            {i < NODES.length - 1 ? (
              <line x1={(bw + 120) / 2} y1={i * (bh + 34) + bh + 3} x2={(bw + 120) / 2} y2={(i + 1) * (bh + 34) - 3} stroke="var(--ink-3)" strokeWidth={1.5} markerEnd="url(#arrow-v)" />
            ) : null}
          </g>
        ))}
      </svg>
      <figcaption className="mt-3 text-sm text-ink-3">The whole pipeline runs nightly. The website is a static build that reads only the JSON snapshot in step 5: no database or API is queried at runtime.</figcaption>
    </figure>
  );
}
