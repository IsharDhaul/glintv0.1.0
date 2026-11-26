import { describe, expect, it } from "vitest";
import { DEFAULT_UNIVERSE } from "@/lib/screen/defaults";
import type { Screen } from "@/lib/screen/types";
import { MOCK_DATA } from "./data";
import { MOCK_WARNING, mockCompany, mockCsv, mockDistribution, mockScreen, mockSearch, responseColumns } from "./generate";
import { loadPresetFiles } from "./presetFiles";

const MOCK_PRESETS = await loadPresetFiles();

const screen: Screen = {
  dsl_version: 1,
  name: "Test screen",
  filters: {
    op: "and",
    children: [
      { metric: "roic", cmp: "gte", value: 0.15, missing: "fail" },
      { metric: "fcf_yield", cmp: "gte", value: 0.05, missing: "fail" },
      {
        op: "or",
        children: [
          { metric: "revenue_growth_yoy", cmp: "gte", value: 0.05, missing: "fail" },
          { metric: "operating_margin_change_yoy", cmp: "gte", value: 0.02, missing: "fail" },
        ],
      },
    ],
  },
  columns: ["ticker", "name", "market_cap", "roic", "not_a_metric"],
  limit: 50,
  near_misses: true,
};

describe("mockScreen", () => {
  const res = mockScreen(MOCK_DATA, screen);

  it("names one funnel step per top-level filter, with counts that add up", () => {
    expect(res.funnel.map((s) => s.label)).toEqual([
      "Universe",
      "ROIC ≥ 15.0%",
      "FCF yield ≥ 5.0%",
      expect.stringContaining(" OR "),
    ]);
    for (let i = 1; i < res.funnel.length; i++) {
      const prev = res.funnel[i - 1]!;
      const step = res.funnel[i]!;
      expect(step.remaining).toBeLessThanOrEqual(prev.remaining);
      expect(step.removed).toBe(prev.remaining - step.remaining);
      expect(step.removed_missing).toBeLessThanOrEqual(step.removed);
    }
    expect(res.funnel.filter((s) => s.binding).length).toBeLessThanOrEqual(1);
    expect(res.total).toBe(res.funnel.at(-1)!.remaining);
  });

  it("returns synthetic rows carrying every requested column, nulls with a reason", () => {
    expect(res.results.length).toBeGreaterThan(0);
    expect(res.results.length).toBeLessThanOrEqual(Math.min(screen.limit, res.total));
    for (const row of res.results) {
      expect(row.ticker.startsWith("SYN")).toBe(true);
      expect(Object.keys(row.values)).toEqual(responseColumns(screen));
      expect(row.values.not_a_metric).toBeNull();
      expect(row.notes.not_a_metric?.code).toBe("MISSING_INPUT");
      for (const [id, v] of Object.entries(row.values)) {
        if (v === null) expect(row.notes[id], `${row.ticker}.${id} is null without a reason`).toBeDefined();
      }
    }
  });

  it("is deterministic per request and says it is a mock", () => {
    expect(mockScreen(MOCK_DATA, screen)).toEqual(res);
    expect(res.warnings).toContain(MOCK_WARNING);
  });

  it("near misses point at a real top-level filter", () => {
    for (const nm of res.near_misses) {
      expect(nm.ticker.startsWith("SYN")).toBe(true);
      expect(res.funnel.some((s) => s.label === nm.failed_label)).toBe(true);
    }
  });


  it("note is set exactly when the compared value is null (CONTRACT #18)", () => {
    // Each screen is built to hit one display path: a small sector (no sector percentile) and a
    // sector median ≤ 0 (a ratio to it isn't meaningful). Plain missing values come from `screen`.
    const one = (filter: Screen["filters"], universe: Partial<NonNullable<Screen["universe"]>>): Screen => ({ ...screen, name: "notes", filters: filter, universe: { ...DEFAULT_UNIVERSE, ...universe } });
    const screens: Screen[] = [
      screen,
      one({ op: "and", children: [{ metric: "operating_margin", cmp: "pct_rank_gte", value: 0.7, within: "sector", missing: "fail" }] }, { sectors_include: ["Capital Markets", "Consumer Staples"], market_cap_min: 1e9 }),
      one({ op: "and", children: [{ metric: "net_debt", cmp: "vs_sector_median_lte", value: 0.8, missing: "fail" }] }, { sectors_include: ["Capital Markets", "Technology"] }),
    ];
    const codes = new Set<string>();
    for (const s of screens) {
      for (const m of mockScreen(MOCK_DATA, s).near_misses) {
        const comparedIsNull = m.value === null || (m.cmp.startsWith("vs_sector_median") && m.threshold === null) || (m.cmp.startsWith("pct_rank") && m.value === null);
        expect(m.note !== null && m.note !== undefined, `${m.ticker} ${m.cmp}`).toBe(comparedIsNull);
        if (m.note) codes.add(m.note.code);
      }
    }
    expect(codes).toContain("SMALL_PEER_GROUP");
    expect(codes).toContain("NEGATIVE_DENOMINATOR");
  });

  it("near misses follow the engine: at most 25, closest first, no-distance last", () => {
    for (let k = 0; k < 10; k++) {
      const list = mockScreen(MOCK_DATA, { ...screen, name: `nm ${k}` }).near_misses;
      expect(list.length).toBeLessThanOrEqual(25);
      const d = list.map((m) => m.distance);
      const firstNull = d.indexOf(null);
      const numeric = (firstNull < 0 ? d : d.slice(0, firstNull)) as number[];
      expect(numeric).toEqual([...numeric].sort((a, b) => a - b));
      if (firstNull >= 0) expect(d.slice(firstNull).every((x) => x === null)).toBe(true);
    }
  });

  it("empty scenario ends at zero with no rows", () => {
    const empty = mockScreen(MOCK_DATA, screen, { empty: true });
    expect(empty.total).toBe(0);
    expect(empty.results).toEqual([]);
  });

  it("ranks 1..n when the screen ranks", () => {
    const ranked = mockScreen(MOCK_DATA, MOCK_PRESETS.find((p) => p.screen.rank)!.screen);
    expect(ranked.results.map((r) => r.rank)).toEqual(ranked.results.map((_, i) => i + 1));
  });

  it("matches the engine's column rules: defaults, categorical fields, rank_score", () => {
    const bare = mockScreen(MOCK_DATA, { dsl_version: 1, name: "bare", limit: 10, near_misses: false });
    expect(Object.keys(bare.results[0]!.values)).toEqual(["ticker", "name", "sector", "market_cap"]);
    expect(bare.results[0]!.values.ticker).toBe(bare.results[0]!.ticker);
    expect(bare.results.map((r) => r.ticker)).toEqual([...bare.results.map((r) => r.ticker)].sort());

    const qc = MOCK_PRESETS.find((p) => p.id === "quality-compounders")!;
    const ranked = mockScreen(MOCK_DATA, qc.screen);
    for (const row of ranked.results) expect(row.values.rank_score).toBe(row.rank_score);
  });

  it("serves the real config/presets files", () => {
    expect(MOCK_PRESETS.map((p) => p.id)).toEqual(expect.arrayContaining(["quality-compounders", "magic-formula", "dilution-watch"]));
  });

  it("every mock preset produces a response", () => {
    for (const p of MOCK_PRESETS) expect(mockScreen(MOCK_DATA, p.screen).funnel[0]!.label).toBe("Universe");
  });
});

describe("other mocks", () => {
  it("distribution bins cover every non-null value", () => {
    const d = mockDistribution(MOCK_DATA, "roic", "universe", null);
    expect(d.bins.reduce((s, b) => s + b.count, 0)).toBe(d.count);
    expect(d.count + d.null_count).toBe(MOCK_DATA.rows.length);
  });

  it("company lookup is synthetic and links nowhere real", () => {
    const ticker = MOCK_DATA.rows[0]!.ticker;
    const c = mockCompany(MOCK_DATA, ticker.toLowerCase())!;
    expect(c.company.kind).toBe("synthetic");
    expect(c.sources.every((s) => !s.url.startsWith("http"))).toBe(true);
    expect(mockCompany(MOCK_DATA, "AAPL")).toBeNull();
  });

  it("search ranks exact before prefix", () => {
    const t = MOCK_DATA.rows[0]!.ticker;
    expect(mockSearch(MOCK_DATA, t).results[0]?.match).toBe("exact");
  });

  it("csv has visible columns, as-of stamps and notes", () => {
    const res = mockScreen(MOCK_DATA, screen);
    const [header, first] = mockCsv(res, screen).split("\n");
    expect(header).toBe("ticker,name,market_cap,roic,not_a_metric,as_of_fundamentals,as_of_prices,notes");
    expect(first).toContain("not_a_metric: MISSING_INPUT");
  });
});
