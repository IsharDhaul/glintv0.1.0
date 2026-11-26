// "Include it": the condition with its threshold moved just far enough to let one company through.
// Used by the sieve's removed list and the near-miss list. Display-side editing of the user's own
// threshold; nothing here computes a metric.

import type { Unit } from "@/lib/format";
import { roundForInput } from "@/lib/units";
import type { Condition } from "./types";

/** The input step roundForInput rounds to, at value v. */
function stepOf(unit: Unit, v: number): number {
  switch (unit) {
    case "frac":
    case "pp":
      return 0.001;
    case "x":
      return 0.1;
    case "days":
      return 1;
    case "usd":
      return v === 0 ? 1 : 10 ** (Math.floor(Math.log10(Math.abs(v))) - 2);
    default:
      return 0.01;
  }
}

/** A typeable threshold that `x` passes: rounded down for ≥ / >, up for ≤ / <. */
function passingThreshold(x: number, cmp: "gte" | "gt" | "lte" | "lt", unit: Unit): number {
  const step = stepOf(unit, x);
  let t = roundForInput(unit, x);
  if (cmp === "gte" && t > x) t = roundForInput(unit, t - step);
  if (cmp === "gt" && t >= x) t = roundForInput(unit, t - step);
  if (cmp === "lte" && t < x) t = roundForInput(unit, t + step);
  if (cmp === "lt" && t <= x) t = roundForInput(unit, t + step);
  return t;
}

/**
 * The relaxed condition, or null when relaxing can't include the company: a missing value (only
 * "missing values pass" can), a vs-median or categorical test, or a threshold that wouldn't move.
 * `value` is the raw value; `compared` is the percentile for percentile tests.
 */
export function relaxCondition(cond: Condition, value: unknown, compared: number | null, unit: Unit): Condition | null {
  const pct = cond.cmp === "pct_rank_gte" || cond.cmp === "pct_rank_lte";
  const x = pct ? compared : value;
  if (typeof x !== "number" || !Number.isFinite(x)) return null;
  if (cond.cmp === "between" && Array.isArray(cond.value)) {
    const [lo, hi] = cond.value as [number, number];
    if (x < lo) return { ...cond, value: [passingThreshold(x, "gte", unit), hi] };
    if (x > hi) return { ...cond, value: [lo, passingThreshold(x, "lte", unit)] };
    return null;
  }
  const base = pct ? (cond.cmp === "pct_rank_gte" ? "gte" : "lte") : cond.cmp;
  if ((base !== "gte" && base !== "gt" && base !== "lte" && base !== "lt") || typeof cond.value !== "number") return null;
  const t = passingThreshold(x, base, pct ? "frac" : unit);
  return t === cond.value ? null : { ...cond, value: t };
}
