import { formatMetric, formatValue } from "@/lib/format";
import { isGroup, type Comparator, type Condition, type Group, type MetricDefinition } from "./types";

const SYMBOL: Partial<Record<Comparator, string>> = {
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  eq: "=",
  neq: "≠",
};

type Value = Condition["value"];

function show(metric: MetricDefinition | undefined, v: Value): string {
  if (v === null || v === undefined) return "?";
  if (Array.isArray(v)) return v.map((x) => show(metric, x)).join(", ");
  return metric ? formatMetric(metric, v) : formatValue("text", v);
}

/** Human label for one condition, e.g. "ROIC ≥ 15.0%". Used by filter cards and the mock sieve. */
export function describeCondition(c: Condition, metrics: Map<string, MetricDefinition>): string {
  const m = metrics.get(c.metric);
  const name = m?.name ?? c.metric;
  const scope = c.within === "sector" ? "sector" : "universe";
  switch (c.cmp) {
    case "between": {
      const [lo, hi] = Array.isArray(c.value) ? c.value : [];
      return `${name} between ${show(m, lo ?? null)} and ${show(m, hi ?? null)}`;
    }
    case "in":
      return `${name} in ${show(m, c.value)}`;
    case "is_null":
      return `${name} is missing`;
    case "not_null":
      return `${name} has a value`;
    case "pct_rank_gte":
      return `${name} pct rank ≥ ${formatValue("frac", Number(c.value))} (${scope})`;
    case "pct_rank_lte":
      return `${name} pct rank ≤ ${formatValue("frac", Number(c.value))} (${scope})`;
    case "vs_sector_median_gte":
    case "vs_sector_median_lte": {
      const sym = c.cmp.endsWith("gte") ? "≥" : "≤";
      // frac/pp metrics compare as a difference, others as a ratio (SPEC §2.5).
      const diff = m?.unit === "frac" || m?.unit === "pp";
      return diff
        ? `${name} ${sym} sector median ${formatValue("pp", Number(c.value))}`
        : `${name} ${sym} ${formatValue("x", Number(c.value))} sector median`;
    }
    default:
      return `${name} ${SYMBOL[c.cmp] ?? c.cmp} ${show(m, c.value)}`;
  }
}

/** Label for a top-level step: a condition, or an OR/AND group summarised by its children. */
export function describeNode(node: Condition | Group, metrics: Map<string, MetricDefinition>): string {
  if (!isGroup(node)) return describeCondition(node, metrics);
  const parts = (node.children ?? []).map((ch) => describeNode(ch, metrics));
  if (parts.length === 0) return "Empty group";
  return parts.join(node.op === "or" ? " OR " : " AND ");
}

export function metricMap(defs: MetricDefinition[]): Map<string, MetricDefinition> {
  return new Map(defs.map((d) => [d.id, d]));
}
