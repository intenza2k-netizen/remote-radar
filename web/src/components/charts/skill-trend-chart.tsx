"use client";

import { LineChart } from "./line-chart";
import { fmtInt, fmtWeek } from "@/lib/format";
import { weekPos } from "@/lib/weeks";
import type { TrendPoint } from "@/lib/types";

/** Single-skill weekly share (client wrapper so formatter functions stay on the client side). */
export function SkillTrendChart({ name, trend }: { name: string; trend: TrendPoint[] }) {
  return (
    <LineChart
      area
      series={[{ id: name, label: name, color: "var(--s1)", points: trend.map((t) => ({ x: t.week, value: t.share, note: `${fmtInt(t.count)} jobs` })) }]}
      xs={trend.map((t) => t.week)}
      xLabel={fmtWeek}
      xPos={weekPos}
      valueLabel={(v) => `${Math.round(v * 1000) / 10}%`}
      ariaLabel={`Share of weekly job postings mentioning ${name}`}
      measure="Share of postings"
    />
  );
}
