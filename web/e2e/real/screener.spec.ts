import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

// WT-09 step 5, on a real build: run a preset → open the drawer → the source link points at
// sec.gov → export CSV → reload the share URL. No mock banner, and the real as-of stamps show.

const SHOT = `test-results/real/screener-${new Date().toISOString().slice(0, 10)}.png`;

test("real build: preset → drawer → sec.gov source → CSV → share URL", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);

  // Real mode: the as-of line names a real SEC bulk file and price close, and no banner shows.
  await page.goto("/");
  const asOf = page.getByText(/^Fundamentals: SEC bulk file of/);
  await expect(asOf).toContainText(/Prices: close of \w+/);
  await expect(asOf).not.toContainText("—");
  await expect(page.getByTestId("synthetic-banner")).toHaveCount(0);

  // Run a preset
  await page.getByRole("button", { name: "Presets" }).click();
  const screened = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/screen") &&
      r.request().method() === "POST" &&
      (r.request().postDataJSON() as { name?: string } | null)?.name === "Quality compounders",
  );
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  const { total } = (await (await screened).json()) as { total: number };
  await expect(page.getByRole("heading", { name: "Quality compounders" })).toBeVisible();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
  await expect(page.getByText(new RegExp(`(of ${total.toLocaleString("en-US")}|^${total.toLocaleString("en-US")} companies)$`))).toBeVisible();
  const first = page.locator("tbody tr[data-index]").first();
  await expect(first).toBeVisible();
  const ticker = (await first.getByRole("rowheader").textContent())?.trim() ?? "";
  expect(ticker).toMatch(/^[A-Z][A-Z0-9.]*$/);
  expect(ticker, "a synthetic ticker on a real build").not.toMatch(/^SYN\d{4}$/);
  await page.screenshot({ path: SHOT, fullPage: false });

  // Open the drawer: every source links to SEC EDGAR
  await first.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("region", { name: "Screen check" })).toBeVisible();
  const links = drawer.getByRole("region", { name: "Sources" }).getByRole("link");
  await expect(links.first()).toBeVisible();
  for (const href of await links.evaluateAll((as) => as.map((a) => a.getAttribute("href")))) {
    expect(href).toMatch(/^https:\/\/www\.sec\.gov\/Archives\/edgar\/data\/\d+\/\d{18}\/$/);
  }
  await page.keyboard.press("Escape");

  // Export CSV: real tickers, storage units, the same first row as the table
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^glint-quality-compounders-\d{4}-\d{2}-\d{2}\.csv$/);
  const [cols = [], ...rows] = parseCsv(await readFile((await file.path()) as string, "utf8"));
  // A ranked preset leads with `rank` (the API exports the visible columns, rank first).
  expect(cols.slice(0, 4)).toEqual(["rank", "ticker", "name", "sector"]);
  for (const c of ["as_of_fundamentals", "as_of_prices", "notes"]) expect(cols, c).toContain(c);
  expect(rows.length).toBe(total);
  expect(rows[0]?.[1]).toBe(ticker);
  // Storage units, not display strings: 0.15, never "15.0%". `notes` is prose and may say "50%".
  const notes = cols.indexOf("notes");
  for (const row of rows) expect(row.filter((_, i) => i !== notes).join(",")).not.toMatch(/\d%/);

  // Reload the share URL
  await page.getByRole("button", { name: "Copy share link" }).click();
  const link = await page.evaluate(() => navigator.clipboard.readText());
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "Quality compounders" })).toBeVisible();
  await expect(page.locator("tbody tr[data-index]").first().getByRole("rowheader")).toHaveText(ticker);
});

/** RFC 4180 rows: quoted fields may hold commas, quotes ("") and newlines. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  const endField = () => {
    row.push(field);
    field = "";
  };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch !== '"') field += ch;
      else if (text[i + 1] === '"') field += text[++i];
      else quoted = false;
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      endField();
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      endField();
      rows.push(row);
      row = [];
    } else {
      field += ch;
    }
  }
  if (field || row.length) {
    endField();
    rows.push(row);
  }
  return rows;
}
