import { describe, expect, it } from "vitest";
import { evidenceLabel, formatEvidence, series, sourceHref } from "./company";
import { formatValue } from "./format";
import { metricMap } from "./screen/describe";
import type { MetricDefinition } from "./screen/types";

const metrics = metricMap([
  { id: "share_count_change_yoy", name: "Share count change (YoY)", category: "quality", unit: "frac", better: "lower", tier: "sec", priority: "P0", basis: "ttm", definition: "", inputs: [], status: "live" },
] satisfies MetricDefinition[]);

describe("flag evidence", () => {
  it("formats registry metrics with their unit and other values plainly", () => {
    expect(formatEvidence("share_count_change_yoy", 0.124, metrics)).toBe("12.4%");
    expect(formatEvidence("days", 482, metrics)).toBe("482");
    expect(formatEvidence("ratio", 1.234, metrics)).toBe("1.23");
    expect(formatEvidence("late", true, metrics)).toBe("Yes");
    expect(formatEvidence("form", "NT 10-K", metrics)).toBe("NT 10-K");
    expect(formatEvidence("x", null, metrics)).toBe("—");
  });

  it("formats market_cap_implausible's non-metric evidence with its unit", () => {
    expect(formatEvidence("avg_dollar_volume_recent", 4_000_000, metrics)).toBe(formatValue("usd", 4_000_000));
    expect(formatEvidence("market_cap_to_adv", 0.25, metrics)).toBe("25.0%");
    expect(formatEvidence("adv_sessions", 20, metrics)).toBe("20");
  });

  it("labels keys by metric name when known", () => {
    expect(evidenceLabel("share_count_change_yoy", metrics)).toBe("Share count change (YoY)");
    expect(evidenceLabel("prior_fy_end", metrics)).toBe("prior fy end");
  });
});

describe("sources", () => {
  it("links only to EDGAR archives", () => {
    expect(sourceHref("https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/")).toMatch(/^https:\/\/www\.sec\.gov/);
    expect(sourceHref("#synthetic-filing")).toBeNull();
    expect(sourceHref("http://www.sec.gov/Archives/edgar/data/1/2/")).toBeNull();
    expect(sourceHref("https://evil.example/Archives/edgar/data/1/")).toBeNull();
  });
});

describe("history series", () => {
  it("splits by basis, oldest first", () => {
    const pts = [
      { basis: "fy" as const, period_end: "2024-12-31", value: 2 },
      { basis: "ttm" as const, period_end: "2025-06-30", value: 9 },
      { basis: "fy" as const, period_end: "2023-12-31", value: 1 },
    ];
    expect(series(pts, "fy").map((p) => p.value)).toEqual([1, 2]);
    expect(series(pts, "ttm")).toHaveLength(1);
    expect(series(undefined, "fy")).toEqual([]);
  });
});
