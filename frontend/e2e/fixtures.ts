import type { Page } from "@playwright/test";

// The four badge tokens from bible §9.7 — the ONLY allowed verdict strings.
// Kept in one place so every spec (and the taxonomy assertion) references the
// same canonical set. Mirrors frontend/src/components/DealBadge.ts.
export const BADGE_TOKENS = ["DEAL", "FAIR", "SUSPICIOUS", "OVERPRICED"] as const;
export type BadgeToken = (typeof BADGE_TOKENS)[number];

// A deterministic /search JSON payload shaped exactly like the real backend
// (dealfinder/serve.py → aggregate()). deal_pct is chosen per row so that the
// DealBadge thresholds in DealBadge.ts produce one of each of the four badges:
//   80 → SUSPICIOUS (>=60), 25 → DEAL (>=10), 0 → FAIR (>-10), -30 → OVERPRICED.
export const SEARCH_RESPONSE = {
  query: "noise cancelling headphones",
  count: 4,
  median_price: 100.0,
  results: [
    { id: "s1", title: "Too-cheap Headphones", price: 20.0, source: "web:bargainz", deal_pct: 80.0 },
    { id: "d1", title: "Sony WH-1000XM5", price: 75.0, source: "BestBuy:sale", deal_pct: 25.0 },
    { id: "f1", title: "Bose QuietComfort", price: 100.0, source: "eBay:NEW", deal_pct: 0.0 },
    { id: "o1", title: "Overpriced Cans", price: 130.0, source: "RapidAPI:store", deal_pct: -30.0 },
  ],
};

// Empty result envelope — the well-formed "no offers" shape the backend returns
// when every source is down (see tests/test_chaos.py).
export const EMPTY_RESPONSE = {
  query: "zzznothing",
  count: 0,
  median_price: 0.0,
  results: [],
};

/**
 * Stub the network so the SPA renders deterministically with no backend.
 *
 * The app prefers `/search/stream` (SSE via EventSource). EventSource can't be
 * intercepted by `page.route`, and abort()ing it makes useSearch fall back to a
 * plain `GET /search` fetch — which we DO intercept and fulfill with JSON. That
 * exercises the real fallback path in api.ts and gives us a stable DOM.
 */
export async function stubSearch(page: Page, json: unknown): Promise<void> {
  // Fail the SSE connection so useSearch falls back to fetch(/search).
  await page.route("**/search/stream*", (route) => route.abort());
  await page.route(/\/search(\?|$)/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(json),
    }),
  );
}
