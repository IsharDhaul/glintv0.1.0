import { expect, test, type Locator } from "@playwright/test";
import lz from "lz-string";

/** The tooltip text of a null glyph ("—" / "n/m") in the panel, after focusing it. */
async function reasonOf(glyph: Locator): Promise<string> {
  const trigger = glyph.locator("xpath=ancestor::span[@tabindex='0'][1]");
  await trigger.focus();
  const id = await trigger.getAttribute("aria-describedby");
  return (await glyph.page().locator(`[id="${id}"]`).textContent()) ?? "";
}

test("null comparisons show — or n/m with the reason from NearMiss.note (CONTRACT #18)", async ({ page }) => {
  // Each screen hits one null path for real (the mock evaluates screens like the engine):
  // a sector whose median net debt is ≤ 0 (a ratio to it is n/m), and sectors too small to rank.
  const open = async (filter: object, universe: object) => {
    const screen = { dsl_version: 1, name: "Note check", filters: { op: "and", children: [filter] }, universe, limit: 100, near_misses: true };
    await page.goto(`/?mock=ok&s=${lz.compressToEncodedURIComponent(JSON.stringify(screen))}`);
    const panel = page.getByRole("region", { name: "Near misses" });
    await expect(panel.getByRole("listitem").first()).toBeVisible();
    return panel;
  };

  let panel = await open({ metric: "net_debt", cmp: "vs_sector_median_lte", value: 0.8, missing: "fail" }, { sectors_include: ["Capital Markets", "Technology"] });
  const nm = panel.getByText("n/m", { exact: true }).first();
  await expect(nm).toBeVisible();
  expect(await reasonOf(nm)).toContain("Not meaningful: the denominator is zero or negative");

  panel = await open(
    { metric: "operating_margin", cmp: "pct_rank_gte", value: 0.7, within: "sector", missing: "fail" },
    { sectors_include: ["Capital Markets", "Consumer Staples"], market_cap_min: 1e9 },
  );
  const dash = panel.getByText("—", { exact: true }).first();
  await expect(dash).toBeVisible();
  const reason = await reasonOf(dash);
  expect(reason).toContain("Too few companies in the sector");
  expect(reason).not.toContain("no reason given");
  // Reason codes are internal: the tooltip says it in words.
  expect(reason).not.toMatch(/\b[A-Z]{2,}(?:_[A-Z]+)+\b/);
});

test.beforeEach(async ({ page }) => {
  await page.goto("/?mock=ok");
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("region", { name: "Near misses" })).toBeVisible();
});

test("rows are grouped by the filter they missed, with value, threshold and gap", async ({ page }) => {
  const panel = page.getByRole("region", { name: "Near misses" });
  await expect(panel.getByRole("group", { name: /^Missed / }).first()).toBeVisible();
  await expect(panel.getByRole("heading", { name: /^Missed .*, \d+ compan/ }).first()).toBeVisible();
  const first = panel.getByRole("listitem").first();
  await expect(first).toContainText("vs ");
  // The gap is in the metric's own unit ("4.8 pp short"), never a relative "% away".
  await expect(panel).toContainText(/\d pp short/);
  await expect(panel).not.toContainText("away");
});

test("filter chips narrow the list to one failed filter", async ({ page }) => {
  const panel = page.getByRole("region", { name: "Near misses" });
  const chips = panel.getByRole("group", { name: "Show near misses for" }).getByRole("button");
  await expect(chips.first()).toBeVisible();
  const all = await panel.getByRole("listitem").count();
  await chips.nth(1).click();
  await expect(chips.nth(1)).toHaveAttribute("aria-pressed", "true");
  const label = ((await chips.nth(1).textContent()) ?? "").replace(/, \d+$/, "");
  const rows = panel.getByRole("listitem");
  expect(await rows.count()).toBeLessThan(all);
  await expect(panel.getByRole("group", { name: /^Missed / })).toHaveCount(1);
  await expect(panel.getByRole("group", { name: `Missed ${label}` })).toBeVisible();
  await chips.first().click();
  await expect(rows).toHaveCount(all);
});

test("the ticker button opens the drawer, and near misses can be switched off", async ({ page }) => {
  const panel = page.getByRole("region", { name: "Near misses" });
  const btn = panel.getByRole("button", { name: /^Open SYN/ }).first();
  const ticker = (await btn.textContent())?.trim() ?? "";
  await btn.click();
  await expect(page.getByRole("dialog")).toContainText(ticker);
  await page.keyboard.press("Escape");

  await panel.getByRole("checkbox", { name: "Compute near misses" }).uncheck();
  await expect(panel).toContainText("Near misses are off for this screen.");
});

test("Include relaxes the missed filter and the result count follows", async ({ page }) => {
  const panel = page.getByRole("region", { name: "Near misses" });
  const include = panel.getByRole("button", { name: /^Include \(\d+\)/ }).first();
  const preview = Number((await include.innerText()).match(/\((\d+)\)/)?.[1]);
  await include.click();
  await expect(page.getByText(new RegExp(`^${preview} compan`))).toBeVisible();
});


test("zero results: the advice comes from the closest near miss, and its button works", async ({ page }) => {
  const screen = {
    dsl_version: 1,
    name: "Too strict",
    filters: { op: "and", children: [{ metric: "roic", cmp: "gte", value: 5, missing: "fail" }, { metric: "gross_margin", cmp: "gte", value: 0.3, missing: "fail" }] },
    limit: 100,
    near_misses: true,
  };
  await page.goto(`/?mock=ok&s=${lz.compressToEncodedURIComponent(JSON.stringify(screen))}`);
  const advice = page.getByText(/^No company passes all 2 filters\. Lowering ROIC to .* adds \d+ compan/);
  await expect(advice).toBeVisible();
  await page.getByRole("button", { name: /^Lower ROIC to/ }).click();
  await expect(page.getByRole("region", { name: "Results" }).getByText(/^\d+ compan/)).toBeVisible();
  await expect(page.getByText(/^No company passes/)).toHaveCount(0);
});
