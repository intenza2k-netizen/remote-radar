"use client";

import { useCallback, useSyncExternalStore } from "react";

const KEY = "rr-location";
const listeners = new Set<() => void>();
// Fallback for browsers that block storage: the choice then lasts for this page view only.
let memory = "";

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

/**
 * The location a visitor picked, remembered in localStorage (every access wrapped in try/catch).
 * Server render and first client render both see "" (no selection), so there is no hydration mismatch;
 * the stored value appears right after hydration.
 */
export function useStoredLocation(): [string, (value: string) => void] {
  const value = useSyncExternalStore(subscribe, read, () => "");
  const set = useCallback((next: string) => {
    memory = next;
    try {
      if (next) localStorage.setItem(KEY, next);
      else localStorage.removeItem(KEY);
    } catch {
      /* storage blocked: keep the in-memory choice */
    }
    listeners.forEach((l) => l());
  }, []);
  return [value, set];
}
