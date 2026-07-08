import { expect, test } from "@playwright/test";
import { BADGE_TOKENS, EMPTY_RESPONSE, SEARCH_RESPONSE, stubSearch } from "./fixtures";

/**
 * DealFinder SPA e2e (Part 32) — hermetic: the backend is stubbed with
 * `page.route`, so these run with no FastAPI server and no source keys.
 */

test.describe("search results", () => {
  test("renders result cards, each carrying a §9 badge", async ({ page }) => {
    await stubSearch(page, SEARCH_RESPONSE);
    await page.goto("/");

    await page.getByRole("button", { name: /search/i }).click();

    // Summary appears once the (stubbed) search resolves.
    await expect(page.getByTestId("search-summary")).toBeVisible();

    const cards = page.getByTestId("result-card");
    await expect(cards).toHaveCount(SEARCH_RESPONSE.results.length);

    // Every card renders exactly one badge, and every badge is a valid token.
    const badges = page.locator("[data-badge]");
    await expect(badges).toHaveCount(SEARCH_RESPONSE.results.length);

    const values = await badges.evaluateAll((els) =>
      els.map((el) => el.getAttribute("data-badge")),
    );
    for (const v of values) {
      expect(BADGE_TOKENS).toContain(v);
    }
  });

  test("badge taxonomy is EXACTLY the four §9 tokens — no synonyms", async ({ page }) => {
    await stubSearch(page, SEARCH_RESPONSE);
    await page.goto("/");
    await page.getByRole("button", { name: /search/i }).click();
    await expect(page.getByTestId("search-summary")).toBeVisible();

    const rendered = new Set(
      await page.locator("[data-badge]").evaluateAll((els) =>
        els.map((el) => el.getAttribute("data-badge") ?? ""),
      ),
    );

    // The fixture is crafted to surface all four verdicts…
    expect([...rendered].sort()).toEqual([...BADGE_TOKENS].sort());
    // …and nothing outside the closed set is ever emitted.
    for (const token of rendered) {
      expect(BADGE_TOKENS).toContain(token);
    }
  });

  test("a specific offer maps to the expected badge", async ({ page }) => {
    await stubSearch(page, SEARCH_RESPONSE);
    await page.goto("/");
    await page.getByRole("button", { name: /search/i }).click();
    await expect(page.getByTestId("search-summary")).toBeVisible();

    // The 80%-under row is the "too good to be true" trap → SUSPICIOUS.
    const suspicious = page
      .getByTestId("result-card")
      .filter({ hasText: "Too-cheap Headphones" })
      .locator("[data-badge]");
    await expect(suspicious).toHaveAttribute("data-badge", "SUSPICIOUS");
  });
});

test.describe("edge cases", () => {
  test("empty query does not fire a search", async ({ page }) => {
    let searchHit = false;
    await page.route(/\/search/, (route) => {
      searchHit = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(EMPTY_RESPONSE),
      });
    });
    await page.goto("/");

    // Clear the prefilled query, then submit an empty one.
    const input = page.getByRole("textbox", { name: /search for a product/i });
    await input.fill("");
    await page.getByRole("button", { name: /search/i }).click();

    // useSearch guards `if (!q) return;` — no request, no cards, no summary.
    await expect(page.getByTestId("search-summary")).toHaveCount(0);
    await expect(page.getByTestId("result-card")).toHaveCount(0);
    expect(searchHit).toBe(false);
  });

  test("a query with zero offers shows the empty state, not an error", async ({ page }) => {
    await stubSearch(page, EMPTY_RESPONSE);
    await page.goto("/");

    await page.getByRole("textbox", { name: /search for a product/i }).fill("zzznothing");
    await page.getByRole("button", { name: /search/i }).click();

    await expect(page.getByText(/no offers found/i)).toBeVisible();
    await expect(page.getByTestId("result-card")).toHaveCount(0);
    // Well-formed empty response must NOT surface the error banner.
    await expect(page.getByText(/search failed/i)).toHaveCount(0);
  });
});
