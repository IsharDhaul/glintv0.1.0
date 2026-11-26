import { describe, expect, it } from "vitest";
import type { Unit } from "./format";
import { inputAffix, inputText, parseInput, toDisplay, toStorage, roundForInput } from "./units";

describe("toStorage / toDisplay", () => {
  it("percent units convert ×100 exactly once", () => {
    expect(toStorage("frac", 15)).toBe(0.15);
    expect(toStorage("pp", 2)).toBe(0.02);
    expect(toDisplay("frac", 0.15)).toBe(15);
    expect(toDisplay("pp", -0.011)).toBe(-1.1);
  });

  it("strips float noise", () => {
    expect(toDisplay("frac", 0.07)).toBe(7);
    expect(toDisplay("frac", 0.145)).toBe(14.5);
    expect(toStorage("frac", 14.6)).toBe(0.146);
    expect(toStorage("frac", 0.1 + 0.2)).toBe(0.003);
  });

  it.each(["usd", "x", "days", "score", "bool", "text"] as Unit[])("%s passes through", (u) => {
    expect(toStorage(u, 14.2)).toBe(14.2);
    expect(toDisplay(u, 14.2)).toBe(14.2);
  });

  it("round-trips across a range of values", () => {
    for (const unit of ["frac", "pp", "x", "usd", "days"] as Unit[]) {
      for (const v of [-1.5, -0.05, 0, 0.001, 0.15, 0.333, 1, 2.5, 40, 1234.5]) {
        expect(toStorage(unit, toDisplay(unit, v))).toBeCloseTo(v, 12);
      }
    }
  });
});

describe("parseInput (display units in, storage out)", () => {
  it.each([
    ["frac", "15", 0.15],
    ["frac", "15%", 0.15],
    ["frac", " 15.5 % ", 0.155],
    ["frac", "-4.2", -0.042],
    ["frac", "−4.2", -0.042],
    ["frac", "+8", 0.08],
    ["frac", ".5", 0.005],
    ["frac", "1,250", 12.5],
    ["pp", "+2.3 pp", 0.023],
    ["pp", "2", 0.02],
    ["pp", "-5pp", -0.05],
    ["x", "14.2x", 14.2],
    ["x", "8", 8],
    ["days", "47 d", 47],
    ["score", "8", 8],
    ["usd", "300M", 300e6],
    ["usd", "$1.5b", 1.5e9],
    ["usd", "2T", 2e12],
    ["usd", "45k", 45_000],
    ["usd", "$1,000,000", 1e6],
    ["usd", "-$2B", -2e9],
    ["usd", "9.38", 9.38],
  ] as [Unit, string, number][])("%s %j → %d", (unit, text, v) => {
    expect(parseInput(unit, text)).toBeCloseTo(v, 12);
  });

  it.each([
    ["frac", ""],
    ["frac", "abc"],
    ["frac", "15%%"],
    ["frac", "1.2.3"],
    ["frac", "--5"],
    ["x", "x"],
    ["usd", "M"],
    ["usd", "300Q"],
    ["frac", "1e400"],
  ] as [Unit, string][])("%s %j → null", (unit, text) => {
    expect(parseInput(unit, text)).toBeNull();
  });

  it("magnitude suffixes are usd-only", () => {
    expect(parseInput("x", "3b")).toBeNull();
    expect(parseInput("frac", "5m")).toBeNull();
  });
});

describe("inputText (storage → prefill) reads back through parseInput", () => {
  it.each([
    ["frac", 0.15, "15"],
    ["frac", 0.07, "7"],
    ["pp", 0.02, "2"],
    ["x", 14.2, "14.2"],
    ["usd", 1.5e9, "1.5B"],
    ["usd", 300e6, "300M"],
    ["usd", 1_000_000_000_000, "1T"],
    ["usd", 1234.5678, "1234.5678"],
    ["usd", 9.38, "9.38"],
  ] as [Unit, number, string][])("%s %d → %j", (unit, v, text) => {
    expect(inputText(unit, v)).toBe(text);
    expect(parseInput(unit, text)).toBeCloseTo(v, 9);
  });

  it("empty for missing values", () => {
    expect(inputText("frac", null)).toBe("");
    expect(inputText("frac", undefined)).toBe("");
    expect(inputText("frac", Number.NaN)).toBe("");
  });
});

describe("inputAffix", () => {
  it("matches the display units", () => {
    expect(inputAffix("frac")).toEqual({ suffix: "%" });
    expect(inputAffix("pp")).toEqual({ suffix: "pp" });
    expect(inputAffix("usd")).toEqual({ prefix: "$" });
    expect(inputAffix("score")).toEqual({});
  });
});

describe("roundForInput", () => {
  it("rounds a dragged threshold to a typeable step in each unit", () => {
    expect(roundForInput("frac", 0.152349)).toBe(0.152);
    expect(roundForInput("x", 2.04)).toBe(2);
    expect(roundForInput("days", 89.6)).toBe(90);
    expect(roundForInput("usd", 1_234_567_890)).toBe(1_230_000_000);
    expect(roundForInput("score", 0.4567)).toBe(0.46);
  });
});

