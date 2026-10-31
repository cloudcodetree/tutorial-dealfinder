"""Write DealFinder's production secrets to Secret Manager. Prints key names, never values.

One secret, `dealfinder-env`, holds every key as a JSON object. Cloud Run passes it
to the service as DEALFINDER_SECRETS_JSON, and `dealfinder.settings.load_secrets()`
expands it at startup. Each write adds a version and destroys the older ones, so one
version stays active, inside Secret Manager's free 6.

    python deploy/secrets.py check                 # which keys the env file holds, names only
    python deploy/secrets.py push --project P      # env file keys, merged over what is stored
    python deploy/secrets.py edge --project P      # the stored edge secret -> the staging Worker

Values travel on stdin, never in argv, so they never show in a process list.
The env file is the companion's `.env` in the current directory, read here and
nowhere else. Its DATABASE_URL is the developer's own database and is never pushed:
production's comes only from `deploy/create_login_role.py`.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

SECRET = "dealfinder-env"

# The contract's key list (docs/superpowers/plans/2026-10-26-dealfinder-launch-contracts.md).
KEYS = (
    "DATABASE_URL", "BESTBUY_API_KEY", "EBAY_APP_ID", "EBAY_CERT_ID", "EDGE_SHARED_SECRET",
    "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_R2_TOKEN", "RESEND_API_KEY", "UNSUBSCRIBE_SECRET",
    "SENTRY_DSN", "HEALTHCHECK_PAGES_URL", "HEALTHCHECK_ALERTS_URL", "CLOUDFLARE_AI_TOKEN",
)
GENERATED = ("EDGE_SHARED_SECRET", "UNSUBSCRIBE_SECRET")
NEVER_FROM_ENV_FILE = ("DATABASE_URL",)


def new_token() -> str:
    """32 random bytes, URL-safe, the same as secrets.token_urlsafe(32).

    This file is named secrets.py, so run as a script it would shadow the stdlib
    `secrets` module. os.urandom is what that module uses underneath."""
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()


def build_payload(env: dict[str, str]) -> str:
    """Compact JSON of only the contract keys that have a value."""
    return json.dumps({k: env[k] for k in KEYS if env.get(k)}, separators=(",", ":"))


def _gcloud(run, argv: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess:
    return run(argv, input=stdin, capture_output=True, text=True)


def _check(proc: subprocess.CompletedProcess, what: str) -> str:
    if proc.returncode != 0:
        # gcloud's stderr names resources, never secret values.
        raise RuntimeError(f"{what} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def push(payload: str, *, project: str, run=subprocess.run) -> int:
    """Add a version holding `payload`, destroy every older one, return the new number."""
    out = _check(_gcloud(run, ["gcloud", "secrets", "versions", "add", SECRET, "--data-file=-",
                               "--project", project, "--format=value(name.basename())"],
                         stdin=payload), "versions add")
    new = int(out.strip().rsplit("/", 1)[-1])
    # States are filtered here: Secret Manager rejects an OR filter on state.
    listed = _check(_gcloud(run, ["gcloud", "secrets", "versions", "list", SECRET, "--project", project,
                                  "--format=value(name.basename(),state)"]), "versions list")
    for line in listed.splitlines():
        parts = line.split()
        if not parts:
            continue
        v, state = parts[0], (parts[1].lower() if len(parts) > 1 else "enabled")
        if v != str(new) and state != "destroyed":
            _check(_gcloud(run, ["gcloud", "secrets", "versions", "destroy", v, "--secret", SECRET,
                                 "--project", project, "--quiet"]), f"destroy v{v}")
    return new


def current(*, project: str, run=subprocess.run) -> dict:
    """The stored object, or {} before the first version. Never printed."""
    proc = _gcloud(run, ["gcloud", "secrets", "versions", "access", "latest", "--secret", SECRET,
                         "--project", project])
    if proc.returncode != 0 and "NOT_FOUND" in proc.stderr:
        return {}
    return json.loads(_check(proc, "versions access"))


def merge(updates: dict, *, project: str, run=subprocess.run) -> int:
    stored = current(project=project, run=run)
    return push(build_payload({**stored, **updates}), project=project, run=run)


def _env_file() -> dict[str, str]:
    from dotenv import dotenv_values

    path = Path(".env")
    return {k: v for k, v in dotenv_values(path).items() if v} if path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    for name in ("push", "edge"):
        sub.add_parser(name).add_argument("--project", required=True)
    sub.choices["push"].add_argument("--no-env-file", action="store_true",
                                     help="no .env exists yet: store only the generated tokens")
    args = ap.parse_args(argv)

    if args.cmd in ("check", "push") and not Path(".env").exists() and not getattr(args, "no_env_file", False):
        # From the wrong directory a push would store only the generated tokens and
        # silently drop every real key.
        print("✗ no .env here. Run from the companion repo root, the folder that holds your .env, "
              "or pass --no-env-file to store only the generated tokens.", file=sys.stderr)
        return 1

    if args.cmd == "check":
        have = _env_file()
        for k in KEYS:
            print(f"{'✓' if have.get(k) else '·'} {k}")
        return 0

    if args.cmd == "push":
        stored = current(project=args.project)
        from_file = {k: v for k, v in _env_file().items() if k in KEYS and k not in NEVER_FROM_ENV_FILE}
        merged = {**stored, **from_file}
        for k in GENERATED:
            merged.setdefault(k, new_token())
        n = push(build_payload(merged), project=args.project)
        print(f"✓ {SECRET} v{n}: {', '.join(k for k in KEYS if merged.get(k))}")
        return 0

    edge = current(project=args.project).get("EDGE_SHARED_SECRET")
    if not edge:
        print("✗ no EDGE_SHARED_SECRET stored yet. Run push first.", file=sys.stderr)
        return 1
    subprocess.run(["npx", "wrangler", "secret", "put", "EDGE_SHARED_SECRET"], input=edge, text=True,
                   cwd="edge", check=True, capture_output=True)
    print("✓ EDGE_SHARED_SECRET set on dealfinder-edge-staging")
    return 0


if __name__ == "__main__":
    sys.exit(main())
