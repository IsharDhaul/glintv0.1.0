import { expect, test, type Page } from "@playwright/test";

/** The table renders from a deferred copy: wait until it shows the screen's final count. */
async function tableCaughtUp(page: Page) {
  const final = (await page.getByRole("list", { name: /Sieve/ }).getByRole("listitem").last().innerText()).match(/\n(\d+)\n/)?.[1];
  await expect(page.getByRole("region", { name: "Results" }).getByText(new RegExp(`^${final} compan`))).toBeVisible();
}

const tickerOf = async (page: Page, i: number) =>
  ((await page.locator("tbody tr[data-index]").nth(i).getByRole("rowheader").innerText()).match(/SYN\d{4}/) ?? [""])[0];

test.beforeEach(async ({ page }) => {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await tableCaughtUp(page);
});

test("pinned rows fill the tray; Compare shows each filter side by side with percentiles", async ({ page }) => {
  const rows = page.locator("tbody tr[data-index]");
  const a = await tickerOf(page, 0);
  const b = await tickerOf(page, 1);
  const tray = page.getByRole("region", { name: "Compare tray" });
  await expect(tray).toHaveCount(0);

  await rows.nth(0).focus();
  await page.keyboard.press("x");
  await expect(tray).toContainText(a);
  await expect(tray.getByRole("button", { name: "Pin another to compare" })).toBeDisabled();
  await rows.nth(1).focus();
  await page.keyboard.press("x");
  await expect(page).toHaveURL(new RegExp(`[?&]c=${a}%2C${b}|[?&]c=${a},${b}`));

  await tray.getByRole("button", { name: "Compare 2" }).click();
  const sheet = page.getByRole("dialog", { name: "Compare 2 companies" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("columnheader", { name: new RegExp(a) })).toBeVisible();
  await expect(sheet.getByRole("columnheader", { name: new RegExp(b) })).toBeVisible();
  await expect(sheet.getByRole("rowheader", { name: "ROIC ≥ 15.0%" })).toBeVisible();
  await expect(sheet.getByRole("row", { name: /Screen check/ })).toContainText("Passes all");
  await expect(sheet.getByText(/^p\d{1,3},/).first()).toBeVisible();

  // Esc closes and returns focus; the ticker opens its drawer.
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await page.keyboard.press("c");
  await expect(sheet).toBeVisible();
  await sheet.getByRole("button", { name: b, exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { level: 2 })).toContainText(b);
});

test("the tray's chips unpin; Clear empties it; pins survive a reload", async ({ page }) => {
  const rows = page.locator("tbody tr[data-index]");
  const a = await tickerOf(page, 0);
  await rows.nth(0).focus();
  await page.keyboard.press("x");
  await rows.nth(1).focus();
  await page.keyboard.press("x");
  await page.reload();
  const tray = page.getByRole("region", { name: "Compare tray" });
  await expect(tray).toContainText(a);
  await tray.getByRole("button", { name: `Unpin ${a}` }).click();
  await expect(tray).not.toContainText(a);
  await tray.getByRole("button", { name: "Clear" }).click();
  await expect(tray).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]c=/);
});

test("the drawer pins with x", async ({ page }) => {
  const a = await tickerOf(page, 0);
  await page.locator("tbody tr[data-index]").first().click();
  await expect(page.getByRole("dialog")).toBeFocused();
  await page.keyboard.press("x");
  await expect(page.getByRole("region", { name: "Compare tray" })).toContainText(a);
});

test("quick pins all land (the URL is read fresh, not from the last render)", async ({ page }) => {
  const rows = page.locator("tbody tr[data-index]");
  const t = [await tickerOf(page, 0), await tickerOf(page, 1), await tickerOf(page, 2)];
  for (const i of [0, 1, 2]) {
    await rows.nth(i).focus();
    await page.keyboard.press("x");
  }
  const tray = page.getByRole("region", { name: "Compare tray" });
  for (const x of t) await expect(tray).toContainText(x);
  await expect(tray.getByRole("button", { name: "Compare 3" })).toBeEnabled();
});
