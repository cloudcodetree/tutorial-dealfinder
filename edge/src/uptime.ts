// The 10-minute uptime probe, run from the Worker's Cron Trigger. Healthchecks.io
// emails the owner when a ping is late or reports a failure. No GCP alerting: its
// pricing lists a monthly charge per alert condition.
//
//   assets  the app shell comes back from Workers Static Assets
//   api     the backend's /readyz answers 200 within 15 s (a cold start fits)
//   public  /api/health answers through the Worker's own custom domain, the path a
//           visitor takes (Cloudflare: a Custom Domain can be fetched from a Worker
//           in the same zone)
//
// The deal-pages probe waits with the R2 bucket for a Best Buy key.

export interface UptimeEnv {
  ASSETS: Fetcher;
  BACKEND_ORIGIN: string;
  PUBLIC_ORIGIN?: string;
  EDGE_SHARED_SECRET: string;
  HEALTHCHECK_UPTIME_URL?: string;
}

const TIMEOUT_MS = 15_000;

async function probe(run: () => Promise<boolean>): Promise<boolean> {
  try {
    return await run();
  } catch {
    return false;      // a thrown fetch or a timeout is a failed probe, never a crashed cron
  }
}

export async function runUptime(env: UptimeEnv, now: Date): Promise<{ ok: boolean; failed: string[] }> {
  void now;   // the deal-pages probe will compare the sitemap's age with it
  const probes: Array<[string, () => Promise<boolean>]> = [
    ['assets', async () => {
      const r = await env.ASSETS.fetch('https://assets.local/');
      return r.status === 200 && (await r.text()).includes('id="root"');
    }],
    ['api', async () => {
      const r = await fetch(`${env.BACKEND_ORIGIN}/readyz`, {
        headers: { 'X-DealFinder-Edge': env.EDGE_SHARED_SECRET },
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
      return r.status === 200;
    }],
  ];
  if (env.PUBLIC_ORIGIN) {
    probes.push(['public', async () => {
      const r = await fetch(`${env.PUBLIC_ORIGIN}/api/health`, { signal: AbortSignal.timeout(TIMEOUT_MS) });
      return r.status === 200;
    }]);
  }
  const failed: string[] = [];
  for (const [name, run] of probes) if (!(await probe(run))) failed.push(name);
  const ok = failed.length === 0;
  if (env.HEALTHCHECK_UPTIME_URL) {
    await probe(async () => {
      await fetch(ok ? env.HEALTHCHECK_UPTIME_URL! : `${env.HEALTHCHECK_UPTIME_URL}/fail`,
                  ok ? {} : { method: 'POST', body: `failed: ${failed.join(', ')}` });
      return true;
    });
  }
  return { ok, failed };
}
