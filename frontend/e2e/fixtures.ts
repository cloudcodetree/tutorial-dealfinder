import type { Page, Route } from "@playwright/test";

// The four badge tokens. The browser never computes a verdict: a badge shows only
// what the backend returned.
export const BADGE_TOKENS = ["DEAL", "FAIR", "SUSPICIOUS", "OVERPRICED"] as const;
export type BadgeToken = (typeof BADGE_TOKENS)[number];

// GET /check, shaped exactly like dealfinder/shop.py check_deal().
export const CHECK_DEAL = {
  title: "Sony WH-1000XM5",
  price: 199,
  category: "audio",
  fair: 285.15,
  residual_frac: 0.302,
  verdict: "deal",
  basis: "model",
  reason: "30% below our fair price for this model (~$285).",
};

export const CHECK_UNKNOWN_CATEGORY = {
  title: "Garden hose 50 ft",
  price: 25,
  category: null,
  fair: null,
  residual_frac: null,
  verdict: null,
  basis: null,
  reason: "We can't estimate a fair price for this kind of product yet.",
};

export const CONFIG = {
  supabaseUrl: "https://demo-ref.supabase.co",
  supabasePublishableKey: "sb_publishable_test",
  providers: ["google", "github"],
};

// An override is either a body to return with 200, or {status} for an error.
type Stub = Record<string, unknown> | { status: number; body?: unknown };
type Overrides = { config?: Stub; check?: Stub };

const ROUTES: Array<[RegExp, keyof Overrides]> = [
  [/^\/api\/config\.json$/, "config"],
  [/^\/api\/check$/, "check"],
];
const DEFAULTS: Overrides = { config: CONFIG };
const SUPABASE_HOST = new URL(CONFIG.supabaseUrl).host;

declare module "@playwright/test" {
  interface Page {
    /** How many /api requests started with this path prefix. */
    apiCalls(prefix: string): number;
    /** /api requests no stub matched. A test that sees one is calling an unplanned route. */
    unexpected: string[];
    /** Requests that left the app's origin and were blocked. */
    offHost: string[];
  }
}

const isError = (s: Stub): s is { status: number; body?: unknown } =>
  typeof (s as { status?: unknown }).status === "number" && Object.keys(s).every((k) => k === "status" || k === "body");

/** Route every /api call to a stub, answer the mocked Supabase host, and block every
 *  other off-origin request, so a test can never reach a real service. */
export async function stubApi(page: Page, overrides: Overrides): Promise<void> {
  const stubs: Overrides = { ...DEFAULTS, ...overrides };
  const calls: string[] = [];
  page.unexpected = [];
  page.offHost = [];
  page.apiCalls = (prefix: string) => calls.filter((p) => p.startsWith(prefix)).length;

  await page.route("**/*", async (route: Route) => {
    const url = new URL(route.request().url());
    const own = url.hostname === "127.0.0.1" || url.hostname === "localhost";
    if (url.host === SUPABASE_HOST) return route.fulfill({ status: 200, json: {} });
    if (!own) {
      page.offHost.push(url.href);
      return route.abort();
    }
    if (!url.pathname.startsWith("/api/")) return route.fallback();
    calls.push(url.pathname);
    const match = ROUTES.find(([re]) => re.test(url.pathname));
    const stub = match ? stubs[match[1]] : undefined;
    if (!stub) {
      page.unexpected.push(url.pathname);
      return route.fulfill({ status: 404, json: { detail: "not stubbed" } });
    }
    if (isError(stub)) return route.fulfill({ status: stub.status, json: stub.body ?? { detail: `HTTP ${stub.status}` } });
    return route.fulfill({ status: 200, json: stub });
  });
}
