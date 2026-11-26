import { formatGap, formatMetric, formatPercentilePoints, type Unit } from "@/lib/format";
import { CMP_LABEL } from "./filters";
import type { CellNote } from "@/lib/notes";
import type { MetricDefinition, NearMiss } from "./types";

// Display rules for near misses, following the engine (WT-04 decisions):
// - metric/cmp/value/threshold describe the *explaining leaf* (an OR group's closest child);
// - percentile filters report the company's percentile against the percentile threshold;
// - vs-median filters report the raw value against the raw value the median implies;
// - the API's distance (|x − t| / |t|, or the percentile gap) only orders the list; what's shown
//   is the gap in the metric's own unit (describeDistance).

const PCT = new Set(["pct_rank_gte", "pct_rank_lte"]);
const VS = new Set(["vs_sector_median_gte", "vs_sector_median_lte"]);

/** Unit `value` and `threshold` are in: percentiles are fractions; everything else the metric's. */
export function nearMissUnit(m: NearMiss, metrics: Map<string, MetricDefinition>): Unit {
  if (PCT.has(m.cmp)) return "frac";
  return metrics.get(m.metric)?.unit ?? "text";
}

/** The comparison as shown: "≥ 15.0%", "between 8.0x and 20.0x", "percentile ≥ 70.0%", "≥ $1.20B (sector median)". */
export function describeThreshold(m: NearMiss, metrics: Map<string, MetricDefinition>): string {
  const unit = nearMissUnit(m, metrics);
  const def = { id: PCT.has(m.cmp) ? "" : m.metric, unit };
  const one = (v: unknown) => (v === null || v === undefined ? "—" : formatMetric(def, v as number | string | boolean));
  const t = m.threshold;
  if (m.cmp === "between" && Array.isArray(t)) return `between ${one(t[0])} and ${one(t[1])}`;
  if (m.cmp === "in" && Array.isArray(t)) return `one of ${t.map(one).join(", ")}`;
  if (VS.has(m.cmp)) return `${m.cmp.endsWith("gte") ? "≥" : "≤"} ${one(t)} (implied by the sector median)`;
  if (m.cmp === "is_null" || m.cmp === "not_null") return CMP_LABEL[m.cmp];
  return `${CMP_LABEL[m.cmp]} ${Array.isArray(t) ? t.map(one).join(", ") : one(t)}`;
}

/**
 * How far the value is from passing, in the metric's own unit: "7.5 pp short" (≥ filters),
 * "0.4x over" (≤ filters), "$120M below the range", "3.0 pts short" (percentile filters).
 * Computed from value and threshold, never from the API's relative `distance` (which only orders
 * the list). Null when either side is missing or the filter isn't a numeric comparison.
 */
export function describeDistance(m: NearMiss, metrics: Map<string, MetricDefinition>): string | null {
  const x = m.value;
  const t = m.threshold;
  if (typeof x !== "number" || !Number.isFinite(x)) return null;
  const pct = PCT.has(m.cmp);
  const gap = (g: number) => (pct ? formatPercentilePoints(g) : formatGap(nearMissUnit(m, metrics), g));
  if (m.cmp === "between") {
    if (!Array.isArray(t) || typeof t[0] !== "number" || typeof t[1] !== "number") return null;
    if (x < t[0]) return `${gap(t[0] - x)} below the range`;
    if (x > t[1]) return `${gap(x - t[1])} above the range`;
    return null;
  }
  if (typeof t !== "number" || !Number.isFinite(t)) return null;
  const atLeast = m.cmp === "gte" || m.cmp === "gt" || m.cmp === "pct_rank_gte" || m.cmp === "vs_sector_median_gte";
  const atMost = m.cmp === "lte" || m.cmp === "lt" || m.cmp === "pct_rank_lte" || m.cmp === "vs_sector_median_lte";
  if (!atLeast && !atMost) return null;
  const g = atLeast ? t - x : x - t;
  // A strict comparison fails at the threshold itself.
  if (g <= 0) return g === 0 ? "at the threshold" : null;
  return `${gap(g)} ${atLeast ? "short" : "over"}`;
}

/** The reason for a null near-miss value (`NearMiss.note`, CONTRACT #18). */
export function nearMissNote(m: NearMiss): CellNote | null {
  return m.note ?? null;
}

/** Counts per failed filter, in first-seen order, for the panel's filter chips. */
export function countByFilter(items: NearMiss[]): { key: string; path: (string | number)[]; count: number }[] {
  const out = new Map<string, { key: string; path: (string | number)[]; count: number }>();
  for (const m of items) {
    const key = m.failed_filter_path.join(".");
    const cur = out.get(key);
    if (cur) cur.count++;
    else out.set(key, { key, path: m.failed_filter_path, count: 1 });
  }
  return [...out.values()];
}

/** The unsigned gap to passing, in the metric's own units (percentile points for percentile
 * filters), for sorting a group; null when either side is missing or it isn't a numeric test. */
export function gapOf(m: NearMiss): number | null {
  const x = m.value;
  const t = m.threshold;
  if (typeof x !== "number" || !Number.isFinite(x)) return null;
  if (Array.isArray(t) && typeof t[0] === "number" && typeof t[1] === "number") return x < t[0] ? t[0] - x : x > t[1] ? x - t[1] : null;
  return typeof t === "number" && Number.isFinite(t) ? Math.abs(x - t) : null;
}
