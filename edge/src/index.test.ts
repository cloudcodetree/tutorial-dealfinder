import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker, { routeOf, searchCacheKey, type Env } from './index';

let env: Env;
let sent: Request[];
let waited: Promise<unknown>[];
let cache: Map<string, Response>;
let puts: number;
let backend: (req: Request) => Response | Promise<Response>;

const ctx = () => ({ waitUntil: (p: Promise<unknown>) => waited.push(p) }) as unknown as ExecutionContext;
const call = (path: string, init?: RequestInit) =>
  worker.fetch(new Request('https://deals.beta.cloudcodetree.com' + path, init), env, ctx());
const lastFetch = () => sent[sent.length - 1];

beforeEach(() => {
  sent = [];
  waited = [];
  cache = new Map();
  puts = 0;
  backend = () => new Response('{"results":[]}', { status: 200, headers: { 'Cache-Control': 'public, max-age=300' } });
  vi.stubGlobal('fetch', async (input: RequestInfo, init?: RequestInit) => {
    const req = new Request(input, init);
    sent.push(req);
    return backend(req);
  });
  vi.stubGlobal('caches', {
    default: {
      match: async (key: string) => cache.get(key)?.clone(),
      put: async (key: string, res: Response) => { puts++; cache.set(key, res); },
    },
  });
  env = {
    ASSETS: { fetch: async () => new Response('<div id="root"></div>', { headers: { 'content-type': 'text/html' } }) },
    ASK_LIMITER: { limit: async () => ({ success: true }) },
    STREAM_LIMITER: { limit: async () => ({ success: true }) },
    BACKEND_ORIGIN: 'https://backend.test',
    LAUNCHED: 'false',
    EDGE_SHARED_SECRET: 's3cret',
  } as unknown as Env;
});

afterEach(() => vi.unstubAllGlobals());

describe('dealfinder-edge', () => {
  it('routes the contract table', () => {
    expect(routeOf('/api/search')).toBe('api'); expect(routeOf('/lab')).toBe('lab');
    expect(routeOf('/lab/x')).toBe('lab');      expect(routeOf('/deal/a-b')).toBe('assets');
    expect(routeOf('/sitemap.xml')).toBe('assets'); expect(routeOf('/watchlist')).toBe('assets');
    expect(routeOf('/laboratory')).toBe('assets'); expect(routeOf('/apix')).toBe('assets');
  });

  it('strips /api and adds the edge secret and client IP', async () => {
    await call('/api/watchlist', { headers: { 'CF-Connecting-IP': '1.2.3.4', 'X-DealFinder-Edge': 'forged' } });
    expect(lastFetch().url).toBe('https://backend.test/watchlist');
    expect(lastFetch().headers.get('X-DealFinder-Edge')).toBe('s3cret');
    expect(lastFetch().headers.get('CF-Connecting-IP')).toBe('1.2.3.4');
  });

  it('caches anonymous search under a normalized key', async () => {
    await call('/api/search?q=%20Noise%20%20Cancelling&utm=x');
    await Promise.all(waited);
    const second = await call('/api/search?q=noise%20cancelling');
    expect(second.headers.get('X-DealFinder-Cache')).toBe('HIT');
    expect(sent.length).toBe(1);
    expect(searchCacheKey(new URL('https://x/api/search?q=TV&k=5&utm=y'))).toBe(
      'https://x/api/search?k=5&q=tv');
  });

  it('keys the cache by host, so beta and production never share an answer', () => {
    // Both hosts live in the cloudcodetree.com zone, and the Cache API is per zone.
    const beta = searchCacheKey(new URL('https://deals.beta.cloudcodetree.com/api/search?q=tv'));
    const prod = searchCacheKey(new URL('https://deals.cloudcodetree.com/api/search?q=tv'));
    expect(beta).toBe('https://deals.beta.cloudcodetree.com/api/search?k=12&q=tv');
    expect(beta).not.toBe(prod);
  });

  it('authorized search bypasses the edge cache', async () => {
    await call('/api/search?q=tv', { headers: { Authorization: 'Bearer t' } });
    await call('/api/search?q=tv', { headers: { Authorization: 'Bearer t' } });
    await Promise.all(waited);
    expect(sent.length).toBe(2); expect(puts).toBe(0);
  });

  it('never edge-caches a search the backend marked no-store', async () => {
    backend = () => new Response('{"results":[],"degraded":true}', { status: 200, headers: { 'Cache-Control': 'no-store' } });
    await call('/api/search?q=tv');
    await Promise.all(waited);
    expect(puts).toBe(0);
  });

  it('limits the LLM routes and /api/search/stream', async () => {
    env.ASK_LIMITER = { limit: async () => ({ success: false }) } as unknown as RateLimit;
    env.STREAM_LIMITER = { limit: async () => ({ success: false }) } as unknown as RateLimit;
    for (const p of ['/api/ask?q=x', '/api/ask_agentic?q=x', '/api/review?q=x', '/api/search/stream?q=x']) {
      expect((await call(p)).status).toBe(429);
    }
    expect(sent.length).toBe(0);
  });

  it('proxies /lab with the edge secret and the path unchanged', async () => {
    await call('/lab/static/x.js', { headers: { 'CF-Connecting-IP': '1.2.3.4' } });
    expect(lastFetch().url).toBe('https://backend.test/lab/static/x.js');
    expect(lastFetch().headers.get('X-DealFinder-Edge')).toBe('s3cret');
  });

  it('backend outage is a clean 503', async () => {
    backend = () => { throw new Error('down'); };
    const res = await call('/api/search?q=tv');
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ detail: 'backend unavailable' });
    backend = () => new Response('boom', { status: 500 });
    expect((await call('/api/check?title=x&price=1')).status).toBe(503);
  });

  it('never sends the edge secret off the backend origin', async () => {
    for (const p of ['/api//evil.test/x', '/api/%2F%2Fevil.test/x', '/lab//evil.test/x']) {
      const res = await call(p);
      expect(res.status).toBe(400);
    }
    expect(sent.length).toBe(0);
  });

  it('rejects encoded paths, so a limiter cannot be skipped by spelling', async () => {
    env.ASK_LIMITER = { limit: async () => ({ success: false }) } as unknown as RateLimit;
    expect((await call('/api/a%73k?q=x')).status).toBe(400);
    expect(sent.length).toBe(0);
  });

  it('a cached search sends the backend exactly the values in its cache key', async () => {
    await call('/api/search?q=TV&q=evil&k=5&k=24&utm=x');
    expect(lastFetch().url).toBe('https://backend.test/search?k=5&q=tv');
  });

  it('everything is noindex before launch, assets included', async () => {
    expect((await call('/lab')).headers.get('X-Robots-Tag')).toBe('noindex');
    const page = await call('/');
    expect(page.headers.get('X-Robots-Tag')).toBe('noindex');
    expect(page.headers.get('X-Content-Type-Options')).toBe('nosniff');
    env.LAUNCHED = 'true';
    expect((await call('/')).headers.get('X-Robots-Tag')).toBeNull();
  });
});
