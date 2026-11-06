"use client";

import { useId, useMemo, useRef, useState } from "react";
import { categoryLabel, fmtInt } from "@/lib/format";

export type PickerOption = { slug: string; name: string; count: number; category: string };

type Props = {
  options: PickerOption[];
  /** Already-selected slugs are hidden from the list (the parent shows them as chips). */
  selected: string[];
  onPick: (slug: string) => void;
  placeholder?: string;
  disabled?: boolean;
  label: string;
};

/** Small accessible combobox: type to search, arrows to move, Enter to pick, Esc to close. */
export function SkillPicker({ options, selected, onPick, placeholder = "Search skills…", disabled = false, label }: Props) {
  const id = useId();
  const listId = `${id}-list`;
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const chosen = new Set(selected);
    const pool = options.filter((o) => !chosen.has(o.slug));
    if (!q) return pool.slice(0, 8);
    const starts = pool.filter((o) => o.name.toLowerCase().startsWith(q) || o.slug.startsWith(q));
    const contains = pool.filter((o) => !starts.includes(o) && (o.name.toLowerCase().includes(q) || o.slug.includes(q)));
    return [...starts, ...contains].slice(0, 8);
  }, [options, query, selected]);

  function pick(slug: string) {
    onPick(slug);
    setQuery("");
    setCursor(0);
    inputRef.current?.focus();
  }

  const activeId = open && matches[cursor] ? `${id}-opt-${matches[cursor].slug}` : undefined;

  return (
    <div
      className="relative"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <label htmlFor={`${id}-input`} className="sr-only">
        {label}
      </label>
      <input
        id={`${id}-input`}
        ref={inputRef}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={activeId}
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
        placeholder={placeholder}
        value={query}
        className="field w-full disabled:opacity-60"
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setCursor(0);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setCursor((c) => Math.min(matches.length - 1, c + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setCursor((c) => Math.max(0, c - 1));
          } else if (e.key === "Enter") {
            if (open && matches[cursor]) {
              e.preventDefault();
              pick(matches[cursor].slug);
            }
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open && !disabled ? (
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-auto rounded-lg border border-line-strong bg-surface p-1 shadow-lg"
        >
          {matches.length === 0 ? (
            <li className="px-3 py-2 text-sm text-ink-3" role="presentation">
              No matching skills
            </li>
          ) : (
            matches.map((o, i) => (
              <li
                key={o.slug}
                id={`${id}-opt-${o.slug}`}
                role="option"
                aria-selected={i === cursor}
                className={`flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-sm ${i === cursor ? "bg-surface-2" : ""}`}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setCursor(i)}
                onClick={() => pick(o.slug)}
              >
                <span className="text-ink">{o.name}</span>
                <span className="tnum whitespace-nowrap text-xs text-ink-3">
                  {categoryLabel(o.category)} &middot; {fmtInt(o.count)}
                </span>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
