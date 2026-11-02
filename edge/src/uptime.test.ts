import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runUptime, type UptimeEnv } from './uptime';

const HC = 'https://hc-ping.com/uuid-1';
const NOW = new Date('2026-11-02T08:00:00Z');
let pings: string[];
let failBody: string | undefined;
let backend: (url: string, init?: RequestInit) => Response | Promise<Response>;

const env = (over: Partial<UptimeEnv> = {}): UptimeEnv => ({
  ASSETS: { fetch: async () => new Response('<div id="root"></div>', { status: 200 }) } as unknown as Fetcher,
  BACKEND_ORIGIN: 'https://backend.test',
  PUBLIC_ORIGIN: 'https://deals.test',
  EDGE_SHARED_SECRET: 's3cret',
  HEALTHCHECK_UPTIME_URL: HC,
  ...over,
});

beforeEach(() => {
  pings = [];
  failBody = undefined;
  backend = () => new Response('{"db":"ok","schema":"current"}', { status: 200 });
  vi.stubGlobal('fetch', async (input: RequestInfo, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.url;
    if (url.startsWith(HC)) {
      pings.push(url);
      failBody = init?.body as string | undefined;
      return new Response('OK');
    }
    return backend(url, init);
  });
});

describe('uptime', () => {
  it('pings ok when every probe passes', async () => {
    expect(await runUptime(env(), NOW)).toEqual({ ok: true, failed: [] });
    expect(pings).toEqual([HC]);
  });

  it('pings /fail naming the backend when /readyz is down', async () => {
    backend = (url) => new Response('down', { status: url.endsWith('/readyz') ? 503 : 200 });
    expect((await runUptime(env(), NOW)).failed).toEqual(['api']);
    expect(pings).toEqual([HC + '/fail']);
    expect(failBody).toBe('failed: api');
  });

  it('sends the edge secret to the backend', async () => {
    const seen: Array<string | null> = [];
    backend = (url, init) => {
      if (url.endsWith('/readyz')) seen.push(new Headers(init?.headers).get('X-DealFinder-Edge'));
      return new Response('{}', { status: 200 });
    };
    await runUptime(env(), NOW);
    expect(seen).toEqual(['s3cret']);
  });

  it('fails the assets probe when the app shell is missing', async () => {
    const r = await runUptime(env({ ASSETS: { fetch: async () => new Response('nope', { status: 200 }) } as unknown as Fetcher }), NOW);
    expect(r.failed).toEqual(['assets']);
  });

  it('fails the public probe when the site does not answer through the Worker', async () => {
    backend = (url) => new Response('', { status: url.startsWith('https://deals.test/') ? 522 : 200 });
    expect((await runUptime(env(), NOW)).failed).toEqual(['public']);
  });

  it('counts a thrown fetch as a failure, never as a crash', async () => {
    backend = () => { throw new Error('network'); };
    expect((await runUptime(env(), NOW)).failed).toEqual(['api', 'public']);
  });

  it('does nothing without HEALTHCHECK_UPTIME_URL', async () => {
    await runUptime(env({ HEALTHCHECK_UPTIME_URL: undefined }), NOW);
    expect(pings).toEqual([]);
  });
});
