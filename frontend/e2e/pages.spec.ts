import { expect, test } from "@playwright/test";
import { CHECK_DEAL, stubApi } from "./fixtures";

test("how we rank explains the one signal running at launch", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/how-we-rank");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("How we rank");
  await expect(page).toHaveTitle("How we rank · DealFinder");
  const main = page.locator("main");
  for (const phrase of [/fair price/i, /July 2026 snapshot/i, /no verdict/i, /no paid placement/i,
                        /"was" price is never used/i, /no live store results/i])
    await expect(main).toContainText(phrase);
  await expect(main).not.toContainText(/eBay|median of the Best Buy/i);   // these come with live search
});

test("privacy page states only what is true now", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy");
  const main = page.locator("main");
  await expect(main).toContainText("Checking a price needs no account");
  await expect(main).toContainText(/sets no cookies/i);
  await expect(main).not.toContainText(/email alerts|Resend|watchlist|saved searches/i);   // these arrive with alerts
});

test("shopper pages set no cookies and call no third parties", async ({ page, context }) => {
  const hosts = new Set<string>();
  page.on("request", (r) => hosts.add(new URL(r.url()).host));
  await stubApi(page, { check: CHECK_DEAL });
  for (const path of ["/", "/check", "/how-we-rank", "/privacy", "/nope"]) await page.goto(path);
  await page.goto("/check?title=Sony%20WH-1000XM5&price=199");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.locator("[data-badge]")).toHaveCount(1);
  expect(await context.cookies()).toEqual([]);
  expect([...hosts].filter((h) => h !== "127.0.0.1:4173")).toEqual([]);
});
