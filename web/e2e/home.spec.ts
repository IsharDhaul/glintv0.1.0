import { expect, test } from "@playwright/test";

test("screener layout: banner, as-of line, universe, sieve, results, drawer", async ({ page }) => {
  await page.goto("/?mock=ok");
  await expect(page.getByTestId("synthetic-banner")).toHaveText("Synthetic data: these are not real companies");
  await expect(page.getByText(/Filings as of .* ET\. Prices at the close of/)).toBeVisible();
  // The universe sits behind one control; the excluded count is always visible beside it.
  await expect(page.getByText(/^\d+ excluded$/)).toBeVisible();
  await page.getByRole("button", { name: /^Universe \d+ rules/ }).click();
  const rules = page.getByRole("list", { name: "Universe" });
  await expect(rules).toContainText("Operating companies only");
  await expect(rules).toContainText("Trades at least $1M a day");
  await expect(rules.getByRole("img", { name: /^Locked: Glint only screens companies whose filings include XBRL/ })).toBeVisible();
  await rules.getByRole("button", { name: "Remove universe rule: Trades at least $1M a day" }).click();
  await expect(rules).not.toContainText("Trades at least");
  await page.keyboard.press("Escape");
  await expect(rules).toBeHidden();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("Universe");

  const firstRow = page.locator("tbody tr").first();
  await expect(firstRow).toContainText("SYN");
  await firstRow.click();
  await expect(page.getByRole("dialog")).toContainText("Synthetic Co");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("a preset loads its filters, sieve steps and ranking", async ({ page }) => {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("heading", { name: "Quality compounders" })).toBeVisible();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await expect(page.getByRole("region", { name: "Ranked by" })).toContainText("ROIC");
  await expect(page.getByText(/Near misses/)).toBeVisible();
});

test("API down and no build show their states", async ({ page }) => {
  await page.goto("/?mock=down");
  await expect(page.getByRole("alert").filter({ hasText: "Can't reach the Glint API" }).first()).toBeVisible();
  await page.goto("/?mock=nobuild");
  await expect(page.getByRole("alert").filter({ hasText: "glint refresh" }).first()).toBeVisible();
  await page.goto("/?mock=ok");
});
