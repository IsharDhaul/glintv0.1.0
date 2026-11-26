import { describe, expect, it } from "vitest";
import { fuzzyFilter, fuzzyScore } from "./fuzzy";

describe("fuzzyScore", () => {
  it("ranks exact, prefix, word start, substring, then subsequence", () => {
    const s = (q: string, t: string) => fuzzyScore(q, t) ?? -1;
    expect(s("roic", "ROIC")).toBeGreaterThan(s("roic", "ROIC (sector)"));
    expect(s("gross", "Gross margin")).toBeGreaterThan(s("margin", "Gross margin"));
    expect(s("margin", "Gross margin")).toBeGreaterThan(s("argin", "Gross margin"));
    expect(s("argin", "Gross margin")).toBeGreaterThan(s("gm", "Gross margin"));
    expect(fuzzyScore("gm", "Gross margin")).not.toBeNull();
    expect(fuzzyScore("zz", "Gross margin")).toBeNull();
  });

  it("filters and orders a list", () => {
    const items = ["Free cash flow margin", "FCF yield", "Gross margin"];
    expect(fuzzyFilter("fcf", items, (x) => x)).toEqual(["FCF yield", "Free cash flow margin"]);
  });
});
