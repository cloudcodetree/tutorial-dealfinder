import { expect, test } from "@playwright/test";
import { BADGE_TOKENS } from "./fixtures";

/**
 * Full-stack, live-backend e2e (opt-in). Drives a REAL search end to end:
 * SPA → Vite dev proxy → FastAPI /search(/stream) → live sources.
 *
 * Requires, before `npx playwright test`:
 *   1. the FastAPI backend on :8000 —
 *        .venv/bin/uvicorn dealfinder.serve:app --port 8000
 *   2. E2E_LIVE=1 in the environment.
 *
 * Off by default: live sources are slow (the load test in scripts/loadtest.py
 * measured /search p50 ~10s against this machine) and depend on the network,
 * so this is a smoke check you run deliberately — not part of the hermetic CI
 * lane. It asserts the *shape*, never a specific offer/price (those vary).
 */
test.describe("live backend", () => {
  test.skip(!process.env.E2E_LIVE, "set E2E_LIVE=1 and run the FastAPI backend on :8000");
  // Live sources can take tens of seconds per search.
  test.setTimeout(120_000);

  test("real search renders cards with valid §9 badges", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /search/i }).click();

    // Either offers arrive or the honest empty state shows — both are valid.
    await expect(page.getByTestId("search-summary")).toBeVisible({ timeout: 90_000 });

    const cards = page.getByTestId("result-card");
    const n = await cards.count();
    if (n === 0) {
      await expect(page.getByText(/no offers found/i)).toBeVisible();
      return;
    }

    const values = await page
      .locator("[data-badge]")
      .evaluateAll((els) => els.map((el) => el.getAttribute("data-badge")));
    expect(values.length).toBe(n);
    for (const v of values) {
      expect(BADGE_TOKENS).toContain(v);
    }
  });
});
