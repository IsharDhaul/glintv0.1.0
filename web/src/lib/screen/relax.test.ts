import { describe, expect, it } from "vitest";
import { relaxCondition } from "./relax";
import type { Condition } from "./types";

const c = (p: Partial<Condition>): Condition => ({ metric: "roic", cmp: "gte", value: 0.15, missing: "fail", ...p });

describe("relaxCondition", () => {
  it("moves a ≥ threshold down to a typeable value the company passes", () => {
    expect(relaxCondition(c({}), 0.1466, null, "frac")?.value).toBe(0.146);
    expect(relaxCondition(c({ cmp: "gt" }), 0.146, null, "frac")?.value).toBe(0.145);
  });
  it("moves a ≤ threshold up", () => {
    expect(relaxCondition(c({ metric: "pe_ttm", cmp: "lte", value: 20 }), 22.41, null, "x")?.value).toBe(22.5);
    expect(relaxCondition(c({ metric: "pe_ttm", cmp: "lt", value: 20 }), 22.5, null, "x")?.value).toBe(22.6);
  });
  it("widens the nearer bound of a range", () => {
    expect(relaxCondition(c({ cmp: "between", value: [0.05, 0.4] }), 0.0412, null, "frac")?.value).toEqual([0.041, 0.4]);
  });
  it("uses the percentile for percentile filters", () => {
    expect(relaxCondition(c({ cmp: "pct_rank_gte", value: 0.7 }), 0.12, 0.6531, "frac")?.value).toBe(0.653);
  });
  it("can't include a missing value or a median test", () => {
    expect(relaxCondition(c({}), null, null, "frac")).toBeNull();
    expect(relaxCondition(c({ cmp: "vs_sector_median_gte", value: 0.02 }), 0.1, null, "frac")).toBeNull();
  });
});
