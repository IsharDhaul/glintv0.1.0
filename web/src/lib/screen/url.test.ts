import { describe, expect, it } from "vitest";
import { encodeScreen } from "./codec";
import { emptyScreen } from "./defaults";
import { addFilter, removeAt } from "./filters";
import { sameScreen, screenFromParam, screenParam, shareUrl, stableJson, uiFromSearch, withScreenParam, withUiParams } from "./url";

const roic = { metric: "roic", cmp: "gte" as const, value: 0.15, missing: "fail" as const };

describe("URL codec for screens", () => {
  it("the empty screen has no param, so a fresh screener is a clean URL", () => {
    expect(screenParam(emptyScreen())).toBeNull();
    // Adding and removing a filter comes back to the empty screen.
    expect(screenParam(removeAt(addFilter(emptyScreen(), roic), { top: 0 }))).toBeNull();
  });

  it("round-trips a screen through the param", () => {
    const s = addFilter({ ...emptyScreen(), name: "Mine" }, roic);
    const p = screenParam(s);
    expect(p).not.toBeNull();
    expect(sameScreen(screenFromParam(p), s)).toBe(true);
  });

  it("falls back to the empty screen for a missing or broken param", () => {
    expect(screenFromParam(null)).toEqual(emptyScreen());
    expect(screenFromParam("garbage")).toEqual(emptyScreen());
  });

  it("compares screens by content, not key order", () => {
    expect(stableJson({ b: 1, a: [{ d: 2, c: 3 }] })).toBe('{"a":[{"c":3,"d":2}],"b":1}');
    const a = addFilter(emptyScreen(), roic);
    const b = { ...(Object.fromEntries(Object.entries(a).reverse()) as typeof a), filters: { children: a.filters?.children, op: "and" as const } };
    expect(sameScreen(a, b)).toBe(true);
  });

  it("sets or removes s and keeps other params", () => {
    expect(withScreenParam("?mock=ok", "abc")).toBe("?mock=ok&s=abc");
    expect(withScreenParam("?mock=ok&s=abc", null)).toBe("?mock=ok");
    expect(withScreenParam("?s=abc", null)).toBe("");
  });

  it("share URLs carry only the screen", () => {
    const s = addFilter(emptyScreen(), roic);
    expect(shareUrl("https://glint.example", s)).toBe(`https://glint.example/?s=${encodeScreen(s)}`);
    expect(shareUrl("https://glint.example", emptyScreen())).toBe("https://glint.example/");
  });

  it("selected ticker and open drawer ride in t and d, alongside s", () => {
    expect(uiFromSearch("?s=abc&t=adbe&d=1")).toEqual({ ticker: "ADBE", drawer: true, pinned: [] });
    expect(uiFromSearch("?d=1")).toEqual({ ticker: null, drawer: false, pinned: [] }); // no drawer without a ticker
    expect(uiFromSearch("?c=adbe,msft,aapl,nvda").pinned).toEqual(["ADBE", "MSFT", "AAPL"]); // at most three
    expect(withUiParams("?s=abc", { ticker: null, drawer: false, pinned: ["ADBE", "MSFT"] })).toBe("?s=abc&c=ADBE%2CMSFT");
    expect(withUiParams("?s=abc&mock=ok", { ticker: "ADBE", drawer: true })).toBe("?s=abc&mock=ok&t=ADBE&d=1");
    expect(withUiParams("?s=abc&t=ADBE&d=1", { ticker: "ADBE", drawer: false })).toBe("?s=abc&t=ADBE");
    expect(withUiParams("?t=ADBE&d=1", { ticker: null, drawer: false })).toBe("");
    const s = screenFromParam(null);
    expect(shareUrl("https://glint.example", s, { ticker: "ADBE", drawer: true })).toBe("https://glint.example/?t=ADBE&d=1");
  });
});

