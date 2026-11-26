import { describe, expect, it } from "vitest";
import { formulaParts, splitDefinition } from "./metricText";

describe("splitDefinition", () => {
  it("takes the first sentence as the formula", () => {
    expect(splitDefinition("fcf_ttm / market_cap. Keeps negatives.")).toEqual({ formula: "fcf_ttm / market_cap", rules: "Keeps negatives." });
  });
  it("keeps decimals and bracketed parts inside the formula", () => {
    expect(splitDefinition("cfo / net_income, clamped at 0.5x.")).toEqual({ formula: "cfo / net_income, clamped at 0.5x", rules: "" });
    expect(splitDefinition("a / b. (Null if b ≤ 0.)").rules).toBe("(Null if b ≤ 0.)");
  });
  it("rewrites reason codes into words before splitting", () => {
    const { formula, rules } = splitDefinition("net_debt / ebitda_ttm. Null (NEGATIVE_DENOMINATOR) if EBITDA ≤ 0.");
    expect(formula).toBe("net_debt / ebitda_ttm");
    expect(rules).not.toMatch(/NEGATIVE_DENOMINATOR/);
  });
});

describe("formulaParts", () => {
  it("sets symbolic expressions as code and moves a worded aside out", () => {
    expect(formulaParts("fcf_ttm / market_cap")).toEqual({ expr: "fcf_ttm / market_cap", note: "", code: true });
    expect(formulaParts("capex_ttm / revenue_ttm (capex is a positive outflow in XBRL)")).toEqual({
      expr: "capex_ttm / revenue_ttm",
      note: "capex is a positive outflow in XBRL",
      code: true,
    });
    expect(formulaParts("pb_x / equity (MRQ)")).toEqual({ expr: "pb_x / equity (MRQ)", note: "", code: true });
    expect(formulaParts("dso + dio − dpo").code).toBe(true);
  });
  it("sets sentences in the word face", () => {
    expect(formulaParts("Last close of the primary ticker (the most liquid common class)").code).toBe(false);
    expect(formulaParts("Number of flags raised (§2.10)").code).toBe(false);
    expect(formulaParts("The 9 binary tests of Piotroski (2000), latest FY vs prior FY, scaled as in the paper by total assets at the start").code).toBe(false);
  });
});
