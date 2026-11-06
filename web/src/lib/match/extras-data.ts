import "server-only";
import { getArchetypes } from "@/lib/archetypes";
import { getGeo } from "@/lib/geo-data";
import { getSalaryModel } from "@/lib/salary-model-data";
import { buildExtras, type MatchExtras } from "./extras";

/** Build-time loader for the matcher's v4 inputs; each missing or malformed file just leaves its feature out. */
export function getMatchExtras(): MatchExtras {
  return buildExtras(getArchetypes(), getSalaryModel(), getGeo());
}
