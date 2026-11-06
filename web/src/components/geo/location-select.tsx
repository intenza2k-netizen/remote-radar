import { fmtInt } from "@/lib/format";
import type { LocationOptions } from "@/lib/geo";

/**
 * A native select of regions and countries, each with how many postings are open to it. Native on
 * purpose: ~230 options stay usable on a phone and type-to-find works. `keep` is a value that must
 * stay selectable even when it is not in the list (an old bookmarked link).
 */
export function LocationSelect({
  id,
  value,
  onChange,
  options,
  emptyLabel,
  keep,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  options: LocationOptions;
  emptyLabel: string;
  keep?: string;
}) {
  const known = options.regions.some((o) => o.value === keep) || options.countries.some((o) => o.value === keep);
  return (
    <select id={id} className="field w-full text-ellipsis" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{emptyLabel}</option>
      {keep && !known ? <option value={keep}>{keep}</option> : null}
      <optgroup label="Regions">
        {options.regions.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label} ({fmtInt(o.count)})
          </option>
        ))}
      </optgroup>
      <optgroup label="Countries">
        {options.countries.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label} ({fmtInt(o.count)})
          </option>
        ))}
      </optgroup>
    </select>
  );
}
