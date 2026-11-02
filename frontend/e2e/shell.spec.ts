import { expect, test } from "@playwright/test";
import { stubApi } from "./fixtures";

const PAGES: Array<[string, RegExp]> = [
  ["/", /check a deal/i],
  ["/check", /check a deal/i],
  ["/how-we-rank", /how we rank/i],
  ["/privacy", /privacy/i],
];

test("every route renders its heading", async ({ page }) => {
  await stubApi(page, {});
  for (const [path, h1] of PAGES) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(h1);
  }
  expect(page.offHost).toEqual([]);
});

test("unknown route shows not found with a way home", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/nope");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/not found/i);
  await expect(page.getByRole("link", { name: /back to check a deal/i })).toHaveAttribute("href", "/");
});

test("footer carries the model and staleness notes on every page", async ({ page }) => {
  await stubApi(page, {});
  for (const [path] of PAGES) {
    await page.goto(path);
    const footer = page.getByRole("contentinfo");
    await expect(footer).toContainText("price model");
    await expect(footer).toContainText("may be out of date");
    await expect(footer).toContainText("labeled AI-written");
  }
});

test("footer links to how we rank, privacy and the lab", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/");
  const footer = page.getByRole("contentinfo");
  await expect(footer.getByRole("link", { name: "How we rank" })).toHaveAttribute("href", "/how-we-rank");
  await expect(footer.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
  await expect(footer.getByRole("link", { name: "Under the hood" })).toHaveAttribute("href", "/lab");
});

test("a skip link leads to the main content", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/");
  await expect(page.getByRole("link", { name: /skip to content/i })).toHaveAttribute("href", "#main");
  await expect(page.locator("main#main")).toHaveCount(1);
});

test("config failure does not block the page", async ({ page }) => {
  await stubApi(page, { config: { status: 500 } });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/check a deal/i);
  expect(page.unexpected).toEqual([]);
});

test("robots.txt keeps crawlers off the API and the lab", async ({ request }) => {
  const body = await (await request.get("/robots.txt")).text();
  expect(body).toContain("Disallow: /api/");
  expect(body).toContain("Disallow: /lab");
});
