// The screen engine's rules (engine/glint/screen/compile.py + engine.py) over a column store, for
// the live preview and for mock mode. One evaluator for both, held to the engine by a parity test
// (engine.parity.test.ts against web/mocks/parity.json, which the engine writes).
//
// - universe: exchange, kinds, sectors, foreign/stale/no-facts, numeric bounds a null never meets;
// - stats over the universe: percent_rank() per scope (null for nulls and small sectors), sector
//   medians (null for small sectors), peer counts;
// - a leaf compares a raw value, a percentile, or a gap/ratio to the sector median, with
//   `float_tolerance`; `missing` decides nulls; `opt` is "would pass if every null passed";
// - funnel steps are sequential; near misses fail exactly one top-level step;
// - distance = |x − t| / |t| (|x − t| when t = 0), or the percentile gap.
// Leaf results and stats are cached per universe, so dragging one threshold recomputes one leaf.

import type { components } from "@/lib/api/types";
import type { Store } from "@/lib/data/snapshot";
import { noteAt } from "@/lib/data/snapshot";
import { NOTE_DISPLAY } from "@/lib/notes";
import { effectiveUniverse } from "./defaults";
import { describeCondition, describeNode } from "./describe";
import { isGroup, type Condition, type Group, type MetricDefinition, type Screen } from "./types";

type S = components["schemas"];
type Cell = string | number | boolean | null;

/** engine/glint/screen/engine.py MAX_NEAR_MISSES. */
export const MAX_NEAR_MISSES = 25;

const CATEGORICAL = new Set(["ticker", "name", "sector", "exchange", "kind"]);
const PCT = new Set(["pct_rank_gte", "pct_rank_lte"]);
const VS = new Set(["vs_sector_median_gte", "vs_sector_median_lte"]);
const NUMERIC_CMP = new Set(["gt", "gte", "lt", "lte", "between", "pct_rank_gte", "pct_rank_lte", "vs_sector_median_gte", "vs_sector_median_lte"]);

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

type LeafResult = {
  cond: Condition;
  /** Compared value (raw / percentile / gap or ratio); NaN = null. Undefined for categorical leaves. */
  v: Float64Array | undefined;
  /** vs-median only: raw value the median implies; NaN = null. */
  t: Float64Array | undefined;
  ok: Uint8Array;
  opt: Uint8Array;
  /** Distance; NaN = none. */
  d: Float64Array;
};

type NodeResult = { node: Condition | Group; ok: Uint8Array; opt: Uint8Array; leaf: LeafResult | null; children: NodeResult[] | null; path: (string | number)[] };

export type Evaluation = {
  /** Snapshot rows in the universe, by row index. */
  universe: Int32Array;
  universeIfNullsPassed: number;
  total: number;
  funnel: S["FunnelStep"][];
  /** Passing row indices, in snapshot order. */
  passing: Int32Array;
  nearMisses: S["NearMiss"][];
  /** Rank scores for passing rows (when the screen ranks). */
  scores: Map<number, Score>;
  /** 1 = best among scored passing rows. */
  positions: Map<number, number>;
  whyPassed(row: number): S["FilterOutcome"][];
};

/** Codes that render as "n/m". */
const NM_CODES = new Set<string>(Object.entries(NOTE_DISPLAY).filter(([, d]) => d.shown === "n/m").map(([code]) => code));

export type Distribution = {
  metric: string;
  /** p1 and p99 of the values in the universe: the bins' range. */
  lo: number;
  hi: number;
  bins: { lo: number; hi: number; count: number }[];
  underflow: number;
  overflow: number;
  min: number | null;
  max: number | null;
  count: number;
  missing: number;
  notMeaningful: number;
  median: number | null;
};

/** A company a sieve stage removed (`ScreenEngine.removedAt`). */
export type Removed = {
  row: number;
  ticker: string;
  name: string;
  reason: "failed" | "no_data";
  /** The condition that explains the removal (the closest/furthest leaf of a group). */
  cond: Condition;
  /** Path of that condition when it is the stage itself (a top-level condition), else null. */
  leafPath: (string | number)[] | null;
  /** The company's raw value for the condition's metric. */
  value: Cell;
  /** The value the condition compared (percentile, gap or ratio to the median), when it differs. */
  compared: number | null;
  distance: number | null;
};

export type Score = { score: number | null; contributions: Record<string, number | null>; note: S["CellNote"] | null };

/**
 * A reusable evaluator over one store. Keep one per store: its caches (universe, stats, leaves)
 * make repeated evaluation of a screen that changes one threshold at a time cheap.
 */
export class ScreenEngine {
  private universeCache = new Map<string, { rows: Int32Array; mask: Uint8Array; optimistic: number }>();
  private statCache = new Map<string, Float64Array>();
  private leafCache = new Map<string, LeafResult>();
  private distCache = new Map<string, Distribution>();

  constructor(
    readonly store: Store,
    readonly defs: Map<string, MetricDefinition>,
  ) {}

  private get tol(): number {
    return this.store.config.float_tolerance;
  }

  // ---- field access ----------------------------------------------------------------------

  /** Categorical field value for a row. */
  private cat(field: string, i: number): string | null {
    const r = this.store.rows;
    switch (field) {
      case "ticker":
        return r.ticker[i] ?? null;
      case "name":
        return r.name[i] ?? null;
      case "sector":
        return r.sector[i] ?? null;
      case "exchange":
        return r.exchange[i] ?? null;
      case "kind":
        return r.kind[i] ?? null;
      default:
        return null;
    }
  }

  /** A row's value for a metric or field, as the API would report it. */
  cell(field: string, i: number): Cell {
    if (CATEGORICAL.has(field)) return this.cat(field, i);
    const c = this.store.col(field);
    const v = c?.[i];
    if (v === undefined || Number.isNaN(v)) return null;
    return this.defs.get(field)?.unit === "bool" ? v !== 0 : v;
  }

  // ---- universe -----------------------------------------------------------------------------

  private universe(u: Required<S["Universe"]>): { key: string; rows: Int32Array; mask: Uint8Array; optimistic: number } {
    const key = JSON.stringify(u);
    const hit = this.universeCache.get(key);
    if (hit) return { key, ...hit };
    const { n, rows } = this.store;
    const mask = new Uint8Array(n);
    let optimistic = 0;
    const bounds: [Float64Array | undefined, "gte" | "lte", number | null][] = [
      [this.store.col("market_cap"), "gte", u.market_cap_min],
      [this.store.col("market_cap"), "lte", u.market_cap_max],
      [this.store.col("avg_dollar_volume_3m"), "gte", u.avg_dollar_volume_min],
      [this.store.col("days_since_filing"), "lte", u.max_days_since_filing],
    ];
    const sectorsIn = new Set<string>(u.sectors_include);
    const sectorsOut = new Set<string>(u.sectors_exclude);
    const exchanges = new Set<string>(u.exchanges);
    const kinds = new Set<string>(u.exclude_kinds);
    const list: number[] = [];
    for (let i = 0; i < n; i++) {
      let strict = true;
      let opt = true;
      const ex = rows.exchange[i] ?? null;
      if (ex === null) strict = false;
      else if (!exchanges.has(ex)) strict = opt = false;
      if (sectorsIn.size > 0 && !sectorsIn.has(rows.sector[i] as string)) strict = opt = false;
      if (sectorsOut.has(rows.sector[i] as string)) strict = opt = false;
      if (kinds.has(rows.kind[i] as string)) strict = opt = false;
      if (!u.include_foreign_filers && rows.is_foreign_filer[i]) strict = opt = false;
      if (!u.include_stale && rows.is_stale[i]) strict = opt = false;
      if (!u.include_no_facts && !rows.has_facts[i]) strict = opt = false;
      for (const [col, op, bound] of bounds) {
        if (bound === null) continue;
        const v = col?.[i];
        if (v === undefined || Number.isNaN(v)) strict = false;
        else if (op === "gte" ? v < bound : v > bound) strict = opt = false;
      }
      if (strict) {
        mask[i] = 1;
        list.push(i);
      }
      if (opt) optimistic++;
    }
    const entry = { rows: Int32Array.from(list), mask, optimistic };
    this.universeCache.set(key, entry);
    return { key, ...entry };
  }

  // ---- stats over the universe ----------------------------------------------------------------

  private stat(key: string, build: () => Float64Array): Float64Array {
    let s = this.statCache.get(key);
    if (!s) this.statCache.set(key, (s = build()));
    return s;
  }

  /** count(x) OVER (PARTITION BY sector), per row (0 outside the universe). */
  private peerCount(uk: string, U: Int32Array, metric: string): Float64Array {
    return this.stat(`n|${uk}|${metric}`, () => {
      const col = this.store.col(metric);
      const sector = this.store.rows.sector;
      const counts = new Map<string, number>();
      for (const i of U) if (col && !Number.isNaN(col[i] as number)) counts.set(sector[i] as string, (counts.get(sector[i] as string) ?? 0) + 1);
      const out = new Float64Array(this.store.n);
      for (const i of U) out[i] = counts.get(sector[i] as string) ?? 0;
      return out;
    });
  }

  private small(uk: string, U: Int32Array, metric: string, i: number): boolean {
    return (this.peerCount(uk, U, metric)[i] ?? 0) < this.store.config.small_peer_group_min;
  }

  /** percent_rank() over non-null values in scope: (rank − 1) / (n − 1), ties share the lowest rank. */
  percentile(uk: string, U: Int32Array, metric: string, within: S["Within"], ascending = true): Float64Array {
    return this.stat(`p|${uk}|${metric}|${within}|${ascending}`, () => {
      const col = this.store.col(metric);
      const out = new Float64Array(this.store.n).fill(Number.NaN);
      if (!col) return out;
      const sector = this.store.rows.sector;
      const groups = new Map<string, number[]>();
      for (const i of U) {
        if (Number.isNaN(col[i] as number)) continue;
        if (within === "sector" && this.small(uk, U, metric, i)) continue;
        const g = within === "sector" ? (sector[i] as string) : "";
        const list = groups.get(g);
        if (list) list.push(i);
        else groups.set(g, [i]);
      }
      for (const list of groups.values()) {
        list.sort((a, b) => (ascending ? (col[a] as number) - (col[b] as number) : (col[b] as number) - (col[a] as number)));
        const m = list.length;
        let rank = 0;
        for (let k = 0; k < m; k++) {
          const i = list[k] as number;
          if (k === 0 || col[i] !== col[list[k - 1] as number]) rank = k;
          out[i] = m > 1 ? rank / (m - 1) : 0;
        }
      }
      return out;
    });
  }

  /** rank() with 1 = best over non-null values in scope (rank_sum). */
  private ordinal(uk: string, U: Int32Array, metric: string, within: S["Within"], higherFirst: boolean): Float64Array {
    return this.stat(`o|${uk}|${metric}|${within}|${higherFirst}`, () => {
      const p = this.percentile(uk, U, metric, within, !higherFirst);
      const sizes = new Map<string, number>();
      const sector = this.store.rows.sector;
      for (const i of U) if (!Number.isNaN(p[i] as number)) sizes.set(within === "sector" ? (sector[i] as string) : "", (sizes.get(within === "sector" ? (sector[i] as string) : "") ?? 0) + 1);
      const out = new Float64Array(this.store.n).fill(Number.NaN);
      for (const i of U) {
        const v = p[i] as number;
        if (Number.isNaN(v)) continue;
        const m = sizes.get(within === "sector" ? (sector[i] as string) : "") ?? 1;
        out[i] = Math.round(v * (m - 1)) + 1;
      }
      return out;
    });
  }

  /** Sector median over the universe (interpolated, like DuckDB's median); null for small sectors. */
  private median(uk: string, U: Int32Array, metric: string): Float64Array {
    return this.stat(`m|${uk}|${metric}`, () => {
      const col = this.store.col(metric);
      const sector = this.store.rows.sector;
      const groups = new Map<string, number[]>();
      for (const i of U) {
        const v = col?.[i];
        if (v === undefined || Number.isNaN(v)) continue;
        const g = groups.get(sector[i] as string);
        if (g) g.push(v);
        else groups.set(sector[i] as string, [v]);
      }
      const med = new Map<string, number>();
      for (const [s, vals] of groups) {
        vals.sort((a, b) => a - b);
        const mid = (vals.length - 1) / 2;
        med.set(s, ((vals[Math.floor(mid)] as number) + (vals[Math.ceil(mid)] as number)) / 2);
      }
      const out = new Float64Array(this.store.n).fill(Number.NaN);
      for (const i of U) if (!this.small(uk, U, metric, i)) out[i] = med.get(sector[i] as string) ?? Number.NaN;
      return out;
    });
  }

  // ---- leaves ---------------------------------------------------------------------------------

  private leaf(uk: string, U: Int32Array, cond: Condition): LeafResult {
    const key = `${uk}|${JSON.stringify(cond)}`;
    const hit = this.leafCache.get(key);
    if (hit) return hit;
    const n = this.store.n;
    const ok = new Uint8Array(n);
    const opt = new Uint8Array(n);
    const d = new Float64Array(n).fill(Number.NaN);
    const tol = this.tol;
    const c = cond.value;
    const nullTest = cond.cmp === "is_null" || cond.cmp === "not_null";
    const passIfNull = cond.missing === "pass" ? 1 : 0;

    if (CATEGORICAL.has(cond.metric) || this.defs.get(cond.metric)?.unit === "bool" || !NUMERIC_CMP.has(cond.cmp)) {
      // Categorical or boolean comparisons (eq / neq / in / null tests).
      for (const i of U) {
        const x = this.cell(cond.metric, i);
        let pass: boolean;
        switch (cond.cmp) {
          case "eq":
            pass = x === c;
            break;
          case "neq":
            pass = x !== null && x !== c;
            break;
          case "in":
            pass = Array.isArray(c) && (c as Cell[]).includes(x);
            break;
          case "is_null":
            pass = x === null;
            break;
          case "not_null":
            pass = x !== null;
            break;
          default:
            pass = false;
        }
        if (nullTest) {
          ok[i] = pass ? 1 : 0;
          opt[i] = cond.cmp === "not_null" ? 1 : ok[i] as number;
        } else if (x === null) {
          ok[i] = passIfNull;
          opt[i] = 1;
        } else {
          ok[i] = opt[i] = pass ? 1 : 0;
        }
      }
      const res: LeafResult = { cond, v: undefined, t: undefined, ok, opt, d };
      this.leafCache.set(key, res);
      return res;
    }

    const raw = this.store.col(cond.metric) ?? new Float64Array(n).fill(Number.NaN);
    let v: Float64Array = raw;
    let t: Float64Array | undefined;
    if (PCT.has(cond.cmp)) {
      v = this.percentile(uk, U, cond.metric, cond.within ?? "universe");
    } else if (VS.has(cond.cmp)) {
      const med = this.median(uk, U, cond.metric);
      const k = c as number;
      const unit = this.defs.get(cond.metric)?.unit;
      const diff = unit === "frac" || unit === "pp";
      v = new Float64Array(n).fill(Number.NaN);
      t = new Float64Array(n).fill(Number.NaN);
      for (const i of U) {
        const x = raw[i] as number;
        const m = med[i] as number;
        if (Number.isNaN(m)) continue;
        if (diff) {
          v[i] = x - m; // NaN when x is NaN
          t[i] = m + k;
        } else if (m > 0) {
          v[i] = x / m;
          t[i] = m * k;
        }
      }
    }

    const between = cond.cmp === "between" && Array.isArray(c) ? (c as [number, number]) : null;
    for (const i of U) {
      const x = v[i] as number;
      if (Number.isNaN(x)) {
        if (nullTest) {
          ok[i] = cond.cmp === "is_null" ? 1 : 0;
          opt[i] = cond.cmp === "not_null" ? 1 : ok[i] as number;
        } else {
          ok[i] = passIfNull;
          opt[i] = 1;
        }
      } else {
        let pass: boolean;
        switch (cond.cmp) {
          case "gt":
            pass = x > (c as number) + tol;
            break;
          case "gte":
          case "pct_rank_gte":
          case "vs_sector_median_gte":
            pass = x >= (c as number) - tol;
            break;
          case "lt":
            pass = x < (c as number) - tol;
            break;
          case "lte":
          case "pct_rank_lte":
          case "vs_sector_median_lte":
            pass = x <= (c as number) + tol;
            break;
          case "between":
            pass = between !== null && x >= between[0] - tol && x <= between[1] + tol;
            break;
          case "is_null":
            pass = false;
            break;
          case "not_null":
            pass = true;
            break;
          default:
            pass = false;
        }
        ok[i] = opt[i] = pass ? 1 : 0;
      }
      // engine leaf_distance_sql
      const rel = (a: number, at: number) => Math.abs(a - at) / (Math.abs(at) || 1);
      const r0 = raw[i] as number;
      if (PCT.has(cond.cmp)) {
        if (!Number.isNaN(x) && isNum(c)) d[i] = Math.abs(x - c);
      } else if (VS.has(cond.cmp)) {
        const ti = (t as Float64Array)[i] as number;
        if (!Number.isNaN(r0) && !Number.isNaN(ti)) d[i] = rel(r0, ti);
      } else if (between && !Number.isNaN(r0)) {
        d[i] = rel(r0, r0 < between[0] ? between[0] : between[1]);
      } else if ((cond.cmp === "gt" || cond.cmp === "gte" || cond.cmp === "lt" || cond.cmp === "lte") && !Number.isNaN(r0) && isNum(c)) {
        d[i] = rel(r0, c);
      }
    }
    const res: LeafResult = { cond, v, t, ok, opt, d };
    this.leafCache.set(key, res);
    return res;
  }

  private node(uk: string, U: Int32Array, node: Condition | Group, path: (string | number)[]): NodeResult {
    if (!isGroup(node)) {
      const leaf = this.leaf(uk, U, node);
      return { node, ok: leaf.ok, opt: leaf.opt, leaf, children: null, path };
    }
    const children = (node.children ?? []).map((ch, j) => this.node(uk, U, ch, [...path, "children", j]));
    const n = this.store.n;
    const ok = new Uint8Array(n);
    const opt = new Uint8Array(n);
    const and = node.op === "and";
    for (const i of U) {
      let a = and ? 1 : 0;
      let b = and ? 1 : 0;
      for (const ch of children) {
        if (and) {
          a &= ch.ok[i] as number;
          b &= ch.opt[i] as number;
        } else {
          a |= ch.ok[i] as number;
          b |= ch.opt[i] as number;
        }
      }
      ok[i] = a;
      opt[i] = b;
    }
    return { node, ok, opt, leaf: null, children, path };
  }

  /** engine _explain_failure for one row: OR → closest failing child; AND → the furthest. */
  private explain(n: NodeResult, i: number): LeafResult {
    if (n.leaf) return n.leaf;
    const failing = (n.children ?? []).filter((c) => !c.ok[i]).map((c) => this.explain(c, i));
    const dist = (lf: LeafResult) => lf.d[i] as number;
    if (isGroup(n.node) && n.node.op === "or") {
      const known = failing.filter((lf) => !Number.isNaN(dist(lf)));
      return known.length > 0 ? known.reduce((a, b) => (dist(b) < dist(a) ? b : a)) : (failing[0] as LeafResult);
    }
    const unknown = failing.find((lf) => Number.isNaN(dist(lf)));
    return unknown ?? failing.reduce((a, b) => (dist(b) > dist(a) ? b : a));
  }

  /** A company's percentile within its sector (0..1) over the screen's universe; null if none. */
  sectorPercentile(universe: S["Universe"] | undefined, metric: string, row: number): number | null {
    const { key: uk, rows: U } = this.universe(effectiveUniverse(universe));
    const p = this.percentile(uk, U, metric, "sector")[row] as number;
    return Number.isNaN(p) ? null : p;
  }

  /** The median of a metric in a company's sector over the screen's universe; null for small sectors. */
  sectorMedianOf(universe: S["Universe"] | undefined, metric: string, row: number): number | null {
    const { key: uk, rows: U } = this.universe(effectiveUniverse(universe));
    const m = this.median(uk, U, metric)[row] as number;
    return Number.isNaN(m) ? null : m;
  }

  // ---- distributions -----------------------------------------------------------------------

  /**
   * A metric's distribution over the screen's universe: `bins` equal-width bins between p1 and p99,
   * values below p1 / above p99 counted as underflow / overflow (so one −17,919% outlier can't
   * squash the chart), and nulls split into missing and not meaningful by their reason code.
   */
  distribution(universe: S["Universe"] | undefined, metric: string, bins = 30): Distribution {
    const u = effectiveUniverse(universe);
    const { key: uk, rows: U } = this.universe(u);
    const cacheKey = `dist|${uk}|${metric}|${bins}`;
    const hit = this.distCache.get(cacheKey);
    if (hit) return hit;
    const col = this.store.col(metric);
    const vals: number[] = [];
    let missing = 0;
    let notMeaningful = 0;
    for (const i of U) {
      const v = col?.[i];
      if (v !== undefined && !Number.isNaN(v)) vals.push(v);
      else if (NM_CODES.has(noteAt(this.store, metric, i) ?? "")) notMeaningful++;
      else missing++;
    }
    vals.sort((a, b) => a - b);
    const q = (p: number) => (vals.length ? (vals[Math.min(vals.length - 1, Math.max(0, Math.round(p * (vals.length - 1))))] as number) : 0);
    const lo = q(0.01);
    const hi = q(0.99);
    const width = hi > lo ? (hi - lo) / bins : 0;
    const counts = new Array<number>(width > 0 ? bins : 1).fill(0);
    let underflow = 0;
    let overflow = 0;
    for (const v of vals) {
      if (width === 0) counts[0] = (counts[0] as number) + 1;
      else if (v < lo) underflow++;
      else if (v > hi) overflow++;
      else {
        const k = Math.min(bins - 1, Math.floor((v - lo) / width));
        counts[k] = (counts[k] as number) + 1;
      }
    }
    const out: Distribution = {
      metric,
      lo,
      hi,
      bins: counts.map((count, k) => ({ lo: width > 0 ? lo + k * width : lo, hi: width > 0 ? lo + (k + 1) * width : hi, count })),
      underflow,
      overflow,
      min: vals[0] ?? null,
      max: vals.at(-1) ?? null,
      count: vals.length,
      missing,
      notMeaningful,
      median: vals.length ? ((vals[Math.floor((vals.length - 1) / 2)] as number) + (vals[Math.ceil((vals.length - 1) / 2)] as number)) / 2 : null,
    };
    this.distCache.set(cacheKey, out);
    return out;
  }

  // ---- the screen ---------------------------------------------------------------------------

  /**
   * `opts.nearMisses: false` skips near misses and `opts.rank: false` skips scoring: the drag path
   * and every count-only caller need just the funnel (with `rank: false`, `scores` and `positions`
   * are empty).
   */
  evaluate(screen: Screen, opts: { nearMisses?: boolean; rank?: boolean } = {}): Evaluation {
    const u = effectiveUniverse(screen.universe);
    const { key: uk, rows: U, optimistic } = this.universe(u);
    const top = screen.filters?.children ?? [];
    const steps = top.map((node, k) => this.node(uk, U, node, ["filters", "children", k]));

    // Funnel: sequential steps.
    const funnel: S["FunnelStep"][] = [
      { index: 0, label: "Universe", filter_path: null, remaining: U.length, removed: this.store.n - U.length, removed_missing: optimistic - U.length, binding: false },
    ];
    let alive = U;
    steps.forEach((st, k) => {
      const kept: number[] = [];
      let missing = 0;
      for (const i of alive) {
        if (st.ok[i]) kept.push(i);
        else if (st.opt[i]) missing++;
      }
      funnel.push({
        index: k + 1,
        label: describeNode(st.node, this.defs),
        filter_path: ["filters", "children", k],
        remaining: kept.length,
        removed: alive.length - kept.length,
        removed_missing: missing,
        binding: false,
      });
      alive = Int32Array.from(kept);
    });
    const filterSteps = funnel.slice(1);
    const most = Math.max(0, ...filterSteps.map((s) => s.removed));
    const first = filterSteps.find((s) => s.removed === most);
    if (first && most > 0) first.binding = true;

    const nearMisses = opts.nearMisses === false ? [] : this.nearMisses(uk, U, steps);
    const { scores, positions } = opts.rank === false ? { scores: new Map<number, Score>(), positions: new Map<number, number>() } : this.rank(uk, U, screen, alive);

    return {
      universe: U,
      universeIfNullsPassed: optimistic,
      total: this.store.n,
      funnel,
      passing: alive,
      nearMisses,
      scores,
      positions,
      whyPassed: (row) => this.whyPassed(uk, U, steps, row),
    };
  }

  private nearMisses(uk: string, U: Int32Array, steps: NodeResult[]): S["NearMiss"][] {
    const out: S["NearMiss"][] = [];
    for (const i of U) {
      let failedAt = -1;
      let failed = 0;
      for (let k = 0; k < steps.length && failed < 2; k++) {
        if (!(steps[k] as NodeResult).ok[i]) {
          failed++;
          failedAt = k;
        }
      }
      if (failed !== 1) continue;
      const step = steps[failedAt] as NodeResult;
      const leaf = this.explain(step, i);
      const { cond } = leaf;
      const raw = this.cell(cond.metric, i);
      const compared = leaf.v ? (leaf.v[i] as number) : Number.NaN;
      const value: Cell = PCT.has(cond.cmp) ? (Number.isNaN(compared) ? null : compared) : raw;
      const threshold = VS.has(cond.cmp)
        ? Number.isNaN((leaf.t as Float64Array)[i] as number)
          ? null
          : ((leaf.t as Float64Array)[i] as number)
        : ((cond.value ?? null) as S["NearMiss"]["threshold"]);
      const comparedNull = leaf.v ? Number.isNaN(compared) : raw === null;
      const dist = leaf.d[i] as number;
      out.push({
        cik: this.store.rows.cik[i] as string,
        ticker: this.store.rows.ticker[i] as string,
        name: this.store.rows.name[i] as string,
        sector: this.store.rows.sector[i] as S["Sector"],
        failed_filter_path: ["filters", "children", failedAt],
        failed_label: describeNode(step.node, this.defs),
        metric: cond.metric,
        cmp: cond.cmp,
        value,
        threshold,
        distance: Number.isNaN(dist) ? null : dist,
        note: comparedNull ? this.nearMissNote(uk, U, cond.metric, i) : null,
      });
    }
    out.sort((a, b) => Number(a.distance === null) - Number(b.distance === null) || (a.distance ?? 0) - (b.distance ?? 0) || (a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0));
    return out.slice(0, MAX_NEAR_MISSES);
  }

  /** engine _near_miss_note: the metric's own reason, a small sector, or a median ≤ 0. */
  private nearMissNote(uk: string, U: Int32Array, metric: string, i: number): S["CellNote"] {
    const sector = this.store.rows.sector[i] as string;
    if (this.cell(metric, i) === null) {
      const code = noteAt(this.store, metric, i);
      return code ? { code, message: "" } : { code: "MISSING_INPUT", message: `${metric} is missing; no reason recorded.` };
    }
    if (this.small(uk, U, metric, i)) {
      return { code: "SMALL_PEER_GROUP", message: `Fewer than ${this.store.config.small_peer_group_min} ${metric} values in ${sector}: no sector percentile or median.` };
    }
    return { code: "NEGATIVE_DENOMINATOR", message: `${sector} median ${metric} is ≤ 0: a ratio to it isn't meaningful.` };
  }

  private rank(uk: string, U: Int32Array, screen: Screen, passing: Int32Array): { scores: Map<number, Score>; positions: Map<number, number> } {
    const scores = new Map<number, Score>();
    const positions = new Map<number, number>();
    const rank = screen.rank;
    if (!rank || rank.factors.length === 0) return { scores, positions };
    const method = rank.method ?? "percentile_composite";
    const within = rank.within ?? "universe";
    const required = method === "rank_sum" ? 1 : (rank.min_factor_coverage ?? 0.7);
    const totalW = rank.factors.reduce((s, f) => s + f.weight, 0);
    const meanW = totalW / rank.factors.length;
    const cols = rank.factors.map((f) => {
      const higher = this.defs.get(f.metric)?.better === "higher";
      return method === "percentile_composite" ? this.percentile(uk, U, f.metric, within, higher) : this.ordinal(uk, U, f.metric, within, higher);
    });
    for (const i of passing) {
      const raw = cols.map((c) => c[i] as number);
      const presentW = rank.factors.reduce((s, f, k) => s + (Number.isNaN(raw[k] as number) ? 0 : f.weight), 0);
      const contributions: Record<string, number | null> = Object.fromEntries(rank.factors.map((f) => [f.metric, null]));
      if (presentW / totalW < required - this.tol) {
        const missing = rank.factors.filter((_, k) => Number.isNaN(raw[k] as number)).map((f) => f.metric);
        const small = missing.some((m) => this.small(uk, U, m, i));
        scores.set(i, {
          score: null,
          contributions,
          note: {
            code: small ? "SMALL_PEER_GROUP" : "MISSING_INPUT",
            message: `Factor coverage ${Math.round((presentW / totalW) * 100)}% < ${Math.round(required * 100)}%: ${missing.join(", ")} ${small ? "fewer than the minimum peers in its sector" : "missing"}.`,
          },
        });
        continue;
      }
      let score = 0;
      rank.factors.forEach((f, k) => {
        const r = raw[k] as number;
        if (Number.isNaN(r)) return;
        const c = method === "percentile_composite" ? (f.weight / presentW) * r : (f.weight / meanW) * r;
        contributions[f.metric] = c;
        score += c;
      });
      scores.set(i, { score, contributions, note: null });
    }
    const sign = method === "rank_sum" ? 1 : -1;
    const tick = this.store.rows.ticker;
    [...passing]
      .filter((i) => scores.get(i)?.score !== null)
      .sort((a, b) => sign * ((scores.get(a)?.score as number) - (scores.get(b)?.score as number)) || ((tick[a] as string) < (tick[b] as string) ? -1 : 1))
      .forEach((i, k) => positions.set(i, k + 1));
    return { scores, positions };
  }

  /** api/why.py: the universe outcome, then one outcome per filter leaf (depth-first). */
  private whyPassed(uk: string, U: Int32Array, steps: NodeResult[], row: number): S["FilterOutcome"][] {
    const inUniverse = this.universeCache.get(uk)?.mask[row] === 1;
    const out: S["FilterOutcome"][] = [{ filter_path: ["universe"], label: "Universe", passed: inUniverse, value: null, sector_percentile: null }];
    if (!inUniverse) return out;
    const walk = (n: NodeResult) => {
      if (n.children) return n.children.forEach(walk);
      const cond = n.leaf?.cond as Condition;
      const unit = this.defs.get(cond.metric)?.unit;
      const numeric = !CATEGORICAL.has(cond.metric) && unit !== undefined && unit !== "bool";
      const p = numeric ? (this.percentile(uk, U, cond.metric, "sector")[row] as number) : Number.NaN;
      out.push({
        filter_path: n.path,
        label: describeCondition(cond, this.defs),
        passed: Boolean(n.ok[row]),
        value: this.cell(cond.metric, row),
        sector_percentile: Number.isNaN(p) ? null : p,
      });
    };
    steps.forEach(walk);
    return out;
  }

  /**
   * The companies a sieve stage removed (alive before it, failed it), closest to passing first,
   * then those it removed for missing data. Each carries the value the stage compared (the
   * explaining leaf's, for a group) and the distance, so the UI can offer to include it.
   */
  removedAt(screen: Screen, stepIndex: number, limit = 50): Removed[] {
    const top = screen.filters?.children ?? [];
    const k = stepIndex - 1;
    if (k < 0 || k >= top.length) return [];
    const u = effectiveUniverse(screen.universe);
    const { key: uk, rows: U } = this.universe(u);
    const steps = top.slice(0, k + 1).map((node, j) => this.node(uk, U, node, ["filters", "children", j]));
    const out: Removed[] = [];
    const step = steps[k] as NodeResult;
    for (const i of U) {
      let alive = true;
      for (let j = 0; j < k && alive; j++) if (!(steps[j] as NodeResult).ok[i]) alive = false;
      if (!alive || step.ok[i]) continue;
      const leaf = this.explain(step, i);
      const compared = leaf.v ? (leaf.v[i] as number) : Number.NaN;
      const raw = this.cell(leaf.cond.metric, i);
      const d = leaf.d[i] as number;
      out.push({
        row: i,
        ticker: this.store.rows.ticker[i] as string,
        name: this.store.rows.name[i] as string,
        reason: step.opt[i] ? "no_data" : "failed",
        cond: leaf.cond,
        leafPath: leaf === step.leaf ? step.path : null,
        value: raw,
        compared: Number.isNaN(compared) ? null : compared,
        distance: Number.isNaN(d) ? null : d,
      });
    }
    const tick = this.store.rows.ticker;
    out.sort(
      (a, b) =>
        Number(a.reason === "no_data") - Number(b.reason === "no_data") ||
        Number(a.distance === null) - Number(b.distance === null) ||
        (a.distance ?? 0) - (b.distance ?? 0) ||
        ((tick[a.row] as string) < (tick[b.row] as string) ? -1 : 1),
    );
    return out.slice(0, limit);
  }

  /**
   * Passing rows in the engine's result order: by `sort`, else by rank (best first) when ranked,
   * else by ticker. Nulls last; ties by ticker.
   */
  order(screen: Screen, ev: Evaluation): number[] {
    const tick = this.store.rows.ticker;
    const byTicker = (a: number, b: number) => ((tick[a] as string) < (tick[b] as string) ? -1 : (tick[a] as string) > (tick[b] as string) ? 1 : 0);
    const base = [...ev.passing].sort(byTicker);
    const sort = screen.sort ?? null;
    if (sort === null || sort.by === "rank_score") {
      if (ev.positions.size === 0) return base;
      const ranked = base.filter((i) => ev.positions.has(i)).sort((a, b) => (ev.positions.get(a) as number) - (ev.positions.get(b) as number));
      if (sort?.dir === "asc") ranked.reverse();
      return [...ranked, ...base.filter((i) => !ev.positions.has(i))];
    }
    const key = (i: number) => this.cell(sort.by, i);
    const present = base.filter((i) => key(i) !== null);
    const dir = sort.dir ?? "desc";
    present.sort((a, b) => {
      const x = key(a) as number | string | boolean;
      const y = key(b) as number | string | boolean;
      // Code-point order for text, like the engine's Python sort.
      const c = typeof x === "string" || typeof y === "string" ? (String(x) < String(y) ? -1 : String(x) > String(y) ? 1 : 0) : Number(x) - Number(y);
      return dir === "asc" ? c : -c;
    });
    return [...present, ...base.filter((i) => key(i) === null)];
  }
}
