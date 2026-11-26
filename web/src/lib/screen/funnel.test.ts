import { describe, expect, it } from "vitest";
import { emptyScreen } from "./defaults";
import { metricMap } from "./describe";
import { nodeAtPath, stepLabel } from "./funnel";
import type { MetricDefinition, Screen } from "./types";

const metrics = metricMap([
  { id: "market_cap", name: "Market cap", category: "size_liquidity", unit: "usd", better: "neutral", tier: "price", priority: "P0", basis: "mixed", definition: "", inputs: [], status: "live" },
  { id: "roic", name: "ROIC", category: "profitability", unit: "frac", better: "higher", tier: "sec", priority: "P0", basis: "ttm", definition: "", inputs: [], status: "live" },
] satisfies MetricDefinition[]);

const screen: Screen = {
  ...emptyScreen(),
  filters: {
    op: "and",
    children: [
      { metric: "market_cap", cmp: "gte", value: 1e9, missing: "fail" },
      { op: "or", children: [{ metric: "roic", cmp: "gte", value: 0.15, missing: "fail" }, { metric: "roic", cmp: "lt", value: 0, missing: "fail" }] },
    ],
  },
};

describe("funnel labels", () => {
  it("resolve filter paths, including inside groups", () => {
    expect(nodeAtPath(screen, ["filters", "children", 0])).toMatchObject({ metric: "market_cap" });
    expect(nodeAtPath(screen, ["filters", "children", 1, "children", 1])).toMatchObject({ cmp: "lt" });
    expect(nodeAtPath(screen, ["filters", "children", 5])).toBeNull();
    expect(nodeAtPath(screen, ["universe"])).toBeNull();
    expect(nodeAtPath(screen, null)).toBeNull();
  });

  it("build labels with format.ts (3 significant figures), not the API's string", () => {
    const api = { filter_path: ["filters", "children", 0], label: "Market cap ≥ $1.0B" };
    expect(stepLabel(api, screen, metrics)).toBe("Market cap ≥ $1.00B");
    expect(stepLabel({ filter_path: ["filters", "children", 1], label: "x" }, screen, metrics)).toBe("ROIC ≥ 15.0% OR ROIC < 0.0%");
  });

  it("fall back to the API label when the path doesn't resolve, and name the universe", () => {
    expect(stepLabel({ filter_path: ["filters", "children", 9], label: "From API" }, screen, metrics)).toBe("From API");
    expect(stepLabel({ filter_path: null, label: "anything" }, screen, metrics)).toBe("Universe");
  });
});
