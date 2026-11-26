import { expect, test, type Page } from "@playwright/test";

const rows = (page: Page) => page.locator("tbody tr[data-index]");

async function openPreset(page: Page) {
  await page.getByRole("button", { name: "Presets" }).click();
  await page.getByRole("menuitem", { name: /Quality compounders/ }).click();
  await expect(page.getByRole("list", { name: /Sieve/ })).toContainText("ROIC ≥ 15.0%");
}

test.describe("states (SPEC §3.3)", () => {
  test("loading: skeleton first, then results", async ({ page }) => {
    await page.goto("/?mock=slow");
    await expect(page.getByRole("status", { name: "Loading results" })).toBeVisible();
    await expect(rows(page).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("status", { name: "Loading results" })).toHaveCount(0);
  });

  test("API down mid-session: banner, preview results greyed out", async ({ page }) => {
    // No ?mock= in the URL: the scenario then comes from sessionStorage, which the test flips.
    await page.goto("/");
    await page.evaluate(() => sessionStorage.setItem("glint.mockScenario", "ok"));
    await openPreset(page);
    await page.evaluate(() => sessionStorage.setItem("glint.mockScenario", "down"));
    await page.getByRole("button", { name: "Remove filter: FCF margin" }).click();
    // The live preview keeps answering from this build's data, but nothing on screen is confirmed:
    // it says so, and the results are greyed out.
    await expect(page.getByRole("alert").filter({ hasText: "Can't reach the Glint API" })).toContainText("a preview from this build's data");
    await expect(rows(page).first()).toContainText(/SYN/);
    await expect(page.locator("div.opacity-50").filter({ has: page.getByRole("table") })).toBeVisible();
    await page.evaluate(() => sessionStorage.setItem("glint.mockScenario", "ok"));
  });

  test("API down from the start: banner without promising old results", async ({ page }) => {
    await page.goto("/?mock=down");
    const banner = page.getByRole("alert").filter({ hasText: "Can't reach the Glint API" });
    await expect(banner).toBeVisible();
    await expect(banner).not.toContainText("last results");
    await page.goto("/?mock=ok");
  });

  test("empty result: says what happened and what to do, with near misses", async ({ page }) => {
    await page.goto("/?mock=empty");
    await openPreset(page);
    await expect(page.getByText(/^No company passes (all \d+ filters|the filter)\./)).toBeVisible();
    await expect(page.getByRole("region", { name: "Near misses" })).toBeVisible();
    await page.goto("/?mock=ok");
  });

  test("no build yet: the command to run", async ({ page }) => {
    await page.goto("/?mock=nobuild");
    await expect(page.getByRole("alert").filter({ hasText: "No build yet." })).toContainText("glint refresh");
    await expect(page.getByRole("status").filter({ hasText: "No build yet" }).first()).toBeVisible(); // as-of line
    await page.goto("/?mock=ok");
  });
});

test.describe("keyboard and accessibility (SPEC §3.3, §3.5)", () => {
  test("? lists the shortcuts; Esc closes and focus returns", async ({ page }) => {
    await page.goto("/?mock=ok");
    await expect(rows(page).first()).toBeVisible();
    await page.keyboard.press("?");
    const dialog = page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(dialog).toContainText("Add a filter");
    await expect(dialog.getByRole("button", { name: /Close/ })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("j from anywhere jumps into the results; shortcuts stay off while typing", async ({ page }) => {
    await page.goto("/?mock=ok");
    await expect(rows(page).first()).toBeVisible();
    await page.locator("body").press("j");
    await expect(rows(page).first()).toBeFocused();
    await page.keyboard.press("j");
    await expect(rows(page).nth(1)).toBeFocused();

    await page.getByRole("button", { name: "Add filter" }).click();
    await page.getByRole("combobox", { name: "Search metrics" }).fill("roic");
    await page.keyboard.press("Enter");
    const input = page.getByRole("textbox", { name: "ROIC threshold" });
    await input.fill("1");
    await input.press("f");
    await input.press("j");
    await expect(page.getByRole("dialog", { name: "Add a filter" })).toBeHidden();
    await expect(input).toBeFocused();
  });

  test("focus rings are purple, with a paper gap", async ({ page }) => {
    await page.goto("/?mock=ok");
    await expect(rows(page).first()).toBeVisible();
    const button = page.getByRole("button", { name: "Add filter" });
    await button.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    // --focus-ring: 2px paper, then 2px purple outside it. Compare with --purple as the browser
    // resolves it (the CSS build may serve OKLCH as Lab).
    const ring = () =>
      button.evaluate((el) => {
        const probe = document.createElement("span");
        probe.style.color = "var(--purple)";
        document.body.append(probe);
        const purple = getComputedStyle(probe).color;
        probe.remove();
        return getComputedStyle(el).boxShadow.includes(purple) ? "purple" : getComputedStyle(el).boxShadow;
      });
    await expect.poll(ring).toBe("purple");
  });

  test("reduced motion turns off animation and transitions", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/?mock=ok");
    await expect(rows(page).first()).toBeVisible();
    await rows(page).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const motion = await dialog.evaluate((el) => {
      const pulse = document.createElement("div");
      pulse.className = "animate-pulse glint-new";
      document.body.append(pulse);
      const p = getComputedStyle(pulse);
      const out = { transition: getComputedStyle(el).transitionDuration, animation: p.animationName };
      pulse.remove();
      return out;
    });
    expect(motion.transition).toBe("0s");
    expect(motion.animation).toBe("none");
  });

  test("the synthetic banner can't be hidden and is on every page", async ({ page }) => {
    for (const path of ["/", "/presets", "/metrics", "/about", "/company/SYN0001"]) {
      await page.goto(`${path}?mock=ok`);
      const banner = page.getByTestId("synthetic-banner");
      await expect(banner, path).toHaveText("Synthetic data: these are not real companies");
      await expect(banner.getByRole("button")).toHaveCount(0);
    }
  });
});
