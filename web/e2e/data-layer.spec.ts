import { expect, test } from "@playwright/test";

test("mock mode serves every hook with synthetic data", async ({ page }) => {
  await page.goto("/dev/hooks?mock=ok");
  await expect(page.getByTestId("hook-meta")).toContainText("synthetic=true");
  await expect(page.getByTestId("hook-metrics")).toContainText("metrics");
  await expect(page.getByTestId("hook-screen")).toContainText("Universe → ROIC ≥ 15.0%");
  await expect(page.getByTestId("hook-screen")).toContainText("Synthetic data");
  await expect(page.getByTestId("hook-search")).toContainText("SYN00");
  await expect(page.getByTestId("hook-company")).toContainText("Synthetic Co");
});

test("mock scenarios drive the API-down and no-build errors", async ({ page }) => {
  await page.goto("/dev/hooks?mock=down");
  await expect(page.getByTestId("hook-meta")).toContainText("network:");
  await page.goto("/dev/hooks?mock=nobuild");
  await expect(page.getByTestId("hook-meta")).toContainText("no_build:");
  await page.goto("/dev/hooks?mock=ok");
  await expect(page.getByTestId("hook-meta")).toContainText("synthetic=true");
});
