import { describe, expect, it } from "vitest";
import type { Unit } from "@/lib/format";
import { emptyScreen } from "./defaults";
import { metricMap } from "./describe";
import {
  addFilter,
  addOrGroup,
  allowedComparators,
  getAt,
  isComplete,
  newCondition,
  removeAt,
  runnable,
  updateAt,
  valueKind,
  withComparator,
} from "./filters";
import type { Condition, MetricDefinition } from "./types";

const def = (id: string, unit: Unit, better: MetricDefinition["better"] = "higher"): MetricDefinition => ({
  id,
  name: id,
  category: "profitability",
  unit,
  better,
  tier: "sec",
  priority: "P0",
  basis: "ttm",
  definition: "",
  inputs: [],
  status: "live",
});
const metrics = metricMap([def("roic", "frac"), def("pe_ttm", "x", "lower"), def("dps_no_cut_5y", "bool"), def("market_cap", "usd", "neutral")]);

describe("comparators follow the contract's ALLOWED_CMPS", () => {
  it("numeric units get numeric, between, percentile, vs-median and null tests", () => {
    for (const u of ["usd", "frac", "pp", "x", "days", "score"] as Unit[]) {
      expect(new Set(allowedComparators(u))).toEqual(
        new Set(["gt", "gte", "lt", "lte", "between", "pct_rank_gte", "pct_rank_lte", "vs_sector_median_gte", "vs_sector_median_lte", "is_null", "not_null"]),
      );
    }
  });
  it("bool and text", () => {
    expect(new Set(allowedComparators("bool"))).toEqual(new Set(["eq", "neq", "is_null", "not_null"]));
    expect(new Set(allowedComparators("text"))).toEqual(new Set(["eq", "neq", "in", "is_null", "not_null"]));
  });
});

describe("conditions", () => {
  it("new conditions point toward 'better' and start empty", () => {
    expect(newCondition("roic", metrics)).toEqual({ metric: "roic", cmp: "gte", value: null, missing: "fail" });
    expect(newCondition("pe_ttm", metrics).cmp).toBe("lte");
    expect(newCondition("dps_no_cut_5y", metrics)).toMatchObject({ cmp: "eq", value: true });
    expect(newCondition("sector", metrics)).toMatchObject({ cmp: "in", value: null });
  });

  it("switching comparator keeps a value of the same shape, drops one of another, and sets within", () => {
    const c: Condition = { metric: "roic", cmp: "gte", value: 0.15, missing: "pass" };
    expect(withComparator(c, "lt", "frac")).toEqual({ metric: "roic", cmp: "lt", value: 0.15, missing: "pass" });
    expect(withComparator(c, "between", "frac").value).toBeNull();
    expect(withComparator(c, "pct_rank_gte", "frac")).toMatchObject({ value: null, within: "universe" });
    expect(withComparator({ ...c, cmp: "pct_rank_gte", within: "sector", value: 0.7 }, "gte", "frac")).not.toHaveProperty("within");
  });

  it.each([
    [{ cmp: "gte", value: 0.15 }, "frac", true],
    [{ cmp: "gte", value: null }, "frac", false],
    [{ cmp: "between", value: [0.1, 0.2] }, "frac", true],
    [{ cmp: "between", value: [0.2, 0.1] }, "frac", false],
    [{ cmp: "between", value: [0.1] }, "frac", false],
    [{ cmp: "pct_rank_gte", value: 0.7 }, "frac", true],
    [{ cmp: "pct_rank_gte", value: 70 }, "frac", false],
    [{ cmp: "is_null", value: null }, "frac", true],
    [{ cmp: "eq", value: true }, "bool", true],
    [{ cmp: "eq", value: "x" }, "bool", false],
    [{ cmp: "in", value: ["Banks"] }, "text", true],
    [{ cmp: "in", value: [] }, "text", false],
  ] as [Partial<Condition>, Unit, boolean][])("%j (%s) complete=%s", (part, unit, ok) => {
    expect(isComplete({ metric: "m", missing: "fail", cmp: "gte", ...part } as Condition, unit)).toBe(ok);
  });

  it("value kinds", () => {
    expect(valueKind("vs_sector_median_gte", "frac")).toBe("vs_median");
    expect(valueKind("eq", "text")).toBe("category");
    expect(valueKind("eq", "bool")).toBe("bool");
  });
});

describe("runnable", () => {
  it("drops incomplete filters and maps the rest to funnel steps", () => {
    let s = emptyScreen();
    s = addFilter(s, { metric: "roic", cmp: "gte", value: 0.15, missing: "fail" });
    s = addFilter(s, newCondition("pe_ttm", metrics)); // incomplete
    s = addOrGroup(s, newCondition("market_cap", metrics)); // group of one incomplete → dropped
    s = addFilter(s, { metric: "pe_ttm", cmp: "lte", value: 20, missing: "fail" });
    const r = runnable(s, metrics);
    expect(r.screen.filters?.children).toHaveLength(2);
    expect(r.stepOf).toEqual([1, null, null, 2]);
  });

  it("keeps a group's complete children only", () => {
    let s = addOrGroup(emptyScreen(), { metric: "roic", cmp: "gte", value: 0.1, missing: "fail" });
    s = addFilter(s, newCondition("pe_ttm", metrics), 0);
    const g = runnable(s, metrics).screen.filters?.children?.[0];
    expect(g).toEqual({ op: "or", children: [{ metric: "roic", cmp: "gte", value: 0.1, missing: "fail" }] });
  });
});

describe("top-level operator", () => {
  it("runnable and edits keep a top-level OR (a shared screen must run as written)", () => {
    const a: Condition = { metric: "roic", cmp: "gte", value: 0.15, missing: "fail" };
    const b: Condition = { metric: "pe_ttm", cmp: "lte", value: 20, missing: "fail" };
    const s = { ...emptyScreen(), filters: { op: "or" as const, children: [a] } };
    expect(runnable(s, metrics).screen.filters?.op).toBe("or");
    expect(addFilter(s, b).filters?.op).toBe("or");
    expect(removeAt(addFilter(s, b), { top: 0 }).filters).toEqual({ op: "or", children: [b] });
    expect(updateAt(s, { top: 0 }, { ...a, value: 0.2 }).filters?.op).toBe("or");
  });
});

describe("tree edits", () => {
  const a: Condition = { metric: "roic", cmp: "gte", value: 0.15, missing: "fail" };
  const b: Condition = { metric: "pe_ttm", cmp: "lte", value: 20, missing: "fail" };

  it("add, update and remove inside an OR group", () => {
    let s = addOrGroup(emptyScreen(), a);
    s = addFilter(s, b, 0);
    expect(getAt(s, { top: 0, child: 1 })).toEqual(b);
    s = updateAt(s, { top: 0, child: 1 }, { ...b, value: 15 });
    expect((getAt(s, { top: 0, child: 1 }) as Condition).value).toBe(15);
    s = removeAt(s, { top: 0, child: 0 });
    expect(s.filters?.children).toEqual([{ op: "or", children: [{ ...b, value: 15 }] }]);
    s = removeAt(s, { top: 0, child: 0 });
    expect(s.filters?.children).toEqual([]);
  });

  it("top-level edits leave other filters alone", () => {
    let s = addFilter(addFilter(emptyScreen(), a), b);
    s = updateAt(s, { top: 1 }, { ...b, value: 10 });
    s = removeAt(s, { top: 0 });
    expect(s.filters?.children).toEqual([{ ...b, value: 10 }]);
  });
});
