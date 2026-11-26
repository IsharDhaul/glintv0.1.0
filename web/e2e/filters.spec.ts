import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/?mock=ok");
  await expect(page.locator("tbody tr").first()).toBeVisible();
});

test("add a filter from the keyboard and type a threshold in display units", async ({ page }) => {
  await page.keyboard.press("f");
  const picker = page.getByRole("dialog", { name: "Add a filter" });
  await expect(picker).toBeVisible();
  await page.getByRole("combobox", { name: "Search metrics" }).fill("roic");
  await expect(picker).toContainText("nopat_ttm / average invested capital"); // formula preview
  await page.keyboard.press("Enter");
  await expect(picker).toBeHidden();

  await expect(page.getByText("Enter a value to apply this filter.")).toBeVisible();
  await page.getByRole("textbox", { name: "ROIC threshold" }).fill("15");
  const sieve = page.getByRole("list", { name: /Sieve/ });
  await expect(sieve).toContainText("ROIC ≥ 15.0%");
  await expect(page.getByText(/\d+ kept, [\d,]+ failed, [\d,]+ had no data/)).toBeVisible();
  await expect(page.getByRole("figure", { name: /ROIC distribution/ })).toBeVisible();
});

test("comparators are limited to the metric's unit and between takes two bounds", async ({ page }) => {
  await page.getByRole("button", { name: "Add filter" }).click();
  await page.getByRole("combobox", { name: "Search metrics" }).fill("P/E");
  await page.getByRole("option", { name: /P\/E \(TTM\)/ }).click();
  const cmp = page.getByRole("combobox", { name: /Comparator for P\/E/ });
  await expect(cmp).toHaveValue("lte"); // lower is better
  await expect(cmp.locator("option")).not.toContainText(["is one of"]);
  await cmp.selectOption("between");
  await page.getByRole("textbox", { name: /lower bound/ }).fill("8");
  await page.getByRole("textbox", { name: /upper bound/ }).fill("20");
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("between 8.0x and 20.0x");
});

test("invalid input is flagged and not applied", async ({ page }) => {
  await page.keyboard.press("f");
  await page.getByRole("combobox", { name: "Search metrics" }).fill("gross margin");
  await page.keyboard.press("Enter");
  await page.getByRole("textbox", { name: "Gross margin threshold" }).fill("abc");
  await expect(page.getByText("Not a number")).toBeVisible();
  await expect(page.getByRole("list", { name: /Sieve/ })).not.toContainText("Gross margin");
});

test("OR group with two conditions runs as one sieve step", async ({ page }) => {
  await page.getByRole("button", { name: "Add OR group" }).click();
  await page.getByRole("combobox", { name: "Search metrics" }).fill("revenue growth");
  await page.keyboard.press("Enter");
  await page.getByRole("textbox", { name: /Revenue growth.*threshold/ }).fill("5");
  await page.getByRole("button", { name: "Add to this group" }).click();
  await page.getByRole("combobox", { name: "Search metrics" }).fill("operating margin");
  await page.getByRole("option", { name: /^Operating margin$/ }).first().click();
  await page.getByRole("textbox", { name: /Operating margin threshold/ }).fill("10");
  const sieve = page.getByRole("list", { name: /Sieve/ });
  await expect(sieve).toContainText(" OR ");
  await expect(sieve.getByRole("listitem")).toHaveCount(2); // universe + one group step
  await page.getByRole("button", { name: /Expand Revenue growth/ }).click();
  await page.getByRole("checkbox", { name: "Missing values pass" }).first().check();
});

test("Esc closes the picker without adding anything", async ({ page }) => {
  await page.keyboard.press("f");
  await expect(page.getByRole("dialog", { name: "Add a filter" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Add a filter" })).toBeHidden();
  await expect(page.getByText(/Add a filter to start narrowing/)).toBeVisible();
});

test("a percentile above 100 says so instead of 'enter a value' (review fix)", async ({ page }) => {
  await page.keyboard.press("f");
  await page.getByRole("combobox", { name: "Search metrics" }).fill("gross margin");
  await page.keyboard.press("Enter");
  await page.getByRole("combobox", { name: /Comparator for Gross margin/ }).selectOption("pct_rank_gte");
  await page.getByRole("textbox", { name: /percentile/ }).fill("150");
  await expect(page.getByText("Enter a percentile from 0 to 100.")).toBeVisible();
});
