import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

// WT-05 step 13: the brief's scenario end to end in mock mode: load, add a filter, apply a
// preset, open the drawer, export CSV, reload the share URL.

test("load → filter → preset → drawer → CSV → share URL", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);

  // Load
  await page.goto("/?mock=ok");
  await expect(page.getByTestId("synthetic-banner")).toBeVisible();
  await expect(page.locator("tbody tr[data-index]").first()).toContainText("SYN");

  // Add a filter
  await page.keyboard.press("f");
  await page.getByRole("combobox", { name: "Search metrics" }).fill("roic");
  await page.keyboard.press("Enter");
  await page.getByRole("textbox", { name: "ROIC threshold" }).fill("20");
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 20.0%");

  // Apply a preset (replaces the screen)
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("Gross margin ≥ 40.0%");
  await expect(page.getByRole("list", { name: /Sieve/ })).not.toContainText("ROIC ≥ 20.0%");

  // Open the drawer
  await page.locator("tbody tr[data-index]").first().click();
  await expect(page.getByRole("dialog").getByRole("region", { name: "Screen check" })).toBeVisible();
  await page.keyboard.press("Escape");

  // Export CSV
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^glint-quality-compounders-\d{4}-\d{2}-\d{2}\.csv$/);
  const csv = await readFile((await file.path()) as string, "utf8");
  const [header, ...lines] = csv.trim().split("\n");
  const cols = (header ?? "").split(",");
  expect(cols.slice(0, 4)).toEqual(["ticker", "name", "rank_score", "sector"]); // ranked: Score follows the name
  for (const c of ["roic", "gross_margin", "rank_score", "flag_count", "data_coverage", "as_of_fundamentals", "as_of_prices", "notes"]) {
    expect(cols, c).toContain(c);
  }
  expect(lines.length).toBeGreaterThan(0);
  expect(lines[0]).toMatch(/^SYN/);
  // Storage units, not display strings: 0.15, never "15.0%".
  expect(csv).not.toMatch(/\d%/);

  // Reload the share URL
  await page.getByRole("button", { name: "Copy share link" }).click();
  const link = await page.evaluate(() => navigator.clipboard.readText());
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "Quality compounders" })).toBeVisible();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("FCF margin ≥ 10.0%");
});
