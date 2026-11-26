// Synthetic responses for mock mode, computed from the synthetic build's own data
// (web/mocks/*.json, written by `glint fixtures synthetic`).
//
// Screens are evaluated for real by the shared screen engine (lib/screen/engine.ts, held to the
// Python engine by a parity test) over the mock companies,
// so the sieve, results, near misses and why-it-passed always agree. Company pages serve the
// build's own header, flags and history. Nothing here samples rows or invents a number.

import type { components } from "@/lib/api/types";
import { metricMap } from "@/lib/screen/describe";
import type { MetricDefinition, Screen } from "@/lib/screen/types";
import { ScreenEngine } from "@/lib/screen/engine";
import { mockStore } from "./store";

export type Profile = { header: S["CompanyHeader"]; is_stale: boolean; flags: S["FlagOut"][] };
export type ScreenConfig = S["SnapshotScreenConfig"];

type S = components["schemas"];
export type MockRow = S["ResultRow"];

export type MockHistory = {
  /** Period ends per basis, oldest first; shared by every series. */
  periods: Record<"fy" | "ttm", string[]>;
  /** cik → metric → basis → values, oldest first. */
  series: Record<string, Record<string, Partial<Record<"fy" | "ttm", (number | null)[]>>>>;
};

export type MockData = {
  meta: S["MetaResponse"];
  metrics: MetricDefinition[];
  rows: MockRow[];
  profiles: Record<string, Profile>;
  history: MockHistory;
  config: ScreenConfig;
};

export const MOCK_WARNING = "Synthetic data: screens run in the browser over the mock's synthetic companies.";

const SYNTHETIC_MISSING = (metric: string): S["CellNote"] => ({
  code: "MISSING_INPUT",
  message: `Synthetic: ${metric} is not in the mock set.`,
});

// Mirrors the engine (WT-04): `values` holds exactly `screen.columns`, in order, defaulting to
// these; categorical fields come from the row; `rank_score` is filled in after ranking.
export const DEFAULT_COLUMNS = ["ticker", "name", "sector", "market_cap"];
const CATEGORICAL = new Set(["ticker", "name", "sector", "exchange", "kind"]);
export const RANK_SCORE = "rank_score";

export function responseColumns(screen: Screen): string[] {
  return screen.columns && screen.columns.length > 0 ? screen.columns : DEFAULT_COLUMNS;
}

function project(row: MockRow, columns: string[], profile: Profile | undefined): MockRow {
  const values: MockRow["values"] = {};
  const notes: MockRow["notes"] = {};
  for (const id of columns) {
    if (CATEGORICAL.has(id)) {
      values[id] = id === "exchange" ? (profile?.header.exchange ?? null) : id === "kind" ? (profile?.header.kind ?? null) : row[id as "ticker" | "name" | "sector"];
    } else if (id === RANK_SCORE) {
      values[id] = null;
    } else if (id in row.values) {
      values[id] = row.values[id] ?? null;
      const note = row.notes[id];
      if (note) notes[id] = note;
    } else {
      values[id] = null;
      notes[id] = SYNTHETIC_MISSING(id);
    }
  }
  return { ...row, values, notes, rank: null, rank_score: null, factor_contributions: {} };
}

let engineCache: { data: MockData; engine: ScreenEngine } | null = null;

/** One engine per mock data object: its caches make repeated screens cheap. */
export function mockEngine(data: MockData): ScreenEngine {
  if (engineCache?.data !== data) engineCache = { data, engine: new ScreenEngine(mockStore(data), metricMap(data.metrics)) };
  return engineCache.engine;
}

/**
 * POST /api/screen over the mock companies. `empty` (the ?mock=empty scenario) adds a last filter
 * nothing can pass, so the empty state still has an honest sieve behind it.
 */
export function mockScreen(data: MockData, screen: Screen, opts: { empty?: boolean } = {}): S["ScreenResponse"] {
  const run: Screen = opts.empty
    ? { ...screen, filters: { op: screen.filters?.op ?? "and", children: [...(screen.filters?.children ?? []), { metric: "ticker", cmp: "in", value: ["NO-SUCH-TICKER"], missing: "fail" }] } }
    : screen;
  const engine = mockEngine(data);
  const ev = engine.evaluate(run);
  if (opts.empty) ev.funnel.at(-1)!.label = "Empty-results scenario (?mock=empty)";
  const byCik = new Map(data.rows.map((r) => [r.cik, r]));
  const cols = responseColumns(run);
  const results = engine
    .order(run, ev)
    .slice(0, run.limit)
    .map((i) => {
      const row = byCik.get(engine.store.rows.cik[i] as string) as MockRow;
      const out = project(row, cols, data.profiles[row.cik]);
      const sc = ev.scores.get(i);
      if (!sc) return out;
      if (RANK_SCORE in out.values) out.values[RANK_SCORE] = sc.score;
      if (RANK_SCORE in out.values && sc.note) out.notes[RANK_SCORE] = sc.note;
      return { ...out, rank: ev.positions.get(i) ?? null, rank_score: sc.score, factor_contributions: sc.contributions };
    });
  // The engine's notes carry codes only; the mock rows have the messages.
  const nearMisses = run.near_misses
    ? ev.nearMisses.map((m) => (m.note && m.note.message === "" ? { ...m, note: byCik.get(m.cik)?.notes[m.metric] ?? m.note } : m))
    : [];
  return {
    build_id: data.meta.build_id,
    as_of: data.meta.as_of,
    universe_count: ev.universe.length,
    funnel: ev.funnel,
    total: ev.passing.length,
    results,
    near_misses: nearMisses,
    warnings: [MOCK_WARNING],
  };
}

/** why_passed for the drawer: the same evaluation as the screen (api/why.py). */
export function mockWhyPassed(data: MockData, screen: Screen, cik: string): S["FilterOutcome"][] {
  const engine = mockEngine(data);
  const i = engine.store.index.get(cik);
  if (i === undefined) return [{ filter_path: ["universe"], label: "Universe", passed: false, value: null, sector_percentile: null }];
  return engine.evaluate(screen).whyPassed(i);
}

/** Histogram of the synthetic sample: 24 bins between the 2nd and 98th percentile. */
export function mockDistribution(
  data: MockData,
  metric: string,
  within: S["Within"],
  sector: S["Sector"] | null,
): S["DistributionResponse"] {
  const rows = within === "sector" && sector ? data.rows.filter((row) => row.sector === sector) : data.rows;
  const vals = rows.map((row) => row.values[metric]).filter((v): v is number => typeof v === "number");
  vals.sort((a, b) => a - b);
  const q = (p: number) => vals[Math.min(vals.length - 1, Math.max(0, Math.floor(p * (vals.length - 1))))] ?? 0;
  const lo = q(0.02);
  const hi = q(0.98);
  const nBins = 24;
  const width = (hi - lo) / nBins || 1;
  const bins = Array.from({ length: nBins }, (_, i) => ({ lo: lo + i * width, hi: lo + (i + 1) * width, count: 0 }));
  for (const v of vals) {
    const i = Math.min(nBins - 1, Math.max(0, Math.floor((v - lo) / width)));
    (bins[i] as S["HistogramBin"]).count++;
  }
  return {
    build_id: data.meta.build_id,
    metric,
    within,
    sector,
    count: vals.length,
    null_count: rows.length - vals.length,
    bins,
    percentiles: { p5: q(0.05), p25: q(0.25), p50: q(0.5), p75: q(0.75), p95: q(0.95) },
  };
}

export function mockSectors(data: MockData): S["SectorsResponse"] {
  const counts = new Map<S["Sector"], number>();
  for (const row of data.rows) counts.set(row.sector, (counts.get(row.sector) ?? 0) + 1);
  return {
    build_id: data.meta.build_id,
    sectors: [...counts].map(([sector, count]) => ({ sector, count })).sort((a, b) => b.count - a.count),
  };
}

export function mockSearch(data: MockData, q: string): S["SearchResponse"] {
  const needle = q.trim().toUpperCase();
  const results: S["SearchHit"][] = [];
  for (const row of data.rows) {
    const t = row.ticker.toUpperCase();
    const n = row.name.toUpperCase();
    const match: S["MatchType"] | null =
      t === needle ? "exact" : t.startsWith(needle) ? "ticker_prefix" : n.startsWith(needle) ? "name_prefix" : n.includes(needle) ? "fuzzy" : null;
    if (!match) continue;
    const score = { exact: 1, ticker_prefix: 0.8, name_prefix: 0.6, fuzzy: 0.3 }[match];
    results.push({ cik: row.cik, ticker: row.ticker, name: row.name, exchange: null, sector: row.sector, kind: "synthetic", match, score });
  }
  results.sort((a, b) => b.score - a.score || a.ticker.localeCompare(b.ticker));
  return { build_id: data.meta.build_id, query: q, results: results.slice(0, 20) };
}

export function mockCompany(data: MockData, ticker: string, screen: Screen | null = null): S["CompanyResponse"] | null {
  const row = data.rows.find((x) => x.ticker.toUpperCase() === ticker.toUpperCase());
  const profile = row ? data.profiles[row.cik] : undefined;
  if (!row || !profile) return null;
  const metrics: S["CompanyResponse"]["metrics"] = {};
  for (const def of data.metrics) {
    metrics[def.id] = { value: row.values[def.id] ?? null, note: row.notes[def.id] ?? (def.id in row.values ? null : SYNTHETIC_MISSING(def.id)) };
  }
  const history = Object.fromEntries(
    Object.keys(data.history.series[row.cik] ?? {}).map((m) => [m, mockHistoryPoints(data, row.cik, m)]),
  );
  const h = profile.header;
  // The filings behind the header's dates. Accession numbers are deliberately fake and link nowhere.
  const sources: S["SourceFiling"][] = [];
  const seq = row.cik.slice(-5);
  if (h.last_quarterly_date) sources.push({ accn: `0009999999-${h.last_quarterly_date.slice(2, 4)}-1${seq}`, form: "10-Q", filed: h.last_quarterly_date, url: "#synthetic-filing" });
  if (h.last_annual_date) sources.push({ accn: `0009999999-${h.last_annual_date.slice(2, 4)}-0${seq}`, form: "10-K", filed: h.last_annual_date, url: "#synthetic-filing" });
  sources.sort((a, b) => (a.filed < b.filed ? 1 : -1));
  return {
    build_id: data.meta.build_id,
    company: h,
    as_of: data.meta.as_of,
    metrics,
    flags: profile.flags,
    history,
    sources,
    why_passed: screen ? mockWhyPassed(data, screen, row.cik) : null,
  };
}

/** One metric's FY points then TTM points, oldest first, as the build stores them. */
export function mockHistoryPoints(data: MockData, cik: string, metric: string): S["HistoryPoint"][] {
  const series = data.history.series[cik]?.[metric];
  if (!series) return [];
  return (["fy", "ttm"] as const).flatMap((basis) =>
    (series[basis] ?? []).map((value, k) => ({ basis, period_end: data.history.periods[basis][k] as string, value })),
  );
}

/** CSV for /api/screen/export: visible columns + as-of stamps + null-reason notes (SPEC §2.12). */
export function mockCsv(res: S["ScreenResponse"], screen: Screen): string {
  const cols = responseColumns(screen);
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const header = [...cols, "as_of_fundamentals", "as_of_prices", "notes"];
  const lines = res.results.map((row) => {
    const notes = Object.entries(row.notes)
      .map(([k, n]) => `${k}: ${n.code}`)
      .join("; ");
    return [
      ...cols.map((c) => (row.values[c] === null || row.values[c] === undefined ? "" : String(row.values[c]))),
      res.as_of.fundamentals ?? "",
      res.as_of.prices ?? "",
      notes,
    ]
      .map((x) => esc(String(x)))
      .join(",");
  });
  return [header.join(","), ...lines].join("\n") + "\n";
}
