import { expect, test } from "@playwright/test";
import { stubApi } from "./fixtures";

const PRIVACY_HEADINGS = ["Effective date", "What we collect", "Who processes it", "Reviewing and changing your data",
  "Deleting your sign-in account", "Do Not Track", "Tracking by other parties", "Cookies and storage",
  "How long we keep it", "Children", "Changes to this policy", "Contact"];

test("privacy is final and covers every required section in order", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/privacy");
  await expect(page.getByText("Draft: final policy lands before launch")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(PRIVACY_HEADINGS);
});

test("privacy states the launch facts", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/privacy");
  const main = page.locator("main");
  for (const fact of [/needs no account/i, /never stored or logged/i, /IP address/i, /sets no cookies/i,
                      /__cf_bm/, /does not train on/i, /under 13/i, /cloudcodetree\.com\/about\/contact/])
    await expect(main).toContainText(fact);
  await expect(main).not.toContainText(/Resend|alert history|72 h/i);   // these arrive with alerts
});

test("how-we-rank carries the promises", async ({ page }) => {
  await stubApi(page, {});
  await page.goto("/how-we-rank");
  for (const t of ["no paid placement", "AI-written text", "Prices change, so check the store before you buy."])
    await expect(page.getByText(t, { exact: false }).first()).toBeVisible();
});
