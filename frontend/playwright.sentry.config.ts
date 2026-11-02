import { defineConfig, devices } from "@playwright/test";

/**
 * The Sentry spec needs a build with a DSN, and every other spec needs one without,
 * so it has its own build (dist-sentry/) and preview port. The DSN points at a
 * project that does not exist, and the spec answers the envelope itself.
 *
 *   npx playwright test -c playwright.sentry.config.ts
 */
const DSN = "https://public@o0.ingest.us.sentry.io/0";

export default defineConfig({
  testDir: "./e2e-sentry",
  forbidOnly: !!process.env.CI,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:4175" },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command:
      `VITE_SENTRY_DSN=${DSN} npx vite build --outDir dist-sentry && ` +
      "npx vite preview --outDir dist-sentry --host 127.0.0.1 --port 4175 --strictPort",
    url: "http://127.0.0.1:4175",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
