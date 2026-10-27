// dealfinder-edge: the Worker that owns deals.cloudcodetree.com.
//
//   /api/*   -> the Cloud Run backend with /api stripped. Anonymous GET /api/search
//               is edge-cached 300 s. The LLM routes and the SSE stream are limited here.
//   /lab, /lab/* -> the backend, path unchanged
//   anything else -> the React app from Workers Static Assets (SPA fallback)
//
// Every proxied request carries X-DealFinder-Edge, the shared secret the backend's
// edge guard checks, and the visitor's CF-Connecting-IP, which its limiter keys on.
// Deal pages and R2 wait for a Best Buy key (Plan 3, "Launch without Best Buy").

export interface Env {
  ASSETS: Fetcher;
  ASK_LIMITER?: RateLimit;
  STREAM_LIMITER?: RateLimit;
  BACKEND_ORIGIN: string;
  LAUNCHED?: string;
  EDGE_SHARED_SECRET: string;
}

export type Route = 'api' | 'lab' | 'assets';

export function routeOf(pathname: string): Route {
  if (pathname === '/api' || pathname.startsWith('/api/')) return 'api';
  if (pathname === '/lab' || pathname.startsWith('/lab/')) return 'lab';
  return 'assets';
}

const SITE = 'https://deals.cloudcodetree.com';
const SEARCH_TTL_S = 300;
// The routes that can call an LLM share the hardest limit, as in the app (ratelimit.LIMITS).
const ASK_PATHS = new Set(['/api/ask', '/api/ask_agentic', '/api/review']);
const STREAM_PATH = '/api/search/stream';

/** The edge-cache key for an anonymous search: only q (trimmed, lowercased,
 *  whitespace collapsed) and k (default 12). Tracking parameters never split the cache. */
export function searchCacheKey(url: URL): string | null {
  if (url.pathname !== '/api/search') return null;
  const q = (url.searchParams.get('q') ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
  const k = url.searchParams.get('k') ?? '12';
  return `${SITE}/api/search?k=${encodeURIComponent(k)}&q=${encodeURIComponent(q)}`;
}

const json = (body: unknown, status: number, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });

function withSiteHeaders(res: Response, env: Env): Response {
  const out = new Response(res.body, res);
  out.headers.set('X-Content-Type-Options', 'nosniff');
  out.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  if (env.LAUNCHED !== 'true') out.headers.set('X-Robots-Tag', 'noindex');
  return out;
}

async function proxy(request: Request, env: Env, backendPath: string): Promise<Response> {
  const inbound = new URL(request.url);
  const target = new URL(backendPath + inbound.search, env.BACKEND_ORIGIN);
  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.set('X-DealFinder-Edge', env.EDGE_SHARED_SECRET);    // replaces any forged value
  const ip = request.headers.get('CF-Connecting-IP');
  if (ip) headers.set('CF-Connecting-IP', ip);
  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
  let res: Response;
  try {
    res = await fetch(target.toString(), {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      redirect: 'manual',
    });
  } catch {
    return json({ detail: 'backend unavailable' }, 503);
  }
  if (res.status >= 500) return json({ detail: 'backend unavailable' }, 503);
  return res;
}

async function limited(limiter: RateLimit | undefined, request: Request): Promise<boolean> {
  if (!limiter) return false;
  const key = request.headers.get('CF-Connecting-IP') ?? 'unknown';
  const { success } = await limiter.limit({ key });
  return !success;
}

/** The backend marks degraded and signed-in results no-store or private. Those never enter the shared cache. */
function shareable(res: Response): boolean {
  const cc = (res.headers.get('Cache-Control') ?? '').toLowerCase();
  return res.status === 200 && !cc.includes('no-store') && !cc.includes('private');
}

async function api(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  if (ASK_PATHS.has(url.pathname) && (await limited(env.ASK_LIMITER, request))) {
    return json({ detail: 'slow down' }, 429, { 'Retry-After': '60' });
  }
  if (url.pathname === STREAM_PATH && (await limited(env.STREAM_LIMITER, request))) {
    return json({ detail: 'slow down' }, 429, { 'Retry-After': '10' });
  }
  const backendPath = url.pathname.slice('/api'.length) || '/';
  const key = searchCacheKey(url);
  if (!key || request.method !== 'GET' || request.headers.has('Authorization')) {
    return proxy(request, env, backendPath);
  }
  const cache = caches.default;
  const hit = await cache.match(key);
  if (hit) {
    const res = new Response(hit.body, hit);
    res.headers.set('X-DealFinder-Cache', 'HIT');
    return res;
  }
  const res = await proxy(request, env, backendPath);
  if (shareable(res)) {
    const stored = new Response(res.clone().body, res);
    stored.headers.set('Cache-Control', `public, s-maxage=${SEARCH_TTL_S}`);
    ctx.waitUntil(cache.put(key, stored));
  }
  const out = new Response(res.body, res);
  out.headers.set('X-DealFinder-Cache', 'MISS');
  return out;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const { pathname } = new URL(request.url);
    const route = routeOf(pathname);
    let res: Response;
    if (route === 'api') res = await api(request, env, ctx);
    else if (route === 'lab') res = await proxy(request, env, pathname);
    else res = await env.ASSETS.fetch(request);
    return withSiteHeaders(res, env);
  },
} satisfies ExportedHandler<Env>;
