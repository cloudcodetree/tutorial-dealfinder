import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright e2e config for the DealFinder SPA (Part 32).
 *
 * `webServer` boots the Vite dev server so the tests run against the *real*
 * built app (App.tsx → useSearch → EventSource/fetch → ResultCard/DealBadge).
 *
 * Two modes:
 *
 *   1. UI-only (default, hermetic): specs that assert rendering + the §9 badge
 *      taxonomy stub the network at `**​/search*` with `page.route`, so they need
 *      NO FastAPI backend and NO source keys. Deterministic in CI.
 *
 *   2. Full-stack (opt-in): run the FastAPI backend on :8000 first
 *        .venv/bin/uvicorn dealfinder.serve:app --port 8000
 *      then the Vite dev proxy (vite.config.ts) forwards /search & /search/stream
 *      to it. Set E2E_LIVE=1 to also run the live-backend spec, which drives a
 *      real search end-to-end. Live sources make it slow (see the load test in
 *      scripts/loadtest.py: /search p50 ~10s), so it's off by default.
 *
 * Browsers are NOT bundled — run `npx playwright install chromium` once before
 * `npx playwright test`.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    // Bind Vite explicitly to 127.0.0.1 (not the default `localhost`, which can
    // resolve to IPv6 ::1 while baseURL/url use IPv4) and `strictPort` so we fail
    // loudly rather than drift to a port the baseURL doesn't match.
    command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
