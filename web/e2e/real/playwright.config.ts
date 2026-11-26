import { readFileSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

// WT-09 step 5: Playwright against a real build through the real API. Local only, never CI: it
// needs `glint refresh` to have run. `npx playwright test -c e2e/real` reuses a running
// `make dev`, or starts one. Ports come from the env, then the root .env, as `make dev` does.

function dotenv(key: string): string | undefined {
  try {
    const text = readFileSync(new URL("../../../.env", import.meta.url), "utf8");
    return text.match(new RegExp(`^${key}=([^\\s#]*)`, "m"))?.[1];
  } catch {
    return undefined;
  }
}

const port = Number(process.env.PORT ?? dotenv("PORT") ?? 3000);

export default defineConfig({
  testDir: ".",
  workers: 1, // perf.spec times the UI; parallel specs would compete for the same servers
  outputDir: "../../test-results/real",
  timeout: 60_000, // first hits compile pages in `next dev`
  expect: { timeout: 15_000 },
  use: { baseURL: `http://localhost:${port}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "make -C ../../.. dev",
    url: `http://localhost:${port}`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
