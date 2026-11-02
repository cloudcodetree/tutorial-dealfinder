#!/usr/bin/env python3
"""Create DealFinder's Healthchecks.io checks, idempotently. Prints no ping URL.

    python scripts/healthchecks_setup.py --out <scratchpad>/pings.json [--dry-run]

Reads HEALTHCHECKS_API_KEY (a read-write project key) from the environment or the
companion's `.env`. Each check is POSTed with `unique: ["name"]`, so a re-run returns
the existing check instead of a duplicate. Every check alerts all of the project's
channels (`channels: "*"`), which is the owner's email. The ping URLs go only to the
--out file: each one lets anyone report the site healthy.

At launch there is one check. The pages and alerts checks wait with their jobs for a
Best Buy key (Plan 5, "Launch without Best Buy").
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

API = "https://healthchecks.io/api/v3/checks/"
# name → (timeout, grace) in seconds. The uptime cron runs every 10 minutes.
CHECKS = {"dealfinder-uptime": (10 * 60, 20 * 60)}


def run(*, api_key: str, out: Path, dry_run: bool = False) -> dict[str, str]:
    if dry_run:
        for name, (timeout, grace) in CHECKS.items():
            print(f"would create {name}: timeout {timeout}s, grace {grace}s, all channels")
        return {}
    pings = {}
    for name, (timeout, grace) in CHECKS.items():
        r = httpx.post(API, headers={"X-Api-Key": api_key}, timeout=30,
                       json={"name": name, "timeout": timeout, "grace": grace,
                             "channels": "*", "unique": ["name"], "tags": "dealfinder"})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Healthchecks refused {name}: HTTP {r.status_code}")
        pings[name] = r.json()["ping_url"]
        print(f"✓ {name} ({'created' if r.status_code == 201 else 'already there'})")
    out.write_text(json.dumps(pings, indent=2) + "\n")
    print(f"ping URLs written to {out}")
    return pings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    key = os.getenv("HEALTHCHECKS_API_KEY")
    if not key and Path(".env").exists():
        from dotenv import dotenv_values
        key = dotenv_values(".env").get("HEALTHCHECKS_API_KEY")
    if not key and not args.dry_run:
        print("✗ HEALTHCHECKS_API_KEY is not set (a read-write project key from healthchecks.io)", file=sys.stderr)
        return 1
    try:
        run(api_key=key or "", out=args.out, dry_run=args.dry_run)
    except RuntimeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
