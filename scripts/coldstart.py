#!/usr/bin/env python3
"""Measure DealFinder's cold start on Cloud Run: the first request after scale-to-zero.

    python scripts/coldstart.py --base https://deals.cloudcodetree.com/api --project P --runs 3

Each run forces a new revision (a COLDSTART_NONCE env var), so no instance of the
old one can answer. A deploy starts one instance of its own to pass the readiness
check, and Cloud Run keeps an idle instance for up to 15 minutes, so the script
then waits --idle-s seconds (default 960) before it times the first GET /health
and the first GET /readyz, request to last byte. (Cloud Run reserves /healthz.) That makes each run about 16
minutes. It prints every run and the median, and exits 1 if any cold /health
took more than 10 s.

Stdlib only. The gcloud call is read-write on the service (a new revision with the
same image and config), so it runs only with the owner's go.
"""
from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
import urllib.request
from typing import Callable

GATE_S = 10.0


def measure(base: str, *, runs: int, redeploy: Callable[[], None], wait: Callable[[], None],
            get: Callable[[str], None], clock: Callable[[], float] = time.monotonic) -> list[tuple[float, float]]:
    out = []
    for _ in range(runs):
        redeploy()
        wait()
        timings = []
        for route in ("health", "readyz"):
            start = clock()
            get(f"{base}/{route}")
            timings.append(clock() - start)
        out.append((timings[0], timings[1]))
    return out


def report(runs: list[tuple[float, float]]) -> int:
    for i, (h, r) in enumerate(runs, 1):
        print(f"run {i}: health {h:.1f}s readyz {r:.1f}s")
    print(f"median: health {statistics.median(h for h, _ in runs):.1f}s "
          f"readyz {statistics.median(r for _, r in runs):.1f}s")
    slow = [h for h, _ in runs if h > GATE_S]
    if slow:
        print(f"✗ a cold /health took {max(slow):.1f}s, over the {GATE_S:.0f}s gate")
        return 1
    return 0


def _get(url: str) -> None:
    # /readyz may answer 503 while the schema is pending. Its timing still counts.
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            r.read()
    except urllib.error.HTTPError as e:
        e.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--idle-s", type=int, default=960)
    args = ap.parse_args(argv)

    def redeploy() -> None:
        subprocess.run(["gcloud", "run", "services", "update", "dealfinder-api", "--region", "us-central1",
                        "--project", args.project, f"--update-env-vars=COLDSTART_NONCE={int(time.time())}",
                        "--quiet"], check=True, capture_output=True)

    runs = measure(args.base.rstrip("/"), runs=args.runs, redeploy=redeploy,
                   wait=lambda: time.sleep(args.idle_s), get=_get)
    return report(runs)


if __name__ == "__main__":
    sys.exit(main())
