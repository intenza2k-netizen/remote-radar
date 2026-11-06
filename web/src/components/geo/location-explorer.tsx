"use client";

import { useMemo } from "react";
import { LocationRanking } from "./location-ranking";
import { LocationResult } from "./location-result";
import { LocationSelect } from "./location-select";
import { useStoredLocation } from "./use-stored-location";
import { findLocation, locationOptions, type GeoLocation } from "@/lib/geo";

/**
 * The interactive part of /locations: pick where you live (remembered in this browser), see what is
 * open to you, and compare all locations underneath. Nothing is selected until the visitor chooses.
 */
export function LocationExplorer({ rows, listed }: { rows: GeoLocation[]; listed: number }) {
  const [stored, setStored] = useStoredLocation();
  const options = useMemo(() => locationOptions(rows), [rows]);
  const row = findLocation(rows, stored); // a stale stored value (not in this snapshot) is ignored

  // Choosing from the ranking further down brings the picker (and the details under it) into view.
  function chooseFromRanking(location: string) {
    setStored(location);
    document.getElementById("geo-pick")?.scrollIntoView({ block: "start" });
  }

  return (
    <div>
      <div className="card p-4 sm:p-5">
        <label htmlFor="geo-pick" className="mb-1 block text-sm font-medium">
          Where would you work from?
        </label>
        <div className="max-w-md">
          <LocationSelect id="geo-pick" value={row?.location ?? ""} onChange={setStored} options={options} emptyLabel="Choose a country or region..." />
        </div>
        <p className="mt-2 text-xs text-ink-3">Remembered in this browser only; nothing is sent anywhere. Choosing a region such as Europe counts only postings open to the whole region.</p>
      </div>

      <div className="mt-8">
        {row ? (
          <LocationResult row={row} listed={listed} />
        ) : (
          <div className="rounded-lg border border-dashed border-line-strong p-8 text-center">
            <p className="font-medium">Pick a country or region above</p>
            <p className="mx-auto mt-1 max-w-xl text-sm text-ink-3">
              You will see how many remote postings are open to you, how many are data roles, what they pay and which skills they ask for. The ranking below does not need a choice.
            </p>
          </div>
        )}
      </div>

      <section aria-labelledby="geo-rank-h" className="mt-14 border-t border-line pt-10">
        <h2 id="geo-rank-h" className="text-xl font-semibold tracking-tight sm:text-2xl">
          Where data roles are open to the most people
        </h2>
        <p className="mb-5 mt-2 max-w-3xl text-sm text-ink-2">
          Open data postings per location, counting postings that say worldwide for every place. Click a name in the table to see its details above.
        </p>
        <LocationRanking rows={rows} listed={listed} selected={row?.location ?? ""} onSelect={chooseFromRanking} />
      </section>
    </div>
  );
}
