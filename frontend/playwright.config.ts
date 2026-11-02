import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright e2e for the shopper front end.
 *
 * `webServer` builds the app and serves `dist/` with `vite preview`, so the tests
 * run against the same files the deals Worker serves. Every spec except
 * live.spec.ts stubs `/api/**` with e2e/fixtures.ts `stubApi`, so no backend
 * and no keys are needed. live.spec.ts is opt-in: E2E_LIVE=1 and a backend on :8000.
 *
 * Two projects: a desktop browser and a 375 px phone.
 * Browsers are not bundled. Run `npx playwright install chromium` once.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile-375",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true },
    },
  ],
  webServer: {
    // 127.0.0.1, not localhost, which can resolve to ::1 while baseURL is IPv4.
    command: "npm run build && npm run preview -- --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
