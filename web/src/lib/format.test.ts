import { describe, expect, it } from "vitest";
import {
  formatBool,
  formatUsdShort,
  formatCount,
  formatDate,
  formatDateTimeEt,
  formatDays,
  formatFiscalYearEnd,
  formatFrac,
  formatMetric,
  formatMultiple,
  formatPp,
  formatScore,
  formatUsd,
  formatValue,
  formatGap,
  formatPrice,
  formatPercentile,
  describePercentile,
  type Unit,
} from "./format";

describe("prices and percentiles", () => {
  it("prices always have two decimals", () => {
    expect(formatPrice(512.4)).toBe("$512.40");
    expect(formatPrice(1204)).toBe("$1,204.00");
  });
  it("percentiles read p87, and say their direction", () => {
    expect(formatPercentile(0.873)).toBe("p87");
    expect(describePercentile(0.87, "higher", "Technology")).toBe("better than 87% of Technology");
    expect(describePercentile(0.87, "lower", "Technology")).toBe("better than 13% of Technology");
    expect(describePercentile(0.87, "neutral", "Technology")).toBe("higher than 87% of Technology");
  });
});

const M = "−";

describe("formatCount", () => {
  it.each([
    [0, "0"],
    [7, "7"],
    [1104, "1,104"],
    [6000, "6,000"],
    [1234567, "1,234,567"],
  ])("%d → %s", (n, s) => expect(formatCount(n)).toBe(s));
});

describe("formatUsd (SPEC §3.3: $1.24B / $312M)", () => {
  it.each([
    [1.24e9, "$1.24B"],
    [312e6, "$312M"],
    [12.4e9, "$12.4B"],
    [842e6, "$842M"],
    [1.5e12, "$1.50T"],
    [300e6, "$300M"],
    [1e6, "$1.00M"],
    [45_600, "$45.6K"],
    [1000, "$1.00K"],
    [9.375051, "$9.38"],
    [0.5, "$0.50"],
    [0, "$0.00"],
    [-2.5e9, `${M}$2.50B`],
    [-312e6, `${M}$312M`],
  ])("%d → %s", (v, s) => expect(formatUsd(v)).toBe(s));

  it("rolls up at the boundary instead of printing $1000M", () => {
    expect(formatUsd(999.96e6)).toBe("$1.00B");
    expect(formatUsd(999.4e6)).toBe("$999M");
    expect(formatUsd(9.996e9)).toBe("$10.0B");
    expect(formatUsd(99.96e9)).toBe("$100B");
    expect(formatUsd(999.996)).toBe("$1.00K");
  });
});

describe("formatFrac (0.152 → 15.2%)", () => {
  it.each([
    [0.152, "15.2%"],
    [0.15, "15.0%"],
    [0, "0.0%"],
    [1, "100.0%"],
    [12.5, "1,250.0%"],
    [-0.042, `${M}4.2%`],
    [0.0004, "0.0%"],
    [-0.0004, "0.0%"],
    [0.00049, "0.0%"],
    [0.0005, "0.1%"],
  ])("%d → %s", (v, s) => expect(formatFrac(v)).toBe(s));
});

describe("formatPp (always signed)", () => {
  it.each([
    [0.023, "+2.3 pp"],
    [-0.011, `${M}1.1 pp`],
    [0, "0.0 pp"],
    [-0.0001, "0.0 pp"],
    [0.05, "+5.0 pp"],
  ])("%d → %s", (v, s) => expect(formatPp(v)).toBe(s));
});

describe("formatMultiple / formatDays / formatScore / formatBool", () => {
  it.each([
    [14.2, "14.2x"],
    [14.25, "14.3x"],
    [9.8, "9.8x"],
    [1011.52317, "1,011.5x"],
    [-3.2, `${M}3.2x`],
    [-0.01, "0.0x"],
  ])("multiple %d → %s", (v, s) => expect(formatMultiple(v)).toBe(s));

  it.each([
    [47, "47 d"],
    [47.6, "48 d"],
    [0, "0 d"],
    [-3, `${M}3 d`],
    [-0.2, "0 d"],
  ])("days %d → %s", (v, s) => expect(formatDays(v)).toBe(s));

  it("score: n/max for integers with a scale, else 2 dp", () => {
    expect(formatScore(7, 9)).toBe("7/9");
    expect(formatScore(7)).toBe("7.00");
    expect(formatScore(2.987)).toBe("2.99");
    expect(formatScore(7.5, 9)).toBe("7.50");
    expect(formatScore(-1.234)).toBe(`${M}1.23`);
  });

  it("bool", () => {
    expect(formatBool(true)).toBe("Yes");
    expect(formatBool(false)).toBe("No");
  });
});

describe("formatValue dispatches on every unit", () => {
  const cases: [Unit, number | boolean | string, string][] = [
    ["usd", 1.24e9, "$1.24B"],
    ["frac", 0.152, "15.2%"],
    ["pp", 0.023, "+2.3 pp"],
    ["x", 14.2, "14.2x"],
    ["days", 47, "47 d"],
    ["score", 2.5, "2.50"],
    ["bool", true, "Yes"],
    ["bool", 0, "No"],
    ["text", "Technology", "Technology"],
    ["frac", "already text", "already text"],
    ["usd", false, "No"],
  ];
  it.each(cases)("%s %s → %s", (unit, v, s) => expect(formatValue(unit, v)).toBe(s));

  it("non-finite numbers are not meaningful, never 'NaN%'", () => {
    expect(formatValue("frac", Number.NaN)).toBe("n/m");
    expect(formatValue("x", Number.POSITIVE_INFINITY)).toBe("n/m");
  });

  it("covers every Unit in the contract", () => {
    const units: Unit[] = ["usd", "frac", "pp", "x", "days", "score", "bool", "text"];
    for (const u of units) expect(typeof formatValue(u, 1)).toBe("string");
  });
});

describe("formatMetric", () => {
  it("uses the score scale for piotroski_f", () => {
    expect(formatMetric({ id: "piotroski_f", unit: "score" }, 8)).toBe("8/9");
    expect(formatMetric({ id: "altman_z", unit: "score" }, 3)).toBe("3.00");
    expect(formatMetric({ id: "roic", unit: "frac" }, 0.312)).toBe("31.2%");
    expect(formatMetric({ id: "flag_count", unit: "score" }, 2)).toBe("2");
  });
});

describe("dates", () => {
  it("formatDate gives the UTC calendar date", () => {
    expect(formatDate("2026-01-01")).toBe("2026-01-01");
    expect(formatDate("2026-01-02T08:00:00Z")).toBe("2026-01-02");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not a date")).toBe("—");
  });

  it("formatFiscalYearEnd reads SEC MMDD", () => {
    expect(formatFiscalYearEnd("1231")).toBe("Dec 31");
    expect(formatFiscalYearEnd("0630")).toBe("Jun 30");
    expect(formatFiscalYearEnd("0105")).toBe("Jan 5");
    expect(formatFiscalYearEnd("1331")).toBe("1331");
    expect(formatFiscalYearEnd(null)).toBe("—");
  });

  it("formatDateTimeEt converts to New York time, both DST and standard", () => {
    expect(formatDateTimeEt("2026-01-02T08:00:00Z")).toBe("2026-01-02 03:00 ET");
    expect(formatDateTimeEt("2026-07-02T07:00:00Z")).toBe("2026-07-02 03:00 ET");
    expect(formatDateTimeEt("2026-01-02T03:30:00Z")).toBe("2026-01-01 22:30 ET");
    expect(formatDateTimeEt(undefined)).toBe("—");
  });
});

describe("formatGap", () => {
  it("never shows a real gap as zero", () => {
    expect(formatGap("frac", 0.0002)).toBe("< 0.1 pp");
    expect(formatGap("frac", 0.075)).toBe("7.5 pp");
    expect(formatGap("x", 0.02)).toBe("< 0.1x");
    expect(formatGap("x", 0.4)).toBe("0.4x");
  });
});


describe("formatUsdShort", () => {
  it("drops trailing zeros for sentences", () => {
    expect(formatUsdShort(1e6)).toBe("$1M");
    expect(formatUsdShort(2e9)).toBe("$2B");
    expect(formatUsdShort(1.5e9)).toBe("$1.5B");
    expect(formatUsdShort(312e6)).toBe("$312M");
    expect(formatUsdShort(300e6)).toBe("$300M");
  });
});
