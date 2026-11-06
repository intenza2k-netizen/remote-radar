"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { GROUP_BY_ID, NETWORK_GROUPS } from "./stats";
import { fmtInt } from "@/lib/format";
import type { NetLayout, NetworkData } from "@/lib/insights";

type State = { active: string | null; group: string | null };

/**
 * Skill co-occurrence network. The layout (positions, label placement) is computed on the server at
 * build time, so this component only draws SVG and handles highlighting. Hover or keyboard focus on a
 * bubble highlights its partners; on touch screens the first tap selects (and shows a link), the second
 * follows it. The legend doubles as a filter by category, so identity never depends on colour alone.
 */
export function SkillNetwork({ data }: { data: NetworkData }) {
  const [hover, setHover] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [group, setGroup] = useState<string | null>(null);

  const bySlug = useMemo(() => new Map(data.nodes.map((n) => [n.slug, n])), [data.nodes]);
  const neighbours = useMemo(() => {
    const m = new Map<string, { slug: string; pmi: number; count: number }[]>();
    for (const e of data.edges) {
      if (!bySlug.has(e.a) || !bySlug.has(e.b)) continue;
      (m.get(e.a) ?? m.set(e.a, []).get(e.a)!).push({ slug: e.b, pmi: e.pmi, count: e.count });
      (m.get(e.b) ?? m.set(e.b, []).get(e.b)!).push({ slug: e.a, pmi: e.pmi, count: e.count });
    }
    for (const list of m.values()) list.sort((x, y) => y.pmi - x.pmi || y.count - x.count);
    return m;
  }, [data.edges, bySlug]);

  const active = hover ?? pinned;
  const activeNode = active ? bySlug.get(active) : undefined;
  const near = active ? new Set((neighbours.get(active) ?? []).map((x) => x.slug)) : null;
  const groupCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const n of data.nodes) m.set(n.group, (m.get(n.group) ?? 0) + 1);
    return m;
  }, [data.nodes]);

  const state: State = { active, group };

  return (
    <div>
      <div role="group" aria-label="Filter the map by category" className="flex flex-wrap gap-2">
        {NETWORK_GROUPS.filter((g) => groupCounts.has(g.id)).map((g) => (
          <button key={g.id} type="button" className="chip" aria-pressed={group === g.id} onClick={() => setGroup(group === g.id ? null : g.id)}>
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: g.color, boxShadow: group === g.id ? "0 0 0 2px var(--bg)" : "none" }} />
            {g.label} <span className="tnum opacity-60">{groupCounts.get(g.id)}</span>
          </button>
        ))}
      </div>

      <div className="card mt-4 p-1.5 sm:p-3">
        <div className="md:hidden">
          <Net layout={data.tall} data={data} state={state} near={near} bySlug={bySlug} onHover={setHover} onPin={setPinned} pinned={pinned} suffix="tall" />
        </div>
        <div className="hidden md:block">
          <Net layout={data.wide} data={data} state={state} near={near} bySlug={bySlug} onHover={setHover} onPin={setPinned} pinned={pinned} suffix="wide" />
        </div>
      </div>

      <div className="mt-3 min-h-[4.5rem] text-sm" aria-live="polite">
        {activeNode ? (
          <div>
            <p className="text-ink">
              <strong className="font-semibold">{activeNode.name}</strong>{" "}
              <span className="text-ink-3">
                &middot; {GROUP_BY_ID.get(activeNode.group)?.label} &middot; {fmtInt(activeNode.count)} postings &middot;{" "}
              </span>
              <Link href={`/skills/${activeNode.slug}`} className="link">
                Open skill page
              </Link>
            </p>
            {(neighbours.get(activeNode.slug) ?? []).length ? (
              <p className="mt-1 text-ink-2">
                Closest partners:{" "}
                {(neighbours.get(activeNode.slug) ?? [])
                  .slice(0, 5)
                  .map((p) => `${bySlug.get(p.slug)?.name ?? p.slug} (${fmtInt(p.count)} together, ${fmtInt(2 ** p.pmi)}× chance)`)
                  .join("; ")}
                .
              </p>
            ) : (
              <p className="mt-1 text-ink-3">No pairing with enough shared postings to draw a line.</p>
            )}
          </div>
        ) : (
          <p className="text-ink-3">
            Hover or focus a bubble to see its partners. On a touch screen, tap a bubble, then follow the link. Bubble area shows how many postings mention the skill; lines join skills that often appear together.
          </p>
        )}
      </div>
    </div>
  );
}

function Net({
  layout,
  data,
  state,
  near,
  bySlug,
  onHover,
  onPin,
  pinned,
  suffix,
}: {
  layout: NetLayout;
  data: NetworkData;
  state: State;
  near: Set<string> | null;
  bySlug: Map<string, NetworkData["nodes"][number]>;
  onHover: (s: string | null) => void;
  onPin: (s: string | null) => void;
  pinned: string | null;
  suffix: string;
}) {
  const { active, group } = state;
  const fs = layout.fontSize;
  const inGroup = (slug: string) => !group || bySlug.get(slug)?.group === group;

  return (
    <svg
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      className="block h-auto w-full"
      role="group"
      aria-label={`Network of the ${data.nodes.length} most requested skills. Each bubble is a skill, sized by postings; lines join skills that often appear together. A table of the strongest pairs follows.`}
    >
      <g aria-hidden="true">
        {layout.edges.map((e) => {
          const touches = active != null && (e.a === active || e.b === active);
          let opacity = e.o;
          let width = e.w * 0.8;
          if (active) {
            opacity = touches ? 0.85 : 0.04;
            width = touches ? e.w + 0.6 : e.w * 0.6;
          } else if (group) {
            opacity = inGroup(e.a) || inGroup(e.b) ? e.o : 0.03;
          }
          return <line key={`${e.a}|${e.b}`} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke={touches ? "var(--ink-2)" : "var(--ink-3)"} strokeWidth={width} strokeLinecap="round" opacity={opacity} />;
        })}
      </g>

      {layout.nodes.map((p) => {
        const node = bySlug.get(p.slug);
        if (!node) return null;
        const color = GROUP_BY_ID.get(node.group)?.color ?? "var(--muted)";
        const isActive = active === p.slug;
        const isNear = near?.has(p.slug) ?? false;
        let dim = false;
        if (active) dim = !isActive && !isNear;
        else if (group) dim = !inGroup(p.slug);
        const showLabel = p.label != null ? !dim || isNear || isActive : isActive || isNear || (!!group && inGroup(p.slug));
        const lx = p.label?.x ?? Math.max(2, Math.min(layout.width - 2 - node.name.length * fs * 0.56, p.x - (node.name.length * fs * 0.56) / 2));
        const ly = p.label?.y ?? p.y + p.r + fs * 0.95 + 1;
        return (
          <Link
            key={p.slug}
            href={`/skills/${p.slug}`}
            aria-label={`${node.name}: ${fmtInt(node.count)} postings, ${GROUP_BY_ID.get(node.group)?.label ?? ""}`}
            onMouseEnter={() => onHover(p.slug)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(p.slug)}
            onBlur={() => onHover(null)}
            onClick={(e) => {
              if (typeof window !== "undefined" && window.matchMedia("(hover: none)").matches && pinned !== p.slug) {
                e.preventDefault();
                onPin(p.slug);
              }
            }}
            style={{ outline: "none", cursor: "pointer" }}
            data-net={suffix}
          >
            <circle cx={p.x} cy={p.y} r={Math.max(p.r + 3, 11)} fill="transparent" />
            {isActive ? <circle cx={p.x} cy={p.y} r={p.r + 4} fill="none" stroke="var(--accent)" strokeWidth={2} /> : null}
            <circle cx={p.x} cy={p.y} r={p.r} fill={color} stroke="var(--surface)" strokeWidth={1.5} opacity={dim ? 0.16 : isActive || isNear ? 1 : 0.9} />
            {showLabel ? (
              <text
                x={lx}
                y={ly}
                fontSize={fs}
                fill="var(--ink)"
                stroke="var(--surface)"
                strokeWidth={3.5}
                strokeLinejoin="round"
                paintOrder="stroke"
                opacity={dim ? 0.3 : 1}
                fontWeight={isActive ? 600 : 400}
                pointerEvents="none"
              >
                {node.name}
              </text>
            ) : null}
          </Link>
        );
      })}
    </svg>
  );
}
