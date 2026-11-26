import { describe, expect, it } from "vitest";
import { emptyScreen } from "./defaults";
import { effectiveSort, nextSort, responseColumns, setColumns, userColumns, responseBadges, withBadgeColumns } from "./columns";
import type { Screen } from "./types";

describe("columns", () => {
  it("ticker first, badges excluded from the user's columns", () => {
    const s = { ...emptyScreen(), columns: ["name", "roic", "ticker", "flag_count"] };
    expect(userColumns(s)).toEqual(["ticker", "name", "roic"]);
    expect(withBadgeColumns(s, new Set(["flag_count", "data_coverage"])).columns).toEqual(["ticker", "name", "roic", "flag_count", "data_coverage"]);
    // A real build serves only live metrics: planned badge columns must not be requested (engine 422s).
    expect(withBadgeColumns(s, new Set(["roic"])).columns).toEqual(["ticker", "name", "roic"]);
    expect(responseBadges({ results: [{ values: { ticker: "X", data_coverage: 1 } }] })).toEqual(["data_coverage"]);
    expect(responseBadges({ results: [] })).toEqual([]);
  });

  it("defaults when the screen has none", () => {
    expect(userColumns({ ...emptyScreen(), columns: undefined })).toEqual(["ticker", "name", "sector", "market_cap"]);
  });

  it("responseColumns follows the response, not the newer screen", () => {
    const res = { results: [{ values: { ticker: "SYN1", name: "x", market_cap: 1, flag_count: 0, data_coverage: 1 } }] };
    expect(responseColumns(res, { ...emptyScreen(), columns: ["roic"] })).toEqual(["ticker", "name", "market_cap"]);
    expect(responseColumns({ results: [] }, { ...emptyScreen(), columns: ["roic"] })).toEqual(["ticker", "roic"]);
  });

  it("setColumns keeps ticker pinned first", () => {
    expect(setColumns(emptyScreen(), ["roic", "ticker", "name"]).columns).toEqual(["ticker", "roic", "name"]);
  });
});

describe("sorting", () => {
  it("default follows the engine", () => {
    expect(effectiveSort(emptyScreen())).toEqual({ by: "ticker", dir: "asc" });
    expect(effectiveSort({ ...emptyScreen(), rank: { method: "rank_sum", within: "universe", factors: [], min_factor_coverage: 1 } })).toEqual({
      by: "rank_score",
      dir: "desc",
    });
  });

  it("numeric: desc → asc → default", () => {
    let s = emptyScreen();
    s = { ...s, sort: nextSort(s, "roic", true) };
    expect(s.sort).toEqual({ by: "roic", dir: "desc" });
    s = { ...s, sort: nextSort(s, "roic", true) };
    expect(s.sort).toEqual({ by: "roic", dir: "asc" });
    s = { ...s, sort: nextSort(s, "roic", true) };
    expect(s.sort).toBeNull();
  });

  it("text starts ascending; a new column restarts", () => {
    let s: Screen = { ...emptyScreen(), sort: { by: "roic", dir: "asc" } };
    s = { ...s, sort: nextSort(s, "name", false) };
    expect(s.sort).toEqual({ by: "name", dir: "asc" });
  });
});
