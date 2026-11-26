import { expect, test, type Page } from "@playwright/test";

// Phone layout (docs/ui-spec.md §2, Phase 4.12): results first, filters behind a sticky bar.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

async function loadQualityCompounders(page: Page) {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("button", { name: "Filters (5)" })).toBeVisible();
}

test("results come first: a summary bar, then a compact table with one chosen metric", async ({ page }) => {
  await loadQualityCompounders(page);
  await expect(page.getByText(/^5 filters, \d+ results?$/)).toBeVisible();
  await expect(page.getByText(/in the universe; .* removes the most\./)).toBeVisible();
  // No rail and no sieve row on the page itself.
  await expect(page.getByRole("complementary", { name: "Screen definition" })).toHaveCount(0);
  const results = page.getByRole("region", { name: "Results" });
  await expect(results.locator("tbody tr[data-index]").first()).toBeInViewport();
  const headers = results.getByRole("columnheader");
  await expect(headers).toHaveText([/Ticker/, /Name/, /Score/, /ROIC/]);
  await results.getByRole("combobox", { name: "Metric column" }).selectOption({ label: "Gross margin" });
  await expect(headers).toHaveText([/Ticker/, /Name/, /Score/, /Gross margin/]);
  // Universe honesty survives the fold: the excluded count is in the summary.
  await expect(page.getByRole("button", { name: /^Universe \d+ rules/ })).toBeVisible();
  await expect(page.getByText(/^\d+ excluded$/)).toBeVisible();
  // Near misses start collapsed.
  await expect(page.getByRole("button", { name: /Near misses/ })).toHaveAttribute("aria-expanded", "false");
});

test("Filters opens a bottom sheet with the sieve and the filters; Esc closes it", async ({ page }) => {
  await loadQualityCompounders(page);
  const opener = page.getByRole("button", { name: "Filters (5)" });
  await opener.click();
  const sheet = page.getByRole("dialog", { name: "Edit the screen" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await expect(sheet.getByRole("group", { name: /Filter: ROIC/ })).toBeVisible();
  await expect(sheet.getByRole("button", { name: /^Show \d+ results?$/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test("tapping or swiping left on a row opens the drawer full width", async ({ page }) => {
  await loadQualityCompounders(page);
  const row = page.locator("tbody tr[data-index]").first();
  await row.tap();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  expect((await drawer.boundingBox())?.width).toBeGreaterThan(380);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  const second = page.locator("tbody tr[data-index]").nth(1);
  const ticker = ((await second.getByRole("rowheader").innerText()).match(/SYN\d{4}/) ?? [""])[0];
  const box = (await second.boundingBox())!;
  const y = box.y + box.height / 2;
  await second.dispatchEvent("touchstart", { touches: [{ identifier: 1, clientX: box.x + 300, clientY: y }] });
  await second.dispatchEvent("touchend", { changedTouches: [{ identifier: 1, clientX: box.x + 120, clientY: y + 4 }] });
  await expect(page.getByRole("dialog").getByRole("heading", { level: 2 })).toContainText(ticker);
});

test("the header band is one row: nav folds into a menu", async ({ page }) => {
  await page.goto("/presets?mock=ok");
  await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("menuitem", { name: "Metrics" }).click();
  await expect(page).toHaveURL(/\/metrics/);
});
