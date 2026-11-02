// The one client for the DealFinder backend. Every call goes to the same-origin
// /api, which the deals Worker (and Vite's dev proxy) maps to the FastAPI routes
// with /api stripped. The browser never computes a verdict: it shows what the
// backend returned.

const API = "/api";

export type Verdict = "deal" | "fair" | "overpriced" | "suspicious";

/** GET /check: one price the shopper found, rated against our price model's fair price. */
export interface CheckResponse {
  title: string;
  price: number;
  category: string | null;
  fair: number | null;
  residual_frac: number | null;
  verdict: Verdict | null;
  basis: "model" | null;
  reason: string;
}

/** GET /config.json: public settings only. */
export interface PublicConfig {
  supabaseUrl: string | null;
  supabasePublishableKey: string | null;
  providers: string[];
}

/** A failed call. `detail` is the backend's message, or a fixed one when the
 *  network failed (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const NETWORK = "Could not reach DealFinder. Check your connection and try again.";

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API + path);
  } catch {
    throw new ApiError(0, NETWORK);
  }
  if (!res.ok) {
    let detail = `Something went wrong (HTTP ${res.status}). Try again.`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // not JSON: keep the generic message
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function checkDeal(title: string, price: number): Promise<CheckResponse> {
  const q = new URLSearchParams({ title, price: String(price) });
  return getJson<CheckResponse>(`/check?${q}`);
}

let config: Promise<PublicConfig | null> | null = null;

/** The public config, fetched once per page. A failure resolves to null and is kept. */
export function getConfig(): Promise<PublicConfig | null> {
  config ??= getJson<PublicConfig>("/config.json").catch(() => null);
  return config;
}
