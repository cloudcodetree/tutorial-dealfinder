import { expect, test } from "@playwright/test";
import { CHECK_DEAL, CHECK_UNKNOWN_CATEGORY, stubApi } from "./fixtures";

async function check(page: import("@playwright/test").Page, title: string, price: string) {
  await page.getByLabel("Product name").fill(title);
  await page.getByLabel("Price you see (USD)").fill(price);
  await page.getByRole("button", { name: "Check" }).click();
}

test("the front page is Check a deal", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Check a deal");
  await expect(page.getByLabel("Product name")).toBeVisible();
});

test("check a deal shows the server verdict, reason and fair price", async ({ page }) => {
  await stubApi(page, { check: CHECK_DEAL });
  await page.goto("/check");
  await check(page, "Sony WH-1000XM5", "199");
  await expect(page.locator("[data-badge]")).toHaveText(CHECK_DEAL.verdict.toUpperCase());
  await expect(page.locator("[data-badge]")).toHaveAttribute("aria-label", "Verdict: deal");
  await expect(page.getByText(CHECK_DEAL.reason)).toBeVisible();
  await expect(page.getByText("Our fair price ~$285")).toBeVisible();
  expect(page.apiCalls("/api/check")).toBe(1);
});

test("unknown category shows the reason with no badge and no fair price", async ({ page }) => {
  await stubApi(page, { check: CHECK_UNKNOWN_CATEGORY });
  await page.goto("/check");
  await check(page, "Cast iron skillet", "20");
  await expect(page.getByText(CHECK_UNKNOWN_CATEGORY.reason)).toBeVisible();
  await expect(page.locator("[data-badge]")).toHaveCount(0);
  await expect(page.getByText(/our fair price/i)).toHaveCount(0);
});

test("invalid check input sends nothing", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/check");
  await page.getByLabel("Price you see (USD)").fill("0");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByText(/enter a product name/i)).toBeVisible();
  await expect(page.getByText(/enter a price above \$0/i)).toBeVisible();
  expect(page.apiCalls("/api/check")).toBe(0);
});

test("a name shorter than the backend accepts is caught before sending", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/check");
  await check(page, "tv", "100");
  await expect(page.getByText(/at least 3 characters/i)).toBeVisible();
  expect(page.apiCalls("/api/check")).toBe(0);
});

test("a backend 422 shows one plain message", async ({ page }) => {
  await stubApi(page, { check: { status: 422, body: { detail: [{ loc: ["query", "price"] }] } } });
  await page.goto("/check");
  await check(page, "Sony WH-1000XM5", "199");
  await expect(page.getByText("Enter a product name and a price above $0.")).toBeVisible();
});

test("a failed check shows a message and never a stale verdict", async ({ page }) => {
  await stubApi(page, { check: CHECK_DEAL });
  await page.goto("/check");
  await check(page, "Sony WH-1000XM5", "199");
  await expect(page.locator("[data-badge]")).toHaveCount(1);
  await page.unroute("**/*");
  await stubApi(page, { check: { status: 429, body: { detail: "slow down" } } });
  await check(page, "Sony WH-1000XM5", "150");
  await expect(page.getByRole("alert")).toContainText(/slow down|too many/i);
  await expect(page.locator("[data-badge]")).toHaveCount(0);
});

test("a title and price in the address prefill the form", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/check?title=Sony%20WH-1000XM5&price=199");
  await expect(page.getByLabel("Product name")).toHaveValue("Sony WH-1000XM5");
  await expect(page.getByLabel("Price you see (USD)")).toHaveValue("199");
});
