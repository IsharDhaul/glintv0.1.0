import type { components } from "@/lib/api/types";
import type { Screen } from "./types";

type Universe = components["schemas"]["Universe"];
type Exchange = components["schemas"]["Exchange"];

// Mirrors engine/glint/contracts/screen.py defaults. The OpenAPI schema carries the scalar
// defaults but not pydantic default_factory lists, so they're restated here; defaults.test.ts
// checks the scalar ones against contracts/openapi.json.
export const DEFAULT_EXCHANGES: Exchange[] = ["NYSE", "Nasdaq", "NYSE American", "TXSE"];

export const DEFAULT_UNIVERSE: Required<Universe> = {
  exchanges: DEFAULT_EXCHANGES,
  sectors_include: [],
  sectors_exclude: [],
  exclude_kinds: ["spac", "fund", "shell", "no_common_equity"],
  include_foreign_filers: true,
  include_stale: false,
  include_no_facts: false,
  market_cap_min: null,
  market_cap_max: null,
  avg_dollar_volume_min: 1_000_000,
  max_days_since_filing: null,
};

export const DEFAULT_COLUMNS = ["ticker", "name", "sector", "market_cap"];

/** The universe a screen actually runs on: its own fields over the contract defaults. */
export function effectiveUniverse(u: Universe | undefined): Required<Universe> {
  const out = { ...DEFAULT_UNIVERSE };
  for (const [k, v] of Object.entries(u ?? {})) {
    if (v !== undefined) (out as Record<string, unknown>)[k] = v;
  }
  return out;
}

export function emptyScreen(): Screen {
  return {
    dsl_version: 1,
    name: "Untitled screen",
    filters: { op: "and", children: [] },
    rank: null,
    columns: DEFAULT_COLUMNS,
    sort: null,
    limit: 100,
    near_misses: true,
  };
}
