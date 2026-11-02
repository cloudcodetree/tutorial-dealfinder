#!/usr/bin/env python3
"""Create DealFinder's two Sentry projects, idempotently. Prints no DSN.

    python scripts/sentry_setup.py --org <org-slug> --team <team-slug> --out <scratchpad>/sentry.json

Reads SENTRY_AUTH_TOKEN (scope project:write) from the environment or the companion's
`.env`. Creates `dealfinder-api` (python-fastapi) and `dealfinder-web`
(javascript-react) with Sentry's default alert rule, which emails the owner on a new
issue; an existing project (HTTP 409) is reused. Each project must end up with an issue
alert rule, or the run fails. The DSNs go only to the --out file: SENTRY_DSN goes into
`dealfinder-env` (deploy/secrets.py), and VITE_SENTRY_DSN into the repo variable.

API: https://docs.sentry.io/api/projects/create-a-new-project/ and
https://docs.sentry.io/api/projects/list-a-projects-client-keys/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

API = "https://sentry.io/api/0"
PROJECTS = {"dealfinder-api": "python-fastapi", "dealfinder-web": "javascript-react"}


def run(*, token: str, org: str, team: str, out: Path) -> dict[str, str]:
    auth = {"Authorization": f"Bearer {token}"}
    dsns = {}
    with httpx.Client(headers=auth, timeout=30) as http:
        for slug, platform in PROJECTS.items():
            r = http.post(f"{API}/teams/{org}/{team}/projects/",
                          json={"name": slug, "slug": slug, "platform": platform, "default_rules": True})
            if r.status_code not in (201, 409):
                raise RuntimeError(f"Sentry refused {slug}: HTTP {r.status_code}")
            keys = http.get(f"{API}/projects/{org}/{slug}/keys/")
            if keys.status_code != 200 or not keys.json():
                raise RuntimeError(f"no client key for {slug}: HTTP {keys.status_code}")
            rules = http.get(f"{API}/projects/{org}/{slug}/rules/")
            if rules.status_code != 200 or not rules.json():
                raise RuntimeError(f"{slug} has no issue alert rule: add one that emails you, then re-run")
            dsns[slug] = keys.json()[0]["dsn"]["public"]
            print(f"✓ {slug} ({'created' if r.status_code == 201 else 'already there'}), alert rule present")
    out.write_text(json.dumps(dsns, indent=2) + "\n")
    print(f"DSNs written to {out}")
    return dsns


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--org", required=True)
    ap.add_argument("--team", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    token = os.getenv("SENTRY_AUTH_TOKEN")
    if not token and Path(".env").exists():
        from dotenv import dotenv_values
        token = dotenv_values(".env").get("SENTRY_AUTH_TOKEN")
    if not token:
        print("✗ SENTRY_AUTH_TOKEN is not set (an auth token with project:write)", file=sys.stderr)
        return 1
    try:
        run(token=token, org=args.org, team=args.team, out=args.out)
    except RuntimeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
