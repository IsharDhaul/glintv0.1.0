import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PORT ?? 3000);

// E2E runs against mock mode (synthetic JSON in web/mocks), so it needs no API or real build.
export default defineConfig({
  testDir: "e2e",
  testIgnore: "real/**", // real-build specs: local only, `npx playwright test -c e2e/real`
  grepInvert: process.env.GLINT_PERF ? undefined : /@perf/, // timing tests: `make perf`
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: `http://localhost:${port}`, trace: "on-first-retry" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // CI runs a production build: no on-demand dev compiles to abort navigations or slow first
  // hits. Locally, reuse a running `make dev-web` (or start `next dev`).
  webServer: {
    command: process.env.CI ? `npm run build && npm run start` : `npm run dev`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: process.env.CI ? 300_000 : 60_000,
    env: { NEXT_PUBLIC_GLINT_MOCK: "1", PORT: String(port) },
  },
});
