import { compressToEncodedURIComponent } from "lz-string";
import { describe, expect, it } from "vitest";
import { decodeScreen, encodeScreen } from "./codec";
import { emptyScreen } from "./defaults";
import type { Screen } from "./types";

const screen: Screen = {
  ...emptyScreen(),
  name: "Quality — test ✓",
  universe: { include_foreign_filers: false, include_stale: false, include_no_facts: false, avg_dollar_volume_min: 1e6, market_cap_min: 3e8 },
  filters: {
    op: "and",
    children: [
      { metric: "roic", cmp: "gte", value: 0.15, missing: "fail" },
      { op: "or", children: [{ metric: "sector", cmp: "in", value: ["Banks", "Insurance"], missing: "pass" }] },
    ],
  },
  sort: { by: "roic", dir: "desc" },
};

describe("screen codec", () => {
  it("round-trips exactly, unicode included", () => {
    expect(decodeScreen(encodeScreen(screen))).toEqual(screen);
  });

  it("is URL-safe", () => {
    expect(encodeScreen(screen)).toMatch(/^[A-Za-z0-9+\-$]*$/);
    expect(encodeURIComponent(encodeScreen(screen))).toBe(encodeScreen(screen).replace(/\+/g, "%2B").replace(/\$/g, "%24"));
  });

  it("rejects junk and non-screens instead of throwing", () => {
    expect(decodeScreen(null)).toBeNull();
    expect(decodeScreen("")).toBeNull();
    expect(decodeScreen("not-lz")).toBeNull();
    expect(decodeScreen(compressToEncodedURIComponent("[1,2]"))).toBeNull();
    expect(decodeScreen(compressToEncodedURIComponent(JSON.stringify({ dsl_version: 2, name: "x" })))).toBeNull();
  });

  it("fills DSL defaults a hand-written link may omit", () => {
    const s = decodeScreen(compressToEncodedURIComponent(JSON.stringify({ dsl_version: 1, name: "bare" })));
    expect(s).toMatchObject({ limit: 100, near_misses: true });
  });
});
