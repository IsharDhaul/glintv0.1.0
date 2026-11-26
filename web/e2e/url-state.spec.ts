import { expect, test, type Page } from "@playwright/test";

const sieve = (page: Page) => page.getByRole("list", { name: /Sieve/ });

async function addRoic(page: Page, threshold: string) {
  await page.getByRole("button", { name: "Add filter" }).click();
  await page.getByRole("combobox", { name: "Search metrics" }).fill("roic");
  await page.keyboard.press("Enter");
  await page.getByRole("textbox", { name: "ROIC threshold" }).fill(threshold);
}

test("a fresh screener has a clean URL; edits land in ?s= and survive a reload", async ({ page }) => {
  await page.goto("/?mock=ok");
  await expect(page.locator("tbody tr[data-index]").first()).toBeVisible();
  expect(new URL(page.url()).searchParams.get("s")).toBeNull();

  await addRoic(page, "15");
  await expect(page).toHaveURL(/[?&]s=/);
  await expect(page).toHaveURL(/mock=ok/); // other params are kept
  await page.reload();
  await expect(sieve(page)).toContainText("ROIC ≥ 15.0%");
  await expect(page.getByRole("textbox", { name: "ROIC threshold" })).toHaveValue("15");
});

test("Back undoes a filter change and Forward redoes it", async ({ page }) => {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(sieve(page)).toContainText("Gross margin ≥ 40.0%");
  await expect(page).toHaveURL(/[?&]s=/);
  const presetUrl = page.url();

  await page.getByRole("button", { name: "Remove filter: Gross margin" }).click();
  await expect(sieve(page)).not.toContainText("Gross margin");
  await expect.poll(() => page.url()).not.toBe(presetUrl);

  await page.goBack();
  await expect(page).toHaveURL(presetUrl);
  await expect(sieve(page)).toContainText("Gross margin ≥ 40.0%");
  await expect(page.getByRole("button", { name: "Remove filter: Gross margin" })).toBeVisible();

  await page.goForward();
  await expect(sieve(page)).not.toContainText("Gross margin");

  // Back twice returns to the empty screen (the preset load was its own entry).
  await page.goBack();
  await page.goBack();
  await expect(page.getByText(/Add a filter to start narrowing/)).toBeVisible();
});

test("typing a threshold is one history entry, not one per keystroke", async ({ page }) => {
  await page.goto("/?mock=ok");
  await expect(page.locator("tbody tr[data-index]").first()).toBeVisible();
  const before = await page.evaluate(() => history.length);
  await addRoic(page, "");
  await page.getByRole("textbox", { name: "ROIC threshold" }).pressSequentially("12.5", { delay: 40 });
  await expect(sieve(page)).toContainText("ROIC ≥ 12.5%");
  await page.waitForTimeout(600);
  expect(await page.evaluate(() => history.length)).toBeLessThanOrEqual(before + 2); // add filter, then the value
});

test("Share copies a clean link that opens the same screen", async ({ page, context, browserName }) => {
  test.skip(browserName !== "chromium", "clipboard permissions are Chromium-only here");
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(sieve(page)).toContainText("ROIC ≥ 15.0%");
  await page.getByRole("button", { name: "Copy share link" }).click();
  await expect(page.getByText("Link copied.")).toBeVisible();
  const link = await page.evaluate(() => navigator.clipboard.readText());
  expect(link).toMatch(/^http:\/\/localhost:\d+\/\?s=/);
  expect(link).not.toContain("mock=");

  const other = await context.newPage();
  await other.goto(link);
  await expect(other.getByRole("heading", { name: "Quality compounders" })).toBeVisible();
  await expect(other.getByRole("list", { name: /Sieve/ })).toContainText("FCF margin ≥ 10.0%");
});

test("an unreadable share link is reported and left in the address bar (review fix)", async ({ page }) => {
  await page.goto("/?mock=ok&s=not-a-screen");
  await expect(page.getByRole("alert").filter({ hasText: "couldn't be read" })).toBeVisible();
  await expect(page.getByText(/Add a filter to start narrowing/)).toBeVisible();
  await page.waitForTimeout(800); // past the URL debounce
  expect(new URL(page.url()).searchParams.get("s")).toBe("not-a-screen");
});
