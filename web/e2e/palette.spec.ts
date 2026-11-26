import { expect, test } from "@playwright/test";

const palette = (page: import("@playwright/test").Page) => page.getByRole("dialog", { name: "Search and commands" });

test.beforeEach(async ({ page }) => {
  await page.goto("/?mock=ok");
  await expect(page.locator("tbody tr[data-index]").first()).toBeVisible();
});

test("/ opens the palette; a ticker opens the drawer, which survives a reload", async ({ page }) => {
  await page.keyboard.press("/");
  const box = palette(page).getByRole("combobox");
  await expect(box).toBeFocused();
  await box.fill("SYN0042");
  await expect(palette(page).getByRole("option").first()).toContainText("SYN0042");
  await page.keyboard.press("Enter");
  await expect(palette(page)).toBeHidden();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toContainText("SYN0042");
  await expect(page).toHaveURL(/[?&]t=SYN0042&d=1/);

  await page.reload();
  await expect(page.getByRole("dialog")).toContainText("SYN0042");
  await expect(page.getByRole("dialog")).toBeFocused(); // the drawer takes focus once it's open
  await page.keyboard.press("Escape");
  await expect(page).not.toHaveURL(/d=1/);
  await expect(page).toHaveURL(/t=SYN0042/); // still the selected row
});

test("⌘K / Ctrl+K opens it even while typing; ⌘Enter opens the full page", async ({ page }) => {
  await page.keyboard.press("ControlOrMeta+k");
  await palette(page).getByRole("combobox").fill("SYN0042");
  await expect(palette(page).getByRole("option").first()).toContainText("SYN0042");
  await page.keyboard.press("ControlOrMeta+Enter");
  await expect(page).toHaveURL(/\/company\/SYN0042/);
});

test("runs commands: apply a preset, add a filter", async ({ page }) => {
  await page.keyboard.press("/");
  await palette(page).getByRole("combobox").fill("quality comp");
  await expect(palette(page).getByRole("option").first()).toContainText("Apply preset: Quality compounders");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");

  await page.keyboard.press("/");
  await palette(page).getByRole("combobox").fill("dividend yield");
  await palette(page).getByRole("option", { name: /Add filter: Dividend yield/ }).click();
  await expect(page.getByRole("textbox", { name: /Dividend yield threshold/ })).toBeVisible();
});

test("no match says so; Esc closes and returns focus", async ({ page }) => {
  const trigger = page.getByRole("button", { name: /Search/ }).first();
  await trigger.click();
  await palette(page).getByRole("combobox").fill("zzzzqq");
  await expect(palette(page)).toContainText("No company or command matches");
  await page.keyboard.press("Escape");
  await expect(palette(page)).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("density lives in Settings", async ({ page }) => {
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("menuitemradio", { name: "Comfortable rows" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "comfortable");
});
