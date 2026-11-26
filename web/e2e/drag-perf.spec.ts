import { expect, test } from "@playwright/test";

// @perf (make perf; excluded from the default run). docs/interaction-architecture.md target: the
// sieve updates within 50 ms of a threshold move. Measured in the page, from the keydown that
// moves the handle to the next frame after the sieve's count changes. Asserted: median and p95
// < 50 ms both on this machine and at 4× CPU throttle (docs/ui-decisions.md has the history).

async function measure(page: import("@playwright/test").Page, rate: number): Promise<{ n: number; median: number; p95: number; max: number }> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate });
  await page.getByRole("slider", { name: /ROIC/ }).focus();
  const samples = await page.evaluate(async () => {
    const sieve = document.querySelector('[aria-label^="Sieve"]') as HTMLElement;
    const handle = document.activeElement as HTMLElement;
    const out: number[] = [];
    for (let k = 0; k < 40; k++) {
      const before = sieve.innerText;
      const key = k % 20 < 10 ? "ArrowLeft" : "ArrowRight";
      const t0 = performance.now();
      handle.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
      const changed = await new Promise<boolean>((resolve) => {
        const deadline = t0 + 500;
        const tick = () => {
          if (sieve.innerText !== before) return resolve(true);
          if (performance.now() > deadline) return resolve(false);
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
      if (changed) out.push(performance.now() - t0);
      await new Promise((r) => setTimeout(r, 30));
    }
    return out;
  });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
  samples.sort((a, b) => a - b);
  const q = (x: number) => samples[Math.min(samples.length - 1, Math.floor(x * samples.length))] ?? Number.NaN;
  return { n: samples.length, median: q(0.5), p95: q(0.95), max: samples.at(-1) ?? Number.NaN };
}

test("@perf dragging a threshold updates the sieve within 50 ms", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.locator("tbody tr[data-index]").first()).toBeVisible();
  await page.getByRole("button", { name: "Expand ROIC" }).click();
  await expect(page.getByRole("slider", { name: /ROIC/ })).toBeVisible();
  await page.waitForTimeout(1500); // snapshot and first server answer settle

  // Times include up to one frame of rAF polling (~17 ms).
  const fast = await measure(page, 1);
  const slow = await measure(page, 4);
  const line = (r: typeof fast) => `n=${r.n} median=${r.median.toFixed(1)} ms p95=${r.p95.toFixed(1)} ms max=${r.max.toFixed(1)} ms`;
  console.log(`drag → sieve, this machine: ${line(fast)}`);
  console.log(`drag → sieve, 4× CPU throttle: ${line(slow)}`);
  expect(fast.n).toBeGreaterThan(20);
  expect(fast.p95).toBeLessThan(50);
  expect(slow.median).toBeLessThan(50);
  expect(slow.p95).toBeLessThan(50);
});
