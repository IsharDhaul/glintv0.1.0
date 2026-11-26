import { formatBool, formatCount, formatMetric, formatValue, type Unit } from "./format";
import type { components } from "./api/types";
import type { MetricDefinition } from "./screen/types";

type HistoryPoint = components["schemas"]["HistoryPoint"];

/** Units for flag-evidence keys that aren't registry metric ids (market_cap_implausible). */
const EVIDENCE_UNITS: Record<string, Unit> = {
  avg_dollar_volume_recent: "usd",
  market_cap_to_adv: "frac",
};

/**
 * One flag-evidence value as text. Keys that are registry metric ids format with the metric's
 * unit; other numbers as counts (integers) or 2 dp; strings and booleans as themselves.
 */
export function formatEvidence(key: string, value: unknown, metrics: Map<string, MetricDefinition>): string {
  const unit = EVIDENCE_UNITS[key];
  if (unit && typeof value === "number") return formatValue(unit, value);
  const def = metrics.get(key);
  if (def && (typeof value === "number" || typeof value === "boolean" || typeof value === "string")) return formatMetric(def, value);
  if (typeof value === "number") return Number.isInteger(value) ? formatCount(value) : formatValue("score", value);
  if (typeof value === "boolean") return formatBool(value);
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "—";
  return JSON.stringify(value);
}

/** Readable evidence key: the metric's name, else the key with underscores as spaces. */
export function evidenceLabel(key: string, metrics: Map<string, MetricDefinition>): string {
  return metrics.get(key)?.name ?? key.replace(/_/g, " ");
}

/** Only real EDGAR archive URLs become links (mock and malformed ones stay plain text). */
export function sourceHref(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && u.hostname === "www.sec.gov" && u.pathname.startsWith("/Archives/edgar/data/") ? u.href : null;
  } catch {
    return null;
  }
}

/** A sparkline series: points of one basis, oldest first. */
export function series(points: HistoryPoint[] | undefined, basis: HistoryPoint["basis"]): HistoryPoint[] {
  return (points ?? []).filter((p) => p.basis === basis).sort((a, b) => a.period_end.localeCompare(b.period_end));
}
