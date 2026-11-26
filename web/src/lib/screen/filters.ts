// Filter-builder logic, pure and UI-free. Comparator rules mirror the contract
// (engine/glint/contracts/screen.py ALLOWED_CMPS and Condition._value_shape).

import type { Unit } from "@/lib/format";
import { isGroup, type Comparator, type Condition, type Group, type MetricDefinition, type Screen } from "./types";

/** Categorical fields a filter may test (contract CATEGORICAL_FIELDS); the UI offers sector. */
export const FILTER_FIELDS: Record<string, { name: string; unit: Unit }> = {
  sector: { name: "Sector", unit: "text" },
};

const NUMERIC_UNITS: ReadonlySet<Unit> = new Set(["usd", "frac", "pp", "x", "days", "score"]);

/** Comparators the API accepts for a unit, in the order the UI lists them. */
export function allowedComparators(unit: Unit): Comparator[] {
  if (NUMERIC_UNITS.has(unit)) {
    return ["gte", "gt", "lte", "lt", "between", "pct_rank_gte", "pct_rank_lte", "vs_sector_median_gte", "vs_sector_median_lte", "not_null", "is_null"];
  }
  if (unit === "bool") return ["eq", "neq", "not_null", "is_null"];
  return ["in", "eq", "neq", "not_null", "is_null"];
}

/** The comparator picker's options in words (the row's button keeps the symbol). */
export const CMP_WORDS: Record<Comparator, string> = {
  gte: "At least (≥)",
  gt: "More than (>)",
  lte: "At most (≤)",
  lt: "Less than (<)",
  between: "Between",
  eq: "Is",
  neq: "Is not",
  in: "Is one of",
  is_null: "Is missing",
  not_null: "Has a value",
  pct_rank_gte: "Percentile at least",
  pct_rank_lte: "Percentile at most",
  vs_sector_median_gte: "Relative to sector median, at least",
  vs_sector_median_lte: "Relative to sector median, at most",
};

export const CMP_LABEL: Record<Comparator, string> = {
  gte: "≥",
  gt: ">",
  lte: "≤",
  lt: "<",
  between: "between",
  eq: "is",
  neq: "is not",
  in: "is one of",
  is_null: "is missing",
  not_null: "has a value",
  pct_rank_gte: "percentile ≥",
  pct_rank_lte: "percentile ≤",
  vs_sector_median_gte: "≥ sector median",
  vs_sector_median_lte: "≤ sector median",
};

/** The shape of value a comparator takes; drives which input the card shows. */
export type ValueKind = "none" | "number" | "range" | "percentile" | "vs_median" | "bool" | "category";

export function valueKind(cmp: Comparator, unit: Unit): ValueKind {
  switch (cmp) {
    case "is_null":
    case "not_null":
      return "none";
    case "between":
      return "range";
    case "pct_rank_gte":
    case "pct_rank_lte":
      return "percentile";
    case "vs_sector_median_gte":
    case "vs_sector_median_lte":
      return "vs_median";
    case "eq":
    case "neq":
      return unit === "bool" ? "bool" : "category";
    case "in":
      return "category";
    default:
      return "number";
  }
}

/** Unit the value of a vs-median filter is typed in: a pp difference for frac/pp, else a ratio. */
export function vsMedianUnit(unit: Unit): Unit {
  return unit === "frac" || unit === "pp" ? "pp" : "x";
}

export function unitOf(metric: string, metrics: Map<string, MetricDefinition>): Unit {
  return metrics.get(metric)?.unit ?? FILTER_FIELDS[metric]?.unit ?? "text";
}

/** A sensible first comparator: toward the metric's "better" end. */
export function defaultComparator(def: Pick<MetricDefinition, "unit" | "better"> | undefined): Comparator {
  const unit = def?.unit ?? "text";
  if (unit === "bool") return "eq";
  if (!NUMERIC_UNITS.has(unit)) return "in";
  return def?.better === "lower" ? "lte" : "gte";
}

/** New condition for a picked metric. Its value is empty until the user types one. */
export function newCondition(metric: string, metrics: Map<string, MetricDefinition>): Condition {
  const def = metrics.get(metric);
  const cmp = defaultComparator(def ?? (FILTER_FIELDS[metric] ? { unit: "text", better: "neutral" } : undefined));
  return { metric, cmp, value: cmp === "eq" && def?.unit === "bool" ? true : null, missing: "fail" };
}

/** Switch comparator, keeping the value when its shape still fits and setting `within` as the contract wants. */
export function withComparator(c: Condition, cmp: Comparator, unit: Unit): Condition {
  const sameKind = valueKind(c.cmp, unit) === valueKind(cmp, unit);
  const next: Condition = { metric: c.metric, cmp, missing: c.missing, value: sameKind ? c.value : null };
  if (cmp === "eq" && unit === "bool" && next.value === null) next.value = true;
  if (cmp === "pct_rank_gte" || cmp === "pct_rank_lte") next.within = c.within ?? "universe";
  return next;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Would the API accept this condition's value? (Contract Condition._value_shape.) */
export function isComplete(c: Condition, unit: Unit): boolean {
  const v = c.value;
  switch (valueKind(c.cmp, unit)) {
    case "none":
      return v === null || v === undefined;
    case "range":
      return Array.isArray(v) && v.length === 2 && isNum(v[0]) && isNum(v[1]) && v[0] <= v[1];
    case "percentile":
      return isNum(v) && v >= 0 && v <= 1;
    case "bool":
      return typeof v === "boolean";
    case "category":
      return c.cmp === "in" ? Array.isArray(v) && v.length > 0 && v.every((x) => typeof x === "string") : typeof v === "string" && v.length > 0;
    default:
      return isNum(v);
  }
}

/**
 * The screen the API should run: incomplete conditions and empty groups dropped.
 * `stepOf[i]` maps the user's top-level filter i to its funnel step index (null if dropped).
 */
export function runnable(screen: Screen, metrics: Map<string, MetricDefinition>): { screen: Screen; stepOf: (number | null)[] } {
  const top = screen.filters?.children ?? [];
  const keep = (n: Condition | Group): Condition | Group | null => {
    if (!isGroup(n)) return isComplete(n, unitOf(n.metric, metrics)) ? n : null;
    const children = (n.children ?? []).map(keep).filter((x): x is Condition | Group => x !== null);
    return children.length > 0 ? { ...n, children } : null;
  };
  const stepOf: (number | null)[] = [];
  const children: (Condition | Group)[] = [];
  for (const n of top) {
    const k = keep(n);
    stepOf.push(k ? children.length + 1 : null);
    if (k) children.push(k);
  }
  // Keep the top-level operator: a shared or hand-written screen may be a top-level OR.
  return { screen: { ...screen, filters: { op: screen.filters?.op ?? "and", children } }, stepOf };
}

// ---- Tree edits. The UI supports top-level AND children plus one level of OR groups. ----

/** Where a node lives: a top-level index, and optionally a child index inside an OR group. */
export type NodePath = { top: number; child?: number };

function topChildren(s: Screen): (Condition | Group)[] {
  return s.filters?.children ?? [];
}

function withTop(s: Screen, children: (Condition | Group)[]): Screen {
  return { ...s, filters: { op: s.filters?.op ?? "and", children } };
}

export function addFilter(s: Screen, c: Condition, intoGroup?: number): Screen {
  const top = topChildren(s);
  if (intoGroup === undefined) return withTop(s, [...top, c]);
  return withTop(
    s,
    top.map((n, i) => (i === intoGroup && isGroup(n) ? { ...n, children: [...(n.children ?? []), c] } : n)),
  );
}

export function addOrGroup(s: Screen, first: Condition): Screen {
  return withTop(s, [...topChildren(s), { op: "or", children: [first] }]);
}

export function updateAt(s: Screen, path: NodePath, c: Condition): Screen {
  return withTop(
    s,
    topChildren(s).map((n, i) => {
      if (i !== path.top) return n;
      if (path.child === undefined) return c;
      return isGroup(n) ? { ...n, children: (n.children ?? []).map((ch, j) => (j === path.child ? c : ch)) } : n;
    }),
  );
}

/** Remove a node. An OR group left with no children disappears; with one child it stays a group. */
export function removeAt(s: Screen, path: NodePath): Screen {
  const top = topChildren(s);
  if (path.child === undefined) return withTop(s, top.filter((_, i) => i !== path.top));
  return withTop(
    s,
    top.flatMap((n, i) => {
      if (i !== path.top || !isGroup(n)) return [n];
      const children = (n.children ?? []).filter((_, j) => j !== path.child);
      return children.length > 0 ? [{ ...n, children }] : [];
    }),
  );
}

export function getAt(s: Screen, path: NodePath): Condition | Group | undefined {
  const n = topChildren(s)[path.top];
  if (path.child === undefined || !n || !isGroup(n)) return n;
  return n.children?.[path.child];
}
