#!/usr/bin/env python3
"""Concurrent load test for the DealFinder FastAPI service (Part 32).

Fires N concurrent GETs at /healthz and /search?q=..., then reports p50/p95/p99
latency and throughput per endpoint. Uses only the stdlib asyncio event loop plus
httpx (already a project dependency).

It is *honest by construction*: it probes /healthz first and, if the app is not
up, prints a clear message and exits WITHOUT inventing numbers. Any figure it
reports is a real measurement against a running server.

Usage:
    # start the API in another shell first:
    #   .venv/bin/uvicorn dealfinder.serve:app --port 8000
    .venv/bin/python scripts/loadtest.py
    .venv/bin/python scripts/loadtest.py --base http://127.0.0.1:8000 \
        --requests 80 --concurrency 8 --query "noise cancelling headphones"

Notes
-----
* `/search` hits live sources (or the offline snapshot stub in tests). Keep the
  request count modest so you don't hammer real APIs / trip a source's rate limit
  — the circuit breaker in aggregate.py exists precisely for that.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Sample:
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0
    statuses: dict[int, int] = field(default_factory=dict)


def _pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile (deterministic, no interpolation surprises)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


async def _one(client: httpx.AsyncClient, url: str, sample: Sample) -> None:
    t0 = time.perf_counter()
    try:
        r = await client.get(url, timeout=30.0)
        dt = (time.perf_counter() - t0) * 1000.0
        sample.latencies_ms.append(dt)
        sample.statuses[r.status_code] = sample.statuses.get(r.status_code, 0) + 1
        if r.status_code >= 500:
            sample.errors += 1
    except Exception:
        sample.errors += 1


async def _run_endpoint(
    base: str, path: str, total: int, concurrency: int
) -> tuple[Sample, float]:
    url = base.rstrip("/") + path
    sample = Sample()
    sem = asyncio.Semaphore(concurrency)

    async def guarded(client: httpx.AsyncClient) -> None:
        async with sem:
            await _one(client, url, sample)

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    wall_start = time.perf_counter()
    async with httpx.AsyncClient(limits=limits) as client:
        await asyncio.gather(*(guarded(client) for _ in range(total)))
    wall = time.perf_counter() - wall_start
    return sample, wall


def _report(name: str, sample: Sample, wall: float, total: int) -> None:
    ok = len(sample.latencies_ms)
    thru = ok / wall if wall > 0 else 0.0
    print(f"\n{name}")
    print(f"  requests   : {total}  (ok={ok}, errors={sample.errors})")
    print(f"  statuses   : {dict(sorted(sample.statuses.items()))}")
    if ok:
        print(f"  latency ms : p50={_pct(sample.latencies_ms, 50):.1f}  "
              f"p95={_pct(sample.latencies_ms, 95):.1f}  "
              f"p99={_pct(sample.latencies_ms, 99):.1f}  "
              f"(min={min(sample.latencies_ms):.1f}, "
              f"max={max(sample.latencies_ms):.1f}, "
              f"mean={statistics.mean(sample.latencies_ms):.1f})")
    print(f"  throughput : {thru:.1f} req/s  (wall {wall:.2f}s)")


async def _amain(args: argparse.Namespace) -> int:
    base = args.base.rstrip("/")

    # --- Liveness probe: never fabricate numbers against a dead server. ---------
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(base + "/healthz", timeout=3.0)
        if r.status_code != 200:
            print(f"App at {base}/healthz returned {r.status_code}; expected 200. "
                  "Start it with `.venv/bin/uvicorn dealfinder.serve:app --port 8000`.")
            return 2
    except Exception as e:
        print(f"App is NOT up at {base}/healthz ({type(e).__name__}: {e}).")
        print("Start it first, e.g.: .venv/bin/uvicorn dealfinder.serve:app --port 8000")
        print("Refusing to report latencies against a server that isn't running.")
        return 2

    print(f"App is UP at {base} — running load test "
          f"(requests={args.requests}, concurrency={args.concurrency}).")

    hz, hz_wall = await _run_endpoint(base, "/healthz", args.requests, args.concurrency)
    _report("GET /healthz", hz, hz_wall, args.requests)

    search_path = f"/search?q={httpx.QueryParams({'q': args.query})['q']}"
    se, se_wall = await _run_endpoint(base, search_path, args.requests, args.concurrency)
    _report(f"GET /search?q={args.query!r}", se, se_wall, args.requests)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--requests", type=int, default=60, help="requests per endpoint")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--query", default="noise cancelling headphones")
    args = ap.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
