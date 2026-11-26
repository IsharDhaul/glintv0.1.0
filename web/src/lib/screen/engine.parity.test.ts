// The browser's screen engine against the real one. web/mocks/parity.json is written by the
// Python engine (`glint fixtures synthetic` → export_parity): run_screen on a build of exactly the
// mock's companies, for every preset and the shapes in PARITY_SCREENS. Any difference here means
// the live preview could show something the server wouldn't.

import { describe, expect, it } from "vitest";
import parity from "../../../mocks/parity.json";
import { MOCK_DATA } from "@/mocks/data";
import { mockEngine } from "@/mocks/generate";
import type { Screen } from "./types";

type Case = (typeof parity)["cases"][number];
const engine = mockEngine(MOCK_DATA);
const tick = engine.store.rows.ticker;
const close = (a: number | null, b: number | null) => (a === null || b === null ? a === b : Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b)));

describe.each(parity.cases.map((c) => [c.screen.name, c] as [string, Case]))("parity: %s", (_name, c) => {
  const screen = c.screen as unknown as Screen;
  const ev = engine.evaluate(screen);

  it("funnel: same counts at every stage, same binding stage", () => {
    expect(ev.funnel.map((s) => ({ index: s.index, filter_path: s.filter_path, remaining: s.remaining, removed: s.removed, removed_missing: s.removed_missing, binding: s.binding }))).toEqual(c.funnel);
  });

  it("results: same companies, same order, same ranks and scores", () => {
    const order = engine.order(screen, ev).slice(0, screen.limit);
    expect(order.map((i) => tick[i])).toEqual(c.results.map((r) => r.ticker));
    order.forEach((i, k) => {
      const want = c.results[k]!;
      expect(ev.positions.get(i) ?? null, want.ticker).toBe(want.rank);
      const got = ev.scores.get(i)?.score ?? null;
      expect(close(got, want.rank_score), `${want.ticker} score ${got} vs ${want.rank_score}`).toBe(true);
    });
  });

  it("near misses: same companies, failed filter, value, threshold, distance and reason", () => {
    const got = ev.nearMisses.map((m) => ({
      ticker: m.ticker,
      failed_filter_path: m.failed_filter_path,
      metric: m.metric,
      cmp: m.cmp,
      note: m.note?.code ?? null,
    }));
    expect(got).toEqual(c.near_misses.map(({ ticker, failed_filter_path, metric, cmp, note }) => ({ ticker, failed_filter_path, metric, cmp, note })));
    ev.nearMisses.forEach((m, k) => {
      const want = c.near_misses[k]!;
      expect(close(m.distance, want.distance), `${m.ticker} distance`).toBe(true);
      if (typeof want.value === "number") expect(close(m.value as number, want.value), `${m.ticker} value`).toBe(true);
      else expect(m.value).toEqual(want.value);
      if (Array.isArray(want.threshold)) expect(m.threshold).toEqual(want.threshold);
      else if (typeof want.threshold === "number") expect(close(m.threshold as number, want.threshold), `${m.ticker} threshold`).toBe(true);
      else expect(m.threshold).toEqual(want.threshold);
    });
  });
});
