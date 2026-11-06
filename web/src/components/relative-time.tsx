"use client";

import { useSyncExternalStore } from "react";
import { fmtDateShort, relativeTime } from "@/lib/format";

function subscribe(notify: () => void) {
  const id = setInterval(notify, 60_000);
  return () => clearInterval(id);
}
// Minute resolution keeps the snapshot stable between ticks.
const getNow = () => Math.floor(Date.now() / 60_000) * 60_000;
const getServerNow = () => null;

/** Server/prerender and first paint show the absolute date; the browser upgrades it to "3 hours ago". */
export function RelativeTime({ iso }: { iso: string }) {
  const now = useSyncExternalStore(subscribe, getNow, getServerNow);
  return (
    <time dateTime={iso} title={new Date(iso).toUTCString()}>
      {now == null ? fmtDateShort(iso) : relativeTime(iso, now)}
    </time>
  );
}
