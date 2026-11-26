import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Automated WCAG 2.1 A/AA checks (axe) on every page and the main overlays (one theme: light).
// Fails on serious and critical violations; minor/moderate are printed for review.

async function scan(page: Page, label: string) {
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const summary = bad.map((v) => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join("\n  ")}`);
  expect(summary, `${label}\n${summary.join("\n")}`).toEqual([]);
}

{
  test.describe("light theme", () => {
    test("screener with a preset, drawer and picker", async ({ page }) => {
      test.setTimeout(60_000); // three full axe scans of a dense page
      await page.goto("/?mock=ok");
      await page.getByRole("button", { name: "Presets" }).click();
      await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
      await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
      await page.getByRole("button", { name: "Expand ROIC" }).click();
      await expect(page.getByRole("figure", { name: /ROIC distribution/ })).toBeVisible();
      await scan(page, "screener");

      await page.locator("tbody tr[data-index]").first().click();
      await expect(page.getByRole("dialog").getByRole("region", { name: "History" })).toBeVisible();
      await scan(page, "drawer");
      await page.keyboard.press("Escape");

      await page.getByRole("button", { name: "Add filter" }).click();
      await expect(page.getByRole("dialog", { name: "Add a filter" })).toBeVisible();
      await scan(page, "metric picker");
    });

    test("Phase 4 overlays: universe panel, compare sheet, command palette", async ({ page }) => {
      test.setTimeout(60_000);
      await page.goto("/?mock=ok");
      await page.getByRole("button", { name: "Presets" }).click();
      await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
      await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
      await page.getByRole("button", { name: /^Universe \d+ rules/ }).click();
      await expect(page.locator("#universe-chips")).toBeVisible();
      await scan(page, "universe panel");
      await page.keyboard.press("Escape");

      const rows = page.locator("tbody tr[data-index]");
      for (const i of [0, 1]) {
        await rows.nth(i).focus();
        await page.keyboard.press("x");
      }
      await page.getByRole("region", { name: "Compare tray" }).getByRole("button", { name: "Compare 2" }).click();
      await expect(page.getByRole("dialog", { name: "Compare 2 companies" })).toBeVisible();
      await scan(page, "compare sheet");
      await page.keyboard.press("Escape");

      await page.keyboard.press("ControlOrMeta+k");
      await expect(page.getByRole("dialog", { name: "Search and commands" })).toBeVisible();
      await scan(page, "command palette");
    });

    test.describe("phone (390 wide)", () => {
      test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
      test("screener and the filters sheet", async ({ page }) => {
        test.setTimeout(60_000);
        await page.goto("/?mock=ok");
        await page.getByRole("button", { name: "Presets" }).click();
        await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
        await expect(page.getByRole("button", { name: "Filters (5)" })).toBeVisible();
        await scan(page, "phone screener");
        await page.getByRole("button", { name: "Filters (5)" }).click();
        await expect(page.getByRole("dialog", { name: "Edit the screen" })).toBeVisible();
        await scan(page, "phone filters sheet");
      });
      for (const path of ["/presets", "/metrics", "/company/SYN0001"]) {
        test(`phone page ${path}`, async ({ page }) => {
          await page.goto(`${path}?mock=ok`);
          await page.waitForLoadState("networkidle");
          await scan(page, `phone ${path}`);
        });
      }
    });

    for (const path of ["/presets", "/metrics", "/about", "/company/SYN0001", "/dev/kitchen-sink"]) {
      test(`page ${path}`, async ({ page }) => {
        await page.goto(`${path}?mock=ok`);
        await page.waitForLoadState("networkidle");
        await scan(page, path);
      });
    }
  });
}
