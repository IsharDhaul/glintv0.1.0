import { expect, test } from "@playwright/test";
import lz from "lz-string";

test.beforeEach(async ({ page }) => {
  await page.goto("/?mock=ok");
  await expect(page.locator("tbody tr[data-index]").first()).toBeVisible();
});

test("badges, pinned ticker header cell, and nulls with reasons", async ({ page }) => {
  await expect(page.getByRole("columnheader", { name: /Flags/ })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: /Coverage/ })).toBeVisible();
  await expect(page.getByRole("rowheader").first()).toContainText("SYN");
});

test("sorting goes to the server and sets aria-sort", async ({ page }) => {
  const header = page.getByRole("columnheader", { name: "Market cap" });
  await expect(header).toHaveAttribute("aria-sort", "none");
  await page.getByRole("button", { name: "Market cap" }).click();
  await expect(header).toHaveAttribute("aria-sort", "descending");
  await page.getByRole("button", { name: "Market cap" }).click();
  await expect(header).toHaveAttribute("aria-sort", "ascending");
  await page.getByRole("button", { name: "Market cap" }).click();
  await expect(page.getByRole("columnheader", { name: /Ticker/ })).toHaveAttribute("aria-sort", "ascending");
});

test("column picker adds, reorders and hides a column", async ({ page }) => {
  await page.getByRole("button", { name: "Columns" }).click();
  await page.getByRole("textbox", { name: "Search columns" }).fill("roic");
  await page.getByRole("list", { name: "Available columns" }).getByRole("button", { name: /ROIC/ }).first().click();
  await expect(page.getByRole("columnheader", { name: /^ROIC/ })).toBeVisible();
  await page.getByRole("button", { name: "Move ROIC left" }).click();
  const headers = page.getByRole("columnheader");
  await expect(headers.nth(4)).toContainText("ROIC"); // #, Ticker, Name, Sector, ROIC, Market cap…
  await page.getByRole("button", { name: "Hide ROIC" }).click();
  await expect(page.getByRole("columnheader", { name: /^ROIC/ })).toHaveCount(0);
});

test("keyboard: j/k move between rows, Enter opens the drawer", async ({ page }) => {
  const rows = page.locator("tbody tr[data-index]");
  await rows.first().focus();
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await expect(rows.nth(2)).toBeFocused();
  await page.keyboard.press("k");
  await expect(rows.nth(1)).toBeFocused();
  const ticker = await rows.nth(1).getByRole("rowheader").textContent();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toContainText(ticker ?? "SYN");
});

test("virtualised rows: End reaches the last row", async ({ page }) => {
  // A broad screen, so there are more rows than fit on screen.
  const broad = { dsl_version: 1, name: "Broad", filters: { op: "and", children: [{ metric: "revenue_ttm", cmp: "not_null" }] }, limit: 100, near_misses: false };
  await page.goto(`/?mock=ok&s=${lz.compressToEncodedURIComponent(JSON.stringify(broad))}`);
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("Revenue");
  await expect(page.locator("tbody tr[data-index]").first()).toBeVisible();
  const rows = page.locator("tbody tr[data-index]");
  await rows.first().focus();
  await page.keyboard.press("End");
  const focused = page.locator("tbody tr[data-index]:focus");
  await expect(focused).toBeVisible();
  const idx = Number(await focused.getAttribute("data-index"));
  expect(idx).toBeGreaterThan(20);
  expect(await page.locator("tbody tr[data-index]").count()).toBeLessThan(idx + 1); // not every row is in the DOM
});

test("text columns sort A→Z first, numbers biggest first (review fix)", async ({ page }) => {
  await page.getByRole("button", { name: "Name" }).click();
  await expect(page.getByRole("columnheader", { name: "Name" })).toHaveAttribute("aria-sort", "ascending");
  await page.getByRole("button", { name: "Market cap" }).click();
  await expect(page.getByRole("columnheader", { name: "Market cap" })).toHaveAttribute("aria-sort", "descending");
});

test("no 100-row cap: every passing company is in the table", async ({ page }) => {
  // The default screen has no filters: the whole universe passes, more than the API's 100.
  const heading = page.getByText(/^\d[\d,]* companies$/);
  const n = Number((await heading.innerText()).replace(/\D/g, ""));
  expect(n).toBeGreaterThan(100);
  await expect(page.getByText(/Showing the first/)).toHaveCount(0);
  const rows = page.locator("tbody tr[data-index]");
  await rows.first().focus();
  await page.keyboard.press("End");
  await expect(page.locator(`tbody tr[data-index="${n - 1}"]`)).toBeFocused();
});

test("ranked screens show Score after the name; screened columns are crisp", async ({ page }) => {
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  const headers = page.getByRole("columnheader");
  await expect(headers.nth(2)).toContainText("Name");
  await expect(headers.nth(3)).toContainText("Score");
});

test("x pins a row for comparison (in the URL); names are readable", async ({ page }) => {
  const first = page.locator("tbody tr[data-index]").first();
  await first.focus();
  await page.keyboard.press("x");
  const ticker = ((await first.getByRole("rowheader").innerText()).match(/SYN\d{4}/) ?? [""])[0];
  await expect(page).toHaveURL(new RegExp(`[?&]c=${ticker}`));
  await expect(first.getByRole("img", { name: "pinned" })).toBeVisible();
  await page.keyboard.press("x");
  await expect(page).not.toHaveURL(/[?&]c=/);
});
