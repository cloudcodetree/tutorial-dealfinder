#!/usr/bin/env python3
"""Check that a deployed DealFinder origin sets no cookie except Cloudflare's security ones.

    python scripts/cookie_audit.py https://deals.beta.cloudcodetree.com

It GETs each public page and API route through the deals Worker, prints every
Set-Cookie name per path, and exits 1 on a name outside ESSENTIAL_COOKIES or a page
that does not answer. Deal pages and the sitemap wait for a Best Buy key (Plan 5,
"Launch without Best Buy"). The request names itself: Cloudflare answers Python's
default User-Agent with 403.
"""
from __future__ import annotations

import argparse
import sys

import httpx

ESSENTIAL_COOKIES = {"__cf_bm", "cf_clearance"}
PATHS = ["/", "/check", "/how-we-rank", "/privacy", "/nope", "/lab",
         "/api/config.json", "/api/search?q=tv", "/api/check?title=Sony%20WH-1000XM5&price=199"]
USER_AGENT = "dealfinder-cookie-audit/1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("origin")
    origin = ap.parse_args(argv).origin.rstrip("/")
    extra, failed = set(), []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as http:
        for path in PATHS:
            r = http.get(origin + path)
            names = sorted({c.split("=", 1)[0].strip() for c in r.headers.get_list("set-cookie")})
            print(f"{r.status_code} {path}: {', '.join(names) or 'no cookies'}")
            if r.status_code >= 400:
                failed.append(path)
            extra |= {n for n in names if n not in ESSENTIAL_COOKIES}
    if failed:
        print(f"✗ no answer from: {', '.join(failed)}")
    if extra:
        print(f"✗ non-essential cookies: {', '.join(sorted(extra))}")
    if not failed and not extra:
        print(f"✓ only essential cookies ({', '.join(sorted(ESSENTIAL_COOKIES))}) are allowed, and none other was set")
    return 1 if failed or extra else 0


if __name__ == "__main__":
    sys.exit(main())
