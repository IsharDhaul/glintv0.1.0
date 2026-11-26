import { expect, test } from "@playwright/test";

test("kitchen sink: banner, density and drawer", async ({ page }) => {
  await page.goto("/dev/kitchen-sink");
  await expect(page.getByTestId("synthetic-banner")).toBeVisible();

  const html = page.locator("html");
  // One theme only: nothing sets data-theme.
  await expect(html).not.toHaveAttribute("data-theme", /.+/);
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("menuitemradio", { name: "Comfortable rows" }).click();
  await expect(html).toHaveAttribute("data-density", "comfortable");

  // The preference survives a reload (applied before paint by the inline script).
  await page.reload();
  await expect(html).toHaveAttribute("data-density", "comfortable");

  await page.getByRole("row", { name: /SYNA/ }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toContainText("Synthetic Alpha Holdings");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});
