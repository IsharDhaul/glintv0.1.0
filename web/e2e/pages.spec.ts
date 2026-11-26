import { readdirSync } from "node:fs";

import { expect, test } from "@playwright/test";

// Mock mode serves config/presets/*.json, so the gallery shows one card per file.
const PRESET_COUNT = readdirSync(new URL("../../config/presets/", import.meta.url)).filter((f) => f.endsWith(".json")).length;

test("presets gallery: a card per preset with a live count; the whole card opens it", async ({ page }) => {
  await page.goto("/presets?mock=ok");
  const cards = page.getByRole("article");
  await expect(cards).toHaveCount(PRESET_COUNT);
  // Red-flag screens sit in their own group.
  await expect(page.getByRole("region", { name: "Risk checks" }).getByRole("article")).toHaveCount(2);
  const qc = cards.filter({ has: page.getByRole("heading", { name: "Quality compounders" }) });
  await expect(qc).toContainText("ROIC ≥ 15.0%");
  await expect(qc).toContainText("Source:");
  await expect(qc).toContainText(/\d+ compan(y matches|ies match) in this build/);
  await qc.getByRole("button", { name: "Read more" }).click();
  await expect(qc.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  await expect(qc).toContainText("misses");
  await expect(page).toHaveURL(/\/presets/); // Read more doesn't open the card
  // A click anywhere on the card (here, its summary) opens the screen.
  // force: the stretched link covers the text, so the real click lands on the link.
  const summary = qc.getByText("High returns on capital");
  await summary.evaluate((el) => el.scrollIntoView({ block: "center" })); // clear of the sticky banner
  await summary.click({ force: true });
  await expect(page).toHaveURL(/\/\?s=/);
  await expect(page.getByRole("heading", { name: "Quality compounders" })).toBeVisible();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("Gross margin ≥ 40.0%");
});

test("a preset card's count matches the screener's", async ({ page }) => {
  await page.goto("/presets?mock=ok");
  const qc = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Quality compounders" }) });
  const n = ((await qc.getByText(/in this build/).innerText()).match(/^([\d,]+)/) ?? [])[1];
  await qc.getByRole("link", { name: /Open Quality compounders/ }).click();
  await expect(page.getByRole("region", { name: "Results" }).getByText(new RegExp(`^${n} compan`))).toBeVisible();
});

test("metric dictionary: search, category tabs, anchors", async ({ page }) => {
  await page.goto("/metrics?mock=ok");
  await expect(page.getByRole("article").first()).toBeVisible();
  const total = await page.getByRole("article").count();
  await page.getByRole("searchbox", { name: "Search metrics" }).fill("roic");
  await expect(page.getByRole("article", { name: "ROIC" })).toBeVisible();
  expect(await page.getByRole("article").count()).toBeLessThan(total);
  await page.getByRole("searchbox", { name: "Search metrics" }).fill("");
  await page.getByRole("tab", { name: "Valuation" }).click();
  await expect(page.getByRole("tab", { name: "Valuation" })).toHaveAttribute("aria-selected", "true");
  for (const t of await page.getByRole("article").allTextContents()) expect(t).toContain("Valuation");
  await expect(page.getByRole("article", { name: "P/E (TTM)" })).toContainText("Not meaningful (n/m) for");

  await page.goto("/metrics?mock=ok#gross_margin");
  await expect(page.locator("#gross_margin")).toBeInViewport();
  // An entry: what it tells you, the formula in mono, when it misleads; no reason codes.
  const fcf = page.getByRole("article", { name: "FCF yield" });
  await expect(fcf).toContainText("When it misleads");
  await expect(fcf.locator(".font-code").first()).toHaveText("fcf_ttm / market_cap");
  for (const t of await page.getByRole("article").allTextContents()) expect(t).not.toMatch(/\b[A-Z]{2,}(?:_[A-Z]+)+\b|metric_history|§/);
  // Inputs that are metrics link to their entries.
  await fcf.getByRole("link", { name: "Market cap" }).click();
  await expect(page).toHaveURL(/#market_cap$/);
  await expect(page.locator("#market_cap")).toBeInViewport();
});

test("metric names on the company page link to their dictionary entries", async ({ page }) => {
  await page.goto("/company/SYN0186?mock=ok");
  await page.getByRole("region", { name: "All metrics" }).getByRole("link", { name: "ROIC", exact: true }).click();
  await expect(page).toHaveURL(/\/metrics#roic$/);
  await expect(page.locator("#roic")).toBeInViewport();
});

test("about page states the principles and the disclaimer", async ({ page }) => {
  await page.goto("/about?mock=ok");
  await expect(page.getByRole("heading", { name: "About Glint" })).toBeVisible();
  await expect(page.getByText("Not investment advice.").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Survivorship and look-ahead" })).toContainText("no backtests");
});

test("no horizontal page scroll at 390 px on any page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  for (const path of ["/", "/presets", "/metrics", "/about", "/company/SYN0001"]) {
    await page.goto(`${path}?mock=ok`);
    await page.waitForLoadState("networkidle");
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width, path).toBeLessThanOrEqual(390);
  }
});
