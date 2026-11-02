import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { CHECK_DEAL, CHECK_UNKNOWN_CATEGORY, stubApi } from "./fixtures";

// A product title can be one long unbroken string. It must wrap, never widen the page.
const LONG_TITLE = "X".repeat(120);

async function showCheck(page: Page, title: string) {
  await page.goto(`/check?title=${encodeURIComponent(title)}&price=199`);
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.locator(".check-result-card")).toBeVisible();
}

const VIEWS: Array<[string, (page: Page) => Promise<void>]> = [
  ["/", async (page) => { await page.goto("/"); }],
  ["/check with a verdict", async (page) => { await showCheck(page, "Sony WH-1000XM5"); }],
  ["/check with no verdict", async (page) => { await showCheck(page, "Garden hose 50 ft"); }],
  ["/check with field errors", async (page) => {
    await page.goto("/check");
    await page.getByRole("button", { name: "Check" }).click();
    await expect(page.getByText(/enter a product name/i)).toBeVisible();
  }],
  ["/how-we-rank", async (page) => { await page.goto("/how-we-rank"); }],
  ["/privacy", async (page) => { await page.goto("/privacy"); }],
  ["a 404", async (page) => { await page.goto("/nope"); }],
];

for (const [name, open] of VIEWS) {
  test(`axe: no WCAG A/AA violations on ${name}`, async ({ page }) => {
    await stubApi(page, { check: name.includes("no verdict") ? CHECK_UNKNOWN_CATEGORY : CHECK_DEAL });
    await open(page);
    const { violations } = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
}

test("no horizontal scroll at 375 px", async ({ page }) => {
  test.skip(test.info().project.name !== "mobile-375", "phone width only");
  await stubApi(page, { check: { ...CHECK_DEAL, title: LONG_TITLE } });
  // clientWidth, not innerWidth: an emulated phone (isMobile) widens innerWidth to fit
  // overflowing content, so scrollWidth <= innerWidth can never fail there.
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  for (const path of ["/", "/how-we-rank", "/privacy", "/nope"]) {
    await page.goto(path);
    expect(await fits(), path).toBe(true);
  }
  await showCheck(page, LONG_TITLE);
  expect(await fits(), "/check with a 120-character title").toBe(true);
});
