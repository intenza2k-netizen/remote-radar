"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { LineChart, type LineSeries } from "./line-chart";
import { SkillPicker } from "../skill-picker";
import { fmtInt, fmtWeek } from "@/lib/format";
import { weekPos } from "@/lib/weeks";
import type { TrendPoint } from "@/lib/types";

export type TrendSkill = { slug: string; name: string; category: string; count: number; trend: TrendPoint[] };

const MAX = 6;
// Categorical slots in fixed order; a skill keeps its slot while it stays selected.
const SLOT_VARS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];

type Picked = { slug: string; slot: number };

export function TrendExplorer({ skills, defaultSlugs }: { skills: TrendSkill[]; defaultSlugs: string[] }) {
  const [picked, setPicked] = useState<Picked[]>(() => defaultSlugs.slice(0, MAX).map((slug, slot) => ({ slug, slot })));
  const bySlug = useMemo(() => new Map(skills.map((s) => [s.slug, s])), [skills]);

  function add(slug: string) {
    setPicked((cur) => {
      if (cur.length >= MAX || cur.some((p) => p.slug === slug)) return cur;
      const used = new Set(cur.map((p) => p.slot));
      let slot = 0;
      while (used.has(slot)) slot += 1;
      return [...cur, { slug, slot }];
    });
  }
  function remove(slug: string) {
    setPicked((cur) => cur.filter((p) => p.slug !== slug));
  }

  const xs = skills[0]?.trend.map((t) => t.week) ?? [];
  const series: LineSeries[] = picked.flatMap((p) => {
    const s = bySlug.get(p.slug);
    if (!s) return [];
    return [
      {
        id: s.slug,
        label: s.name,
        color: SLOT_VARS[p.slot],
        points: s.trend.map((t) => ({ x: t.week, value: t.share, note: `${fmtInt(t.count)} jobs` })),
      },
    ];
  });

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start">
        <div className="sm:w-72">
          <SkillPicker
            label="Add a skill to the trend chart"
            options={skills}
            selected={picked.map((p) => p.slug)}
            onPick={add}
            disabled={picked.length >= MAX}
            placeholder={picked.length >= MAX ? `Up to ${MAX} skills` : "Add a skill…"}
          />
        </div>
        <ul className="flex flex-1 flex-wrap gap-2" aria-label="Selected skills (also the chart legend)">
          {series.map((s) => (
            <li key={s.id}>
              <span className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface py-1 pl-3 pr-1 text-sm text-ink">
                <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ background: s.color }} />
                <Link href={`/skills/${s.id}`} className="text-ink no-underline hover:underline">
                  {s.label}
                </Link>
                <button
                  type="button"
                  onClick={() => remove(s.id)}
                  className="grid h-6 w-6 place-items-center rounded-full text-ink-3 hover:bg-surface-2 hover:text-ink"
                  aria-label={`Remove ${s.label} from the chart`}
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                    <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </button>
              </span>
            </li>
          ))}
        </ul>
      </div>

      {series.length ? (
        <LineChart
          series={series}
          xs={xs}
          xLabel={fmtWeek}
          xPos={weekPos}
          valueLabel={(v) => `${(Math.round(v * 1000) / 10).toString()}%`}
          ariaLabel="Share of job postings mentioning each selected skill, by week"
          hideLegend
          measure="Share of postings"
        />
      ) : (
        <p className="rounded-lg border border-dashed border-line-strong p-8 text-center text-sm text-ink-3">Add a skill to see its weekly trend.</p>
      )}
    </div>
  );
}
