import { expect, test } from "@playwright/test";

// Built with VITE_SENTRY_DSN=https://public@o0.ingest.us.sentry.io/0 (playwright.sentry.config.ts).
// The envelope never leaves the browser: this route answers it.

test("a front-end error reaches Sentry without the page's query text", async ({ page }) => {
  const bodies: string[] = [];
  await page.route("**/api/0/envelope/**", async (r) => {
    bodies.push(r.request().postData() ?? "");
    await r.fulfill({ status: 200, body: "{}" });
  });
  await page.goto("/check?title=secret-query&price=1");
  await page.evaluate(() => setTimeout(() => { throw new Error("boom"); }));
  await expect.poll(() => bodies.length).toBeGreaterThan(0);
  const all = bodies.join("");
  expect(all).toContain("boom");
  expect(all).not.toContain("secret-query");
});

test("Sentry sends no personal data and no cookies", async ({ page, context }) => {
  const bodies: string[] = [];
  await page.route("**/api/0/envelope/**", async (r) => {
    bodies.push(r.request().postData() ?? "");
    await r.fulfill({ status: 200, body: "{}" });
  });
  await page.goto("/check");
  await page.evaluate(() => setTimeout(() => { throw new Error("boom"); }));
  await expect.poll(() => bodies.length).toBeGreaterThan(0);
  expect(bodies.join("")).not.toMatch(/"ip_address"|"cookies"/);
  expect(await context.cookies()).toEqual([]);
});
