import { expect, test, type Page } from "@playwright/test";

/** The table renders from a deferred copy: wait until it shows the screen's final count. */
async function tableCaughtUp(page: Page) {
  const final = (await page.getByRole("list", { name: /Sieve/ }).getByRole("listitem").last().innerText()).match(/\n(\d+)\n/)?.[1];
  await expect(page.getByRole("region", { name: "Results" }).getByText(new RegExp(`^${final} compan`))).toBeVisible();
}

test("drawer: screen check, flags, history, metrics by category, sources", async ({ page }) => {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await tableCaughtUp(page);
  await page.locator("tbody tr[data-index]").first().click();

  const drawer = page.getByRole("dialog");
  const why = drawer.getByRole("region", { name: "Screen check" });
  await expect(why).toContainText("In the screen's universe");
  await expect(why).toContainText("ROIC ≥ 15.0%");
  await expect(why).toContainText(/Passed|Failed/);
  // A result row passes every filter: the drawer's header says so.
  await expect(drawer.locator("header")).toContainText(/Passes all \d+/);
  await expect(why.getByRole("heading")).toHaveText("This screen's metrics");
  await expect(drawer.getByRole("region", { name: "Flags" })).toBeVisible();
  await expect(drawer.getByRole("region", { name: "History" }).getByRole("figure", { name: /FY/ }).first()).toBeVisible();
  await drawer.getByText("All metrics", { exact: true }).click();
  await expect(drawer.getByRole("group", { name: "All metrics" })).toContainText("Profitability");

  const sources = drawer.getByRole("region", { name: "Sources" });
  await expect(sources).toContainText(/0009999999-\d{2}-\d{6}/);
  await expect(sources.getByRole("link")).toHaveCount(0); // synthetic accessions are never linked
});

test("company page is shareable and keeps the screen for why-it-passed", async ({ page }) => {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await tableCaughtUp(page);
  const ticker = (await page.locator("tbody tr[data-index]").first().getByRole("rowheader").textContent())?.trim() ?? "";
  await page.locator("tbody tr[data-index]").first().click();
  await page.getByRole("link", { name: "Full page" }).click();

  await expect(page).toHaveURL(new RegExp(`/company/${ticker}\\?s=`));
  await expect(page.getByRole("heading", { level: 1 })).toContainText(ticker);
  await expect(page.getByRole("region", { name: "Screen check" })).toContainText("Gross margin ≥ 40.0%");
  await expect(page.getByRole("link", { name: /Back to Quality compounders/ })).toBeVisible();
  // Every metric carries its sector median and percentile from the build's columns.
  const all = page.getByRole("region", { name: "All metrics" });
  await expect(all).toContainText("Profitability");
  await expect(all.getByText(/^median /).first()).toBeVisible();
  await expect(all.getByText(/^p\d{1,3},/).first()).toBeVisible();
});

test("unknown ticker shows the API's error", async ({ page }) => {
  await page.goto("/company/NOPE?mock=ok");
  await expect(page.getByRole("alert").filter({ hasText: "No company" })).toBeVisible();
});

test("drawer: price and market cap up top; j/k flick through results without closing", async ({ page }) => {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await tableCaughtUp(page);
  const rows = page.locator("tbody tr[data-index]");
  const first = ((await rows.nth(0).getByRole("rowheader").innerText()).match(/SYN\d{4}/) ?? [""])[0];
  const second = ((await rows.nth(1).getByRole("rowheader").innerText()).match(/SYN\d{4}/) ?? [""])[0];
  await rows.first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toContainText("Price");
  await expect(drawer).toContainText("Market cap");
  await expect(drawer).toContainText(/1 of \d+/);
  await expect(drawer).toBeFocused();
  await page.keyboard.press("j");
  await expect(drawer.getByRole("heading", { level: 2 })).toContainText(second);
  await expect(drawer).toContainText(/2 of \d+/);
  await expect(page).toHaveURL(new RegExp(`t=${second}`));
  await page.keyboard.press("k");
  await expect(drawer.getByRole("heading", { level: 2 })).toContainText(first);
});

