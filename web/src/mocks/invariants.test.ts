// Trust invariants (docs/glint-ui-upgrade.md, Phase 0): every number the mock puts on screen
// agrees with every other place it appears. The engine side has the same checks in
// engine/tests/api/test_invariants.py, against the synthetic build and (opt-in) a real one.

import { describe, expect, it } from "vitest";
import { screenCheck } from "@/lib/screen/check";
import { isGroup, type Condition, type Group, type Screen } from "@/lib/screen/types";
import { MOCK_DATA } from "./data";
import { mockCompany, mockEngine, mockScreen } from "./generate";
import { loadPresetFiles } from "./presetFiles";

const PRESETS = await loadPresetFiles();
const TOL = MOCK_DATA.config.float_tolerance;

const TEST_SCREEN: Screen = {
  dsl_version: 1,
  name: "Invariants",
  filters: {
    op: "and",
    children: [
      { metric: "roic", cmp: "gte", value: 0.15, missing: "fail" },
      { metric: "gross_margin", cmp: "gte", value: 0.4, missing: "fail" },
      { metric: "net_debt_to_ebitda", cmp: "lte", value: 2, missing: "pass" },
      { op: "or", children: [
        { metric: "revenue_growth_yoy", cmp: "gte", value: 0.05, missing: "fail" },
        { metric: "fcf_margin", cmp: "between", value: [0.05, 0.4], missing: "fail" },
      ] },
      { metric: "operating_margin", cmp: "pct_rank_gte", value: 0.5, within: "sector", missing: "fail" },
    ],
  },
  columns: ["ticker", "name", "roic", "gross_margin"],
  limit: 1000,
  near_misses: true,
};

const SCREENS: [string, Screen][] = [["test screen", TEST_SCREEN], ...PRESETS.map((p) => [p.id, { ...p.screen, limit: 1000 }] as [string, Screen])];

/** Independent of the mock's evaluator: plain comparisons on the company's own values. Null when
 * the condition needs universe stats (percentiles, sector medians). */
function simplePass(node: Condition | Group, values: Record<string, unknown>): boolean | null {
  if (isGroup(node)) {
    const parts = (node.children ?? []).map((c) => simplePass(c, values));
    if (parts.some((p) => p === null)) return null;
    return node.op === "or" ? parts.some(Boolean) : parts.every(Boolean);
  }
  const x = values[node.metric];
  const t = node.value;
  if (!["gt", "gte", "lt", "lte", "between"].includes(node.cmp)) return null;
  if (typeof x !== "number") return node.missing === "pass";
  switch (node.cmp) {
    case "gt": return x > (t as number) + TOL;
    case "gte": return x >= (t as number) - TOL;
    case "lt": return x < (t as number) - TOL;
    case "lte": return x <= (t as number) + TOL;
    default: {
      const [lo, hi] = t as [number, number];
      return x >= lo - TOL && x <= hi + TOL;
    }
  }
}

const rowOf = (ticker: string) => MOCK_DATA.rows.find((r) => r.ticker === ticker)!;
/** The drawer's verdict: top-level filters the company fails, from its why_passed. */
const topFailures = (screen: Screen, ticker: string) => new Set(screenCheck(screen, mockCompany(MOCK_DATA, ticker, screen)!.why_passed!).failed.map((f) => f.index));

describe("headline values match their history", () => {
  // The sparkline's newest TTM point is the same number as the metric beside it.
  const METRICS = ["revenue_ttm", "operating_margin", "fcf_margin", "share_count_change_yoy"];
  it.each(METRICS)("%s: last TTM point = headline", (metric) => {
    let checked = 0;
    for (const row of MOCK_DATA.rows) {
      const c = mockCompany(MOCK_DATA, row.ticker)!;
      const ttm = (c.history[metric] ?? []).filter((p) => p.basis === "ttm");
      const headline = c.metrics[metric]?.value ?? null;
      if (headline === null) {
        expect(ttm, `${row.ticker} has history for a missing ${metric}`).toEqual([]);
        continue;
      }
      expect(ttm.at(-1)?.value, `${row.ticker} ${metric}`).toBe(headline);
      checked++;
    }
    expect(checked).toBeGreaterThan(200);
  });
});

describe("one source for filing dates and flag evidence", () => {
  const asOf = new Date(MOCK_DATA.meta.as_of.fundamentals!.slice(0, 10)).getTime();
  const days = (iso: string) => Math.round((asOf - new Date(iso).getTime()) / 86_400_000);

  it("days since filing = as-of date − the latest 10-K/10-Q date, and the sources list that filing", () => {
    for (const row of MOCK_DATA.rows) {
      const c = mockCompany(MOCK_DATA, row.ticker)!;
      const latest = [c.company.last_annual_date, c.company.last_quarterly_date].filter(Boolean).sort().at(-1)!;
      const shown = c.metrics.days_since_filing!;
      // A missing value carries its reason; a present one is the date arithmetic, nothing else.
      if (shown.value === null) expect(shown.note, row.ticker).toBeTruthy();
      else expect(shown.value, row.ticker).toBe(days(latest));
      expect(c.sources[0]?.filed, row.ticker).toBe(latest);
      expect(c.sources.find((s) => s.form === "10-K")?.filed).toBe(c.company.last_annual_date);
    }
  });

  it("flag evidence repeats the company's own numbers and dates", () => {
    let flags = 0;
    for (const row of MOCK_DATA.rows) {
      const c = mockCompany(MOCK_DATA, row.ticker)!;
      for (const f of c.flags) {
        flags++;
        for (const [k, v] of Object.entries(f.evidence)) {
          if (k === "last_annual_date") expect(v).toBe(c.company.last_annual_date);
          else if (k in c.metrics && typeof v === "number") expect(v, `${row.ticker} ${f.flag_id} ${k}`).toBe(c.metrics[k]!.value);
        }
      }
      expect(c.metrics.flag_count?.value, row.ticker).toBe(c.flags.length);
    }
    expect(flags).toBeGreaterThan(0);
  });
});

describe.each(SCREENS)("screen invariants: %s", (_id, screen) => {
  const res = mockScreen(MOCK_DATA, screen);
  const top = screen.filters?.children ?? [];

  it("sieve: at every stage kept + failed + no data = the previous stage", () => {
    const companies = MOCK_DATA.meta.universe_counts!.companies;
    expect(res.funnel[0]!.remaining + res.funnel[0]!.removed).toBe(companies);
    for (let i = 1; i < res.funnel.length; i++) {
      const s = res.funnel[i]!;
      const failed = s.removed - s.removed_missing;
      expect(failed).toBeGreaterThanOrEqual(0);
      expect(s.remaining + failed + s.removed_missing).toBe(res.funnel[i - 1]!.remaining);
    }
    expect(res.total).toBe(res.funnel.at(-1)!.remaining);
    expect(res.results.length).toBe(Math.min(screen.limit, res.total));
  });

  it("every company shown as passing passes every active filter", () => {
    for (const r of res.results) {
      const row = rowOf(r.ticker);
      top.forEach((node, i) => {
        const simple = simplePass(node, row.values);
        if (simple !== null) expect(simple, `${r.ticker} fails filter ${i}`).toBe(true);
      });
      // The drawer agrees: no failed filter for a passing company.
      expect(topFailures(screen, r.ticker).size, r.ticker).toBe(0);
    }
  });

  it("every near miss fails exactly one filter, and the value shown fails it", () => {
    for (const m of res.near_misses) {
      const row = rowOf(m.ticker);
      const failed = top.map((node, i) => [simplePass(node, row.values), i] as const).filter(([p]) => p === false);
      const idx = m.failed_filter_path[2] as number;
      // Plain comparisons that fail are exactly the reported one (others may need universe stats).
      for (const [, i] of failed) expect(i, `${m.ticker} also fails filter ${i}`).toBe(idx);
      expect([...topFailures(screen, m.ticker)], m.ticker).toEqual([idx]);

      // The shown value really fails the shown threshold.
      const node = top[idx]!;
      const leaf = !isGroup(node) ? node : null;
      if (m.value === null || typeof m.value !== "number") continue;
      const t = m.threshold;
      const cmp = m.cmp;
      if (cmp === "gte" || cmp === "pct_rank_gte" || cmp === "vs_sector_median_gte") expect(m.value).toBeLessThan((t as number) - TOL);
      if (cmp === "lte" || cmp === "pct_rank_lte" || cmp === "vs_sector_median_lte") expect(m.value).toBeGreaterThan((t as number) + TOL);
      if (cmp === "gt") expect(m.value).toBeLessThanOrEqual((t as number) + TOL);
      if (cmp === "lt") expect(m.value).toBeGreaterThanOrEqual((t as number) - TOL);
      if (cmp === "between") {
        const [lo, hi] = t as [number, number];
        expect(m.value < lo - TOL || m.value > hi + TOL, `${m.ticker} ${m.value} in [${lo}, ${hi}]`).toBe(true);
      }
      if (leaf) expect(m.metric).toBe(leaf.metric);
    }
  });
});

describe.each(SCREENS)("removed lists agree with the sieve: %s", (_id, screen) => {
  const engine = mockEngine(MOCK_DATA);
  const ev = engine.evaluate(screen);
  it("each stage lists exactly what it removed: count, no-data count, and failing values", () => {
    ev.funnel.slice(1).forEach((step) => {
      const removed = engine.removedAt(screen, step.index, 10_000);
      expect(removed.length, `stage ${step.index}`).toBe(step.removed);
      expect(removed.filter((r) => r.reason === "no_data").length, `stage ${step.index} no data`).toBe(step.removed_missing);
      for (const r of removed) {
        if (r.reason !== "failed" || typeof r.value !== "number") continue;
        const node = (screen.filters?.children ?? [])[step.index - 1]!;
        if (isGroup(node)) continue;
        expect(simplePass(node, { [node.metric]: r.value }), `${r.ticker} passes the stage it was removed at`).not.toBe(true);
      }
    });
  });
});
