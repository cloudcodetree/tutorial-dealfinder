import { expect, test } from "@playwright/test";
import { BADGE_TOKENS } from "./fixtures";

/**
 * Full stack, opt-in: the built app → vite preview's /api proxy → the real FastAPI
 * backend on :8000. No stubs.
 *
 *   ../.venv/bin/uvicorn dealfinder.serve:app --port 8000      (in the repo root)
 *   E2E_LIVE=1 npx playwright test e2e/live.spec.ts --project=desktop
 *
 * /check needs no database and no store key: it rates the price with the model
 * trained on the teaching snapshot. The spec asserts the shape, never a number.
 */
test.describe("live backend", () => {
  test.skip(!process.env.E2E_LIVE, "set E2E_LIVE=1 and run the backend on :8000");

  async function check(page: import("@playwright/test").Page, title: string, price: string) {
    await page.goto("/check");
    await page.getByLabel("Product name").fill(title);
    await page.getByLabel("Price you see (USD)").fill(price);
    await page.getByRole("button", { name: "Check" }).click();
    await expect(page.locator(".check-result-card")).toBeVisible({ timeout: 15_000 });
  }

  test("a model we know gets one of the four verdicts", async ({ page }) => {
    await check(page, "Sony WH-1000XM5", "199");
    const badges = await page.locator("[data-badge]").allTextContents();
    expect(badges).toHaveLength(1);
    expect(BADGE_TOKENS).toContain(badges[0]);
    await expect(page.getByText(/our fair price ~\$\d+/i)).toBeVisible();
  });

  test("a product we cannot place gets a reason and no verdict", async ({ page }) => {
    await check(page, "Garden hose 50 ft", "25");
    await expect(page.locator("[data-badge]")).toHaveCount(0);
    await expect(page.locator(".check-result-card .reason")).not.toBeEmpty();
  });
});
