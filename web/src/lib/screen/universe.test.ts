import { describe, expect, it } from "vitest";
import openapi from "../../../../contracts/openapi.json";
import { DEFAULT_UNIVERSE, effectiveUniverse, emptyScreen } from "./defaults";
import { universeChips } from "./universe";

describe("defaults mirror the contract", () => {
  it("scalar Universe defaults match contracts/openapi.json", () => {
    const props = openapi.components.schemas.Universe.properties as Record<string, { default?: unknown }>;
    for (const [k, p] of Object.entries(props)) {
      if ("default" in p) expect(DEFAULT_UNIVERSE[k as keyof typeof DEFAULT_UNIVERSE], k).toEqual(p.default);
    }
  });

  it("empty screen uses the contract's limit and near_misses defaults", () => {
    const props = openapi.components.schemas.Screen.properties as Record<string, { default?: unknown }>;
    const s = emptyScreen();
    expect(s.limit).toBe(props.limit?.default);
    expect(s.near_misses).toBe(props.near_misses?.default);
  });

  it("effectiveUniverse overlays given fields only", () => {
    const e = effectiveUniverse({ include_foreign_filers: false, include_stale: false, include_no_facts: false, avg_dollar_volume_min: null });
    expect(e.avg_dollar_volume_min).toBeNull();
    expect(e.exclude_kinds).toEqual(["spac", "fund", "shell", "no_common_equity"]);
  });
});

describe("universeChips", () => {
  it("default universe", () => {
    expect(universeChips(undefined).map((c) => c.label)).toEqual([
      "US companies that file with the SEC",
      "Listed on NYSE, Nasdaq, NYSE American or TXSE",
      "Operating companies only",
      "Trades at least $1M a day",
      "Only companies with a recent annual report",
      "Only companies with XBRL financials",
    ]);
    // Locked rules say why.
    for (const c of universeChips(undefined).filter((x) => x.clear === null)) expect(c.lockReason).toBeTruthy();
  });

  it("narrowed universe shows every rule, each with a way back", () => {
    const chips = universeChips({
      exchanges: ["NYSE", "Nasdaq"],
      sectors_exclude: ["Banks", "Utilities"],
      include_foreign_filers: false,
      include_stale: false,
      include_no_facts: false,
      market_cap_min: 300e6,
      market_cap_max: 2e9,
      avg_dollar_volume_min: 1e6,
      max_days_since_filing: 450,
    });
    expect(chips.map((c) => c.label)).toEqual([
      "US companies that file with the SEC",
      "Listed on NYSE or Nasdaq",
      "Operating companies only",
      "Leaves out Banks and Utilities",
      "Market cap $300M to $2B",
      "Trades at least $1M a day",
      "No foreign private issuers",
      "Only companies with a recent annual report",
      "Only companies with XBRL financials",
      "Filed in the last 450 days",
    ]);
    expect(chips.find((c) => c.label === "Market cap $300M to $2B")?.clear).toEqual({ market_cap_min: null, market_cap_max: null });
    expect(chips.find((c) => c.key === "scope")?.clear).toBeNull();
    expect(chips.find((c) => c.key === "exchanges")?.clear).toEqual({ exchanges: ["NYSE", "Nasdaq", "NYSE American", "TXSE"] });
  });

  it("stale rule names the window from /api/meta's universe_rules", () => {
    const chip = (rules?: { stale_annual_report_months: number } | null) => universeChips(undefined, rules).find((c) => c.key === "include_stale");
    expect(chip({ stale_annual_report_months: 15 })?.label).toBe("Only companies with an annual report in the last 15 months");
    expect(chip({ stale_annual_report_months: 15 })?.hint).toBe("Companies whose latest annual report is more than 15 months old are left out.");
    // The number follows the config, not code.
    expect(chip({ stale_annual_report_months: 18 })?.label).toBe("Only companies with an annual report in the last 18 months");
    // Until meta has loaded, no number is guessed.
    expect(chip(undefined)?.label).toBe("Only companies with a recent annual report");
    expect(chip(null)?.label).toBe("Only companies with a recent annual report");
    // Including stale companies drops the rule either way.
    expect(universeChips({ ...DEFAULT_UNIVERSE, include_stale: true }, { stale_annual_report_months: 15 }).some((c) => c.key === "include_stale")).toBe(false);
  });
});
