import lzString from "lz-string"; // CommonJS: no named exports under Node's ESM loader
import { expect, test } from "@playwright/test";

const { compressToEncodedURIComponent } = lzString;

// Phase 5 of docs/glint-ui-upgrade.md: slider-drag latency with ~6,000 result rows (the mock has
// only 300). Opt-in (GLINT_E2E_PERF=1), against a production build served by an API on the
// synthetic 6,000-company build:
//   GLINT_DB_DIR=<scratch> uv run glint fixtures synthetic --no-mocks
//   GLINT_DB_DIR=<scratch> uv run uvicorn glint.api.app:create_app --factory --port 8417
//   NEXT_PUBLIC_GLINT_API_URL=http://localhost:8417 npx next build && PORT=3098 npx next start
//   GLINT_E2E_PERF=1 PORT=3098 npx playwright test -c e2e/real drag-6k
// The screen keeps nearly every company (ROIC ≥ −500%, nulls pass, universe opened up), so the
// table holds ~6,000 rows. Timed as in e2e/drag-perf.spec.ts: keydown on the handle to the next
// frame after the sieve's text changes (includes up to one frame of rAF polling).

test.skip(!process.env.GLINT_E2E_PERF, "UI timings: GLINT_E2E_PERF=1, against a production build");

const SCREEN = {
  dsl_version: 1,
  name: "Drag latency, every company",
  universe: {
    exchanges: ["NYSE", "Nasdaq", "NYSE American", "TXSE"],
    sectors_include: [],
    sectors_exclude: [],
    exclude_kinds: [],
    include_foreign_filers: true,
    include_stale: true,
    include_no_facts: true,
    market_cap_min: null,
    market_cap_max: null,
    avg_dollar_volume_min: null,
    max_days_since_filing: null,
  },
  filters: { op: "and", children: [{ metric: "roic", cmp: "gte", value: -5, within: null, missing: "pass" }] },
  rank: { method: "percentile_composite", within: "universe", factors: [{ metric: "roic", weight: 0.5 }, { metric: "fcf_yield", weight: 0.5 }], min_factor_coverage: 0.7 },
  columns: ["ticker", "name", "sector", "market_cap", "roic", "fcf_yield", "rank_score"],
  sort: { by: "rank_score", dir: "desc" },
  limit: 100,
  near_misses: true,
};

test("dragging a threshold over ~6,000 rows updates the sieve within 50 ms (4× throttle)", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto(`/?s=${compressToEncodedURIComponent(JSON.stringify(SCREEN))}`);
  const total = page.getByRole("region", { name: "Results" }).getByText(/^[\d,]+ companies$/);
  await expect(total).toBeVisible();
  expect(Number((await total.innerText()).replace(/\D/g, ""))).toBeGreaterThan(5000);
  await page.getByRole("button", { name: "Expand ROIC" }).click();
  await page.waitForTimeout(2000);

  const cdp = await page.context().newCDPSession(page);
  const run = async (rate: number) => {
    await cdp.send("Emulation.setCPUThrottlingRate", { rate });
    await page.getByRole("slider", { name: /ROIC/ }).focus();
    const samples = await page.evaluate(async () => {
      const sieve = document.querySelector('[aria-label^="Sieve"]') as HTMLElement;
      const handle = document.activeElement as HTMLElement;
      const out: number[] = [];
      for (let k = 0; k < 50; k++) {
        const before = sieve.innerText;
        const t0 = performance.now();
        handle.dispatchEvent(new KeyboardEvent("keydown", { key: k % 20 < 10 ? "ArrowRight" : "ArrowLeft", bubbles: true }));
        const changed = await new Promise<boolean>((resolve) => {
          const tick = () => (sieve.innerText !== before ? resolve(true) : performance.now() > t0 + 500 ? resolve(false) : requestAnimationFrame(tick));
          requestAnimationFrame(tick);
        });
        if (changed) out.push(performance.now() - t0);
        await new Promise((r) => setTimeout(r, 30));
      }
      return out.sort((a, b) => a - b);
    });
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
    const q = (x: number) => samples[Math.min(samples.length - 1, Math.floor(x * samples.length))] ?? Number.NaN;
    console.log(`drag → sieve, ${rate}×, ~6,000 rows: n=${samples.length} median=${q(0.5).toFixed(1)} ms p95=${q(0.95).toFixed(1)} ms max=${(samples.at(-1) ?? Number.NaN).toFixed(1)} ms`);
    return { n: samples.length, median: q(0.5), p95: q(0.95) };
  };
  const fast = await run(1);
  const slow = await run(4);
  expect(fast.n).toBeGreaterThan(30);
  expect(fast.p95).toBeLessThan(50);
  expect(slow.median).toBeLessThan(50);
  expect(slow.p95).toBeLessThan(50);
});
