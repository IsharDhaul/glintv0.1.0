import type { components } from "@/lib/api/types";

type Preset = components["schemas"]["Preset"];

let cache: Promise<Preset[]> | null = null;

/** Browser side of mock presets: fetched once from /mock-data/presets (real config files). */
export function mockPresets(): Promise<Preset[]> {
  cache ??= fetch("/mock-data/presets").then((r) => {
    if (!r.ok) throw new Error(`/mock-data/presets returned ${r.status}`);
    return r.json() as Promise<Preset[]>;
  });
  return cache;
}
