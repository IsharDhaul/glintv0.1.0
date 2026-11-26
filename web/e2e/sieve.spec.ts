import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("list", { name: /Sieve/ }).getByRole("listitem")).toHaveCount(6); // universe + 5 filters
});

test("stages say what they kept, failed and lost to missing data; one removes the most", async ({ page }) => {
  const sieve = page.getByRole("list", { name: /Sieve/ });
  await expect(sieve.getByRole("button", { name: /Removes the most\.$/ })).toHaveCount(1);
  await expect(sieve.getByRole("button", { name: /^Universe: [\d,]+ companies, [\d,]+ outside the universe/ })).toBeVisible();
  await expect(sieve.getByRole("button", { name: /^ROIC ≥ 15\.0%: [\d,]+ kept, [\d,]+ failed, [\d,]+ had no data\./ })).toBeVisible();
  await expect(sieve).toContainText("removes the most");
  await expect(sieve).toContainText("outside the universe");
});

test("selecting a stage lists the companies it removed; Include moves the threshold", async ({ page }) => {
  const sieve = page.getByRole("list", { name: /Sieve/ });
  const roic = sieve.getByRole("button", { name: /^ROIC ≥ 15\.0%/ });
  await roic.click();
  await expect(roic).toHaveAttribute("aria-expanded", "true");
  const panel = page.getByRole("region", { name: /Companies removed by ROIC/ });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("listitem").first()).toContainText(/SYN\d{4}/);

  const include = panel.getByRole("button", { name: /^Include \([\d,]+ results\)/ }).first();
  const preview = Number((await include.innerText()).match(/\(([\d,]+) results\)/)?.[1]?.replace(/,/g, ""));
  await include.click();
  // The threshold moved below 15%, and the result count is the one the button promised.
  await expect(sieve.getByRole("button", { name: /^ROIC ≥ 1[0-4]\.\d%/ })).toBeVisible();
  await expect(page.getByText(new RegExp(`^${preview.toLocaleString("en-US")} compan`))).toBeVisible();
});

test("companies removed for missing data offer to let missing values pass", async ({ page }) => {
  await page.getByRole("list", { name: /Sieve/ }).getByRole("button", { name: /^ROIC ≥ 15\.0%/ }).click();
  const panel = page.getByRole("region", { name: /Companies removed by ROIC/ });
  await expect(panel).toContainText(/[\d,]+ had no ROIC/);
  await panel.getByRole("button", { name: "Let missing values pass" }).first().click();
  await page.getByRole("button", { name: "Expand ROIC" }).click();
  await expect(page.getByRole("checkbox", { name: "Missing values pass" })).toBeChecked();
});

test("Edit this filter focuses its row; the universe stage goes to the universe rules", async ({ page }) => {
  const sieve = page.getByRole("list", { name: /Sieve/ });
  await sieve.getByRole("button", { name: /^Gross margin ≥ 40\.0%/ }).click();
  await page.getByRole("button", { name: "Edit this filter" }).click();
  await expect(page.locator("#filter-1")).toBeFocused();
  await sieve.getByRole("button", { name: /^Universe/ }).click();
  await expect(page.locator("#universe-chips")).toBeFocused();
});

test("labels come from format.ts (3 significant figures)", async ({ page }) => {
  await page.getByRole("button", { name: "Add filter" }).click();
  await page.getByRole("combobox", { name: "Search metrics" }).fill("market cap");
  await page.keyboard.press("Enter");
  await page.getByRole("combobox", { name: /Comparator for Market cap/ }).selectOption("gte");
  await page.getByRole("textbox", { name: "Market cap threshold" }).fill("1.5B");
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("Market cap ≥ $1.50B");
});
