import { describe, expect, it } from "vitest";
import { metricMap } from "./describe";
import { countByFilter, describeDistance, describeThreshold, nearMissNote, nearMissUnit } from "./nearMiss";
import type { MetricDefinition, NearMiss } from "./types";

const d = (id: string, unit: MetricDefinition["unit"]): MetricDefinition => ({
  id,
  name: id,
  category: "profitability",
  unit,
  better: "higher",
  tier: "sec",
  priority: "P0",
  basis: "ttm",
  definition: "",
  inputs: [],
  status: "live",
});
const metrics = metricMap([d("roic", "frac"), d("pe_ttm", "x"), d("market_cap", "usd")]);

const nm = (p: Partial<NearMiss>): NearMiss => ({
  cik: "1",
  ticker: "SYN1",
  name: "Synthetic 1",
  sector: "Technology",
  failed_filter_path: ["filters", "children", 0],
  failed_label: "x",
  metric: "roic",
  cmp: "gte",
  value: 0.146,
  threshold: 0.15,
  distance: 0.0267,
  ...p,
});

describe("near-miss display", () => {
  it("plain thresholds use the metric's unit", () => {
    expect(describeThreshold(nm({}), metrics)).toBe("≥ 15.0%");
    expect(describeThreshold(nm({ metric: "pe_ttm", cmp: "between", threshold: [8, 20], value: 21 }), metrics)).toBe("between 8.0x and 20.0x");
  });

  it("percentile filters are fractions of the ranking, gaps in points", () => {
    const p = nm({ cmp: "pct_rank_gte", value: 0.67, threshold: 0.7, distance: 0.03 });
    expect(nearMissUnit(p, metrics)).toBe("frac");
    expect(describeThreshold(p, metrics)).toBe("percentile ≥ 70.0%");
    expect(describeDistance(p, metrics)).toBe("3.0 pts short");
  });

  it("vs-median shows the raw threshold the median implies", () => {
    expect(describeThreshold(nm({ metric: "market_cap", cmp: "vs_sector_median_gte", threshold: 1.2e9 }), metrics)).toBe(
      "≥ $1.20B (implied by the sector median)",
    );
  });

  it("distance is in the metric's own unit, with the direction in words", () => {
    expect(describeDistance(nm({}), metrics)).toBe("0.4 pp short"); // 14.6% vs ≥ 15%
    expect(describeDistance(nm({ metric: "pe_ttm", cmp: "lte", value: 22.4, threshold: 20 }), metrics)).toBe("2.4x over");
    expect(describeDistance(nm({ metric: "pe_ttm", cmp: "between", threshold: [8, 20], value: 21 }), metrics)).toBe("1.0x above the range");
    expect(describeDistance(nm({ metric: "market_cap", cmp: "gte", value: 8.8e8, threshold: 1e9 }), metrics)).toBe("$120M short");
    expect(describeDistance(nm({ metric: "market_cap", cmp: "vs_sector_median_gte", value: 1e9, threshold: 1.2e9 }), metrics)).toBe("$200M short");
    expect(describeDistance(nm({ cmp: "gt", value: 0.15, threshold: 0.15 }), metrics)).toBe("at the threshold");
  });

  it("no distance without both sides, or for a value that doesn't fail (never an abs() flip)", () => {
    expect(describeDistance(nm({ value: null }), metrics)).toBeNull();
    expect(describeDistance(nm({ threshold: null }), metrics)).toBeNull();
    // −1.9x passes "≤ 2.0x": it must never read as a miss.
    expect(describeDistance(nm({ metric: "pe_ttm", cmp: "lte", value: -1.9, threshold: 2 }), metrics)).toBeNull();
  });

  it("reads NearMiss.note (CONTRACT #18)", () => {
    expect(nearMissNote(nm({}))).toBeNull();
    expect(nearMissNote(nm({ value: null, note: { code: "SMALL_PEER_GROUP", message: "x" } }))?.code).toBe("SMALL_PEER_GROUP");
  });

  it("counts by failed filter in first-seen order", () => {
    const a = ["filters", "children", 0];
    const b = ["filters", "children", 2];
    expect(countByFilter([nm({ failed_filter_path: b }), nm({ failed_filter_path: a }), nm({ failed_filter_path: b })])).toEqual([
      { key: "filters.children.2", path: b, count: 2 },
      { key: "filters.children.0", path: a, count: 1 },
    ]);
  });
});
