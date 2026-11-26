import lzString from "lz-string"; // CommonJS: no named exports under Node's ESM loader
import { expect, test } from "@playwright/test";

const { compressToEncodedURIComponent, decompressFromEncodedURIComponent } = lzString;

// WT-09 step 6: the §5.10 UI budgets on a real build. Opt-in (GLINT_E2E_PERF=1) and only against
// a production build (`npm run build && npm run start`, real mode): `next dev`, which the config
// starts by default, is several times slower and would fail them. "Apply a filter → table
// updated" is timed from the keystroke to the new total on screen (debounce, request, render).
// Scroll is measured on the largest table the API serves: the contract caps `limit` at 1,000
// rows, under the budget's 2,000 (decisions/WT-09.md).

const APPLY_BUDGET_MS = 500;
const MIN_FPS = 55; // 60 fps budget, less headless-timer jitter
const SCROLL_MS = 3_000;
const CHANGE_TIMEOUT_MS = 5_000;

test.skip(!process.env.GLINT_E2E_PERF, "UI timings: GLINT_E2E_PERF=1, against a production build");

// Two numbers per edit: input → "Updating…" shown (perceived), and input → the new total on screen
// (debounce 250 ms + request + render). On the real build: 2–5 ms and 321–433 ms
// (decisions/WT-09.md); before the 350 → 250 ms debounce cut the table took up to 612 ms.
test("apply a filter → pending at once, table updated under 500 ms", async ({ page }) => {
  await page.goto("/");
  const count = page.getByText(/^(Showing the first [\d,]+ of [\d,]+|[\d,]+ companies)$/);
  await expect(count).toBeVisible();
  const before = await count.textContent();

  await page.keyboard.press("f");
  await page.getByRole("combobox", { name: "Search metrics" }).fill("roic");
  await page.keyboard.press("Enter");
  const box = page.getByRole("textbox", { name: "ROIC threshold" });
  await box.fill("15");
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await expect(count).not.toHaveText(before ?? "");
  const settled = await count.textContent();

  // Timed in the page with a MutationObserver from the input event, so Playwright's polling
  // interval isn't part of either number.
  const updated: number[] = [];
  const pending: number[] = [];
  for (const v of ["20", "25", "30", "35", "40"]) {
    const prev = (await count.textContent()) ?? "";
    const handles = [await count.elementHandle(), await box.elementHandle()] as const;
    const changed = page.evaluate(
      ([[el, input], before, wait]) =>
        new Promise<{ pending: number; updated: number }>((done, fail) => {
          if (!el || !input) return fail(new Error("count or threshold box not found"));
          let start: number | null = null;
          let shown: number | null = null;
          input.addEventListener("input", () => (start = performance.now()), { once: true });
          const obs = new MutationObserver(() => {
            if (start === null) return; // a change from before this edit
            const now = performance.now();
            if (shown === null && document.querySelector('[data-testid="results-pending"]')) shown = now;
            if (el.textContent === before) return;
            obs.disconnect();
            done({ pending: (shown ?? now) - start, updated: now - start });
          });
          obs.observe(document.body, { characterData: true, childList: true, subtree: true });
          // Two thresholds can give the same count; fail with a reason instead of hanging.
          setTimeout(() => {
            obs.disconnect();
            fail(new Error(`count didn't change within ${wait} ms`));
          }, wait);
        }),
      [handles, prev, CHANGE_TIMEOUT_MS] as const,
    );
    await box.fill(v);
    const t = await changed;
    pending.push(Math.round(t.pending));
    updated.push(Math.round(t.updated));
    await expect(count).not.toHaveText(prev);
  }
  updated.sort((a, b) => a - b);
  pending.sort((a, b) => a - b);
  const summary = `pending shown ${pending.join(", ")} ms · table updated ${updated.join(", ")} ms`;
  test.info().annotations.push({ type: "apply_filter_ms", description: `${summary} (after "${settled}")` });
  console.log(`apply filter: ${summary}`);
  expect(pending[pending.length - 1]).toBeLessThan(100);
  expect(updated[updated.length - 1]).toBeLessThan(APPLY_BUDGET_MS);
});

test("scroll 1,000 rows at 60 fps", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await page.getByRole("button", { name: "Copy share link" }).click();
  const link = new URL(await page.evaluate(() => navigator.clipboard.readText()));
  const screen = JSON.parse(decompressFromEncodedURIComponent(link.searchParams.get("s") ?? "")) as Record<string, unknown>;
  const big = { ...screen, name: "All rows", filters: { op: "and", children: [] }, limit: 1000 };
  await page.goto(`/?s=${compressToEncodedURIComponent(JSON.stringify(big))}`);
  await expect(page.getByText(/^Showing the first 1,000 of [\d,]+$/)).toBeVisible();

  const frames = await page.getByTestId("results-scroll").evaluate(async (el, ms) => {
    // Position follows elapsed time, so slow frames skip rows instead of slowing the scroll.
    const max = el.scrollHeight - el.clientHeight;
    const gaps: number[] = [];
    const start = performance.now();
    let last = start;
    await new Promise<void>((done) => {
      const tick = (now: number) => {
        gaps.push(now - last);
        last = now;
        el.scrollTop = Math.min(1, (now - start) / ms) * max;
        if (now - start < ms) requestAnimationFrame(tick);
        else done();
      };
      requestAnimationFrame(tick);
    });
    return { gaps, reachedBottom: el.scrollTop + el.clientHeight >= el.scrollHeight - 2 };
  }, SCROLL_MS);

  const total = frames.gaps.reduce((a, b) => a + b, 0);
  const fps = (frames.gaps.length / total) * 1000;
  const worst = Math.max(...frames.gaps);
  const sorted = [...frames.gaps].sort((a, b) => a - b);
  const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? 0;
  const summary = `${fps.toFixed(1)} fps · p95 frame ${p95.toFixed(1)} ms · worst ${worst.toFixed(1)} ms · ${frames.gaps.length} frames`;
  test.info().annotations.push({ type: "scroll", description: summary });
  console.log(`scroll 1,000 rows: ${summary}`);
  expect(frames.reachedBottom).toBe(true);
  expect(fps).toBeGreaterThanOrEqual(MIN_FPS);
});
